"""
API Key model for client authentication.
"""
from sqlalchemy import Column, String, Text, Boolean, DateTime, Index

from app.core.database import Base
from app.core.utils import utc_now


class APIKey(Base):
    """
    API Key model for authenticating Go clients.

    HASH-BASED STORAGE (v8.0+):
    - api_key_hash: SHA-256 hash (PRIMARY KEY - used for all lookups)
    - api_key_encrypted: AES-256-GCM encrypted plaintext (for admin reveal)
    - encryption_salt: Random salt for encryption (16 bytes as hex)

    Security:
    - Hash-based validation prevents plaintext exposure in queries/cache
    - Encrypted storage allows admin reveal functionality
    - Salt-based encryption provides defense-in-depth
    - Plaintext API key is NEVER stored in database

    API keys are created by admin/elevated users through the admin interface.
    Clients send plaintext in requests; server hashes for validation.
    """
    __tablename__ = "api_keys"

    # Primary key - SHA-256 hash of plaintext API key (64 hex chars)
    # Plaintext is NEVER stored; only hash for validation + encrypted for reveal
    api_key_hash = Column(String(64), primary_key=True, nullable=False)

    # Encrypted storage for admin reveal functionality
    api_key_encrypted = Column(Text, nullable=False)  # AES-256-GCM ciphertext
    encryption_salt = Column(String(32), nullable=False)  # 16-byte salt as hex (32 chars)

    # Metadata columns
    name = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    last_used = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Indexes for performance
    # Partial index for active keys (PostgreSQL-specific optimization)
    __table_args__ = (
        Index('idx_api_key_active', 'is_active', postgresql_where=(is_active == True)),
    )

    def __repr__(self):
        return f"<APIKey(name='{self.name}', active={self.is_active})>"

    def update_last_used(self):
        """Update the last_used timestamp to current time."""
        self.last_used = utc_now()
