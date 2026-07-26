"""
Security Headers Middleware.

Adds security-related HTTP headers to all responses to protect against
common web vulnerabilities.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

# Paths that serve actual HTML pages (landing page + docs site) rather than
# JSON API responses. These need a CSP that allows the external CDN scripts/
# fonts and inline event handlers those pages use — the strict
# "default-src 'none'" API policy would (and did) break them completely:
# every <script>, onclick=, external stylesheet, and even favicon request
# gets silently blocked by the browser under that policy.
_HTML_PAGE_PREFIXES = ("/site-docs",)
_HTML_PAGE_EXACT_PATHS = ("/",)

_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"

_HTML_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def _is_html_page(path: str) -> bool:
    """Check whether a request path serves an HTML page rather than the API."""
    if path in _HTML_PAGE_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _HTML_PAGE_PREFIXES)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds security headers to all responses.

    Headers added:
    - X-Content-Type-Options: Prevent MIME sniffing
    - X-Frame-Options: Prevent clickjacking
    - X-XSS-Protection: Enable XSS filter in older browsers
    - Strict-Transport-Security: Force HTTPS
    - Content-Security-Policy: Restrict resource loading (strict for the
      API, relaxed — but still locked down beyond 'self' plus a couple of
      explicitly trusted CDNs — for the landing page / docs site)
    - Referrer-Policy: Control referrer information
    - Permissions-Policy: Control browser features
    """

    def __init__(
        self,
        app: ASGIApp,
        hsts_enabled: bool = True,
        csp_enabled: bool = True,
    ) -> None:
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
        call_next: RequestResponseEndpoint,
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
            if _is_html_page(request.url.path):
                # Relaxed CSP for HTML pages that load external CDN
                # scripts/fonts and use inline <script>/onclick handlers
                # (home.html, docs/index.html served under /site-docs).
                response.headers["Content-Security-Policy"] = _HTML_CSP
            else:
                # Strict CSP for the JSON API (no inline scripts, no
                # external resources).
                response.headers["Content-Security-Policy"] = _API_CSP

        return response
