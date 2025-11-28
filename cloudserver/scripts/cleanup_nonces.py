#!/usr/bin/env python3
"""
Clean up expired nonces from config_nonces table.

This script removes nonces that have expired (expires_at < now()).
Should be run hourly via cron to prevent table bloat.

Redis is the primary nonce store (with automatic expiration), but we also
store nonces in PostgreSQL for durability. This script cleans up the PostgreSQL table.

Usage:
    ./cleanup_nonces.py [--dry-run] [--batch-size SIZE]

Options:
    --dry-run       Show what would be deleted without deleting
    --batch-size    Number of nonces to delete per batch (default: 1000)

Cron example (run every hour at :15):
    15 * * * * /opt/modemcheck/cloudserver/scripts/cleanup_nonces.py >> /var/log/modemcheck/nonce-cleanup.log 2>&1
"""

import sys
import os
import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, delete, func
from app.core.database import init_db, close_db, get_db_context
from app.models.client_config import ConfigNonce


async def cleanup_nonces(dry_run: bool = False, batch_size: int = 1000) -> tuple[int, int]:
    """
    Clean up expired nonces from database.

    Args:
        dry_run: If True, count expired nonces but don't delete
        batch_size: Number of nonces to delete per batch

    Returns:
        Tuple of (total_expired, total_deleted)
    """
    async with get_db_context() as db:
        # Count total expired nonces
        count_query = select(func.count(ConfigNonce.nonce)).where(
            ConfigNonce.expires_at < datetime.now(timezone.utc)
        )
        result = await db.execute(count_query)
        total_expired = result.scalar() or 0

        if total_expired == 0:
            return 0, 0

        if dry_run:
            print(f"DRY RUN: Would delete {total_expired} expired nonces")
            return total_expired, 0

        # Delete in batches to avoid long-running transactions
        total_deleted = 0
        while total_deleted < total_expired:
            # Delete one batch
            delete_query = delete(ConfigNonce).where(
                ConfigNonce.expires_at < datetime.now(timezone.utc)
            ).execution_options(synchronize_session=False)

            # PostgreSQL doesn't support LIMIT on DELETE, so we use a subquery
            # to get the nonces to delete in this batch
            subquery = (
                select(ConfigNonce.nonce)
                .where(ConfigNonce.expires_at < datetime.now(timezone.utc))
                .limit(batch_size)
                .subquery()
            )

            batch_delete = delete(ConfigNonce).where(
                ConfigNonce.nonce.in_(select(subquery))
            ).execution_options(synchronize_session=False)

            result = await db.execute(batch_delete)
            await db.commit()

            deleted_count = result.rowcount
            total_deleted += deleted_count

            print(f"Deleted {deleted_count} expired nonces (total: {total_deleted}/{total_expired})")

            # If we deleted fewer than batch_size, we're done
            if deleted_count < batch_size:
                break

        return total_expired, total_deleted


async def get_nonce_stats():
    """Get statistics about nonces in the database."""
    async with get_db_context() as db:
        # Total nonces
        total_query = select(func.count(ConfigNonce.nonce))
        result = await db.execute(total_query)
        total = result.scalar() or 0

        # Expired nonces
        expired_query = select(func.count(ConfigNonce.nonce)).where(
            ConfigNonce.expires_at < datetime.now(timezone.utc)
        )
        result = await db.execute(expired_query)
        expired = result.scalar() or 0

        # Active nonces
        active = total - expired

        # Oldest nonce
        oldest_query = select(func.min(ConfigNonce.request_timestamp))
        result = await db.execute(oldest_query)
        oldest = result.scalar()

        return {
            "total": total,
            "active": active,
            "expired": expired,
            "oldest_timestamp": oldest
        }


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Clean up expired nonces from config_nonces table"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of nonces to delete per batch (default: 1000)"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show nonce statistics and exit"
    )

    args = parser.parse_args()

    # Initialize database
    init_db()

    try:
        print(f"Nonce Cleanup - {datetime.now(timezone.utc).isoformat()}")
        print("=" * 60)

        # Show stats if requested
        if args.stats:
            stats = await get_nonce_stats()
            print(f"Total nonces: {stats['total']}")
            print(f"Active nonces: {stats['active']}")
            print(f"Expired nonces: {stats['expired']}")
            if stats['oldest_timestamp']:
                print(f"Oldest nonce: {stats['oldest_timestamp'].isoformat()}")
            return 0

        # Get stats before cleanup
        stats_before = await get_nonce_stats()
        print(f"Nonces before cleanup:")
        print(f"  Total: {stats_before['total']}")
        print(f"  Active: {stats_before['active']}")
        print(f"  Expired: {stats_before['expired']}")
        print()

        if stats_before['expired'] == 0:
            print("No expired nonces to clean up.")
            return 0

        # Perform cleanup
        total_expired, total_deleted = await cleanup_nonces(
            dry_run=args.dry_run,
            batch_size=args.batch_size
        )

        if not args.dry_run:
            # Get stats after cleanup
            stats_after = await get_nonce_stats()
            print()
            print(f"Nonces after cleanup:")
            print(f"  Total: {stats_after['total']}")
            print(f"  Active: {stats_after['active']}")
            print(f"  Expired: {stats_after['expired']}")
            print()
            print(f"Cleanup complete: {total_deleted} nonces deleted")

        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Close database connection
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
