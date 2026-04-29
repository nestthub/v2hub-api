"""
Security Headers Middleware.

Adds security-related HTTP headers to all responses to protect against
common web vulnerabilities.
"""

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds security headers to all responses.
    
    Headers added:
    - X-Content-Type-Options: Prevent MIME sniffing
    - X-Frame-Options: Prevent clickjacking
    - X-XSS-Protection: Enable XSS filter in older browsers
    - Strict-Transport-Security: Force HTTPS
    - Content-Security-Policy: Restrict resource loading
    - Referrer-Policy: Control referrer information
    - Permissions-Policy: Control browser features
    """
    
    def __init__(
        self,
        app,
        hsts_enabled: bool = True,
        csp_enabled: bool = True,
    ):
        """
        Initialize security headers middleware.
        
        Args:
            app: FastAPI application
            hsts_enabled: Enable HSTS header (only for HTTPS)
            csp_enabled: Enable CSP header
        """
        super().__init__(app)
        self.hsts_enabled = hsts_enabled
        self.csp_enabled = csp_enabled
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request and add security headers to response."""
        response = await call_next(request)
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # Enable XSS protection (legacy, but doesn't hurt)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Disable unnecessary browser features
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=(), "
            "ambient-light-sensor=(), "
            "autoplay=(), "
            "encrypted-media=(), "
            "picture-in-picture=()"
        )
        
        # HSTS - Force HTTPS (only add if HTTPS is used)
        if self.hsts_enabled and request.url.scheme == "https":
            # 1 year = 31536000 seconds
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        
        # Content Security Policy
        if self.csp_enabled:
            # Strict CSP for API (no inline scripts, no external resources)
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )
        
        return response
