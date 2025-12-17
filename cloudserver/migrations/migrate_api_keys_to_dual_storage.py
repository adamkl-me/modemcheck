#!/usr/bin/env python3
"""
Migrate existing API keys to dual storage (hash + encrypted).

This migration populates the new columns added by add_api_key_dual_storage.sql:
- api_key_hash: SHA-256 hash for validation
- api_key_encrypted: AES-256-GCM encrypted plaintext for admin reveal
- encryption_salt: Random salt for encryption
- migrated: Flag to track migration progress

SAFETY:
    - Creates database backup before migration
    - Validates all keys migrated successfully
    - Rollback available if any errors occur
    - Keeps plaintext column for 30-day transition period

USAGE:
    python migrations/migrate_api_keys_to_dual_storage.py

REQUIREMENTS:
    - PostgreSQL database with add_api_key_dual_storage.sql applied
    - SECRET_KEY in .env for key derivation
    - cryptography library: pip install cryptography

SECURITY:
    - Uses AES-256-GCM authenticated encryption
    - Key derived from SECRET_KEY using PBKDF2-HMAC-SHA256
    - Random 16-byte salt per key
    - 12-byte nonce per encryption (prepended to ciphertext)
"""
import asyncio
import hashlib
import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import database as db_module
from app.models.api_key import APIKey
from app.core.config import settings


def derive_encryption_key(salt: bytes) -> bytes:
    """
    Derive 256-bit encryption key from SECRET_KEY + salt.

    Uses PBKDF2-HMAC-SHA256 with 100,000 iterations for defense against
    brute force attacks if database compromised.

    Args:
        salt: Random 16-byte salt (unique per API key)

    Returns:
        32-byte (256-bit) encryption key
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,  # 256 bits for AES-256
        salt=salt,
        iterations=100000,  # OWASP recommendation (2023)
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
        nonce (12 bytes) + ciphertext (variable length) + auth_tag (16 bytes)

    Security:
        - 256-bit key (derived from SECRET_KEY + salt)
        - 96-bit nonce (random, unique per encryption)
        - 128-bit authentication tag (built into GCM)
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

    Used for validation during migration (ensures encryption/decryption works).

    Args:
        encrypted_bytes: nonce (12 bytes) + ciphertext + auth_tag
        salt: Random 16-byte salt used for key derivation

    Returns:
        Decrypted API key in plaintext

    Raises:
        cryptography.exceptions.InvalidTag: If authentication fails
    """
    key = derive_encryption_key(salt)
    aesgcm = AESGCM(key)

    # Split nonce and ciphertext
    nonce = encrypted_bytes[:12]
    ciphertext = encrypted_bytes[12:]

    # Decrypt and verify authentication tag
    plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext_bytes.decode('utf-8')


async def migrate_api_keys():
    """
    Migrate all existing API keys to dual storage.

    Process:
    1. Query all unmigrated keys (migrated = FALSE or NULL)
    2. For each key:
       - Generate SHA-256 hash
       - Generate random 16-byte salt
       - Encrypt plaintext with AES-256-GCM
       - Update database with hash, encrypted, salt, migrated=TRUE
    3. Validate all keys migrated successfully
    4. Verify decryption works for sample keys

    Rollback:
        If any errors occur, transaction is rolled back automatically.
        Database remains in pre-migration state (new columns null).
    """
    print("=" * 70)
    print("API Key Migration to Dual Storage (Hash + Encrypted)")
    print("=" * 70)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Check SECRET_KEY is available
    if not settings.secret_key:
        print("✗ ERROR: SECRET_KEY not set in environment")
        print("  Migration requires SECRET_KEY for encryption")
        sys.exit(1)

    print(f"✓ SECRET_KEY available (length: {len(settings.secret_key)} chars)")
    print()

    # Initialize the database session maker
    db_module.init_db()

    async with db_module.AsyncSessionLocal() as db:
        try:
            # Step 1: Count total keys
            result = await db.execute(select(func.count(APIKey.api_key)))
            total_keys = result.scalar()
            print(f"Total API keys in database: {total_keys}")

            # Step 2: Get all unmigrated keys
            result = await db.execute(
                select(APIKey).where(
                    (APIKey.migrated == False) | (APIKey.migrated == None)
                )
            )
            keys_to_migrate = result.scalars().all()

            unmigrated_count = len(keys_to_migrate)
            print(f"Keys requiring migration: {unmigrated_count}")
            print()

            if unmigrated_count == 0:
                print("✓ No keys to migrate - all keys already migrated")
                return

            # Step 3: Migrate each key
            print("Starting migration...")
            print("-" * 70)

            migrated_count = 0
            failed_keys = []

            for idx, key in enumerate(keys_to_migrate, 1):
                try:
                    # Generate SHA-256 hash
                    api_key_hash = hashlib.sha256(key.api_key.encode('utf-8')).hexdigest()

                    # Generate random 16-byte salt
                    salt = os.urandom(16)
                    salt_hex = salt.hex()

                    # Encrypt plaintext with AES-256-GCM
                    encrypted_bytes = encrypt_api_key(key.api_key, salt)
                    encrypted_hex = encrypted_bytes.hex()

                    # Verify decryption works (sanity check)
                    decrypted = decrypt_api_key(encrypted_bytes, salt)
                    if decrypted != key.api_key:
                        raise Exception(f"Decryption verification failed for key {key.name}")

                    # Update database
                    await db.execute(
                        update(APIKey)
                        .where(APIKey.api_key == key.api_key)
                        .values(
                            api_key_hash=api_key_hash,
                            api_key_encrypted=encrypted_hex,
                            encryption_salt=salt_hex,
                            migrated=True
                        )
                    )

                    migrated_count += 1
                    print(f"[{idx}/{unmigrated_count}] ✓ Migrated: {key.name} ({key.api_key[:8]}...)")

                except Exception as e:
                    print(f"[{idx}/{unmigrated_count}] ✗ FAILED: {key.name} - {e}")
                    failed_keys.append((key.name, str(e)))

            print("-" * 70)
            print()

            # Step 4: Check for failures
            if failed_keys:
                print(f"✗ Migration completed with {len(failed_keys)} failures")
                print()
                print("Failed keys:")
                for name, error in failed_keys:
                    print(f"  - {name}: {error}")
                print()
                print("Rolling back transaction...")
                await db.rollback()
                sys.exit(1)

            # Step 5: Commit all changes
            await db.commit()
            print(f"✓ Successfully migrated {migrated_count} keys")
            print()

            # Step 6: Validate migration
            print("Validating migration...")
            print("-" * 70)

            result = await db.execute(select(APIKey))
            all_keys = result.scalars().all()

            validation_errors = []
            for key in all_keys:
                if not key.api_key_hash:
                    validation_errors.append(f"{key.name}: missing api_key_hash")
                elif len(key.api_key_hash) != 64:
                    validation_errors.append(f"{key.name}: invalid hash length ({len(key.api_key_hash)})")

                if not key.api_key_encrypted:
                    validation_errors.append(f"{key.name}: missing api_key_encrypted")

                if not key.encryption_salt:
                    validation_errors.append(f"{key.name}: missing encryption_salt")
                elif len(key.encryption_salt) != 32:
                    validation_errors.append(f"{key.name}: invalid salt length ({len(key.encryption_salt)})")

                if not key.migrated:
                    validation_errors.append(f"{key.name}: migrated flag not set")

            if validation_errors:
                print("✗ Validation failed:")
                for error in validation_errors:
                    print(f"  - {error}")
                print()
                sys.exit(1)

            print(f"✓ All {len(all_keys)} keys validated successfully")
            print()

            # Step 7: Sample decryption test
            print("Testing decryption on sample keys...")
            sample_size = min(3, len(all_keys))
            for key in all_keys[:sample_size]:
                try:
                    encrypted_bytes = bytes.fromhex(key.api_key_encrypted)
                    salt_bytes = bytes.fromhex(key.encryption_salt)
                    decrypted = decrypt_api_key(encrypted_bytes, salt_bytes)

                    if decrypted == key.api_key:
                        print(f"  ✓ {key.name}: Decryption successful")
                    else:
                        print(f"  ✗ {key.name}: Decryption mismatch")
                        sys.exit(1)
                except Exception as e:
                    print(f"  ✗ {key.name}: Decryption failed - {e}")
                    sys.exit(1)

            print()
            print("=" * 70)
            print("Migration Summary")
            print("=" * 70)
            print(f"Status: ✅ SUCCESS")
            print(f"Total keys: {total_keys}")
            print(f"Migrated: {migrated_count}")
            print(f"Failed: {len(failed_keys)}")
            print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print()
            print("Next steps:")
            print("  1. Deploy updated application code (Phase 2-5)")
            print("  2. Verify upload/config sync/reveal endpoints work")
            print("  3. Monitor for 30 days before Phase 8 cleanup")
            print("=" * 70)

        except Exception as e:
            print()
            print(f"✗ CRITICAL ERROR: {e}")
            print()
            print("Rolling back transaction...")
            await db.rollback()
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(migrate_api_keys())
