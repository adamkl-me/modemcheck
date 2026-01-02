"""
Summary data aggregation utilities for dashboard Summary View.

Computes Min/Avg/Max/Range/Stdev statistics across all checks in a period.
Uses pre-aggregated trend data and extracted metrics for efficiency.
"""
import statistics
from typing import List, Optional, Tuple
from datetime import datetime

from app.schemas.modem_check import (
    TrendDataItem,
    MinAvgMaxRange,
    PeriodOverview,
    RxSignalSummary,
    TxSignalSummary,
    ErrorRateSummary,
    NetworkSummary,
    SummaryData,
    SummaryDataResponse,
)
from app.core.trend_aggregation import parse_ping_value


def compute_min_avg_max_range(values: List[Optional[float]]) -> Optional[MinAvgMaxRange]:
    """
    Compute Min/Avg/Max/Range/Stdev statistics from a list of values.

    Args:
        values: List of float values (may contain None)

    Returns:
        MinAvgMaxRange with computed statistics, or None if no valid values
    """
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None

    min_val = min(filtered)
    max_val = max(filtered)
    avg_val = sum(filtered) / len(filtered)
    range_val = max_val - min_val
    stdev_val = statistics.stdev(filtered) if len(filtered) > 1 else 0.0

    return MinAvgMaxRange(
        min=round(min_val, 2),
        avg=round(avg_val, 2),
        max=round(max_val, 2),
        range=round(range_val, 2),
        stdev=round(stdev_val, 2)
    )


def count_reboots(checks: List) -> int:
    """
    Count detected reboots by checking when uptime decreased from previous check.

    A reboot is detected when the current check's uptime is less than
    the previous check's uptime (indicating the modem restarted).

    Args:
        checks: List of ModemCheck model instances ordered by check_time

    Returns:
        Number of detected reboots
    """
    reboots = 0
    prev_uptime = None

    for check in checks:
        uptime = check.uptime_seconds
        if uptime is not None and prev_uptime is not None:
            if uptime < prev_uptime:
                reboots += 1
        prev_uptime = uptime

    return reboots


def filter_maintenance_window(
    checks: List,
    trend_items: List[TrendDataItem]
) -> Tuple[List, List[TrendDataItem]]:
    """
    Filter out checks between 2am-5am local time (maintenance window).

    Args:
        checks: List of ModemCheck model instances
        trend_items: Corresponding list of TrendDataItem

    Returns:
        Tuple of (filtered_checks, filtered_trends)
    """
    filtered_checks = []
    filtered_trends = []

    for check, trend in zip(checks, trend_items):
        hour = check.check_time.hour
        if hour < 2 or hour >= 5:  # Keep checks outside 2am-5am
            filtered_checks.append(check)
            filtered_trends.append(trend)

    return filtered_checks, filtered_trends


def compute_summary_data(
    trend_items: List[TrendDataItem],
    checks: List
) -> Optional[SummaryData]:
    """
    Compute summary statistics from pre-aggregated trend data and check records.

    Uses per-check averages for aggregation as specified in requirements.
    Also extracts jitter from full_data JSON since TrendDataItem doesn't include jitter.

    Args:
        trend_items: List of TrendDataItem (pre-aggregated per-check)
        checks: List of ModemCheck model instances (for reboot detection and jitter)

    Returns:
        SummaryData with all aggregated statistics, or None if no data
    """
    if not trend_items:
        return None

    # Period Overview
    timestamps = [t.check_time for t in trend_items if t.check_time]
    checks_with_speedtest = sum(
        1 for t in trend_items
        if (t.download_speed is not None and t.download_speed > 0) or
           (t.upload_speed is not None and t.upload_speed > 0)
    )

    # Convert timestamps to datetime for response
    period_start = None
    period_end = None
    if timestamps:
        period_start = datetime.fromtimestamp(min(timestamps))
        period_end = datetime.fromtimestamp(max(timestamps))

    period = PeriodOverview(
        total_checks=len(trend_items),
        period_start=period_start,
        period_end=period_end,
        checks_with_speedtest=checks_with_speedtest,
        detected_reboots=count_reboots(checks)
    )

    # RX Signal Summary - use avg values from each check
    rx_scqam_power = [t.rx_scqam.avg_power for t in trend_items
                      if t.rx_scqam and t.rx_scqam.avg_power is not None]
    rx_scqam_snr = [t.rx_scqam.avg_snr for t in trend_items
                   if t.rx_scqam and t.rx_scqam.avg_snr is not None]
    rx_ofdm_power = [t.rx_ofdm.avg_power for t in trend_items
                    if t.rx_ofdm and t.rx_ofdm.avg_power is not None]
    rx_ofdm_snr = [t.rx_ofdm.avg_snr for t in trend_items
                  if t.rx_ofdm and t.rx_ofdm.avg_snr is not None]

    rx_signal = RxSignalSummary(
        scqam_power=compute_min_avg_max_range(rx_scqam_power),
        scqam_snr=compute_min_avg_max_range(rx_scqam_snr),
        ofdm_power=compute_min_avg_max_range(rx_ofdm_power),
        ofdm_snr=compute_min_avg_max_range(rx_ofdm_snr)
    )

    # TX Signal Summary
    tx_scqam_power = [t.tx_scqam.avg_power for t in trend_items
                     if t.tx_scqam and t.tx_scqam.avg_power is not None]
    tx_ofdma_power = [t.tx_ofdma.avg_power for t in trend_items
                     if t.tx_ofdma and t.tx_ofdma.avg_power is not None]

    tx_signal = TxSignalSummary(
        scqam_power=compute_min_avg_max_range(tx_scqam_power),
        ofdma_power=compute_min_avg_max_range(tx_ofdma_power)
    )

    # Error Rates Summary - separate SC-QAM and OFDM
    scqam_corrected = [t.rx_scqam.avg_corrected_rate for t in trend_items
                       if t.rx_scqam and t.rx_scqam.avg_corrected_rate is not None]
    scqam_uncorr = [t.rx_scqam.avg_ber for t in trend_items
                   if t.rx_scqam and t.rx_scqam.avg_ber is not None]
    ofdm_corrected = [t.rx_ofdm.avg_corrected_rate for t in trend_items
                      if t.rx_ofdm and t.rx_ofdm.avg_corrected_rate is not None]
    ofdm_uncorr = [t.rx_ofdm.avg_ber for t in trend_items
                  if t.rx_ofdm and t.rx_ofdm.avg_ber is not None]

    error_rates = ErrorRateSummary(
        scqam_corrected_ber=compute_min_avg_max_range(scqam_corrected),
        scqam_uncorrectable_ber=compute_min_avg_max_range(scqam_uncorr),
        ofdm_corrected_ber=compute_min_avg_max_range(ofdm_corrected),
        ofdm_uncorrectable_ber=compute_min_avg_max_range(ofdm_uncorr)
    )

    # Network Performance Summary
    download_speeds = [t.download_speed for t in trend_items
                       if t.download_speed is not None and t.download_speed > 0]
    upload_speeds = [t.upload_speed for t in trend_items
                     if t.upload_speed is not None and t.upload_speed > 0]

    # Ping metrics (separate Google and Cloudflare)
    ping_google = [t.ping_google_avg for t in trend_items
                   if t.ping_google_avg is not None]
    ping_cloudflare = [t.ping_cloudflare_avg for t in trend_items
                       if t.ping_cloudflare_avg is not None]

    # Packet loss (separate Google and Cloudflare)
    loss_google = [t.ping_google_loss for t in trend_items
                   if t.ping_google_loss is not None]
    loss_cloudflare = [t.ping_cloudflare_loss for t in trend_items
                       if t.ping_cloudflare_loss is not None]

    # Jitter - extract from full_data JSON (model columns are not populated)
    jitter_google = [
        parse_ping_value(c.full_data.get('ping_google_jitter'))
        for c in checks
        if c.full_data and c.full_data.get('ping_google_jitter')
    ]
    jitter_google = [j for j in jitter_google if j is not None]

    jitter_cloudflare = [
        parse_ping_value(c.full_data.get('ping_cloudflare_jitter'))
        for c in checks
        if c.full_data and c.full_data.get('ping_cloudflare_jitter')
    ]
    jitter_cloudflare = [j for j in jitter_cloudflare if j is not None]

    network = NetworkSummary(
        download_speed=compute_min_avg_max_range(download_speeds),
        upload_speed=compute_min_avg_max_range(upload_speeds),
        ping_google=compute_min_avg_max_range(ping_google),
        ping_cloudflare=compute_min_avg_max_range(ping_cloudflare),
        loss_google=compute_min_avg_max_range(loss_google),
        loss_cloudflare=compute_min_avg_max_range(loss_cloudflare),
        jitter_google=compute_min_avg_max_range(jitter_google),
        jitter_cloudflare=compute_min_avg_max_range(jitter_cloudflare)
    )

    return SummaryData(
        period=period,
        rx_signal=rx_signal,
        tx_signal=tx_signal,
        error_rates=error_rates,
        network=network
    )


def compute_summary_from_trend_data(
    trend_items: List[TrendDataItem],
    checks: List
) -> SummaryDataResponse:
    """
    Compute both full and maintenance-excluded summary statistics.

    Returns dual summaries for client-side toggling without additional API calls.

    Args:
        trend_items: List of TrendDataItem (pre-aggregated per-check)
        checks: List of ModemCheck model instances (for reboot detection and jitter)

    Returns:
        SummaryDataResponse with both full and maint_excluded summaries
    """
    if not trend_items:
        return SummaryDataResponse(
            success=False,
            error="No data found for the selected criteria"
        )

    # Compute full summary (all data)
    full_summary = compute_summary_data(trend_items, checks)

    # Filter maintenance window (2am-5am) and compute excluded summary
    maint_checks, maint_trends = filter_maintenance_window(checks, trend_items)
    maint_excluded_summary = compute_summary_data(maint_trends, maint_checks)

    return SummaryDataResponse(
        success=True,
        full=full_summary,
        maint_excluded=maint_excluded_summary
    )
