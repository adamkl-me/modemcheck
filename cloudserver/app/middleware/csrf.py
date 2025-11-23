"""
CSRF protection middleware and dependencies.
"""
from typing import Optional
from fastapi import Depends, HTTPException, status, Request, Cookie

from app.core.security import validate_csrf_token, generate_csrf_token


async def get_csrf_token_from_request(request: Request) -> Optional[str]:
    """
    Extract CSRF token from request.

    Checks in order:
    1. X-CSRF-Token header
    2. POST body field 'csrf_token'
    3. Query parameter 'csrf_token'
    """
    # Check header first (preferred method)
    csrf_token = request.headers.get("X-CSRF-Token")
    if csrf_token:
        return csrf_token

    # Check POST body (form data or JSON)
    if request.method == "POST":
        try:
            # Try JSON body first
            if request.headers.get("content-type", "").startswith("application/json"):
                body = await request.json()
                if isinstance(body, dict) and "csrf_token" in body:
                    return body["csrf_token"]
            else:
                # Try form data
                form = await request.form()
                if "csrf_token" in form:
                    return form["csrf_token"]
        except Exception:
            pass

    # Check query parameters (least preferred)
    csrf_token = request.query_params.get("csrf_token")
    if csrf_token:
        return csrf_token

    return None


async def verify_csrf(
    request: Request,
    modemcheck_session: Optional[str] = Cookie(None),
    csrf_token: Optional[str] = Depends(get_csrf_token_from_request)
) -> bool:
    """
    Verify CSRF token matches session (with automatic token rotation).

    Required for all state-changing operations (POST, PUT, DELETE).
    After validation, a new CSRF token is generated to prevent reuse.

    Raises:
        403 if CSRF token is invalid
    """
    # Skip CSRF check for GET, HEAD, OPTIONS
    if request.method in ["GET", "HEAD", "OPTIONS"]:
        return True

    # Require both session and CSRF token
    if not modemcheck_session or not csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token required"
        )

    # Validate CSRF token (one-time use - token is deleted during validation)
    is_valid = await validate_csrf_token(csrf_token, modemcheck_session)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token"
        )

    # Generate new CSRF token for next request (token rotation)
    # Store in request state so response can include it
    new_csrf_token = await generate_csrf_token(modemcheck_session)
    request.state.new_csrf_token = new_csrf_token

    return True
