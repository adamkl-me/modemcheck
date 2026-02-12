"""
Data management router for bulk operations and deletions.
"""
import json
import logging
import re
import tempfile
import zipfile
from io import BytesIO
from typing import List
from datetime import datetime, timezone

from app.core.utils import utc_now

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, delete, and_

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.audit import log_user_activity
from app.core.config import settings
from app.core.zip_security import (
    validate_zip_file,
    check_zip_bomb,
    sanitize_zip_path,
    validate_utf8
)
from app.core.errors import (
    CheckNotFoundError,
    NoChecksFoundError,
    ZipValidationError,
    ZipBombError,
    ValidationError,
)
from app.models import ModemCheck
from app.schemas.modem_check import DeleteCheckRequest, DeleteAllChecksRequest
from app.schemas.common import SuccessResponse
from app.middleware.auth import (
    require_admin,
    require_elevated_or_admin,
    get_client_ip,
    get_user_agent,
)
from app.middleware.csrf import verify_csrf

router = APIRouter(
    prefix="/api/data",
    tags=["Data Management"],
    dependencies=[Depends(verify_csrf)]
)


@router.delete("/check", response_model=SuccessResponse)
@limiter.limit(lambda: settings.api_data_mgmt_rate_limit)
async def delete_check(
    delete_data: DeleteCheckRequest,
    request: Request,
    session_data: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a single check by ID.

    Requires: admin role
    """
    # Get check info before deleting for logging
    result = await db.execute(
        select(ModemCheck).where(ModemCheck.id == delete_data.check_id)
    )
    check = result.scalars().first()

    if not check:
        raise CheckNotFoundError(check_id=delete_data.check_id)

    # Delete check
    await db.execute(
        delete(ModemCheck).where(ModemCheck.id == delete_data.check_id)
    )
    await db.commit()

    # Log action
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="delete_check",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={
            "check_id": delete_data.check_id,
            "modem_id": check.modem_id,
            "filename": check.filename
        },
        user_agent=get_user_agent(request)
    )

    return SuccessResponse(
        success=True,
        message=f"Check {delete_data.check_id} deleted successfully"
    )


@router.delete("/modem_checks", response_model=SuccessResponse)
@limiter.limit(lambda: settings.api_data_mgmt_rate_limit)
async def delete_all_modem_checks(
    delete_data: DeleteAllChecksRequest,
    request: Request,
    session_data: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete all checks for a specific modem.

    Requires: admin role
    """
    # Count checks to be deleted
    count_result = await db.execute(
        select(ModemCheck).where(ModemCheck.modem_id == delete_data.modem_id)
    )
    check_count = len(count_result.scalars().all())

    if check_count == 0:
        raise NoChecksFoundError(modem_id=delete_data.modem_id)

    # Delete all checks
    await db.execute(
        delete(ModemCheck).where(ModemCheck.modem_id == delete_data.modem_id)
    )
    await db.commit()

    # Log action
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="delete_all_modem_checks",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={
            "modem_id": delete_data.modem_id,
            "checks_deleted": check_count
        },
        user_agent=get_user_agent(request)
    )

    return SuccessResponse(
        success=True,
        message=f"Deleted {check_count} checks for modem '{delete_data.modem_id}'"
    )


def is_valid_mac_address(mac: str) -> bool:
    """Validate MAC address format (12 hex chars, with or without separators)."""
    if not mac:
        return False
    # Remove common separators and check for 12 hex characters
    clean_mac = re.sub(r'[:\-\.]', '', mac.upper())
    return bool(re.match(r'^[0-9A-F]{12}$', clean_mac))


async def _process_json_content(content: bytes, filename: str, db: AsyncSession, results: dict):
    """
    Helper function to process a single JSON file content.

    Validates that the file is a valid modem check with required fields:
    - sysinfo object with modemtype, modemmac (valid format), checktime
    - At least one of rx or tx arrays with data

    Args:
        content: File content as bytes
        filename: Name of the file
        db: Database session
        results: Results dictionary to update
    """
    try:
        # Parse JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            results["failed"] += 1
            results["errors"].append(f"{filename}: Invalid JSON - {str(e)}")
            return

        # Validate required structure
        validation_errors = []

        # Must have sysinfo object
        if 'sysinfo' not in data or not isinstance(data.get('sysinfo'), dict):
            validation_errors.append("Missing 'sysinfo' object")
        else:
            sysinfo = data['sysinfo']
            # Must have modem type
            if not sysinfo.get('modemtype'):
                validation_errors.append("Missing 'sysinfo.modemtype'")
            # Must have valid MAC address
            mac = sysinfo.get('modemmac')
            if not mac:
                validation_errors.append("Missing 'sysinfo.modemmac'")
            elif not is_valid_mac_address(mac):
                validation_errors.append(f"Invalid MAC address format: '{mac}'")
            # Must have check time
            if not sysinfo.get('checktime'):
                validation_errors.append("Missing 'sysinfo.checktime'")

        # Must have rx (downstream) or tx (upstream) data - at minimum one
        has_rx = 'rx' in data and isinstance(data.get('rx'), list) and len(data['rx']) > 0
        has_tx = 'tx' in data and isinstance(data.get('tx'), list) and len(data['tx']) > 0
        if not has_rx and not has_tx:
            validation_errors.append("Missing channel data (no 'rx' or 'tx' arrays)")

        if validation_errors:
            results["failed"] += 1
            results["errors"].append(f"{filename}: {'; '.join(validation_errors)}")
            return

        # Extract required fields (now validated)
        sysinfo = data.get('sysinfo', {})
        modem_type = sysinfo.get('modemtype', 'unknown')
        modem_mac = sysinfo.get('modemmac', 'unknown')
        modem_id = f"{modem_type}-{modem_mac}"

        # Get filename from data if not provided
        if not filename or filename == 'unknown.json':
            filename = sysinfo.get('filename', 'unknown.json')

        # Parse check_time (naive UTC for PostgreSQL asyncpg compatibility)
        check_time_raw = sysinfo.get('checktime')
        check_time = None
        if check_time_raw:
            try:
                if isinstance(check_time_raw, int):
                    if check_time_raw > 0:
                        check_time = datetime.fromtimestamp(check_time_raw, tz=timezone.utc).replace(tzinfo=None)  # Naive UTC
                else:
                    check_time_str = str(check_time_raw).replace('Z', '+00:00')
                    aware_dt = datetime.fromisoformat(check_time_str)
                    check_time = aware_dt.replace(tzinfo=None)  # Convert to naive UTC
            except (ValueError, TypeError, OSError) as e:
                # Log but continue with default timestamp
                logger.debug(f"Failed to parse check_time '{check_time_raw}' in {filename}: {e}")

        # Insert into database - let database constraint handle duplicates
        db_filename = f"{modem_id}/{filename}"
        new_check = ModemCheck(
            modem_id=modem_id,
            modem_type=modem_type,
            filename=db_filename,
            check_time=check_time or utc_now(),
            full_data=data,
            created_at=utc_now()
        )
        db.add(new_check)

        # Flush to detect constraint violations immediately
        try:
            await db.flush()
            results["success"] += 1
        except IntegrityError:
            await db.rollback()
            results["failed"] += 1
            results["errors"].append(f"{filename}: Duplicate - already exists in database")

    except Exception as e:
        results["failed"] += 1
        results["errors"].append(f"{filename}: {str(e)}")


@router.post("/bulk_upload")
@limiter.limit(lambda: settings.api_data_mgmt_rate_limit)
async def bulk_upload_checks(
    file: UploadFile = File(...),
    request: Request = None,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Bulk upload modem check JSON files (individual file or ZIP archive).

    Accepts:
    - Single JSON file
    - ZIP archive containing multiple JSON files

    Security features:
    - ZIP bomb detection (100:1 compression ratio limit)
    - Path traversal protection
    - UTF-8 encoding validation
    - File count limits (1000 max)
    - Size limits (100MB uncompressed max)

    Requires: elevated or admin role
    """
    content = await file.read()

    results = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "errors": []
    }

    # Detect if this is a ZIP file
    is_zip = (
        file.content_type == "application/zip" or
        file.content_type == "application/x-zip-compressed" or
        (file.filename and file.filename.lower().endswith('.zip')) or
        (len(content) >= 4 and content[0:4] == b'PK\x03\x04')
    )

    if is_zip:
        # Validate ZIP file
        is_valid, error = validate_zip_file(content)
        if not is_valid:
            raise ZipValidationError(reason=error)

        zip_buffer = BytesIO(content)

        # Check for ZIP bombs
        is_safe, error = check_zip_bomb(zip_buffer, max_ratio=100.0, max_uncompressed_size=100 * 1024 * 1024)
        if not is_safe:
            raise ZipBombError(reason=error)

        # Extract and process files from ZIP
        zip_buffer.seek(0)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            file_list = zf.infolist()

            # Check file count
            json_files = [f for f in file_list if not f.is_dir() and not f.filename.endswith('.zip')]
            if len(json_files) > settings.max_bulk_upload_files:
                raise ValidationError(
                    message=f"Too many files in ZIP. Maximum is {settings.max_bulk_upload_files}",
                    details={"max_files": settings.max_bulk_upload_files, "actual_files": len(json_files)}
                )

            for file_info in file_list:
                # Skip directories
                if file_info.is_dir():
                    continue

                # Skip nested ZIPs
                if file_info.filename.endswith('.zip'):
                    results["failed"] += 1
                    results["errors"].append(f"{file_info.filename}: Nested ZIP files not allowed")
                    results["total"] += 1
                    continue

                # Sanitize path
                safe_path = sanitize_zip_path(file_info.filename)
                if safe_path is None:
                    results["failed"] += 1
                    results["errors"].append(f"{file_info.filename}: Path traversal detected")
                    results["total"] += 1
                    continue

                # Extract file content
                try:
                    file_content = zf.read(file_info)
                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append(f"{file_info.filename}: Extraction failed - {str(e)}")
                    results["total"] += 1
                    continue

                # Validate UTF-8 encoding
                if not validate_utf8(file_content):
                    results["failed"] += 1
                    results["errors"].append(f"{file_info.filename}: Invalid UTF-8 encoding")
                    results["total"] += 1
                    continue

                # Process JSON file
                results["total"] += 1
                await _process_json_content(file_content, file_info.filename, db, results)

    else:
        # Process single JSON file
        results["total"] = 1
        await _process_json_content(content, file.filename or 'uploaded.json', db, results)

    # Commit all successful inserts
    await db.commit()

    # Log action
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="bulk_upload",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={
            "total_files": results["total"],
            "successful": results["success"],
            "failed": results["failed"]
        },
        user_agent=get_user_agent(request)
    )

    return {
        "success": True,
        "message": f"Processed {results['total']} files: {results['success']} succeeded, {results['failed']} failed",
        "results": results
    }


@router.get("/bulk_download")
@limiter.limit(lambda: settings.api_data_mgmt_rate_limit)
async def bulk_download_checks(
    modem_id: str = None,
    start_date: str = None,
    end_date: str = None,
    request: Request = None,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Bulk download modem checks as a ZIP file.

    Uses streaming with batched database queries to minimize memory usage:
    - Fetches records in batches of 500
    - Writes to disk-backed temp file after 10MB
    - Streams response to client

    Requires: elevated or admin role
    """
    from sqlalchemy.orm import load_only

    # Build query with load_only to reduce memory per record
    query = select(ModemCheck).options(
        load_only(ModemCheck.id, ModemCheck.modem_id, ModemCheck.filename, ModemCheck.full_data)
    )
    conditions = []

    if modem_id:
        conditions.append(ModemCheck.modem_id == modem_id)

    if start_date:
        try:
            aware_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            start_dt = aware_dt.replace(tzinfo=None)  # Naive UTC for comparison
            conditions.append(ModemCheck.check_time >= start_dt)
        except ValueError as e:
            logger.debug(f"Invalid start_date format '{start_date}', ignoring filter: {e}")

    if end_date:
        try:
            aware_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            end_dt = aware_dt.replace(tzinfo=None)  # Naive UTC for comparison
            conditions.append(ModemCheck.check_time <= end_dt)
        except ValueError as e:
            logger.debug(f"Invalid end_date format '{end_date}', ignoring filter: {e}")

    if conditions:
        query = query.where(and_(*conditions))

    # Order by ID for consistent batching
    query = query.order_by(ModemCheck.id).limit(10000)

    # Create ZIP using temp file (spills to disk automatically after 10MB)
    # This prevents memory exhaustion with large downloads
    tmp = tempfile.SpooledTemporaryFile(max_size=10*1024*1024)
    files_count = 0

    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Stream results in batches using yield_per for memory efficiency
        result = await db.stream(query)

        async for check in result.scalars():
            # Use filename from database or generate one
            filename = check.filename or f"{check.modem_id}_{check.id}.json"

            # Add JSON data to ZIP
            json_content = json.dumps(check.full_data, indent=2)
            zip_file.writestr(filename, json_content)
            files_count += 1

    if files_count == 0:
        tmp.close()
        raise NoChecksFoundError(criteria="provided filters")

    # Log action
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="bulk_download",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={
            "modem_id": modem_id,
            "start_date": start_date,
            "end_date": end_date,
            "files_count": files_count
        },
        user_agent=get_user_agent(request)
    )

    # Prepare response
    tmp.seek(0)
    filename_suffix = f"_{modem_id}" if modem_id else ""
    download_filename = f"modemcheck_data{filename_suffix}_{utc_now().strftime('%Y%m%d_%H%M%S')}.zip"

    return StreamingResponse(
        tmp,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{download_filename}"'}
    )
