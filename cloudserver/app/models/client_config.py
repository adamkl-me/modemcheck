"""
Client Configuration Management models.

These models support centralized configuration management for ModemCheck clients,
allowing server-side control and locking of client configurations with encryption,
versioning, and audit trails.

Version 2.0: Dual-track versioning (v#_client / v#_server) with 6 status states.
"""
from datetime import datetime, timedelta
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, Index,
    ForeignKey, BigInteger, Enum, CheckConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
import enum

from app.core.database import Base


class ConfigStatus(str, enum.Enum):
    """
    Configuration status states.

    Replaces the old ConfigMode enum with more granular states that track
    both the management mode and the sync state.
    """
    UNMANAGED = "unmanaged"                      # Client-controlled, server just stores
    ONE_TIME_READY = "one_time_ready"            # Server has config ready to push
    ONE_TIME_ACTIVE = "one_time_active"          # Client received and using server config
    ENFORCED_READY = "enforced_ready"            # Server has config ready to enforce
    ENFORCED_ACTIVE = "enforced_active"          # Client using enforced config
    AWAITING_FIRST_SYNC = "awaiting_first_sync"  # Admin pre-created, no client sync yet


# Keep ConfigMode as alias for backward compatibility during transition
ConfigMode = ConfigStatus


class ClientConfig(Base):
    """
    Main configuration storage for clients.

    Stores both plaintext (for admin viewing) and encrypted configs (for security).
    Tracks sync state, dual-track versions, and status.

    Primary key: api_key only (one config per API key)

    Dual-Track Versioning:
    - client_version: Latest v#_client number (configs from client)
    - server_version: Latest v#_server number (configs from admin)
    - active_track: Which track is currently in use ("client" or "server")
    """
    __tablename__ = "client_configs"

    # Primary key - single API key (one config per key)
    api_key = Column(String(255), ForeignKey("api_keys.api_key", ondelete="CASCADE"),
                     primary_key=True, nullable=False)

    # Modem tracking (metadata only, not part of key)
    last_seen_modem_id = Column(String(255), nullable=True, index=True)

    # Configuration data (dual storage for security + usability)
    config_plaintext = Column(JSONB, nullable=False)  # For admin viewing/editing
    config_encrypted = Column(Text, nullable=False)   # AES-256-GCM encrypted blob
    config_hash = Column(String(64), nullable=False)  # SHA256 of canonical JSON

    # Status (replaces mode)
    status = Column(
        Enum(ConfigStatus, name="config_status", native_enum=False),
        nullable=False,
        default=ConfigStatus.UNMANAGED,
        index=True
    )

    # For AWAITING_FIRST_SYNC: what mode to become after first client sync
    # Values: "unmanaged", "one_time", "enforced"
    target_mode = Column(String(20), nullable=True)

    # Dual-track versioning
    client_version = Column(Integer, nullable=False, default=0)  # Latest v#_client
    server_version = Column(Integer, nullable=False, default=0)  # Latest v#_server
    active_track = Column(String(10), nullable=False, default="client")  # "client" or "server"

    # Track what version the client has acknowledged receiving
    client_acked_version = Column(Integer, nullable=True)  # Version number client confirmed
    client_acked_track = Column(String(10), nullable=True)  # Track of confirmed version

    # Sync metadata
    last_sync = Column(DateTime, nullable=True, index=True)

    # Encryption metadata
    encryption_salt = Column(String(32), nullable=False)  # Random salt for encryption

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by = Column(String(255), nullable=False)  # Username who created config
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String(255), nullable=False)  # Username who last updated config

    # Indexes for performance
    __table_args__ = (
        # Covering index for sync endpoint (api_key is PK, so just add other fields)
        Index('idx_client_config_sync', 'status', 'client_version', 'server_version',
              'config_encrypted', 'config_hash', 'encryption_salt'),

        # Index for monitoring stale syncs (managed configs not synced in 48h)
        Index('idx_client_config_stale', 'last_sync', 'status',
              postgresql_where=(
                  (status == ConfigStatus.ONE_TIME_ACTIVE) |
                  (status == ConfigStatus.ENFORCED_ACTIVE) |
                  (status == ConfigStatus.ENFORCED_READY) |
                  (status == ConfigStatus.ONE_TIME_READY)
              )),

        # Index for admin dashboard filtering
        Index('idx_client_config_status_updated', 'status', 'updated_at'),

        # Index for SSE change detection
        Index('idx_client_config_updated_at', 'updated_at'),

        # Index for last seen modem tracking
        Index('idx_client_config_last_modem', 'last_seen_modem_id'),
    )

    @property
    def active_version_display(self) -> str:
        """Get the display string for the active version (e.g., 'v3_client')."""
        if self.active_track == "server":
            return f"v{self.server_version}_server"
        return f"v{self.client_version}_client"

    @property
    def is_managed(self) -> bool:
        """Check if this config is server-managed (not unmanaged)."""
        return self.status not in (ConfigStatus.UNMANAGED, ConfigStatus.AWAITING_FIRST_SYNC)

    def __repr__(self):
        modem_display = self.last_seen_modem_id or 'never synced'
        return f"<ClientConfig(api_key='{self.api_key[:8]}...', last_modem='{modem_display}', status='{self.status}', version={self.active_version_display})>"


class ConfigVersion(Base):
    """
    Stores all configuration versions for history and rollback.

    Replaces the old ConfigBackup table with a more comprehensive version history
    that tracks both client and server version tracks.

    Each version is immutable once created - represents a point-in-time snapshot.
    """
    __tablename__ = "config_versions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Reference to config (api_key is the primary reference)
    api_key = Column(String(255), nullable=False, index=True)

    # Modem ID at time of creation (for tracking/audit, nullable)
    modem_id_at_creation = Column(String(255), nullable=True, index=True)

    # Version identification
    version_number = Column(Integer, nullable=False)  # 1, 2, 3...
    version_track = Column(String(10), nullable=False)  # "client" or "server"
    version_display = Column(String(20), nullable=False)  # "v3_client" or "v1_server"

    # Configuration snapshot
    config_plaintext = Column(JSONB, nullable=False)
    config_encrypted = Column(Text, nullable=False)
    config_hash = Column(String(64), nullable=False)
    encryption_salt = Column(String(32), nullable=False)

    # Status at time of creation
    status_at_creation = Column(
        Enum(ConfigStatus, name="config_status", native_enum=False),
        nullable=False
    )

    # Metadata
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by = Column(String(255), nullable=False)  # Username or "client"
    creation_reason = Column(String(255), nullable=False)  # "client_sync", "admin_update", "client_rejected_enforced", etc.
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible

    __table_args__ = (
        # Unique constraint: only one version per api_key per track per number
        Index('idx_config_version_unique', 'api_key', 'version_track', 'version_number', unique=True),

        # History lookup
        Index('idx_config_version_history', 'api_key', 'created_at'),

        # Track filtering
        Index('idx_config_version_track', 'api_key', 'version_track', 'created_at'),

        # Retention cleanup (90-day retention)
        Index('idx_config_version_retention', 'created_at'),

        # Modem ID tracking (for history display)
        Index('idx_config_version_modem', 'modem_id_at_creation'),
    )

    def __repr__(self):
        modem_display = self.modem_id_at_creation or 'unknown'
        return f"<ConfigVersion(api_key='{self.api_key[:8]}...', modem='{modem_display}', version={self.version_display})>"


class ConfigAuditLog(Base):
    """
    Audit trail for all configuration operations.

    Partitioned by month for scalability (table_name: config_audit_log_YYYYMM).
    Records all config changes with sensitive field redaction.
    90-day retention policy.
    """
    __tablename__ = "config_audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Timestamp (partition key)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Actor information
    username = Column(String(255), nullable=True, index=True)  # NULL for client-initiated
    api_key_hash = Column(String(64), nullable=True, index=True)  # SHA256 of API key
    ip_address = Column(String(45), nullable=False)  # IPv6 compatible

    # Target configuration
    api_key = Column(String(255), nullable=False, index=True)

    # Modem ID tracking (nullable - may not be known for admin operations)
    modem_id = Column(String(255), nullable=True, index=True)

    # Modem change tracking
    old_modem_id = Column(String(255), nullable=True)  # Previous modem ID (for modem_change events)
    new_modem_id = Column(String(255), nullable=True)  # New modem ID (for modem_change events)

    # Action details
    action = Column(String(100), nullable=False, index=True)  # "sync", "update", "rollback", "status_change", "modem_change"
    config_summary = Column(JSONB, nullable=True)  # Changed field names only (no values)

    # Version tracking (now using dual-track format)
    old_version = Column(String(20), nullable=True)  # "v1_client" format
    new_version = Column(String(20), nullable=True)  # "v2_client" format
    old_status = Column(
        Enum(ConfigStatus, name="config_status", native_enum=False),
        nullable=True
    )
    new_status = Column(
        Enum(ConfigStatus, name="config_status", native_enum=False),
        nullable=True
    )

    # Result
    success = Column(Boolean, nullable=False, index=True)
    failure_reason = Column(Text, nullable=True)

    # NOTE: Table partitioning must be created manually via SQL
    # SQLAlchemy does not support declarative partitioning - use migration script
    # See scripts/init_config_partitions.sql for parent table creation
    # See scripts/create_audit_partition.sh for monthly partition creation
    __table_args__ = (
        # Composite indexes (will be created on each partition)
        Index('idx_config_audit_client', 'api_key', 'timestamp'),
        Index('idx_config_audit_user_action', 'username', 'action', 'timestamp'),
        Index('idx_config_audit_action_success', 'action', 'success', 'timestamp'),
        Index('idx_config_audit_modem_change', 'api_key', 'action', 'timestamp',
              postgresql_where=(action == 'modem_change')),
    )

    def __repr__(self):
        modem_display = self.modem_id or 'N/A'
        return f"<ConfigAuditLog(action='{self.action}', modem='{modem_display}', success={self.success})>"


class ConfigNonce(Base):
    """
    Replay attack prevention via nonce tracking.

    Stores used nonces with expiration timestamps.
    Redis is primary store (fast), PostgreSQL is fallback (durable).
    Hourly cleanup job removes expired nonces.
    """
    __tablename__ = "config_nonces"

    nonce = Column(String(64), primary_key=True, nullable=False)  # SHA256 hex string

    # Request metadata for debugging
    api_key_hash = Column(String(64), nullable=False, index=True)
    request_timestamp = Column(DateTime, nullable=False)

    # Expiration (automatically set to request_timestamp + 5 minutes)
    expires_at = Column(DateTime, nullable=False, index=True)

    # Client identification
    ip_address = Column(String(45), nullable=False)
    modem_id = Column(String(255), nullable=True)

    __table_args__ = (
        # Index for cleanup job (delete where expires_at < now())
        Index('idx_config_nonce_expiration', 'expires_at'),

        # Index for API key monitoring (detect replay attempts)
        Index('idx_config_nonce_api_key', 'api_key_hash', 'request_timestamp'),

        # Check constraint: expires_at must be after request_timestamp
        CheckConstraint('expires_at > request_timestamp', name='check_nonce_expiration'),
    )

    def __repr__(self):
        return f"<ConfigNonce(nonce='{self.nonce[:16]}...', expires_at={self.expires_at})>"

    @classmethod
    def create_with_expiry(cls, nonce: str, api_key_hash: str, request_timestamp: datetime,
                          ip_address: str, modem_id: str = None, ttl_seconds: int = 300):
        """
        Create a nonce with automatic expiration time.

        Args:
            nonce: Unique nonce string (SHA256 hex)
            api_key_hash: SHA256 of API key
            request_timestamp: Timestamp from client request (will be converted to naive UTC)
            ip_address: Client IP address
            modem_id: Optional modem ID
            ttl_seconds: Time-to-live in seconds (default: 5 minutes)

        Returns:
            ConfigNonce instance
        """
        # Convert timezone-aware datetime to naive UTC for database storage
        # (PostgreSQL columns are TIMESTAMP WITHOUT TIME ZONE)
        if request_timestamp.tzinfo is not None:
            request_timestamp = request_timestamp.replace(tzinfo=None)

        expires_at = request_timestamp + timedelta(seconds=ttl_seconds)
        return cls(
            nonce=nonce,
            api_key_hash=api_key_hash,
            request_timestamp=request_timestamp,
            expires_at=expires_at,
            ip_address=ip_address,
            modem_id=modem_id
        )


# Backward compatibility: Keep ConfigBackup as alias for ConfigVersion
# This allows gradual migration of code that references ConfigBackup
ConfigBackup = ConfigVersion
