"""
AES-256-GCM encryption/decryption for client configurations.

Uses AES-256-GCM (Galois/Counter Mode) with:
- 256-bit keys derived from secret via PBKDF2-HMAC-SHA256
- Random 16-byte salt per config (stored with ciphertext)
- Random 12-byte nonce (GCM standard, stored with ciphertext)
- Authentication tags prevent tampering

Encrypted format: salt (32 hex chars) + nonce (24 hex chars) + ciphertext (hex)
"""

import os
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.config import settings
from app.core.errors import ConfigEncryptionError


# Thread pool for CPU-intensive crypto operations (avoids blocking event loop)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="crypto_")


def _derive_key(salt: bytes) -> bytes:
    """
    Derive 256-bit encryption key from secret using PBKDF2.

    Args:
        salt: 16-byte random salt

    Returns:
        32-byte encryption key
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,  # 256 bits
        salt=salt,
        iterations=100000,  # OWASP recommendation
    )
    return kdf.derive(settings.secret_key.encode('utf-8'))


def _encrypt_sync(plaintext_dict: Dict[str, Any], salt_hex: str) -> tuple[str, str]:
    """
    Synchronous encryption (runs in thread pool).

    Args:
        plaintext_dict: Configuration dictionary
        salt_hex: 32-character hex salt string

    Returns:
        Tuple of (encrypted_blob, nonce_hex)
        encrypted_blob format: salt + nonce + ciphertext (all hex)

    Raises:
        ConfigEncryptionError: If encryption fails
    """
    try:
        # Convert plaintext to canonical JSON (sorted keys, no whitespace)
        plaintext_json = json.dumps(plaintext_dict, sort_keys=True, separators=(',', ':'))
        plaintext_bytes = plaintext_json.encode('utf-8')

        # Decode salt from hex
        salt = bytes.fromhex(salt_hex)
        if len(salt) != 16:
            raise ConfigEncryptionError(
                message="Invalid salt length",
                details={"expected": 16, "actual": len(salt)}
            )

        # Derive encryption key from secret + salt
        key = _derive_key(salt)

        # Generate random nonce (12 bytes is GCM standard)
        nonce = os.urandom(12)

        # Encrypt with AES-256-GCM
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, associated_data=None)

        # Return: salt (32 hex) + nonce (24 hex) + ciphertext (hex)
        encrypted_blob = salt_hex + nonce.hex() + ciphertext.hex()
        return encrypted_blob, nonce.hex()

    except Exception as e:
        raise ConfigEncryptionError(
            message=f"Encryption failed: {str(e)}",
            details={"error_type": type(e).__name__}
        )


def _decrypt_sync(encrypted_blob: str, salt_hex: str) -> Dict[str, Any]:
    """
    Synchronous decryption (runs in thread pool).

    Args:
        encrypted_blob: Encrypted config (salt + nonce + ciphertext, all hex)
        salt_hex: Expected salt (32 hex chars) - must match blob prefix

    Returns:
        Decrypted configuration dictionary

    Raises:
        ConfigEncryptionError: If decryption or authentication fails
    """
    try:
        # Validate blob format
        if len(encrypted_blob) < 56:  # 32 (salt) + 24 (nonce) + min ciphertext
            raise ConfigEncryptionError(
                message="Encrypted blob too short",
                details={"length": len(encrypted_blob), "minimum": 56}
            )

        # Extract components
        blob_salt_hex = encrypted_blob[:32]
        nonce_hex = encrypted_blob[32:56]
        ciphertext_hex = encrypted_blob[56:]

        # Verify salt matches (prevents salt substitution attacks)
        if blob_salt_hex != salt_hex:
            raise ConfigEncryptionError(
                message="Salt mismatch",
                details={"expected_prefix": salt_hex[:8], "actual_prefix": blob_salt_hex[:8]}
            )

        # Decode components
        salt = bytes.fromhex(salt_hex)
        nonce = bytes.fromhex(nonce_hex)
        ciphertext = bytes.fromhex(ciphertext_hex)

        # Derive decryption key
        key = _derive_key(salt)

        # Decrypt with AES-256-GCM (automatically verifies authentication tag)
        aesgcm = AESGCM(key)
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, associated_data=None)

        # Parse JSON
        plaintext_json = plaintext_bytes.decode('utf-8')
        config_dict = json.loads(plaintext_json)

        return config_dict

    except ValueError as e:
        # GCM authentication failure or hex decode error
        raise ConfigEncryptionError(
            message="Decryption failed (authentication or format error)",
            details={"error": str(e)}
        )
    except json.JSONDecodeError as e:
        raise ConfigEncryptionError(
            message="Decrypted data is not valid JSON",
            details={"error": str(e)}
        )
    except Exception as e:
        raise ConfigEncryptionError(
            message=f"Decryption failed: {str(e)}",
            details={"error_type": type(e).__name__}
        )


async def encrypt_config(config_dict: Dict[str, Any], salt_hex: str = None) -> tuple[str, str]:
    """
    Encrypt configuration dictionary using AES-256-GCM.

    Args:
        config_dict: Configuration to encrypt
        salt_hex: Optional 32-char hex salt. If None, generates random salt.

    Returns:
        Tuple of (encrypted_blob, salt_hex)
        encrypted_blob format: salt + nonce + ciphertext (all hex)

    Raises:
        ConfigEncryptionError: If encryption fails

    Example:
        >>> config = {"CloudURL": "https://example.com", "APIKey": "secret123"}
        >>> encrypted_blob, salt = await encrypt_config(config)
        >>> len(salt)  # 32 hex characters
        32
    """
    # Generate random salt if not provided
    if salt_hex is None:
        salt_hex = os.urandom(16).hex()

    # Run CPU-intensive encryption in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    encrypted_blob, nonce_hex = await loop.run_in_executor(
        _executor,
        _encrypt_sync,
        config_dict,
        salt_hex
    )

    return encrypted_blob, salt_hex


async def decrypt_config(encrypted_blob: str, salt_hex: str) -> Dict[str, Any]:
    """
    Decrypt configuration using AES-256-GCM.

    Args:
        encrypted_blob: Encrypted config (salt + nonce + ciphertext, all hex)
        salt_hex: Salt used for encryption (32 hex chars)

    Returns:
        Decrypted configuration dictionary

    Raises:
        ConfigEncryptionError: If decryption or authentication fails

    Example:
        >>> encrypted = "ab12...cdef"  # From database
        >>> salt = "1234567890abcdef1234567890abcdef"
        >>> config = await decrypt_config(encrypted, salt)
        >>> config["CloudURL"]
        'https://example.com'
    """
    # Run CPU-intensive decryption in thread pool
    loop = asyncio.get_event_loop()
    config_dict = await loop.run_in_executor(
        _executor,
        _decrypt_sync,
        encrypted_blob,
        salt_hex
    )

    return config_dict


def generate_salt() -> str:
    """
    Generate random 16-byte salt for encryption.

    Returns:
        32-character hex string

    Example:
        >>> salt = generate_salt()
        >>> len(salt)
        32
        >>> int(salt, 16)  # Valid hex
        123456789...
    """
    return os.urandom(16).hex()


async def rotate_encryption(
    old_encrypted: str,
    old_salt: str,
    new_salt: str = None
) -> tuple[str, str]:
    """
    Re-encrypt config with a new salt (for key rotation).

    This is useful when rotating the secret_key or implementing
    periodic re-encryption for enhanced security.

    Args:
        old_encrypted: Current encrypted blob
        old_salt: Current salt
        new_salt: Optional new salt (generates random if None)

    Returns:
        Tuple of (new_encrypted_blob, new_salt)

    Raises:
        ConfigEncryptionError: If decryption or encryption fails

    Example:
        >>> new_encrypted, new_salt = await rotate_encryption(old_encrypted, old_salt)
        >>> # Config is now encrypted with new salt
    """
    # Decrypt with old salt
    config_dict = await decrypt_config(old_encrypted, old_salt)

    # Re-encrypt with new salt
    new_encrypted, new_salt = await encrypt_config(config_dict, new_salt)

    return new_encrypted, new_salt


def verify_encryption_key() -> bool:
    """
    Verify that encryption key derivation is working.

    Returns:
        True if encryption/decryption works correctly

    Example:
        >>> verify_encryption_key()
        True
    """
    try:
        # Test encryption with known plaintext
        test_salt = "0" * 32  # Fixed salt for testing
        salt_bytes = bytes.fromhex(test_salt)

        # Derive key
        key = _derive_key(salt_bytes)

        # Verify key length
        if len(key) != 32:
            return False

        # Test encrypt/decrypt
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        plaintext = b"test"
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)

        return decrypted == plaintext

    except Exception:
        return False
