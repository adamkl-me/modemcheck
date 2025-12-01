"""
User model for authentication and authorization.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Enum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class UserRole(str, enum.Enum):
    """User roles for RBAC."""
    ADMIN = "admin"
    ELEVATED = "elevated"
    BASIC = "basic"


class User(Base):
    """
    User model for authentication.

    Roles:
    - admin: Full access (user management, delete operations, all logs)
    - elevated: API key management, bulk operations, client logs
    - basic: View data, change own password
    """
    __tablename__ = "users"

    username = Column(String(255), primary_key=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(
        Enum(UserRole, name="user_role", native_enum=False),
        nullable=False,
        default=UserRole.BASIC,
        index=True
    )
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45), nullable=True)  # IPv6 compatible
    must_change_password = Column(Boolean, nullable=False, default=False)

    def __repr__(self):
        return f"<User(username='{self.username}', role='{self.role}')>"

    def has_role(self, role: UserRole) -> bool:
        """Check if user has specific role."""
        return self.role == role

    def is_admin(self) -> bool:
        """Check if user is admin."""
        return self.role == UserRole.ADMIN

    def is_elevated_or_admin(self) -> bool:
        """Check if user is elevated or admin."""
        return self.role in (UserRole.ADMIN, UserRole.ELEVATED)
