"""
Pydantic schemas for modem check data.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_serializer


class ModemCheckUploadResponse(BaseModel):
    """Response schema for modem check upload."""
    success: bool
    message: Optional[str] = None
    database_id: Optional[int] = None
    modem_id: Optional[str] = None
    check_time: Optional[str] = None
    error: Optional[str] = None


class ModemInfo(BaseModel):
    """Schema for modem information."""
    modem_id: str
    modem_type: Optional[str] = None
    first_seen: datetime
    last_seen: datetime
    check_count: int

    @field_serializer('first_seen', 'last_seen')
    def serialize_datetime(self, dt: datetime) -> str:
        """Serialize datetime as ISO with Z suffix to indicate UTC."""
        return dt.isoformat() + 'Z' if dt else None


class ModemListResponse(BaseModel):
    """Response schema for modem list."""
    success: bool
    modems: List[ModemInfo]


class CheckListItem(BaseModel):
    """Schema for individual check in list."""
    id: int
    filename: str
    check_time: datetime
    modem_type: Optional[str] = None
    avg_downstream_snr: Optional[float] = None
    avg_downstream_power: Optional[float] = None
    total_uncorrected_errors: Optional[int] = None
    client_version: Optional[str] = None

    @field_serializer('check_time')
    def serialize_datetime(self, dt: datetime) -> str:
        """Serialize datetime as ISO with Z suffix to indicate UTC."""
        return dt.isoformat() + 'Z' if dt else None


class CheckListResponse(BaseModel):
    """Response schema for check list."""
    success: bool
    checks: List[CheckListItem]
    total_count: int


class CheckWithFullData(BaseModel):
    """Schema for check with full JSON data included."""
    id: int
    filename: str
    check_time: datetime
    modem_type: Optional[str] = None
    full_data: Dict[str, Any]  # Complete JSON data

    @field_serializer('check_time')
    def serialize_datetime(self, dt: datetime) -> str:
        """Serialize datetime as ISO with Z suffix to indicate UTC."""
        return dt.isoformat() + 'Z' if dt else None


class CheckListWithDataResponse(BaseModel):
    """Response schema for check list with full data."""
    success: bool
    checks: List[CheckWithFullData]
    total_count: int


class CheckDetailResponse(BaseModel):
    """Response schema for single check detail."""
    success: bool
    check: Optional[Dict[str, Any]] = None  # Full JSON data
    error: Optional[str] = None


class DateRangeRequest(BaseModel):
    """Request schema for date range queries."""
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")
    modem_id: Optional[str] = Field(None, description="Filter by modem ID")
    limit: int = Field(default=1000, le=10000, description="Maximum number of checks to return")

    class Config:
        json_schema_extra = {
            "example": {
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
                "modem_id": "XB8-AABBCCDDEEFF",
                "limit": 1000
            }
        }


class BulkUploadResponse(BaseModel):
    """Response schema for bulk upload."""
    success: bool
    message: str
    uploaded_count: int
    failed_count: int
    errors: List[Dict[str, str]] = []


class DeleteCheckRequest(BaseModel):
    """Request schema for deleting a check."""
    check_id: int = Field(..., gt=0)


class DeleteAllChecksRequest(BaseModel):
    """Request schema for deleting all checks for a modem."""
    modem_id: str = Field(..., min_length=1)


# Trend data schemas for optimized dashboard performance
class RxAggregates(BaseModel):
    """Aggregated RX channel metrics for trend charts."""
    min_power: Optional[float] = None
    avg_power: Optional[float] = None
    max_power: Optional[float] = None
    min_snr: Optional[float] = None
    avg_snr: Optional[float] = None
    max_snr: Optional[float] = None
    avg_ber: Optional[float] = None
    max_ber: Optional[float] = None
    avg_corrected_rate: Optional[float] = None
    max_corrected_rate: Optional[float] = None


class TxAggregates(BaseModel):
    """Aggregated TX channel metrics for trend charts."""
    min_power: Optional[float] = None
    avg_power: Optional[float] = None
    max_power: Optional[float] = None
    bonded_count: int = 0
    impaired_count: int = 0


class TrendDataItem(BaseModel):
    """Lightweight check data for trend charts with pre-computed aggregates."""
    id: int
    check_time: int  # Unix timestamp (epoch seconds)

    # Speed test metrics
    upload_speed: Optional[float] = None
    download_speed: Optional[float] = None
    upload_limit: Optional[float] = None
    download_limit: Optional[float] = None

    # Ping/latency metrics
    ping_google_avg: Optional[float] = None
    ping_google_loss: Optional[float] = None
    ping_google_max: Optional[float] = None
    ping_cloudflare_avg: Optional[float] = None
    ping_cloudflare_loss: Optional[float] = None
    ping_cloudflare_max: Optional[float] = None
    speedtest_latency: Optional[float] = None
    speedtest_max_latency: Optional[float] = None

    # Uptime
    uptime_days: Optional[float] = None

    # Pre-aggregated signal metrics
    rx_scqam: Optional[RxAggregates] = None
    rx_ofdm: Optional[RxAggregates] = None
    tx_scqam: Optional[TxAggregates] = None
    tx_ofdma: Optional[TxAggregates] = None


class TrendDataResponse(BaseModel):
    """Response schema for trend data endpoint."""
    success: bool
    data: List[TrendDataItem]
    total_count: int


# Summary view schemas for aggregated statistics across all checks
class MinAvgMaxRange(BaseModel):
    """Statistics for a single metric: min, avg, max, range, and stdev."""
    min: Optional[float] = None
    avg: Optional[float] = None
    max: Optional[float] = None
    range: Optional[float] = None
    stdev: Optional[float] = None


class PeriodOverview(BaseModel):
    """Overview statistics for the selected period."""
    total_checks: int
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    checks_with_speedtest: int = 0
    detected_reboots: int = 0

    @field_serializer('period_start', 'period_end')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        """Serialize datetime as ISO with Z suffix to indicate UTC."""
        return dt.isoformat() + 'Z' if dt else None


class RxSignalSummary(BaseModel):
    """Aggregated downstream signal quality statistics."""
    scqam_power: Optional[MinAvgMaxRange] = None
    scqam_snr: Optional[MinAvgMaxRange] = None
    ofdm_power: Optional[MinAvgMaxRange] = None
    ofdm_snr: Optional[MinAvgMaxRange] = None


class TxSignalSummary(BaseModel):
    """Aggregated upstream signal quality statistics."""
    scqam_power: Optional[MinAvgMaxRange] = None
    ofdma_power: Optional[MinAvgMaxRange] = None


class ErrorRateSummary(BaseModel):
    """Aggregated error rate statistics."""
    scqam_corrected_ber: Optional[MinAvgMaxRange] = None
    scqam_uncorrectable_ber: Optional[MinAvgMaxRange] = None
    ofdm_corrected_ber: Optional[MinAvgMaxRange] = None
    ofdm_uncorrectable_ber: Optional[MinAvgMaxRange] = None


class NetworkSummary(BaseModel):
    """Aggregated network performance statistics."""
    download_speed: Optional[MinAvgMaxRange] = None
    upload_speed: Optional[MinAvgMaxRange] = None
    ping_google: Optional[MinAvgMaxRange] = None
    ping_cloudflare: Optional[MinAvgMaxRange] = None
    loss_google: Optional[MinAvgMaxRange] = None
    loss_cloudflare: Optional[MinAvgMaxRange] = None
    jitter_google: Optional[MinAvgMaxRange] = None
    jitter_cloudflare: Optional[MinAvgMaxRange] = None


class SummaryData(BaseModel):
    """Core summary data (reusable for both full and filtered summaries)."""
    period: Optional[PeriodOverview] = None
    rx_signal: Optional[RxSignalSummary] = None
    tx_signal: Optional[TxSignalSummary] = None
    error_rates: Optional[ErrorRateSummary] = None
    network: Optional[NetworkSummary] = None


class SummaryDataResponse(BaseModel):
    """Response with both full and maintenance-excluded summaries."""
    success: bool
    full: Optional[SummaryData] = None
    maint_excluded: Optional[SummaryData] = None  # 2am-5am excluded
    error: Optional[str] = None
