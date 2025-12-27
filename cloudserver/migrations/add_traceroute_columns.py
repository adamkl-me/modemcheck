#!/usr/bin/env python3
"""
Migration: Add traceroute columns to modem_checks table

This migration adds two columns to store traceroute diagnostic results:
- traceroute_google_hops: Number of hops to reach 8.8.8.8
- traceroute_google_status: Status of the traceroute (success, failed, timeout)

These columns support the v9.3.0 traceroute feature in the Go client.

Run with: python3 migrations/add_traceroute_columns.py upgrade|downgrade|verify
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import engine


async def upgrade():
    """Add traceroute columns to modem_checks table."""
    print("=" * 60)
    print("Migration: Add Traceroute Columns")
    print("=" * 60)
    print()

    async with engine.begin() as conn:
        # Add traceroute_google_hops column
        print("1. Adding traceroute_google_hops column...")
        await conn.execute(text("""
            ALTER TABLE modem_checks
            ADD COLUMN IF NOT EXISTS traceroute_google_hops INTEGER NULL;
        """))
        print("   Done")
        print()

        # Add traceroute_google_status column
        print("2. Adding traceroute_google_status column...")
        await conn.execute(text("""
            ALTER TABLE modem_checks
            ADD COLUMN IF NOT EXISTS traceroute_google_status VARCHAR(50) NULL;
        """))
        print("   Done")
        print()

    print("=" * 60)
    print("Migration completed successfully!")
    print("=" * 60)
    print()
    print("Columns added:")
    print("  - traceroute_google_hops (INTEGER, nullable)")
    print("  - traceroute_google_status (VARCHAR(50), nullable)")
    print()


async def downgrade():
    """Remove traceroute columns from modem_checks table."""
    print("=" * 60)
    print("Rollback: Remove Traceroute Columns")
    print("=" * 60)
    print()

    async with engine.begin() as conn:
        # Drop traceroute_google_hops column
        print("1. Dropping traceroute_google_hops column...")
        await conn.execute(text("""
            ALTER TABLE modem_checks
            DROP COLUMN IF EXISTS traceroute_google_hops;
        """))
        print("   Done")
        print()

        # Drop traceroute_google_status column
        print("2. Dropping traceroute_google_status column...")
        await conn.execute(text("""
            ALTER TABLE modem_checks
            DROP COLUMN IF EXISTS traceroute_google_status;
        """))
        print("   Done")
        print()

    print("=" * 60)
    print("Rollback completed successfully!")
    print("=" * 60)
    print()


async def verify():
    """Verify the traceroute columns exist."""
    print("=" * 60)
    print("Verification: Traceroute Columns")
    print("=" * 60)
    print()

    async with engine.begin() as conn:
        # Check if columns exist
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'modem_checks'
            AND column_name IN ('traceroute_google_hops', 'traceroute_google_status')
            ORDER BY column_name;
        """))
        columns = result.fetchall()

        if len(columns) == 2:
            print("Columns found:")
            for col in columns:
                print(f"  - {col[0]}: {col[1]} (nullable: {col[2]})")
            print()

            # Show sample data if any exists
            count_result = await conn.execute(text("""
                SELECT
                    COUNT(*) as total,
                    COUNT(traceroute_google_hops) as with_hops,
                    COUNT(traceroute_google_status) as with_status
                FROM modem_checks;
            """))
            counts = count_result.fetchone()
            print("Data statistics:")
            print(f"  Total modem checks: {counts[0]}")
            print(f"  With traceroute hops: {counts[1]}")
            print(f"  With traceroute status: {counts[2]}")
            print()

            return True
        else:
            found = [col[0] for col in columns]
            missing = set(['traceroute_google_hops', 'traceroute_google_status']) - set(found)
            print(f"Missing columns: {missing}")
            print()
            return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Traceroute Columns Migration")
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
        success = asyncio.run(verify())
        sys.exit(0 if success else 1)
