"""
Pydantic schemas for modem check data.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


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
