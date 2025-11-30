"""
Make ConfigAuditLog.api_key nullable for security.

This migration makes the api_key field nullable in config_audit_logs table,
allowing us to store only hashed API keys (api_key_hash) instead of plaintext.

Run with: python3 make_audit_api_key_nullable.py
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import get_async_session_maker, async_engine


async def make_api_key_nullable():
    """Make api_key field nullable in config_audit_logs table."""

    print("Making config_audit_logs.api_key nullable...")

    async with async_engine.begin() as conn:
        # Make api_key column nullable
        await conn.execute(text("""
            ALTER TABLE config_audit_logs
            ALTER COLUMN api_key DROP NOT NULL;
        """))

        print("✓ api_key column is now nullable")

    print("\n✓ Migration completed successfully")


if __name__ == "__main__":
    asyncio.run(make_api_key_nullable())
