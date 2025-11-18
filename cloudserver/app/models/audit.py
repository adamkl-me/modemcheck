"""
Audit logging models for tracking user activity and client submissions.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Index

from app.core.database import Base


class UserActivityLog(Base):
    """
    Audit log for user actions (login, logout, admin operations, etc.).

    Tracks all security-relevant user actions for compliance and security monitoring.
    """
    __tablename__ = "user_activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    username = Column(String(255), nullable=False, index=True)
    user_role = Column(String(50), nullable=True)
    action_type = Column(String(100), nullable=False, index=True)
    action_details = Column(Text, nullable=True)  # JSON string with additional details
    ip_address = Column(String(45), nullable=False, index=True)  # IPv6 compatible
    user_agent = Column(Text, nullable=True)
    session_id = Column(String(255), nullable=True)
    success = Column(Boolean, nullable=False)
    failure_reason = Column(Text, nullable=True)

    __table_args__ = (
        Index('idx_user_activity_username_timestamp', 'username', 'timestamp'),
        Index('idx_user_activity_action_timestamp', 'action_type', 'timestamp'),
        Index('idx_user_activity_ip_timestamp', 'ip_address', 'timestamp'),
    )

    def __repr__(self):
        return f"<UserActivityLog(username='{self.username}', action='{self.action_type}', success={self.success})>"


class ClientSubmissionLog(Base):
    """
    Audit log for client check submissions.

    Tracks all modem check uploads from Go clients for monitoring and debugging.
    """
    __tablename__ = "client_submission_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    ip_address = Column(String(45), nullable=False, index=True)  # IPv6 compatible
    api_key_hash = Column(String(255), nullable=False, index=True)  # SHA256 hash of API key
    api_key_name = Column(String(255), nullable=True)
    modem_id = Column(String(255), nullable=False, index=True)
    modem_type = Column(String(100), nullable=True)
    modem_mac = Column(String(17), nullable=True)  # MAC address format: XX:XX:XX:XX:XX:XX
    filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=True)
    check_time = Column(DateTime, nullable=True)
    user_agent = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False)
    failure_reason = Column(Text, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)

    __table_args__ = (
        Index('idx_client_submission_api_key_timestamp', 'api_key_hash', 'timestamp'),
        Index('idx_client_submission_modem_timestamp', 'modem_id', 'timestamp'),
        Index('idx_client_submission_ip_timestamp', 'ip_address', 'timestamp'),
    )

    def __repr__(self):
        return f"<ClientSubmissionLog(modem_id='{self.modem_id}', success={self.success})>"
