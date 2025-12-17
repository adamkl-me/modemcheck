"""
API Key Cryptographic Operations (v7.1+)

Provides encryption/decryption functions for API key dual storage.
Centralizes crypto logic to ensure consistency across admin and migration code.

Security:
- AES-256-GCM authenticated encryption
- PBKDF2-HMAC-SHA256 key derivation (100,000 iterations)
- Random 16-byte salt per key
- Random 12-byte nonce per encryption
"""
import os
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from app.core.config import settings


def hash_api_key(api_key: str) -> str:
    """
    Generate SHA-256 hash of API key for validation lookups.

    Args:
        api_key: Plaintext API key

    Returns:
        64-character hex string (SHA-256)

    Usage:
        api_key_hash = hash_api_key(plaintext_key)
        # Use for database lookups, cache storage
    """
    return hashlib.sha256(api_key.encode('utf-8')).hexdigest()


def derive_encryption_key(salt: bytes) -> bytes:
    """
    Derive 256-bit encryption key from SECRET_KEY + salt.

    Uses PBKDF2-HMAC-SHA256 with 100,000 iterations for defense against
    brute force attacks if database is compromised.

    Args:
        salt: Random 16-byte salt (unique per API key)

    Returns:
        32-byte (256-bit) encryption key

    Security:
        - 100,000 iterations = OWASP recommendation (2023)
        - Salt prevents rainbow table attacks
        - Requires SECRET_KEY to derive (environment variable)
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,  # 256 bits for AES-256
        salt=salt,
        iterations=100000,
    )
    return kdf.derive(settings.secret_key.encode('utf-8'))


def encrypt_api_key(plaintext: str, salt: bytes) -> bytes:
    """
    Encrypt API key with AES-256-GCM authenticated encryption.

    AES-GCM provides both confidentiality and authenticity, preventing
    tampering. The nonce is prepended to ciphertext for storage.

    Args:
        plaintext: API key in plaintext
        salt: Random 16-byte salt for key derivation

    Returns:
        nonce (12 bytes) + ciphertext (variable) + auth_tag (16 bytes)

    Security:
        - 256-bit key (derived from SECRET_KEY + salt)
        - 96-bit nonce (random, unique per encryption)
        - 128-bit authentication tag (built into GCM)

    Storage:
        Store returned bytes as hex string in database
    """
    key = derive_encryption_key(salt)
    aesgcm = AESGCM(key)

    # Generate random 96-bit nonce for GCM mode
    nonce = os.urandom(12)

    # Encrypt plaintext with authenticated encryption
    # GCM mode: ciphertext includes authentication tag
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)

    # Return nonce + ciphertext (nonce needed for decryption)
    return nonce + ciphertext


def decrypt_api_key(encrypted_bytes: bytes, salt: bytes) -> str:
    """
    Decrypt API key from AES-256-GCM ciphertext.

    Args:
        encrypted_bytes: nonce (12 bytes) + ciphertext + auth_tag
        salt: Random 16-byte salt used for key derivation

    Returns:
        Decrypted API key in plaintext

    Raises:
        cryptography.exceptions.InvalidTag: If authentication fails (tampering detected)

    Security:
        - Verifies authentication tag before decrypting
        - Tampered ciphertext will raise exception
        - Requires correct SECRET_KEY to derive encryption key
    """
    key = derive_encryption_key(salt)
    aesgcm = AESGCM(key)

    # Split nonce and ciphertext
    nonce = encrypted_bytes[:12]
    ciphertext = encrypted_bytes[12:]

    # Decrypt and verify authentication tag
    plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext_bytes.decode('utf-8')


def generate_salt() -> bytes:
    """
    Generate cryptographically secure random 16-byte salt.

    Returns:
        16 random bytes

    Usage:
        salt = generate_salt()
        salt_hex = salt.hex()  # Store as hex string in DB
    """
    return os.urandom(16)


def encrypt_api_key_for_storage(api_key: str) -> tuple[str, str, str]:
    """
    Convenience function: Hash + encrypt API key for database storage.

    Combines hash generation, salt generation, and encryption in one call.
    Use this when creating new API keys.

    Args:
        api_key: Plaintext API key

    Returns:
        Tuple of (api_key_hash, api_key_encrypted_hex, encryption_salt_hex)

    Usage:
        key_hash, key_encrypted, salt_hex = encrypt_api_key_for_storage(new_key)
        # Store all three in database
    """
    # Generate hash for validation
    api_key_hash = hash_api_key(api_key)

    # Generate salt and encrypt
    salt = generate_salt()
    encrypted_bytes = encrypt_api_key(api_key, salt)

    # Convert to hex strings for database storage
    encrypted_hex = encrypted_bytes.hex()
    salt_hex = salt.hex()

    return api_key_hash, encrypted_hex, salt_hex


def decrypt_api_key_from_storage(encrypted_hex: str, salt_hex: str) -> str:
    """
    Convenience function: Decrypt API key from hex-encoded database values.

    Use this when revealing API keys to admins.

    Args:
        encrypted_hex: Hex-encoded encrypted API key (from database)
        salt_hex: Hex-encoded salt (from database)

    Returns:
        Decrypted plaintext API key

    Usage:
        plaintext = decrypt_api_key_from_storage(
            row.api_key_encrypted,
            row.encryption_salt
        )
    """
    encrypted_bytes = bytes.fromhex(encrypted_hex)
    salt = bytes.fromhex(salt_hex)
    return decrypt_api_key(encrypted_bytes, salt)
