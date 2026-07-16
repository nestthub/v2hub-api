"""
Main FastAPI application.

Configures and initializes the VPN Subscription API with:
- API routers
- CORS middleware
- Exception handlers
- Lifecycle events
- OpenAPI documentation
- Prometheus metrics
"""

import logging
import re
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from prometheus_client import Counter, Gauge, Histogram, REGISTRY
from prometheus_client.openmetrics.exposition import (
    CONTENT_TYPE_LATEST,
    generate_latest,
)

from src.api.endpoints import admin, public, subscriptions
from src.core.config import settings
from src.core.exceptions import VPNSubscriptionError
from src.db.session import close_db, init_db
from src.middlewares.rate_limit_middleware import (
    check_internal_rate_limit,
    check_public_rate_limit,
    setup_rate_limiting,
)
from src.middlewares.security_headers_middleware import SecurityHeadersMiddleware
from src.services.cache_service import close_redis_client, get_redis_client
from src.utils.http_client import close_http_client

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=settings.log_level,
    format=settings.log_format,
)
logger = logging.getLogger(__name__)


# ─── Prometheus metrics ───────────────────────────────────────────────────────

APP_NAME = "v2hub"

APP_INFO = Gauge(
    "fastapi_app_info",
    "FastAPI application info",
    ["app_name", "version"],
)
APP_INFO.labels(app_name=APP_NAME, version="1.0.0").set(1)

HTTP_REQUESTS_TOTAL = Counter(
    "fastapi_requests_total",
    "Total HTTP requests",
    ["method", "path", "app_name"],
)

HTTP_RESPONSES_TOTAL = Counter(
    "fastapi_responses_total",
    "Total HTTP responses by status code",
    ["method", "path", "status_code", "app_name"],
)

HTTP_REQUEST_DURATION = Histogram(
    "fastapi_requests_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path", "app_name"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "fastapi_requests_in_progress",
    "HTTP requests currently in progress",
    ["method", "path", "app_name"],
)

HTTP_EXCEPTIONS_TOTAL = Counter(
    "fastapi_exceptions_total",
    "Total HTTP exceptions",
    ["method", "path", "exception_type", "app_name"],
)


# ─── Path normalization ───────────────────────────────────────────────────────

# Порядок важен — более специфичные паттерны первыми
PATH_PATTERNS = [
    (re.compile(r"^/sub/[^/]+$"),                         "/sub/{token}"),
    (re.compile(r"^/api/v1/subs/[^/]+/sources$"),         "/api/v1/subs/{token}/sources"),
    (re.compile(r"^/api/v1/subs/[^/]+/comments$"),        "/api/v1/subs/{token}/comments"),
    (re.compile(r"^/api/v1/subs/[^/]+/refresh$"),         "/api/v1/subs/{token}/refresh"),
    (re.compile(r"^/api/v1/subs/[^/]+$"),                 "/api/v1/subs/{token}"),
    (re.compile(r"^/api/v1/admin/users/[^/]+/(.+)$"),     r"/api/v1/admin/users/{id}/\1"),
    (re.compile(r"^/api/v1/admin/users/[^/]+$"),          "/api/v1/admin/users/{id}"),
]

# Мусорные пути от ботов и сканеров — не трекаем
IGNORED_PATHS = re.compile(
    r"^(/wp-admin|/wp-login|/\.env|/\.git|/phpmyadmin|/admin\.php"
    r"|/xmlrpc\.php|/cgi-bin|/actuator|/boaform|/shell"
    r"|.*\.(php|asp|aspx|jsp|cgi|bak|sql|tar|gz)$)"
)


def normalize_path(path: str) -> str | None:
    """
    Нормализует путь для использования в метриках.
    Возвращает None если путь нужно игнорировать (боты, сканеры).
    """
    if IGNORED_PATHS.match(path):
        return None
    for pattern, replacement in PATH_PATTERNS:
        if pattern.match(path):
            return pattern.sub(replacement, path)
    return path


# ═══════════════════════════════════════════════════════════════════════════
# Application Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler. Manages startup and shutdown events."""

    logger.info("Starting VPN Subscription API...")

    try:
        await init_db()
        logger.info("Database connection established")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise

    try:
        redis_client = await get_redis_client()
        if redis_client:
            logger.info("Redis connection established")
        else:
            logger.warning("Redis not available, caching will be degraded")
    except Exception as e:
        logger.warning(f"Redis initialization failed: {e}")

    try:
        await setup_rate_limiting(
            app,
            public_rps=settings.public_rps,
            internal_no_token_rps=settings.internal_no_token_rps,
            internal_with_token_rps=settings.internal_with_token_rps,
        )
        logger.info("Rate limiting configured")
    except Exception as e:
        logger.warning(f"Rate limiting setup failed: {e}")

    logger.info("Application started successfully")

    yield

    logger.info("Shutting down VPN Subscription API...")

    try:
        await close_redis_client()
        logger.info("Redis connection closed")
    except Exception as e:
        logger.error(f"Error closing Redis: {e}")

    try:
        await close_http_client()
        logger.info("HTTP client closed")
    except Exception as e:
        logger.error(f"Error closing HTTP client: {e}")

    try:
        await close_db()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error(f"Error closing database: {e}")

    logger.info("Application shutdown complete")


# ═══════════════════════════════════════════════════════════════════════════
# Application Factory
# ═══════════════════════════════════════════════════════════════════════════

def create_app() -> FastAPI:
    """Create and configure FastAPI application."""

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="""
        VPN Subscription API - Manage and aggregate VPN proxy subscriptions

        ## Features

        * **Subscription Management**: Create, update, delete subscriptions
        * **Source Aggregation**: Combine configs, external URLs, and internal refs
        * **Comment System**: Per-subscription config comments
        * **Recursive Resolution**: Resolve nested subscription references
        * **Two-Tier Caching**: Redis + PostgreSQL for external URLs
        * **Circular Reference Detection**: Prevent infinite loops

        ## Authentication

        Most endpoints require authentication via `API-Token` header.
        Public endpoints (`/sub/{token}`) are accessible without authentication.
        """,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts_enabled=not settings.debug,
        csp_enabled=not settings.debug,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=settings.cors_credentials,
            allow_methods=settings.cors_methods,
            allow_headers=settings.cors_headers,
        )

    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(
        subscriptions.router,
        prefix="/api/v1",
        dependencies=[Depends(check_internal_rate_limit)],
    )
    app.include_router(public.router, dependencies=[Depends(check_public_rate_limit)])

    @app.get("/health")
    async def health():
        """
        Проверяет реальное состояние зависимостей.
        Возвращает 200 только если БД и Redis доступны.
        503 — если хотя бы одна зависимость недоступна.
        """
        from sqlalchemy import text as sa_text
        from src.db.session import engine

        checks: dict[str, str] = {}
        healthy = True

        try:
            async with engine.connect() as conn:
                await conn.execute(sa_text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"error: {e}"
            healthy = False

        try:
            redis_client = await get_redis_client()
            if redis_client:
                await redis_client.ping()
                checks["redis"] = "ok"
            else:
                checks["redis"] = "unavailable"
                healthy = False
        except Exception as e:
            checks["redis"] = f"error: {e}"
            healthy = False

        status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            status_code=status_code,
            content={"status": "ok" if healthy else "degraded", "checks": checks},
        )

    register_exception_handlers(app)

    return app


# ═══════════════════════════════════════════════════════════════════════════
# Exception Handlers
# ═══════════════════════════════════════════════════════════════════════════

def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers."""

    @app.exception_handler(VPNSubscriptionError)
    async def vpn_subscription_error_handler(request: Request, exc: VPNSubscriptionError):
        from src.core.exceptions import to_http_exception
        http_exc = to_http_exception(exc)
        return JSONResponse(
            status_code=http_exc.status_code,
            content=http_exc.detail,
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred",
                "details": {} if not settings.debug else {"error": str(exc)},
            },
        )


# ═══════════════════════════════════════════════════════════════════════════
# Application Instance
# ═══════════════════════════════════════════════════════════════════════════

app = create_app()


# ═══════════════════════════════════════════════════════════════════════════
# Scalar docs (debug only)
# ═══════════════════════════════════════════════════════════════════════════

if settings.debug:
    from scalar_fastapi import get_scalar_api_reference, Theme

    @app.get("/docs", include_in_schema=False)
    async def scalar_docs():
        return get_scalar_api_reference(
            openapi_url=app.openapi_url,
            title=app.title,
            theme=Theme.SATURN,
            dark_mode=True,
            hide_dark_mode_toggle=True,
            hide_models=True,
            hide_download_button=True,
            show_sidebar=True,
            default_open_all_tags=False,
            hide_test_request_button=False,
            custom_css="a[href*='scalar.com'] { display: none !important; }",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Prometheus middleware
# ═══════════════════════════════════════════════════════════════════════════

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method

    if path == "/metrics":
        return await call_next(request)

    normalized = normalize_path(path)

    # Мусорные пути от ботов — пропускаем без трекинга
    if normalized is None:
        return await call_next(request)

    HTTP_REQUESTS_IN_PROGRESS.labels(
        method=method, path=normalized, app_name=APP_NAME
    ).inc()

    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as e:
        HTTP_EXCEPTIONS_TOTAL.labels(
            method=method,
            path=normalized,
            exception_type=type(e).__name__,
            app_name=APP_NAME,
        ).inc()
        raise
    finally:
        duration = time.perf_counter() - start

        HTTP_REQUESTS_TOTAL.labels(
            method=method, path=normalized, app_name=APP_NAME
        ).inc()

        HTTP_RESPONSES_TOTAL.labels(
            method=method,
            path=normalized,
            status_code=str(status_code),
            app_name=APP_NAME,
        ).inc()

        HTTP_REQUEST_DURATION.labels(
            method=method, path=normalized, app_name=APP_NAME
        ).observe(duration)

        HTTP_REQUESTS_IN_PROGRESS.labels(
            method=method, path=normalized, app_name=APP_NAME
        ).dec()

    return response


# ═══════════════════════════════════════════════════════════════════════════
# Metrics endpoint
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/metrics")
def metrics():
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Entrypoint
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=settings.workers,
    )
