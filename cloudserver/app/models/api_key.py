"""
API Key model for client authentication.
"""
from sqlalchemy import Column, String, Boolean, DateTime, Index

from app.core.database import Base
from app.core.utils import utc_now


class APIKey(Base):
    """
    API Key model for authenticating Go clients.

    The api_key field stores the raw API key (used for HMAC validation).
    API keys are created by admin/elevated users through the admin interface.
    """
    __tablename__ = "api_keys"

    api_key = Column(String(255), primary_key=True, nullable=False)
    name = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    last_used = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Partial index for active keys (PostgreSQL-specific optimization)
    # Only indexes rows where is_active = TRUE, making the index smaller and faster
    __table_args__ = (
        Index('idx_api_key_active', 'is_active', postgresql_where=(is_active == True)),
    )

    def __repr__(self):
        return f"<APIKey(name='{self.name}', active={self.is_active})>"

    def update_last_used(self):
        """Update the last_used timestamp to current time."""
        self.last_used = utc_now()
