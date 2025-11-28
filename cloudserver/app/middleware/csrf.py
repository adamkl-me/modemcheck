"""
CSRF protection middleware and dependencies.

This module provides:
1. CSRF token extraction from requests (header, body, query param)
2. CSRF token validation dependency for FastAPI routes
3. Middleware to add new CSRF tokens to response headers (X-New-CSRF-Token)

The middleware enables token rotation without requiring separate session_check calls.
"""
from typing import Optional
from fastapi import Depends, HTTPException, status, Request, Cookie
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.security import validate_csrf_token, generate_csrf_token


class CSRFResponseMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add new CSRF token to response headers after token rotation.

    When a CSRF token is validated (and consumed), a new token is generated
    and stored in request.state.new_csrf_token. This middleware adds that
    token to the response headers so the client can use it for the next request.

    Response Header: X-New-CSRF-Token
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Add new CSRF token to response headers if available."""
        response: Response = await call_next(request)

        # Check if a new CSRF token was generated during request processing
        new_csrf_token = getattr(request.state, 'new_csrf_token', None)
        if new_csrf_token:
            response.headers["X-New-CSRF-Token"] = new_csrf_token

        return response


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

    # Generate new CSRF token for next request (token rotation)
    # Store in request state so response can include it - even on failure
    # This allows the client to recover without a page refresh
    new_csrf_token = await generate_csrf_token(modemcheck_session)
    request.state.new_csrf_token = new_csrf_token

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token"
        )

    return True
