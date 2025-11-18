"""
Metric extraction utilities for modem check data.

Extracts individual metrics from modem check JSON data for efficient database querying.
Compatible with Arris XB8, Motorola DM1000, and Xfinity modems.
"""
from typing import Dict, Any, Optional
from datetime import datetime


def safe_float(value: Any) -> Optional[float]:
    """Safely convert value to float, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        return float(value)
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


def extract_metrics(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract individual metrics from modem check JSON data.

    Args:
        json_data: Full modem check JSON data

    Returns:
        Dictionary with extracted metrics for database columns
    """
    metrics = {}

    # Extract system info
    sysinfo = json_data.get('sysinfo', {})
    metrics['firmware'] = sysinfo.get('firmware')
    metrics['uptime_seconds'] = safe_int(sysinfo.get('uptime'))

    # Parse system time if present
    system_time_str = sysinfo.get('systemtime')
    if system_time_str:
        try:
            metrics['system_time'] = datetime.fromisoformat(system_time_str.replace('Z', '+00:00'))
        except:
            metrics['system_time'] = None
    else:
        metrics['system_time'] = None

    # Extract signal quality metrics
    downstream = json_data.get('downstream', {})
    upstream = json_data.get('upstream', {})

    # Calculate average downstream power and SNR
    if 'channels' in downstream and isinstance(downstream['channels'], list):
        powers = [safe_float(ch.get('power')) for ch in downstream['channels'] if ch.get('power') is not None]
        snrs = [safe_float(ch.get('snr')) for ch in downstream['channels'] if ch.get('snr') is not None]

        if powers:
            metrics['avg_downstream_power'] = sum(powers) / len(powers)
        if snrs:
            metrics['avg_downstream_snr'] = sum(snrs) / len(snrs)

    # Calculate average upstream power
    if 'channels' in upstream and isinstance(upstream['channels'], list):
        powers = [safe_float(ch.get('power')) for ch in upstream['channels'] if ch.get('power') is not None]
        if powers:
            metrics['avg_upstream_power'] = sum(powers) / len(powers)

    # Calculate total errors (corrected and uncorrected)
    total_corrected = 0
    total_uncorrected = 0

    if 'channels' in downstream and isinstance(downstream['channels'], list):
        for ch in downstream['channels']:
            total_corrected += safe_int(ch.get('correcteds')) or 0
            total_uncorrected += safe_int(ch.get('uncorrectables')) or 0

    metrics['total_corrected_errors'] = total_corrected if total_corrected > 0 else None
    metrics['total_uncorrected_errors'] = total_uncorrected if total_uncorrected > 0 else None

    # Extract speed test results
    speedtest = json_data.get('speedtest', {})

    # Check if speedtest is enabled (1) or disabled (0/-1/-2)
    speedtest_enabled = speedtest.get('enabled')
    if speedtest_enabled is not None:
        metrics['speedtest_enabled'] = 1 if speedtest_enabled == 1 else 0

    # iperf3 results
    metrics['iperf3_upload'] = speedtest.get('upload')
    metrics['iperf3_download'] = speedtest.get('download')

    # speedtest.net results
    metrics['speedtest_server_name'] = speedtest.get('server_name')
    metrics['speedtest_server_id'] = speedtest.get('server_id')
    metrics['speedtest_latency'] = safe_float(speedtest.get('latency'))
    metrics['speedtest_max_latency'] = safe_float(speedtest.get('max_latency'))
    metrics['speedtest_jitter'] = safe_float(speedtest.get('jitter'))
    metrics['speedtest_packet_loss'] = safe_float(speedtest.get('packet_loss'))
    metrics['speedtest_dl_latency'] = safe_float(speedtest.get('download_latency'))
    metrics['speedtest_ul_jitter'] = safe_float(speedtest.get('upload_jitter'))

    # Extract ping test results
    ping_tests = json_data.get('ping_tests', {})

    # Google ping results
    google_ping = ping_tests.get('google', {})
    metrics['ping_google_avg'] = safe_float(google_ping.get('avg_latency'))
    metrics['ping_google_loss'] = safe_float(google_ping.get('packet_loss'))
    metrics['ping_google_jitter'] = safe_float(google_ping.get('jitter'))
    metrics['ping_google_max_latency'] = safe_float(google_ping.get('max_latency'))

    # Cloudflare ping results
    cloudflare_ping = ping_tests.get('cloudflare', {})
    metrics['ping_cloudflare_avg'] = safe_float(cloudflare_ping.get('avg_latency'))
    metrics['ping_cloudflare_loss'] = safe_float(cloudflare_ping.get('packet_loss'))
    metrics['ping_cloudflare_jitter'] = safe_float(cloudflare_ping.get('jitter'))
    metrics['ping_cloudflare_max_latency'] = safe_float(cloudflare_ping.get('max_latency'))

    # Extract client information
    metrics['client_version'] = sysinfo.get('client_version')
    metrics['client_os'] = sysinfo.get('client_os')
    metrics['client_arch'] = sysinfo.get('client_arch')

    # Extract network information
    network_info = json_data.get('network_info', {})
    metrics['detection_status'] = sysinfo.get('detection_status')
    metrics['public_ip'] = network_info.get('public_ip')
    metrics['asn'] = network_info.get('asn')
    metrics['isp_name'] = network_info.get('isp_name')
    metrics['ip_city'] = network_info.get('city')
    metrics['ip_country'] = network_info.get('country')

    return metrics
