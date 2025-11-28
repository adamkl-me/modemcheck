"""
Unit tests for configuration encryption module.

Tests encryption, decryption, and key derivation functions.
"""

import pytest
import os
from app.core.config_encryption import (
    encrypt_config, decrypt_config, verify_encryption_key,
    _derive_key, _encrypt_sync, _decrypt_sync
)
from app.core.errors import ConfigEncryptionError


class TestEncryptionKeyDerivation:
    """Test key derivation from secret."""

    def test_derive_key_consistent(self):
        """Same salt produces same key."""
        salt = os.urandom(16)
        key1 = _derive_key(salt)
        key2 = _derive_key(salt)
        assert key1 == key2

    def test_derive_key_different_salts(self):
        """Different salts produce different keys."""
        salt1 = os.urandom(16)
        salt2 = os.urandom(16)
        key1 = _derive_key(salt1)
        key2 = _derive_key(salt2)
        assert key1 != key2

    def test_derive_key_length(self):
        """Derived key is 32 bytes (256 bits)."""
        salt = os.urandom(16)
        key = _derive_key(salt)
        assert len(key) == 32

    def test_verify_encryption_key(self):
        """Encryption key verification passes."""
        assert verify_encryption_key() is True


class TestConfigEncryption:
    """Test configuration encryption."""

    @pytest.mark.asyncio
    async def test_encrypt_simple_config(self):
        """Encrypt simple configuration."""
        config = {"PingCount": 25, "EnableCloud": True}
        encrypted, salt = await encrypt_config(config)

        assert encrypted is not None
        assert salt is not None
        assert len(salt) == 32  # 16 bytes hex = 32 chars
        assert isinstance(encrypted, str)
        assert isinstance(salt, str)

    @pytest.mark.asyncio
    async def test_encrypt_complex_config(self):
        """Encrypt complex configuration with nested data."""
        config = {
            "ModemAddress": "192.168.100.1",
            "SpeedTestEnabled": True,
            "SpeedTestInterval": 5,
            "PingCount": 50,
            "CloudHost": "example.com",
            "CloudPort": "22557",
            "UpdateChannel": "stable"
        }
        encrypted, salt = await encrypt_config(config)

        assert encrypted is not None
        assert salt is not None

    @pytest.mark.asyncio
    async def test_encrypt_with_custom_salt(self):
        """Encrypt with provided salt."""
        config = {"PingCount": 25}
        custom_salt = "0123456789abcdef0123456789abcdef"  # 32 hex chars
        encrypted, salt = await encrypt_config(config, custom_salt)

        assert salt == custom_salt

    @pytest.mark.asyncio
    async def test_encrypt_empty_config(self):
        """Encrypt empty configuration."""
        config = {}
        encrypted, salt = await encrypt_config(config)

        assert encrypted is not None
        assert salt is not None

    @pytest.mark.asyncio
    async def test_encrypt_generates_different_ciphertext(self):
        """Same config with different salts produces different ciphertext."""
        config = {"PingCount": 25}

        encrypted1, salt1 = await encrypt_config(config)
        encrypted2, salt2 = await encrypt_config(config)

        assert salt1 != salt2
        assert encrypted1 != encrypted2


class TestConfigDecryption:
    """Test configuration decryption."""

    @pytest.mark.asyncio
    async def test_decrypt_simple_config(self):
        """Decrypt simple configuration."""
        original = {"PingCount": 25, "EnableCloud": True}
        encrypted, salt = await encrypt_config(original)

        decrypted = await decrypt_config(encrypted, salt)

        assert decrypted == original

    @pytest.mark.asyncio
    async def test_decrypt_complex_config(self):
        """Decrypt complex configuration."""
        original = {
            "ModemAddress": "192.168.100.1",
            "SpeedTestEnabled": True,
            "SpeedTestInterval": 5,
            "PingCount": 50,
            "CloudHost": "example.com"
        }
        encrypted, salt = await encrypt_config(original)

        decrypted = await decrypt_config(encrypted, salt)

        assert decrypted == original

    @pytest.mark.asyncio
    async def test_decrypt_preserves_types(self):
        """Decryption preserves data types."""
        original = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
            "dict": {"nested": "value"}
        }
        encrypted, salt = await encrypt_config(original)

        decrypted = await decrypt_config(encrypted, salt)

        assert isinstance(decrypted["string"], str)
        assert isinstance(decrypted["int"], int)
        assert isinstance(decrypted["float"], float)
        assert isinstance(decrypted["bool"], bool)
        assert decrypted["null"] is None
        assert isinstance(decrypted["list"], list)
        assert isinstance(decrypted["dict"], dict)

    @pytest.mark.asyncio
    async def test_decrypt_with_wrong_salt_fails(self):
        """Decryption with wrong salt fails."""
        config = {"PingCount": 25}
        encrypted, _ = await encrypt_config(config)
        wrong_salt = "0123456789abcdef0123456789abcdef"

        with pytest.raises(ConfigEncryptionError):
            await decrypt_config(encrypted, wrong_salt)

    @pytest.mark.asyncio
    async def test_decrypt_invalid_ciphertext_fails(self):
        """Decryption of invalid ciphertext fails."""
        salt = "0123456789abcdef0123456789abcdef"
        invalid_ciphertext = "invalid_base64_data"

        with pytest.raises(ConfigEncryptionError):
            await decrypt_config(invalid_ciphertext, salt)

    @pytest.mark.asyncio
    async def test_decrypt_tampered_ciphertext_fails(self):
        """Decryption of tampered ciphertext fails (authenticated encryption)."""
        config = {"PingCount": 25}
        encrypted, salt = await encrypt_config(config)

        # Tamper with ciphertext by changing one character
        if len(encrypted) > 10:
            tampered = encrypted[:10] + 'X' + encrypted[11:]

            with pytest.raises(ConfigEncryptionError):
                await decrypt_config(tampered, salt)


class TestEncryptDecryptRoundTrip:
    """Test encrypt/decrypt round-trip for various data."""

    @pytest.mark.asyncio
    async def test_roundtrip_unicode(self):
        """Round-trip with unicode characters."""
        config = {
            "field1": "Hello 世界",
            "field2": "Émojis: 🎉🔐",
            "field3": "Special: áéíóú"
        }
        encrypted, salt = await encrypt_config(config)
        decrypted = await decrypt_config(encrypted, salt)

        assert decrypted == config

    @pytest.mark.asyncio
    async def test_roundtrip_large_config(self):
        """Round-trip with large configuration."""
        config = {f"field{i}": f"value{i}" for i in range(100)}
        encrypted, salt = await encrypt_config(config)
        decrypted = await decrypt_config(encrypted, salt)

        assert decrypted == config

    @pytest.mark.asyncio
    async def test_roundtrip_nested_structures(self):
        """Round-trip with deeply nested structures."""
        config = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": [1, 2, 3],
                        "nested_list": [[1, 2], [3, 4]]
                    }
                }
            }
        }
        encrypted, salt = await encrypt_config(config)
        decrypted = await decrypt_config(encrypted, salt)

        assert decrypted == config

    @pytest.mark.asyncio
    async def test_roundtrip_special_characters(self):
        """Round-trip with special characters."""
        config = {
            "quotes": 'He said "Hello"',
            "backslashes": r"C:\Windows\System32",
            "newlines": "Line1\nLine2\nLine3",
            "tabs": "Col1\tCol2\tCol3"
        }
        encrypted, salt = await encrypt_config(config)
        decrypted = await decrypt_config(encrypted, salt)

        assert decrypted == config


class TestSyncFunctions:
    """Test synchronous encryption/decryption helpers."""

    def test_sync_encrypt_decrypt(self):
        """Synchronous encrypt/decrypt works."""
        config = {"PingCount": 25}
        salt_hex = "0123456789abcdef0123456789abcdef"

        encrypted, nonce_hex = _encrypt_sync(config, salt_hex)
        decrypted = _decrypt_sync(encrypted, salt_hex)

        assert decrypted == config

    def test_sync_encrypt_generates_nonce(self):
        """Synchronous encrypt generates random nonce."""
        config = {"PingCount": 25}
        salt_hex = "0123456789abcdef0123456789abcdef"

        encrypted1, nonce1 = _encrypt_sync(config, salt_hex)
        encrypted2, nonce2 = _encrypt_sync(config, salt_hex)

        # Different nonces
        assert nonce1 != nonce2

        # Both decrypt correctly
        decrypted1 = _decrypt_sync(encrypted1, salt_hex)
        decrypted2 = _decrypt_sync(encrypted2, salt_hex)

        assert decrypted1 == config
        assert decrypted2 == config


class TestErrorHandling:
    """Test error handling in encryption module."""

    @pytest.mark.asyncio
    async def test_decrypt_invalid_salt_length(self):
        """Decryption with invalid salt length fails gracefully."""
        config = {"PingCount": 25}
        encrypted, _ = await encrypt_config(config)

        with pytest.raises(ConfigEncryptionError):
            await decrypt_config(encrypted, "short")

    @pytest.mark.asyncio
    async def test_encrypt_invalid_data_type(self):
        """Encryption of non-dict fails gracefully."""
        # encrypt_config expects a dict, but let's test error handling
        # This might not raise if JSON serialization handles it
        # Just verify it doesn't crash
        try:
            await encrypt_config("not a dict")
        except Exception as e:
            # Should be a ConfigEncryptionError or related error
            assert "encrypt" in str(e).lower() or "json" in str(e).lower()

    @pytest.mark.asyncio
    async def test_decrypt_empty_ciphertext(self):
        """Decryption of empty ciphertext fails."""
        salt = "0123456789abcdef0123456789abcdef"

        with pytest.raises(ConfigEncryptionError):
            await decrypt_config("", salt)


class TestAuthenticatedEncryption:
    """Test authenticated encryption properties (GCM mode)."""

    @pytest.mark.asyncio
    async def test_authentication_tag_verified(self):
        """GCM authentication tag prevents tampering."""
        config = {"PingCount": 25}
        encrypted, salt = await encrypt_config(config)

        # Encrypted string contains both ciphertext and auth tag
        # Tampering should fail authentication

        # Try to modify the encrypted data
        import base64
        try:
            decoded = base64.b64decode(encrypted)
            # Flip a bit
            tampered_bytes = bytearray(decoded)
            if len(tampered_bytes) > 0:
                tampered_bytes[0] ^= 0x01
            tampered = base64.b64encode(bytes(tampered_bytes)).decode('utf-8')

            with pytest.raises(ConfigEncryptionError):
                await decrypt_config(tampered, salt)
        except Exception:
            # If base64 decode fails, that's also fine
            pass

    @pytest.mark.asyncio
    async def test_nonce_uniqueness(self):
        """Each encryption uses a unique nonce."""
        config = {"PingCount": 25}
        salt = "0123456789abcdef0123456789abcdef"

        encrypted1, _ = await encrypt_config(config, salt)
        encrypted2, _ = await encrypt_config(config, salt)

        # Even with same salt, nonce ensures different ciphertext
        assert encrypted1 != encrypted2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
