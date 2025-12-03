#!/usr/bin/env python3
"""
Populate test database with 3,750+ modem checks for performance testing.

Usage:
    cd cloudserver
    source .venv/bin/activate  # If using venv
    python scripts/populate_test_data.py

This script replicates the 75 real fixture checks 50 times with varied timestamps
to create a realistic large dataset for dashboard performance testing.
"""
import sys
import uuid
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

# Add the cloudserver directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from app.models.modem_check import ModemCheck
from app.core.metric_extraction import extract_metrics
from app.core.database import Base
from tests.fixtures.modem_data.loader import load_all_fixture_data, get_modem_ids


# Test database configuration
TEST_DB_URL = "postgresql+asyncpg://modemcheck:modemcheck_test_password@localhost:5433/modemcheck_test"


async def create_tables(engine):
    """Create database tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def clear_test_data(session: AsyncSession):
    """Clear existing test data."""
    result = await session.execute(
        text("DELETE FROM modem_checks WHERE modem_id LIKE 'XB8-PERF%' OR modem_id LIKE 'DM1000-PERF%' OR modem_id LIKE 'CODA56-PERF%'")
    )
    await session.commit()
    print(f"Cleared {result.rowcount} existing test records")


async def populate_test_data(multiplier: int = 50):
    """
    Populate test database with multiplied fixture data.

    Args:
        multiplier: How many times to replicate the 75 base fixtures (default: 50 = 3,750 records)
    """
    print(f"Connecting to test database...")
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Create tables if needed
    await create_tables(engine)

    async with async_session() as session:
        # Clear existing test data
        await clear_test_data(session)

        # Load fixture data
        print("Loading fixture data...")
        fixture_data = load_all_fixture_data()
        modem_ids = get_modem_ids()

        total_checks = sum(len(checks) for checks in fixture_data.values()) * multiplier
        print(f"Will create {total_checks} modem checks ({multiplier}x replication)")

        base_time = datetime.now()
        batch_size = 100
        batch = []
        created_count = 0

        for mult in range(multiplier):
            # Spread checks across time - 4 hours between each multiplier batch
            time_offset = timedelta(hours=mult * 4)

            for modem_type, checks in fixture_data.items():
                # Use a unique modem ID for performance testing
                perf_modem_id = f"{modem_type.upper()}-PERF{mult:03d}"

                for i, check_data in enumerate(checks):
                    # Create unique filename
                    unique_filename = f"perf_test/{modem_type}/{mult:03d}_{uuid.uuid4().hex[:8]}.json"

                    # Calculate check time
                    check_time = base_time - time_offset - timedelta(minutes=i * 15)

                    # Update sysinfo.checktime in the data
                    modified_data = check_data.copy()
                    if 'sysinfo' in modified_data:
                        modified_data['sysinfo'] = modified_data['sysinfo'].copy()
                        modified_data['sysinfo']['checktime'] = int(check_time.timestamp())

                    # Extract metrics
                    metrics = extract_metrics(modified_data)

                    # Create ModemCheck record
                    new_check = ModemCheck(
                        modem_id=perf_modem_id,
                        modem_type=modem_type.upper(),
                        check_time=check_time,
                        filename=unique_filename,
                        full_data=modified_data,
                        firmware=metrics.get('firmware'),
                        uptime_seconds=metrics.get('uptime_seconds'),
                        system_time=metrics.get('system_time'),
                        avg_downstream_power=metrics.get('avg_downstream_power'),
                        avg_downstream_snr=metrics.get('avg_downstream_snr'),
                        avg_upstream_power=metrics.get('avg_upstream_power'),
                        total_corrected_errors=metrics.get('total_corrected_errors'),
                        total_uncorrected_errors=metrics.get('total_uncorrected_errors'),
                        speedtest_enabled=metrics.get('speedtest_enabled'),
                        iperf3_upload=metrics.get('iperf3_upload'),
                        iperf3_download=metrics.get('iperf3_download'),
                        speedtest_server_name=metrics.get('speedtest_server_name'),
                        speedtest_server_id=metrics.get('speedtest_server_id'),
                        speedtest_latency=metrics.get('speedtest_latency'),
                        speedtest_max_latency=metrics.get('speedtest_max_latency'),
                        speedtest_jitter=metrics.get('speedtest_jitter'),
                        speedtest_packet_loss=metrics.get('speedtest_packet_loss'),
                        speedtest_dl_latency=metrics.get('speedtest_dl_latency'),
                        speedtest_ul_jitter=metrics.get('speedtest_ul_jitter'),
                        ping_google_avg=metrics.get('ping_google_avg'),
                        ping_google_loss=metrics.get('ping_google_loss'),
                        ping_google_jitter=metrics.get('ping_google_jitter'),
                        ping_google_max_latency=metrics.get('ping_google_max_latency'),
                        ping_cloudflare_avg=metrics.get('ping_cloudflare_avg'),
                        ping_cloudflare_loss=metrics.get('ping_cloudflare_loss'),
                        ping_cloudflare_jitter=metrics.get('ping_cloudflare_jitter'),
                        ping_cloudflare_max_latency=metrics.get('ping_cloudflare_max_latency'),
                        client_version=metrics.get('client_version'),
                        client_os=metrics.get('client_os'),
                        client_arch=metrics.get('client_arch'),
                        detection_status=metrics.get('detection_status'),
                        public_ip=metrics.get('public_ip'),
                        asn=metrics.get('asn'),
                        isp_name=metrics.get('isp_name'),
                        ip_city=metrics.get('ip_city'),
                        ip_country=metrics.get('ip_country'),
                    )
                    batch.append(new_check)

                    # Batch insert for efficiency
                    if len(batch) >= batch_size:
                        session.add_all(batch)
                        await session.commit()
                        created_count += len(batch)
                        print(f"  Created {created_count}/{total_checks} records...", end='\r')
                        batch = []

        # Insert remaining batch
        if batch:
            session.add_all(batch)
            await session.commit()
            created_count += len(batch)

        print(f"\nSuccessfully created {created_count} modem checks")

        # Show summary
        result = await session.execute(
            text("SELECT modem_id, COUNT(*) FROM modem_checks WHERE modem_id LIKE '%-PERF%' GROUP BY modem_id ORDER BY modem_id")
        )
        rows = result.all()
        print("\nTest data summary:")
        for modem_id, count in rows:
            print(f"  {modem_id}: {count} checks")

    await engine.dispose()
    print("\nDone! You can now test the dashboard performance.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Populate test database with performance test data")
    parser.add_argument("-m", "--multiplier", type=int, default=50,
                        help="How many times to replicate fixtures (default: 50 = 3,750 records)")
    args = parser.parse_args()

    asyncio.run(populate_test_data(args.multiplier))
