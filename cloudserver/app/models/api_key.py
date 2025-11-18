"""
API Key model for client authentication.
"""
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime

from app.core.database import Base


class APIKey(Base):
    """
    API Key model for authenticating Go clients.

    The api_key field stores the raw API key (used for HMAC validation).
    API keys are created by admin/elevated users through the admin interface.
    """
    __tablename__ = "api_keys"

    api_key = Column(String(255), primary_key=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    def __repr__(self):
        return f"<APIKey(name='{self.name}', active={self.is_active})>"

    def update_last_used(self):
        """Update the last_used timestamp to current time."""
        self.last_used = datetime.utcnow()
