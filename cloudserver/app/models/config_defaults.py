"""
Config defaults model for storing default configuration values.
"""
from sqlalchemy import Column, Integer, JSON, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ConfigDefaults(Base):
    """
    Model for storing default configuration values.

    This stores a single row with default values for the config generator.
    Only one row should exist in this table.
    """
    __tablename__ = "config_defaults"

    id = Column(Integer, primary_key=True, index=True)
    defaults = Column(JSON, nullable=False)  # Stores the default configuration as JSON
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ConfigDefaults(id={self.id})>"
