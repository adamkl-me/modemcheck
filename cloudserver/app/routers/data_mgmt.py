"""
Data management router for bulk operations and deletions.
"""
import json
import zipfile
from io import BytesIO
from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.audit import log_user_activity
from app.core.config import settings
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Check not found"
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No checks found for this modem"
        )

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


@router.post("/bulk_upload")
@limiter.limit(lambda: settings.api_data_mgmt_rate_limit)
async def bulk_upload_checks(
    files: List[UploadFile] = File(...),
    request: Request = None,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Bulk upload multiple modem check JSON files.

    Requires: elevated or admin role
    """
    if len(files) > settings.max_bulk_upload_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many files. Maximum is {settings.max_bulk_upload_files}"
        )

    results = {
        "total": len(files),
        "success": 0,
        "failed": 0,
        "errors": []
    }

    for file in files:
        try:
            # Read file content
            content = await file.read()

            # Parse JSON
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                results["failed"] += 1
                results["errors"].append(f"{file.filename}: Invalid JSON - {str(e)}")
                continue

            # Extract required fields
            sysinfo = data.get('sysinfo', {})
            modem_type = sysinfo.get('modemtype', 'unknown')
            modem_mac = sysinfo.get('modemmac', 'unknown')
            modem_id = f"{modem_type}-{modem_mac}"

            # Get filename
            filename = file.filename or sysinfo.get('filename', 'unknown.json')

            # Parse check_time
            check_time_raw = sysinfo.get('checktime')
            check_time = None
            if check_time_raw:
                try:
                    if isinstance(check_time_raw, int):
                        if check_time_raw > 0:
                            check_time = datetime.utcfromtimestamp(check_time_raw)
                    else:
                        check_time_str = str(check_time_raw).replace('Z', '+00:00')
                        check_time = datetime.fromisoformat(check_time_str)
                except Exception:
                    pass

            # Check for duplicate
            existing = await db.execute(
                select(ModemCheck).where(
                    and_(
                        ModemCheck.modem_id == modem_id,
                        ModemCheck.filename == filename
                    )
                )
            )
            if existing.scalars().first():
                results["failed"] += 1
                results["errors"].append(f"{file.filename}: Duplicate - already exists in database")
                continue

            # Insert into database
            db_filename = f"{modem_id}/{filename}"
            new_check = ModemCheck(
                modem_id=modem_id,
                modem_type=modem_type,
                filename=db_filename,
                check_time=check_time or datetime.utcnow(),
                full_data=data,
                created_at=datetime.utcnow()
            )
            db.add(new_check)
            results["success"] += 1

        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"{file.filename}: {str(e)}")

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

    Requires: elevated or admin role
    """
    # Build query
    query = select(ModemCheck)
    conditions = []

    if modem_id:
        conditions.append(ModemCheck.modem_id == modem_id)

    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            conditions.append(ModemCheck.check_time >= start_dt)
        except Exception:
            pass

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            conditions.append(ModemCheck.check_time <= end_dt)
        except Exception:
            pass

    if conditions:
        query = query.where(and_(*conditions))

    # Execute query
    result = await db.execute(query.limit(10000))  # Limit to prevent memory issues
    checks = result.scalars().all()

    if not checks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No checks found matching criteria"
        )

    # Create ZIP file in memory
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for check in checks:
            # Use filename from database or generate one
            filename = check.filename or f"{check.modem_id}_{check.id}.json"

            # Add JSON data to ZIP
            json_content = json.dumps(check.full_data, indent=2)
            zip_file.writestr(filename, json_content)

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
            "files_count": len(checks)
        },
        user_agent=get_user_agent(request)
    )

    # Prepare response
    zip_buffer.seek(0)
    filename_suffix = f"_{modem_id}" if modem_id else ""
    download_filename = f"modemcheck_data{filename_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{download_filename}"'}
    )
