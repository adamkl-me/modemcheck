#!/usr/bin/env python3
"""
Migration: Drop old v2 config indexes replaced by v3

This migration removes old index names that were replaced when upgrading
to the v3 config model. The v3 indexes have improved naming and structure.

Old indexes being dropped:
- idx_client_config_sync (replaced by idx_client_config_sync_v3)
- idx_client_config_stale (replaced by idx_client_config_stale_v3)
- idx_client_config_status_updated (replaced by idx_client_config_status_updated_v3)
- idx_config_version_track (replaced by idx_config_version_unique_v3)

Run with: python3 migrations/drop_old_config_indexes.py upgrade
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import engine


OLD_INDEXES = [
    "idx_client_config_sync",
    "idx_client_config_stale",
    "idx_client_config_status_updated",
    "idx_config_version_track",
]


async def upgrade():
    """Drop old v2 indexes that were replaced by v3 indexes."""
    print("=" * 60)
    print("Migration: Drop Old Config Indexes (v2 -> v3)")
    print("=" * 60)
    print()

    async with engine.begin() as conn:
        for index_name in OLD_INDEXES:
            print(f"Dropping index: {index_name}...")
            await conn.execute(text(f"DROP INDEX IF EXISTS {index_name};"))
            print(f"   ✓ Dropped (if existed)")

        print()

    print("=" * 60)
    print("Migration completed successfully!")
    print("=" * 60)
    print()
    print("Dropped indexes:")
    for idx in OLD_INDEXES:
        print(f"  - {idx}")
    print()
    print("These were replaced by v3 equivalents defined in the model.")
    print()


async def downgrade():
    """
    Rollback not supported - old indexes would need to be recreated manually
    based on old schema definitions. The v3 indexes cover the same use cases.
    """
    print("=" * 60)
    print("Rollback: Not Supported")
    print("=" * 60)
    print()
    print("The old indexes were replaced by v3 equivalents.")
    print("Manual recreation would require old schema definitions.")
    print("The v3 indexes provide equivalent functionality.")
    print()


async def verify():
    """Verify old indexes are gone and new indexes exist."""
    print("=" * 60)
    print("Verification: Config Index Status")
    print("=" * 60)
    print()

    async with engine.begin() as conn:
        # Check for old indexes (should not exist)
        print("Old indexes (should NOT exist):")
        for index_name in OLD_INDEXES:
            result = await conn.execute(text(f"""
                SELECT 1 FROM pg_indexes
                WHERE indexname = '{index_name}';
            """))
            exists = result.fetchone() is not None
            status = "✗ EXISTS (needs cleanup)" if exists else "✓ Not found (good)"
            print(f"  {index_name}: {status}")

        print()

        # Check for v3 indexes (should exist)
        print("New v3 indexes (should exist):")
        v3_indexes = [
            "idx_client_config_sync_v3",
            "idx_client_config_stale_v3",
            "idx_client_config_status_updated_v3",
            "idx_config_version_unique_v3",
        ]
        for index_name in v3_indexes:
            result = await conn.execute(text(f"""
                SELECT 1 FROM pg_indexes
                WHERE indexname = '{index_name}';
            """))
            exists = result.fetchone() is not None
            status = "✓ Exists" if exists else "✗ MISSING"
            print(f"  {index_name}: {status}")

        print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Drop Old Config Index Migration")
    parser.add_argument(
        "action",
        choices=["upgrade", "downgrade", "verify"],
        help="Migration action to perform"
    )
    args = parser.parse_args()

    if args.action == "upgrade":
        asyncio.run(upgrade())
    elif args.action == "downgrade":
        asyncio.run(downgrade())
    elif args.action == "verify":
        asyncio.run(verify())
