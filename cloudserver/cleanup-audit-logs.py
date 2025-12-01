#!/usr/bin/env python3
"""
Audit log cleanup script.

Runs audit log retention policy to delete old logs and prevent database bloat.

Usage:
    # Use default 90-day retention
    python cleanup-audit-logs.py

    # Custom retention periods
    python cleanup-audit-logs.py --user-retention 60 --client-retention 120

    # Dry run (show what would be deleted without deleting)
    python cleanup-audit-logs.py --dry-run

    # Show statistics only
    python cleanup-audit-logs.py --stats-only
"""
import asyncio
import argparse
import sys
from datetime import datetime, timedelta, timezone

from app.core.database import AsyncSessionLocal
from app.core.audit_retention import (
    cleanup_all_audit_logs,
    get_audit_log_statistics,
    cleanup_old_user_activity_logs,
    cleanup_old_client_submission_logs
)


async def main():
    parser = argparse.ArgumentParser(description="Clean up old audit logs")
    parser.add_argument(
        "--user-retention",
        type=int,
        default=90,
        help="Days to retain user activity logs (default: 90)"
    )
    parser.add_argument(
        "--client-retention",
        type=int,
        default=90,
        help="Days to retain client submission logs (default: 90)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Show statistics only (no cleanup)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        print("=" * 70)
        print("ModemCheck Audit Log Cleanup")
        print("=" * 70)
        print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
        print()

        # Show current statistics
        print("Current Audit Log Statistics:")
        print("-" * 70)
        stats = await get_audit_log_statistics(db)

        print(f"\nUser Activity Logs:")
        print(f"  Total count: {stats['user_activity_logs']['total_count']:,}")
        if stats['user_activity_logs']['oldest_timestamp']:
            print(f"  Oldest entry: {stats['user_activity_logs']['oldest_timestamp']}")
            print(f"  Newest entry: {stats['user_activity_logs']['newest_timestamp']}")
            print(f"  Age: {stats['user_activity_logs']['age_days']} days")
        else:
            print("  No entries")

        print(f"\nClient Submission Logs:")
        print(f"  Total count: {stats['client_submission_logs']['total_count']:,}")
        if stats['client_submission_logs']['oldest_timestamp']:
            print(f"  Oldest entry: {stats['client_submission_logs']['oldest_timestamp']}")
            print(f"  Newest entry: {stats['client_submission_logs']['newest_timestamp']}")
            print(f"  Age: {stats['client_submission_logs']['age_days']} days")
        else:
            print("  No entries")

        print(f"\nTotal audit log entries: {stats['total_logs']:,}")

        if args.stats_only:
            print("\n(Statistics only - no cleanup performed)")
            return

        # Calculate what will be deleted
        print("\n" + "=" * 70)
        print("Cleanup Configuration:")
        print("-" * 70)
        print(f"User activity retention: {args.user_retention} days")
        print(f"Client submission retention: {args.client_retention} days")

        user_cutoff = datetime.now(timezone.utc) - timedelta(days=args.user_retention)
        client_cutoff = datetime.now(timezone.utc) - timedelta(days=args.client_retention)

        print(f"\nWill delete:")
        print(f"  User activity logs before: {user_cutoff.isoformat()}")
        print(f"  Client submission logs before: {client_cutoff.isoformat()}")

        if args.dry_run:
            print("\n(DRY RUN - No actual deletion will occur)")

        # Perform cleanup
        print("\n" + "=" * 70)
        print("Cleanup Progress:")
        print("-" * 70)

        if not args.dry_run:
            result = await cleanup_all_audit_logs(
                db,
                user_retention_days=args.user_retention,
                client_retention_days=args.client_retention
            )

            print(f"\nUser Activity Logs:")
            print(f"  Total before: {result['user_activity_logs']['total_before']:,}")
            print(f"  Deleted: {result['user_activity_logs']['deleted']:,}")
            print(f"  Retained: {result['user_activity_logs']['retained']:,}")

            print(f"\nClient Submission Logs:")
            print(f"  Total before: {result['client_submission_logs']['total_before']:,}")
            print(f"  Deleted: {result['client_submission_logs']['deleted']:,}")
            print(f"  Retained: {result['client_submission_logs']['retained']:,}")

            print(f"\nTotal deleted: {result['total_deleted']:,}")
            print(f"Cleanup completed: {result['cleanup_timestamp']}")

            if result['total_deleted'] > 0:
                print("\n✅ Cleanup successful")
            else:
                print("\n✅ No logs to clean up")

        else:
            # Dry run - just show counts
            from sqlalchemy import select, func
            from app.models.audit import UserActivityLog, ClientSubmissionLog

            user_result = await db.execute(
                select(func.count()).select_from(UserActivityLog).where(
                    UserActivityLog.timestamp < user_cutoff
                )
            )
            user_would_delete = user_result.scalar()

            client_result = await db.execute(
                select(func.count()).select_from(ClientSubmissionLog).where(
                    ClientSubmissionLog.timestamp < client_cutoff
                )
            )
            client_would_delete = client_result.scalar()

            print(f"\nWould delete:")
            print(f"  User activity logs: {user_would_delete:,}")
            print(f"  Client submission logs: {client_would_delete:,}")
            print(f"  Total: {user_would_delete + client_would_delete:,}")

            print("\n(DRY RUN - No actual deletion occurred)")

        print("\n" + "=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\nCleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
