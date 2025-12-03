#!/usr/bin/env python3
"""
Standalone test data generator that doesn't require test fixtures.
Creates synthetic modem check data for performance testing.

Usage:
    cat this_script.py | docker exec -i modemcheck-cloud-test python - -m 50
"""
import sys
import uuid
import asyncio
import random
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from app.models.modem_check import ModemCheck
from app.core.database import Base


# Database URL from container environment
import os
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://modemcheck:modemcheck_test_password@modemcheck-postgres-test:5432/modemcheck_test"
)


def generate_synthetic_check(modem_type: str, check_time: datetime) -> dict:
    """Generate synthetic modem check data."""
    # Generate RX SC-QAM channels (32 channels typical)
    rx_channels = []
    for i in range(32):
        rx_channels.append({
            "dcid": i + 1,
            "freq": 507000000 + i * 6000000,
            "power": round(random.uniform(-5, 10), 1),
            "snr": round(random.uniform(35, 42), 1),
            "modulation": "QAM256",
            "octets": random.randint(1000000, 5000000),
            "correcteds": random.randint(0, 1000),
            "uncorrectds": random.randint(0, 50)
        })

    # Generate RX OFDM channels (2 channels typical)
    rxofdm_channels = []
    for i in range(2):
        rxofdm_channels.append({
            "dcid": 33 + i,
            "freq": 722000000 + i * 48000000,
            "plcpower": round(random.uniform(-5, 10), 1),
            "plcsnr": round(random.uniform(35, 40), 1),
            "octets": random.randint(5000000, 20000000),
            "correcteds": random.randint(0, 5000),
            "uncorrectds": random.randint(0, 100)
        })

    # Generate TX SC-QAM channels (4 channels typical)
    tx_channels = []
    for i in range(4):
        tx_channels.append({
            "ucid": i + 1,
            "freq": 17000000 + i * 6400000,
            "power": round(random.uniform(35, 50), 1),
            "modulation": "SC-QAM"
        })

    # Generate TX OFDMA channels (2 channels typical)
    txofdm_channels = []
    for i in range(2):
        txofdm_channels.append({
            "ucid": 5 + i,
            "freq": 50000000 + i * 48000000,
            "power": round(random.uniform(35, 45), 1),
            "state": "OPERATE" if random.random() > 0.1 else "Partial Service"
        })

    # Generate speed test results
    upload_speed = round(random.uniform(15, 45), 2)
    download_speed = round(random.uniform(100, 400), 2)

    return {
        "sysinfo": {
            "checktime": int(check_time.timestamp()),
            "uptime": random.randint(86400, 864000),  # 1-10 days in seconds
            "firmware": "1.2.3.4",
            "model": modem_type
        },
        "rx": rx_channels,
        "rxofdm": rxofdm_channels,
        "tx": tx_channels,
        "txofdm": txofdm_channels,
        "iperf3test_ul": f"{upload_speed} Mbps",
        "iperf3test_dl": f"{download_speed} Mbps",
        "iperf3uploadlimit": 50,
        "iperf3downloadlimit": 500,
        # Ping metrics (flat structure matching real client format)
        "ping_google_avg": f"{round(random.uniform(10, 30), 2)} ms",
        "ping_google_loss": f"{round(random.uniform(0, 2), 1)}%",
        "ping_google_jitter": f"{round(random.uniform(1, 5), 2)} ms",
        "ping_google_max_latency": f"{round(random.uniform(30, 100), 2)} ms",
        "ping_cloudflare_avg": f"{round(random.uniform(8, 25), 2)} ms",
        "ping_cloudflare_loss": f"{round(random.uniform(0, 2), 1)}%",
        "ping_cloudflare_jitter": f"{round(random.uniform(1, 5), 2)} ms",
        "ping_cloudflare_max_latency": f"{round(random.uniform(25, 80), 2)} ms",
        "clientinfo": {
            "version": "6.0.0",
            "os": "linux",
            "arch": "amd64"
        },
        "ipinfo": {
            "ip": f"24.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}",
            "isp": "Test ISP",
            "asn": "AS12345"
        }
    }


def parse_ping_string(value: str) -> float | None:
    """Parse ping string like '15.2 ms' or '0.5%' to float."""
    if not value:
        return None
    import re
    match = re.match(r'([\d.]+)', value)
    return float(match.group(1)) if match else None


def extract_metrics(data: dict) -> dict:
    """Extract metrics from modem check data."""
    sysinfo = data.get('sysinfo', {})
    clientinfo = data.get('clientinfo', {})
    ipinfo = data.get('ipinfo', {})

    # Calculate averages for downstream channels
    rx = data.get('rx', [])
    avg_power = sum(ch.get('power', 0) for ch in rx) / len(rx) if rx else None
    avg_snr = sum(ch.get('snr', 0) for ch in rx) / len(rx) if rx else None
    total_corrected = sum(ch.get('correcteds', 0) for ch in rx)
    total_uncorrected = sum(ch.get('uncorrectds', 0) for ch in rx)

    # Calculate average upstream power
    tx = data.get('tx', [])
    avg_upstream = sum(ch.get('power', 0) for ch in tx) / len(tx) if tx else None

    return {
        'firmware': sysinfo.get('firmware'),
        'uptime_seconds': sysinfo.get('uptime'),
        'system_time': datetime.fromtimestamp(sysinfo.get('checktime', 0)) if sysinfo.get('checktime') else None,
        'avg_downstream_power': avg_power,
        'avg_downstream_snr': avg_snr,
        'avg_upstream_power': avg_upstream,
        'total_corrected_errors': total_corrected,
        'total_uncorrected_errors': total_uncorrected,
        # Parse flat ping strings (matching real client format)
        'ping_google_avg': parse_ping_string(data.get('ping_google_avg')),
        'ping_google_loss': parse_ping_string(data.get('ping_google_loss')),
        'ping_google_max_latency': parse_ping_string(data.get('ping_google_max_latency')),
        'ping_cloudflare_avg': parse_ping_string(data.get('ping_cloudflare_avg')),
        'ping_cloudflare_loss': parse_ping_string(data.get('ping_cloudflare_loss')),
        'ping_cloudflare_max_latency': parse_ping_string(data.get('ping_cloudflare_max_latency')),
        'client_version': clientinfo.get('version'),
        'client_os': clientinfo.get('os'),
        'client_arch': clientinfo.get('arch'),
        'public_ip': ipinfo.get('ip'),
        'isp_name': ipinfo.get('isp'),
        'asn': ipinfo.get('asn'),
    }


async def create_tables(engine):
    """Create database tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def clear_test_data(session: AsyncSession):
    """Clear existing performance test data."""
    result = await session.execute(
        text("DELETE FROM modem_checks WHERE modem_id LIKE '%-PERF%'")
    )
    await session.commit()
    print(f"Cleared {result.rowcount} existing test records")


async def populate_test_data(multiplier: int = 50):
    """
    Populate test database with synthetic data.

    Args:
        multiplier: Number of checks per modem type (default: 50)
    """
    print(f"Connecting to test database...")
    print(f"URL: {DATABASE_URL}")
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Create tables if needed
    await create_tables(engine)

    async with async_session() as session:
        # Clear existing test data
        await clear_test_data(session)

        modem_types = ['XB8', 'DM1000', 'CODA56']
        checks_per_type = 25  # 25 checks per batch
        total_checks = len(modem_types) * checks_per_type * multiplier

        print(f"Will create {total_checks} modem checks ({multiplier}x {checks_per_type} checks × {len(modem_types)} modems)")

        base_time = datetime.now()
        batch_size = 100
        batch = []
        created_count = 0

        for mult in range(multiplier):
            # Spread checks across time - 4 hours between each multiplier batch
            time_offset = timedelta(hours=mult * 4)

            for modem_type in modem_types:
                # Use a unique modem ID for performance testing
                perf_modem_id = f"{modem_type}-PERF{mult:03d}"

                for i in range(checks_per_type):
                    # Calculate check time
                    check_time = base_time - time_offset - timedelta(minutes=i * 15)

                    # Generate synthetic data
                    check_data = generate_synthetic_check(modem_type, check_time)

                    # Extract metrics
                    metrics = extract_metrics(check_data)

                    # Create unique filename
                    unique_filename = f"perf_test/{modem_type}/{mult:03d}_{uuid.uuid4().hex[:8]}.json"

                    # Create ModemCheck record
                    new_check = ModemCheck(
                        modem_id=perf_modem_id,
                        modem_type=modem_type,
                        check_time=check_time,
                        filename=unique_filename,
                        full_data=check_data,
                        firmware=metrics.get('firmware'),
                        uptime_seconds=metrics.get('uptime_seconds'),
                        system_time=metrics.get('system_time'),
                        avg_downstream_power=metrics.get('avg_downstream_power'),
                        avg_downstream_snr=metrics.get('avg_downstream_snr'),
                        avg_upstream_power=metrics.get('avg_upstream_power'),
                        total_corrected_errors=metrics.get('total_corrected_errors'),
                        total_uncorrected_errors=metrics.get('total_uncorrected_errors'),
                        ping_google_avg=metrics.get('ping_google_avg'),
                        ping_google_loss=metrics.get('ping_google_loss'),
                        ping_google_max_latency=metrics.get('ping_google_max_latency'),
                        ping_cloudflare_avg=metrics.get('ping_cloudflare_avg'),
                        ping_cloudflare_loss=metrics.get('ping_cloudflare_loss'),
                        ping_cloudflare_max_latency=metrics.get('ping_cloudflare_max_latency'),
                        client_version=metrics.get('client_version'),
                        client_os=metrics.get('client_os'),
                        client_arch=metrics.get('client_arch'),
                        public_ip=metrics.get('public_ip'),
                        isp_name=metrics.get('isp_name'),
                        asn=metrics.get('asn'),
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
            text("SELECT modem_id, COUNT(*) FROM modem_checks WHERE modem_id LIKE '%-PERF%' GROUP BY modem_id ORDER BY modem_id LIMIT 10")
        )
        rows = result.all()
        print("\nTest data summary (first 10 modems):")
        for modem_id, count in rows:
            print(f"  {modem_id}: {count} checks")

        # Total count
        result = await session.execute(
            text("SELECT COUNT(*) FROM modem_checks WHERE modem_id LIKE '%-PERF%'")
        )
        total = result.scalar()
        print(f"\nTotal performance test records: {total}")

    await engine.dispose()
    print("\nDone! You can now test the dashboard performance.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Populate test database with performance test data")
    parser.add_argument("-m", "--multiplier", type=int, default=50,
                        help="Number of check batches to create (default: 50)")
    args = parser.parse_args()

    asyncio.run(populate_test_data(args.multiplier))
