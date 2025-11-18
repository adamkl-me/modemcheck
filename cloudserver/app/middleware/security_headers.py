"""
Security headers middleware for FastAPI.

Adds HTTP security headers to all responses to prevent common web vulnerabilities.
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all HTTP responses.

    Headers added:
    - Strict-Transport-Security: Enforces HTTPS connections
    - X-Content-Type-Options: Prevents MIME type sniffing
    - X-Frame-Options: Prevents clickjacking attacks
    - X-XSS-Protection: Legacy XSS protection for older browsers
    - Content-Security-Policy: Restricts resource loading to prevent XSS
    - Referrer-Policy: Controls referrer information sharing
    - Permissions-Policy: Controls browser features and APIs
    """

    async def dispatch(self, request: Request, call_next):
        """Add security headers to response."""
        response: Response = await call_next(request)

        # HSTS: Force HTTPS for 1 year (only add if using HTTPS)
        # Check if request is HTTPS via X-Forwarded-Proto header (Cloudflare Tunnel)
        is_https = (
            request.headers.get("x-forwarded-proto", "").lower() == "https"
            or request.url.scheme == "https"
            or settings.is_test()  # Always add in test mode for verification
        )

        if is_https:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking (disallow framing)
        response.headers["X-Frame-Options"] = "DENY"

        # Legacy XSS protection (modern browsers use CSP instead)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Content Security Policy
        # Allows scripts and styles from same origin, inline styles for UI
        # Prevents loading resources from untrusted sources
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline'",  # unsafe-inline needed for inline scripts in HTML
            "style-src 'self' 'unsafe-inline'",   # unsafe-inline needed for inline styles
            "img-src 'self' data:",               # Allow data URIs for inline images
            "font-src 'self'",
            "connect-src 'self'",                 # API calls to same origin only
            "frame-ancestors 'none'",             # Equivalent to X-Frame-Options: DENY
            "base-uri 'self'",
            "form-action 'self'",
            "upgrade-insecure-requests",          # Automatically upgrade HTTP to HTTPS
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        # Referrer policy: Send full URL for same-origin, only origin for cross-origin
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions Policy (formerly Feature Policy)
        # Disable potentially dangerous browser features
        permissions = [
            "geolocation=()",       # Disable geolocation API
            "microphone=()",        # Disable microphone access
            "camera=()",            # Disable camera access
            "payment=()",           # Disable payment request API
            "usb=()",               # Disable USB API
            "magnetometer=()",      # Disable magnetometer
            "gyroscope=()",         # Disable gyroscope
            "accelerometer=()",     # Disable accelerometer
        ]
        response.headers["Permissions-Policy"] = ", ".join(permissions)

        # Remove server identification headers (security by obscurity)
        if "Server" in response.headers:
            del response.headers["Server"]
        if "X-Powered-By" in response.headers:
            del response.headers["X-Powered-By"]

        return response
