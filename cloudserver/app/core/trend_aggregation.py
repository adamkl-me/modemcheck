"""
Trend data aggregation utilities for dashboard performance optimization.

Pre-computes aggregated metrics from modem check data for efficient chart rendering.
Reduces data transfer from ~15-50KB per check to ~500 bytes per check.
"""
from typing import Dict, Any, Optional, List
import re
import math

from app.schemas.modem_check import (
    TrendDataItem,
    RxAggregates,
    TxAggregates,
)


def safe_float(value: Any) -> Optional[float]:
    """Safely convert value to float, returning None on failure or invalid values."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
        # Filter out NaN and infinity values (e.g., "-inf" from disabled TX channels)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (ValueError, TypeError):
        return None


def safe_int(value: Any) -> Optional[int]:
    """Safely convert value to int, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def parse_ping_value(value: Any) -> Optional[float]:
    """
    Parse ping metric string to float.

    Handles formats like:
    - Numeric values (already parsed)
    - "15.2 ms", "25.5ms" (latency)
    - "0.0%", "1.5 %" (packet loss)
    """
    if value is None:
        return None

    # Handle numeric values
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None

    # Handle string values
    if isinstance(value, str):
        if value in ['', 'N/A', '-', 'Failed']:
            return None

        # Remove units and parse: "15.2 ms" -> 15.2, "0.0%" -> 0.0
        match = re.match(r'([\d.]+)\s*(%|ms)?', value.strip())
        if match:
            try:
                return float(match.group(1))
            except (ValueError, TypeError):
                return None

    return None


def parse_speed(speed_value: Any) -> Optional[float]:
    """
    Parse speed string or number to Mbps.

    Handles formats like:
    - Numeric values (already in Mbps)
    - "45.2 Mbps", "1.2 Gbps", "500 Kbps"
    - Failed/disabled states return None
    """
    if speed_value is None:
        return None

    # Handle numeric values (already in Mbps)
    if isinstance(speed_value, (int, float)):
        return float(speed_value) if speed_value > 0 else None

    # Handle string values
    if isinstance(speed_value, str):
        if speed_value in ['Failed', 'N/A', '-1', '-2', '-', 'Disabled', '']:
            return None

        # Try to parse string like "45.2 Mbps"
        match = re.match(r'([\d.]+)\s*(\w+)', speed_value)
        if not match:
            return None

        try:
            value = float(match.group(1))
            unit = match.group(2).lower()

            if 'gbit' in unit or 'gbps' in unit or 'gb' in unit:
                return value * 1000
            elif 'kbit' in unit or 'kbps' in unit or 'kb' in unit:
                return value / 1000
            else:  # Assume Mbps
                return value
        except (ValueError, TypeError):
            return None

    return None


def aggregate_rx_channels(
    channels: List[Dict[str, Any]],
    power_key: str,
    snr_key: str
) -> Optional[RxAggregates]:
    """
    Aggregate RX channel metrics including power, SNR, and error rates.

    Args:
        channels: List of channel dictionaries
        power_key: Key for power value ('power' for SC-QAM, 'plcpower' for OFDM)
        snr_key: Key for SNR value ('snr' for SC-QAM, 'plcsnr' for OFDM)

    Returns:
        RxAggregates with computed min/avg/max values, or None if no data
    """
    if not channels or not isinstance(channels, list):
        return None

    powers = []
    snrs = []
    bers = []
    corrected_rates = []

    for ch in channels:
        if not isinstance(ch, dict):
            continue

        # Extract power
        power = safe_float(ch.get(power_key))
        if power is not None:
            powers.append(power)

        # Extract SNR
        snr = safe_float(ch.get(snr_key))
        if snr is not None:
            snrs.append(snr)

        # Calculate BER: uncorrectables / total * 100
        # Note: octets = unerrored codewords
        unerrored = safe_int(ch.get('octets')) or 0
        correcteds = safe_int(ch.get('correcteds')) or 0
        uncorrectds = safe_int(ch.get('uncorrectds')) or 0
        total = unerrored + correcteds + uncorrectds

        if total > 0:
            ber = (uncorrectds / total) * 100
            corrected_rate = (correcteds / total) * 100
            bers.append(ber)
            corrected_rates.append(corrected_rate)

    # If no valid data found, return None
    if not powers and not snrs and not bers:
        return None

    result = RxAggregates()

    if powers:
        result.min_power = min(powers)
        result.avg_power = sum(powers) / len(powers)
        result.max_power = max(powers)

    if snrs:
        result.min_snr = min(snrs)
        result.avg_snr = sum(snrs) / len(snrs)
        result.max_snr = max(snrs)

    if bers:
        result.avg_ber = sum(bers) / len(bers)
        result.max_ber = max(bers)

    if corrected_rates:
        result.avg_corrected_rate = sum(corrected_rates) / len(corrected_rates)
        result.max_corrected_rate = max(corrected_rates)

    return result


def aggregate_tx_scqam_channels(channels: List[Dict[str, Any]]) -> Optional[TxAggregates]:
    """
    Aggregate TX SC-QAM channel metrics.

    Args:
        channels: List of TX SC-QAM channel dictionaries

    Returns:
        TxAggregates with power metrics and bonded count, or None if no data
    """
    if not channels or not isinstance(channels, list):
        return None

    powers = []

    for ch in channels:
        if not isinstance(ch, dict):
            continue
        power = safe_float(ch.get('power'))
        if power is not None and power != 0:
            powers.append(power)

    if not powers:
        return None

    return TxAggregates(
        min_power=min(powers),
        avg_power=sum(powers) / len(powers),
        max_power=max(powers),
        bonded_count=len(powers),
        impaired_count=0
    )


def aggregate_tx_ofdma_channels(channels: List[Dict[str, Any]]) -> Optional[TxAggregates]:
    """
    Aggregate TX OFDMA channel metrics including state-based counts.

    Args:
        channels: List of TX OFDMA channel dictionaries

    Returns:
        TxAggregates with power metrics, bonded count, and impaired count
    """
    if not channels or not isinstance(channels, list):
        return None

    operate_states = ['OPERATE', 'Locked']
    impaired_states = ['Not Locked', 'RNG1', 'RNG2', 'RNG3', 'Partial Service']

    powers = []
    bonded_count = 0
    impaired_count = 0

    for ch in channels:
        if not isinstance(ch, dict):
            continue

        state = ch.get('state', '')

        # Count bonded vs impaired channels
        if any(s in state for s in operate_states):
            bonded_count += 1
        elif any(s in state for s in impaired_states):
            impaired_count += 1

        # Collect power values
        power = safe_float(ch.get('power'))
        if power is not None:
            powers.append(power)

    if not powers and bonded_count == 0 and impaired_count == 0:
        return None

    result = TxAggregates(
        bonded_count=bonded_count,
        impaired_count=impaired_count
    )

    if powers:
        result.avg_power = sum(powers) / len(powers)

    return result


def aggregate_check_for_trends(check) -> TrendDataItem:
    """
    Convert a full ModemCheck to lightweight TrendDataItem.

    Args:
        check: ModemCheck database model instance

    Returns:
        TrendDataItem with pre-computed aggregates
    """
    data = check.full_data or {}
    sysinfo = data.get('sysinfo', {})

    # Get check time as epoch timestamp
    check_time = sysinfo.get('checktime', 0)
    if not check_time:
        # Fallback to check_time from database column
        if hasattr(check, 'check_time') and check.check_time:
            check_time = int(check.check_time.timestamp())

    # Parse speed values
    upload_speed = parse_speed(data.get('iperf3test_ul'))
    download_speed = parse_speed(data.get('iperf3test_dl'))

    # Get speed limits
    upload_limit = safe_float(data.get('iperf3uploadlimit'))
    download_limit = safe_float(data.get('iperf3downloadlimit'))

    # Calculate uptime in days
    uptime_seconds = sysinfo.get('uptime')
    uptime_days = (uptime_seconds / 86400) if uptime_seconds else None

    # Aggregate signal metrics
    rx_scqam = aggregate_rx_channels(data.get('rx', []), 'power', 'snr')
    rx_ofdm = aggregate_rx_channels(data.get('rxofdm', []), 'plcpower', 'plcsnr')
    tx_scqam = aggregate_tx_scqam_channels(data.get('tx', []))
    tx_ofdma = aggregate_tx_ofdma_channels(data.get('txofdm', []))

    return TrendDataItem(
        id=check.id,
        check_time=check_time,

        # Speed metrics
        upload_speed=upload_speed,
        download_speed=download_speed,
        upload_limit=upload_limit,
        download_limit=download_limit,

        # Ping metrics (from full_data - client sends at root level with string values)
        ping_google_avg=parse_ping_value(data.get('ping_google_avg')),
        ping_google_loss=parse_ping_value(data.get('ping_google_loss')),
        ping_google_max=parse_ping_value(data.get('ping_google_max_latency')),
        ping_cloudflare_avg=parse_ping_value(data.get('ping_cloudflare_avg')),
        ping_cloudflare_loss=parse_ping_value(data.get('ping_cloudflare_loss')),
        ping_cloudflare_max=parse_ping_value(data.get('ping_cloudflare_max_latency')),
        speedtest_latency=parse_ping_value(data.get('speedtest_latency')),
        speedtest_max_latency=parse_ping_value(data.get('speedtest_max_latency')),

        # Uptime
        uptime_days=uptime_days,

        # Aggregated signal metrics
        rx_scqam=rx_scqam,
        rx_ofdm=rx_ofdm,
        tx_scqam=tx_scqam,
        tx_ofdma=tx_ofdma,
    )
