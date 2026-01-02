"""
Database API router for querying modem check data.
"""
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, over

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.config import settings
from app.core.errors import InvalidDateRangeError
from app.models import ModemCheck
from app.schemas.modem_check import (
    ModemInfo,
    ModemListResponse,
    CheckListItem,
    CheckListResponse,
    CheckDetailResponse,
    DateRangeRequest,
    CheckWithFullData,
    CheckListWithDataResponse,
    TrendDataResponse,
    SummaryDataResponse,
)
from app.middleware.auth import require_authenticated_user
from app.core.trend_aggregation import aggregate_check_for_trends
from app.core.summary_aggregation import compute_summary_from_trend_data

router = APIRouter(prefix="/api/db", tags=["Database"])


def parse_datetime_range(start_str: str, end_str: str) -> tuple[datetime, datetime]:
    """
    Parse start/end date strings, handling both date-only and datetime formats.

    Accepts:
    - YYYY-MM-DD (appends 00:00:00 for start, 23:59:59 for end)
    - YYYY-MM-DDTHH:MM or YYYY-MM-DDTHH:MM:SS (uses as-is)

    Returns:
        Tuple of (start_datetime, end_datetime)

    Raises:
        InvalidDateRangeError: If date format is invalid
    """
    try:
        # Parse start datetime
        if 'T' in start_str:
            start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        else:
            start_dt = datetime.fromisoformat(f"{start_str}T00:00:00")

        # Parse end datetime
        if 'T' in end_str:
            end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        else:
            end_dt = datetime.fromisoformat(f"{end_str}T23:59:59")

        return start_dt, end_dt
    except ValueError:
        raise InvalidDateRangeError(
            message="Invalid date format. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM"
        )


@router.get("/list_modems", response_model=ModemListResponse)
@limiter.limit(lambda: settings.api_query_rate_limit)
async def list_modems(
    request: Request,
    session_data: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all modems with summary information.

    Returns:
        List of modems with first_seen, last_seen, and check_count
    """
    # Get modem summary using GROUP BY
    query = select(
        ModemCheck.modem_id,
        ModemCheck.modem_type,
        func.min(ModemCheck.check_time).label('first_seen'),
        func.max(ModemCheck.check_time).label('last_seen'),
        func.count(ModemCheck.id).label('check_count')
    ).group_by(
        ModemCheck.modem_id,
        ModemCheck.modem_type
    ).order_by(
        func.max(ModemCheck.check_time).desc()
    )

    result = await db.execute(query)
    rows = result.all()

    modems = [
        ModemInfo(
            modem_id=row.modem_id,
            modem_type=row.modem_type,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            check_count=row.check_count
        )
        for row in rows
    ]

    return ModemListResponse(success=True, modems=modems)


@router.get("/list_checks", response_model=CheckListResponse)
@limiter.limit(lambda: settings.api_query_rate_limit)
async def list_checks(
    request: Request,
    modem_id: str = Query(..., description="Modem ID to filter by"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    limit: int = Query(default=1000, le=10000, description="Maximum number of checks"),
    session_data: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List checks for a specific modem within a date range.

    Args:
        modem_id: Modem ID to filter
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        limit: Maximum number of checks to return (max 10000)
    """
    # Parse dates (supports both YYYY-MM-DD and YYYY-MM-DDTHH:MM formats)
    start_dt, end_dt = parse_datetime_range(start_date, end_date)

    # Optimized: Use a single query with window function to get both data and count
    # This avoids executing the same WHERE clause twice
    query = select(
        ModemCheck,
        func.count().over().label('total_count')
    ).where(
        and_(
            ModemCheck.modem_id == modem_id,
            ModemCheck.check_time >= start_dt,
            ModemCheck.check_time <= end_dt
        )
    ).order_by(ModemCheck.check_time.desc()).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    # Extract ORM objects and total count
    checks = [row[0] for row in rows] if rows else []
    total_count = rows[0][1] if rows else 0

    check_items = [
        CheckListItem(
            id=check.id,
            filename=check.filename,
            check_time=check.check_time,
            modem_type=check.modem_type,
            avg_downstream_snr=check.avg_downstream_snr,
            avg_downstream_power=check.avg_downstream_power,
            total_uncorrected_errors=check.total_uncorrected_errors,
            client_version=check.client_version
        )
        for check in checks
    ]

    return CheckListResponse(
        success=True,
        checks=check_items,
        total_count=total_count
    )


@router.get("/get_check/{check_id}", response_model=CheckDetailResponse)
@limiter.limit(lambda: settings.api_query_rate_limit)
async def get_check(
    request: Request,
    check_id: int,
    session_data: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get full details for a specific check.

    Returns the complete JSON data for the check.
    """
    result = await db.execute(
        select(ModemCheck).where(ModemCheck.id == check_id)
    )
    check = result.scalars().first()

    if not check:
        return CheckDetailResponse(
            success=False,
            error="Check not found"
        )

    return CheckDetailResponse(
        success=True,
        check=check.full_data  # Return the JSONB data
    )


@router.post("/get_all_checks", response_model=CheckListWithDataResponse)
@limiter.limit("300/second")  # API rate limit: 300 requests per second
async def get_all_checks(
    request: Request,
    date_range: DateRangeRequest,
    session_data: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all checks within a date range with full JSON data, optionally filtered by modem_id.

    This is optimized for the viewer - returns complete check data in a single request.
    """
    # Parse dates (supports both YYYY-MM-DD and YYYY-MM-DDTHH:MM formats)
    start_dt, end_dt = parse_datetime_range(date_range.start_date, date_range.end_date)

    # Build query
    conditions = [
        ModemCheck.check_time >= start_dt,
        ModemCheck.check_time <= end_dt
    ]

    if date_range.modem_id:
        conditions.append(ModemCheck.modem_id == date_range.modem_id)

    query = select(ModemCheck).where(
        and_(*conditions)
    ).order_by(ModemCheck.check_time.desc()).limit(date_range.limit)

    result = await db.execute(query)
    checks = result.scalars().all()

    # Count total
    count_query = select(func.count(ModemCheck.id)).where(and_(*conditions))
    total_result = await db.execute(count_query)
    total_count = total_result.scalar()

    # Return full data for each check
    check_items = [
        CheckWithFullData(
            id=check.id,
            filename=check.filename,
            check_time=check.check_time,
            modem_type=check.modem_type,
            full_data=check.full_data  # Include complete JSON
        )
        for check in checks
    ]

    return CheckListWithDataResponse(
        success=True,
        checks=check_items,
        total_count=total_count
    )


@router.post("/get_trend_data", response_model=TrendDataResponse)
@limiter.limit("300/second")
async def get_trend_data(
    request: Request,
    date_range: DateRangeRequest,
    session_data: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get pre-aggregated trend data for charts.

    Returns lightweight aggregated metrics instead of full JSONB data.
    Significantly reduces transfer size (~500 bytes vs ~15-50KB per check)
    and eliminates client-side aggregation.

    This endpoint is optimized for the dashboard trend view charts.
    """
    # Parse dates (supports both YYYY-MM-DD and YYYY-MM-DDTHH:MM formats)
    start_dt, end_dt = parse_datetime_range(date_range.start_date, date_range.end_date)

    # Build query conditions
    conditions = [
        ModemCheck.check_time >= start_dt,
        ModemCheck.check_time <= end_dt
    ]

    if date_range.modem_id:
        conditions.append(ModemCheck.modem_id == date_range.modem_id)

    # Query checks ordered by time ascending (for chart rendering)
    query = select(ModemCheck).where(
        and_(*conditions)
    ).order_by(ModemCheck.check_time.asc()).limit(date_range.limit)

    result = await db.execute(query)
    checks = result.scalars().all()

    # Aggregate each check for trend display
    trend_items = [aggregate_check_for_trends(check) for check in checks]

    # Count total matching records
    count_query = select(func.count(ModemCheck.id)).where(and_(*conditions))
    total_result = await db.execute(count_query)
    total_count = total_result.scalar()

    return TrendDataResponse(
        success=True,
        data=trend_items,
        total_count=total_count
    )


@router.post("/get_summary_data", response_model=SummaryDataResponse)
@limiter.limit("300/second")
async def get_summary_data(
    request: Request,
    date_range: DateRangeRequest,
    session_data: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get aggregated summary statistics for the selected period.

    Returns Min/Avg/Max/Range for all key metrics across all checks.
    Uses pre-aggregated trend data for efficiency.

    This endpoint is optimized for the dashboard Summary view.
    """
    # Parse dates (supports both YYYY-MM-DD and YYYY-MM-DDTHH:MM formats)
    start_dt, end_dt = parse_datetime_range(date_range.start_date, date_range.end_date)

    # Build query conditions
    conditions = [
        ModemCheck.check_time >= start_dt,
        ModemCheck.check_time <= end_dt
    ]

    if date_range.modem_id:
        conditions.append(ModemCheck.modem_id == date_range.modem_id)

    # Query checks ordered by time ascending (for reboot detection)
    query = select(ModemCheck).where(
        and_(*conditions)
    ).order_by(ModemCheck.check_time.asc()).limit(date_range.limit)

    result = await db.execute(query)
    checks = result.scalars().all()

    if not checks:
        return SummaryDataResponse(
            success=False,
            error="No data found for the selected criteria"
        )

    # Aggregate each check for trend format first
    trend_items = [aggregate_check_for_trends(check) for check in checks]

    # Compute summary from trend data and checks
    return compute_summary_from_trend_data(trend_items, checks)
