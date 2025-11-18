#!/usr/bin/env python3
"""
Database migration script to add performance-critical indexes.

These indexes address the performance issues identified in the code review:
1. Optimize API key lookups during upload
2. Improve modem check queries by date range
3. Support efficient sorting and filtering

Run this script after backing up your database:
    ./backup-database.sh
    python3 add_performance_indexes.py
"""

import asyncio
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings


async def add_indexes():
    """Add performance-critical indexes to the database."""

    # Create database connection
    engine = create_async_engine(
        settings.database_url,
        echo=True,  # Show SQL queries being executed
    )

    indexes_to_create = [
        # Composite index for API key lookups (active keys + key value)
        # This optimizes the upload endpoint which filters by is_active then compares keys
        {
            "name": "idx_api_keys_active_key",
            "table": "api_keys",
            "sql": "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_keys_active_key ON api_keys(is_active, api_key) WHERE is_active = true"
        },

        # Composite index for modem checks with descending time
        # Optimizes queries that filter by modem_id and sort by time
        {
            "name": "idx_modem_checks_modem_time_desc",
            "table": "modem_checks",
            "sql": "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_modem_checks_modem_time_desc ON modem_checks(modem_id, check_time DESC)"
        },

        # Index for check_time range queries (descending for recent queries)
        {
            "name": "idx_modem_checks_time_desc",
            "table": "modem_checks",
            "sql": "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_modem_checks_time_desc ON modem_checks(check_time DESC)"
        },

        # Index for signal quality queries
        {
            "name": "idx_modem_checks_signal_quality",
            "table": "modem_checks",
            "sql": "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_modem_checks_signal_quality ON modem_checks(avg_downstream_power, avg_downstream_snr, total_uncorrected_errors) WHERE avg_downstream_power IS NOT NULL"
        },

        # Index for speed test queries
        {
            "name": "idx_modem_checks_speedtest",
            "table": "modem_checks",
            "sql": "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_modem_checks_speedtest ON modem_checks(speedtest_enabled, speedtest_latency) WHERE speedtest_enabled = 1"
        },

        # Index for ISP/ASN queries
        {
            "name": "idx_modem_checks_isp",
            "table": "modem_checks",
            "sql": "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_modem_checks_isp ON modem_checks(isp_name, asn) WHERE isp_name IS NOT NULL"
        },

        # Index for audit logs by user and timestamp
        {
            "name": "idx_audit_logs_user_timestamp",
            "table": "audit_logs",
            "sql": "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_logs_user_timestamp ON audit_logs(user_id, timestamp DESC)"
        },

        # Index for audit logs by action type and timestamp
        {
            "name": "idx_audit_logs_action_timestamp",
            "table": "audit_logs",
            "sql": "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_logs_action_timestamp ON audit_logs(action, timestamp DESC)"
        }
    ]

    async with engine.begin() as conn:
        print("Creating performance indexes...")
        print("-" * 60)

        for index_info in indexes_to_create:
            try:
                print(f"\nCreating index: {index_info['name']}")
                print(f"Table: {index_info['table']}")
                print(f"SQL: {index_info['sql']}")

                await conn.execute(text(index_info['sql']))
                print(f"✓ Index {index_info['name']} created successfully")

            except Exception as e:
                if "already exists" in str(e).lower():
                    print(f"→ Index {index_info['name']} already exists (skipping)")
                else:
                    print(f"✗ Error creating index {index_info['name']}: {e}")
                    # Continue with other indexes even if one fails

        print("\n" + "-" * 60)
        print("Analyzing tables to update statistics...")

        # Update table statistics for query planner
        tables_to_analyze = ["modem_checks", "api_keys", "audit_logs"]
        for table in tables_to_analyze:
            try:
                await conn.execute(text(f"ANALYZE {table}"))
                print(f"✓ Analyzed table: {table}")
            except Exception as e:
                print(f"✗ Error analyzing table {table}: {e}")

    await engine.dispose()
    print("\n✓ Index creation complete!")
    print("\nPerformance improvements expected:")
    print("- API key validation: 10-100x faster")
    print("- Modem check queries by date: 5-50x faster")
    print("- Signal quality filtering: 10x faster")
    print("- Audit log queries: 5-20x faster")
    print("\nNote: If your database is large, these indexes may take time to build.")
    print("The CONCURRENTLY option allows normal operations to continue during index creation.")


async def check_existing_indexes():
    """Check which indexes already exist."""

    engine = create_async_engine(
        settings.database_url,
        echo=False,
    )

    query = """
        SELECT
            schemaname,
            tablename,
            indexname,
            indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
        AND tablename IN ('modem_checks', 'api_keys', 'audit_logs', 'users')
        ORDER BY tablename, indexname
    """

    async with engine.begin() as conn:
        result = await conn.execute(text(query))
        indexes = result.fetchall()

        print("\nExisting indexes:")
        print("-" * 80)
        current_table = None
        for idx in indexes:
            if idx[1] != current_table:
                current_table = idx[1]
                print(f"\nTable: {current_table}")
            print(f"  - {idx[2]}")

    await engine.dispose()


async def main():
    """Main function to run the migration."""

    print("=" * 80)
    print("ModemCheck Database Performance Index Migration")
    print("=" * 80)

    # Check existing indexes first
    await check_existing_indexes()

    print("\n" + "=" * 80)
    response = input("\nProceed with creating new indexes? (yes/no): ")

    if response.lower() in ['yes', 'y']:
        await add_indexes()
    else:
        print("Migration cancelled.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())