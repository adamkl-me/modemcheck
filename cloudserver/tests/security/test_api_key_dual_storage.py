"""
Security tests for API key dual storage (v7.1+).

Tests verify:
- Hash storage and validation
- Encryption/decryption round-trip
- Cache stores hashes only (no plaintext)
- Reveal endpoint decrypts correctly
- Upload validation uses hash lookups
"""
import pytest
import secrets
import hashlib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import APIKey
from app.core.api_key_crypto import (
    hash_api_key,
    encrypt_api_key_for_storage,
    decrypt_api_key_from_storage,
    encrypt_api_key,
    decrypt_api_key,
    generate_salt
)
from app.core.api_key_cache import APIKeyCache
from app.core.utils import utc_now


class TestAPIKeyHashing:
    """Test hash generation and validation."""

    def test_hash_consistency(self):
        """Same API key should always produce same hash."""
        api_key = "test_key_12345"
        hash1 = hash_api_key(api_key)
        hash2 = hash_api_key(api_key)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 produces 64 hex chars

    def test_hash_uniqueness(self):
        """Different API keys should produce different hashes."""
        key1 = "test_key_1"
        key2 = "test_key_2"

        hash1 = hash_api_key(key1)
        hash2 = hash_api_key(key2)

        assert hash1 != hash2

    def test_hash_format(self):
        """Hash should be lowercase hex string."""
        api_key = secrets.token_hex(32)
        api_hash = hash_api_key(api_key)

        # Should be 64 character hex string (lowercase)
        assert len(api_hash) == 64
        assert all(c in '0123456789abcdef' for c in api_hash)


class TestAPIKeyEncryption:
    """Test encryption and decryption."""

    def test_encryption_round_trip(self):
        """Encrypt then decrypt should return original plaintext."""
        api_key = secrets.token_hex(32)
        salt = generate_salt()

        encrypted = encrypt_api_key(api_key, salt)
        decrypted = decrypt_api_key(encrypted, salt)

        assert decrypted == api_key

    def test_encrypted_format(self):
        """Encrypted output should contain nonce + ciphertext."""
        api_key = "test_key_12345"
        salt = generate_salt()

        encrypted = encrypt_api_key(api_key, salt)

        # Should be: 12-byte nonce + ciphertext + 16-byte auth tag
        # Minimum length: 12 + len(plaintext) + 16
        assert len(encrypted) >= 12 + len(api_key.encode('utf-8')) + 16

    def test_different_salts_produce_different_ciphertexts(self):
        """Same plaintext with different salts should produce different ciphertexts."""
        api_key = "test_key_12345"
        salt1 = generate_salt()
        salt2 = generate_salt()

        encrypted1 = encrypt_api_key(api_key, salt1)
        encrypted2 = encrypt_api_key(api_key, salt2)

        # Different salts → different ciphertexts
        assert encrypted1 != encrypted2

        # But both decrypt to same plaintext
        assert decrypt_api_key(encrypted1, salt1) == api_key
        assert decrypt_api_key(encrypted2, salt2) == api_key

    def test_tampered_ciphertext_fails_auth(self):
        """Tampered ciphertext should fail authentication."""
        api_key = "test_key_12345"
        salt = generate_salt()
        encrypted = encrypt_api_key(api_key, salt)

        # Tamper with last byte
        tampered = bytearray(encrypted)
        tampered[-1] ^= 0xFF
        tampered = bytes(tampered)

        # Should raise exception (authentication failure)
        with pytest.raises(Exception):  # cryptography.exceptions.InvalidTag
            decrypt_api_key(tampered, salt)

    def test_storage_helpers(self):
        """Storage helper functions should work correctly."""
        api_key = secrets.token_hex(32)

        # Encrypt for storage
        api_hash, encrypted_hex, salt_hex = encrypt_api_key_for_storage(api_key)

        # Verify hash
        assert api_hash == hash_api_key(api_key)
        assert len(api_hash) == 64

        # Verify hex encoding
        assert all(c in '0123456789abcdef' for c in encrypted_hex)
        assert all(c in '0123456789abcdef' for c in salt_hex)

        # Decrypt from storage
        decrypted = decrypt_api_key_from_storage(encrypted_hex, salt_hex)
        assert decrypted == api_key


class TestAPIKeyDatabaseStorage:
    """Test API key dual storage in database."""

    @pytest.mark.asyncio
    async def test_create_api_key_with_hash_storage(self, db_session: AsyncSession):
        """Creating API key should store hash + encrypted (v8.0+, no plaintext)."""
        plaintext_key = secrets.token_hex(32)
        api_hash, encrypted_hex, salt_hex = encrypt_api_key_for_storage(plaintext_key)

        api_key = APIKey(
            api_key_hash=api_hash,  # Primary key (v8.0+)
            api_key_encrypted=encrypted_hex,
            encryption_salt=salt_hex,
            name="test_hash_storage",
            created_at=utc_now(),
            is_active=True
        )

        db_session.add(api_key)
        await db_session.commit()

        # Query back from database
        result = await db_session.execute(
            select(APIKey).where(APIKey.api_key_hash == api_hash)
        )
        retrieved = result.scalar_one()

        # Verify hash stored correctly (is now the primary key)
        assert retrieved.api_key_hash == api_hash

        # Verify can decrypt
        decrypted = decrypt_api_key_from_storage(
            retrieved.api_key_encrypted,
            retrieved.encryption_salt
        )
        assert decrypted == plaintext_key

    @pytest.mark.asyncio
    async def test_hash_based_lookup(self, db_session: AsyncSession, active_api_key: APIKey, test_api_key: str):
        """Should be able to look up API key by hash."""
        # Hash the plaintext key (test_api_key is the plaintext)
        api_hash = hash_api_key(test_api_key)

        # Lookup by hash
        result = await db_session.execute(
            select(APIKey).where(APIKey.api_key_hash == api_hash)
        )
        found = result.scalar_one_or_none()

        assert found is not None
        assert found.name == "test_key_active"
        assert found.api_key_hash == api_hash


class TestAPIKeyCache:
    """Test that cache stores hashes only (no plaintext)."""

    @pytest.fixture(autouse=True)
    async def isolate_cache(self):
        """Ensure cache isolation between tests in this class.

        Only invalidates the API key cache, NOT the cache provider itself.
        The cache provider is managed by conftest.py's clear_redis fixture.
        """
        # Before test: clear API key cache
        await APIKeyCache.invalidate_cache()
        yield
        # After test: clear API key cache
        await APIKeyCache.invalidate_cache()

    @pytest.mark.asyncio
    async def test_cache_stores_hashes_only(self):
        """Cache should store hashes, not plaintext API keys."""
        plaintext_key = secrets.token_hex(32)
        api_hash, encrypted_hex, salt_hex = encrypt_api_key_for_storage(plaintext_key)

        # Build cache data (simulating what validate_api_key_cached does)
        # In v8.0+, cache only stores hashes and names - no plaintext anywhere
        cache_data = [
            {'api_key_hash': api_hash, 'name': "test_cache_security"}
        ]

        # Set in cache
        await APIKeyCache.set_cached_keys(cache_data)

        # Retrieve from cache
        cached = await APIKeyCache.get_cached_keys()

        assert cached is not None
        assert len(cached) == 1

        # CRITICAL: Cache should NOT contain plaintext
        assert 'api_key' not in cached[0]
        assert cached[0]['api_key_hash'] == api_hash
        assert cached[0]['name'] == "test_cache_security"

    @pytest.mark.asyncio
    async def test_cache_validation_uses_hash(self, db_session: AsyncSession, active_api_key: APIKey, test_api_key: str):
        """Cache validation should use hash comparison."""
        plaintext_key = test_api_key  # Get plaintext from fixture
        expected_hash = hash_api_key(plaintext_key)

        # Mock DB fallback function - filter by hash to avoid pollution from other tests
        async def mock_db_fallback():
            result = await db_session.execute(
                select(APIKey).where(
                    APIKey.is_active == True,
                    APIKey.api_key_hash == expected_hash
                )
            )
            return result.scalars().all()

        # Clear cache first
        await APIKeyCache.invalidate_cache()

        # Validate API key (triggers cache population)
        is_valid, key_name = await APIKeyCache.validate_api_key_cached(
            plaintext_key,
            mock_db_fallback
        )

        assert is_valid is True
        assert key_name == "test_key_active"

        # Check cache contains hash (not plaintext)
        cached = await APIKeyCache.get_cached_keys()
        assert cached is not None
        assert len(cached) > 0

        # Verify cache stores hash (expected_hash computed at start of test)
        cache_entry = next((k for k in cached if k['name'] == 'test_key_active'), None)
        assert cache_entry is not None
        assert cache_entry['api_key_hash'] == expected_hash
        assert 'api_key' not in cache_entry  # No plaintext!


class TestAPIKeySecurity:
    """Security-focused tests."""

    @pytest.mark.asyncio
    async def test_hash_cannot_be_reversed(self):
        """Hash should be one-way (cannot recover plaintext)."""
        api_key = secrets.token_hex(32)
        api_hash = hash_api_key(api_key)

        # Hash is one-way - cannot recover plaintext from hash alone
        # This test documents the security property (not a functional test)
        assert len(api_hash) == 64
        assert api_hash != api_key

    @pytest.mark.asyncio
    async def test_encrypted_requires_secret_key(self):
        """Decryption requires correct SECRET_KEY."""
        api_key = secrets.token_hex(32)
        api_hash, encrypted_hex, salt_hex = encrypt_api_key_for_storage(api_key)

        # With correct SECRET_KEY (from settings), decryption works
        decrypted = decrypt_api_key_from_storage(encrypted_hex, salt_hex)
        assert decrypted == api_key

        # Note: Cannot test with wrong SECRET_KEY in this test
        # (would require mocking settings.secret_key)

    @pytest.mark.asyncio
    async def test_database_compromise_doesnt_expose_plaintext(self, db_session: AsyncSession):
        """Database compromise should not expose plaintext API keys (v8.0+)."""
        plaintext_key = secrets.token_hex(32)
        api_hash, encrypted_hex, salt_hex = encrypt_api_key_for_storage(plaintext_key)

        # In v8.0+, no plaintext column exists - only hash and encrypted
        api_key = APIKey(
            api_key_hash=api_hash,
            api_key_encrypted=encrypted_hex,
            encryption_salt=salt_hex,
            name="test_security",
            created_at=utc_now(),
            is_active=True
        )

        db_session.add(api_key)
        await db_session.commit()

        # Query database (simulating attacker with DB access)
        result = await db_session.execute(select(APIKey).where(APIKey.name == "test_security"))
        row = result.scalar_one()

        # Attacker has:
        # - api_key_hash (one-way, can't reverse)
        # - api_key_encrypted (requires SECRET_KEY to decrypt)
        # - encryption_salt (useless without SECRET_KEY)
        # v8.0+: NO plaintext column exists anymore!

        # Verify hash cannot be reversed
        assert row.api_key_hash != plaintext_key
        assert len(row.api_key_hash) == 64

        # Verify encrypted data is not plaintext
        assert row.api_key_encrypted != plaintext_key

        # Without SECRET_KEY, attacker cannot decrypt
        # (This is the security property we're documenting)


class TestEndToEndSecurity:
    """End-to-end security workflow tests."""

    @pytest.mark.asyncio
    async def test_upload_uses_hash_validation(self, db_session: AsyncSession, active_api_key: APIKey, test_api_key: str):
        """Upload endpoint should validate using hash lookups."""
        plaintext_key = test_api_key  # Get plaintext from fixture

        # Simulate upload validation flow
        # 1. Client sends plaintext
        # 2. Server hashes it
        api_hash = hash_api_key(plaintext_key)

        # 3. Server looks up by hash
        result = await db_session.execute(
            select(APIKey).where(APIKey.api_key_hash == api_hash)
        )
        found = result.scalar_one_or_none()

        assert found is not None
        assert found.is_active is True

    @pytest.mark.asyncio
    async def test_reveal_endpoint_decrypts(self, db_session: AsyncSession, active_api_key: APIKey, test_api_key: str):
        """Reveal endpoint should decrypt API key correctly."""
        # Simulate admin reveal flow
        # 1. Admin requests reveal
        # 2. Server queries by preview (v8.0+: decrypts all keys to find match)
        # 3. Server decrypts from encrypted column

        decrypted = decrypt_api_key_from_storage(
            active_api_key.api_key_encrypted,
            active_api_key.encryption_salt
        )

        # Verify decrypted matches original (test_api_key is the plaintext)
        assert decrypted == test_api_key
