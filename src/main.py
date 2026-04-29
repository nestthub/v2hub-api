"""
Main FastAPI application.

Configures and initializes the VPN Subscription API with:
- API routers
- CORS middleware
- Exception handlers
- Lifecycle events
- OpenAPI documentation
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.endpoints import admin, public, subscriptions
from src.core.config import settings
from src.core.exceptions import VPNSubscriptionError
from src.db.session import close_db, init_db
from src.services.cache_service import close_redis_client, get_redis_client
from src.utils.http_client import close_http_client

from src.middlewares.rate_limit_middleware import setup_rate_limiting, check_internal_rate_limit, check_public_rate_limit
from src.middlewares.security_headers_middleware import SecurityHeadersMiddleware

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format=settings.log_format,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Application Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    
    Manages startup and shutdown events.
    """
    # Startup
    logger.info("Starting VPN Subscription API...")
    
    # Initialize database connection
    try:
        await init_db()
        logger.info("Database connection established")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise
    
    # Initialize Redis connection
    try:
        redis_client = await get_redis_client()
        if redis_client:
            logger.info("Redis connection established")
        else:
            logger.warning("Redis not available, caching will be degraded")
    except Exception as e:
        logger.warning(f"Redis initialization failed: {e}")
    
    # Setup rate limiting
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
    
    # Shutdown
    logger.info("Shutting down VPN Subscription API...")
    
    # Close Redis connection
    try:
        await close_redis_client()
        logger.info("Redis connection closed")
    except Exception as e:
        logger.error(f"Error closing Redis: {e}")
    
    # Close HTTP client
    try:
        await close_http_client()
        logger.info("HTTP client closed")
    except Exception as e:
        logger.error(f"Error closing HTTP client: {e}")
    
    # Close database connection
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
    """
    Create and configure FastAPI application.
    
    Returns:
        Configured FastAPI application
    """
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
    
    # Add security headers middleware
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts_enabled=not settings.debug,  # Disable HSTS in debug mode
        csp_enabled=not settings.debug,
    )
    
    # Configure CORS
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=settings.cors_credentials,
            allow_methods=settings.cors_methods,
            allow_headers=settings.cors_headers,
        )

    
    # Include routers
    app.include_router(admin.router, prefix="/api/v1")  # Admin endpoints (with signature verification)
    app.include_router(subscriptions.router, prefix="/api/v1", dependencies=[Depends(check_internal_rate_limit)])
    app.include_router(public.router, dependencies=[Depends(check_public_rate_limit)])

    @app.get("/health")
    def health():
        return {"status": "ok"}
    
    # Register exception handlers
    register_exception_handlers(app)
    
    return app


# ═══════════════════════════════════════════════════════════════════════════
# Exception Handlers
# ═══════════════════════════════════════════════════════════════════════════

def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers."""
    
    @app.exception_handler(VPNSubscriptionError)
    async def vpn_subscription_error_handler(
        request: Request,
        exc: VPNSubscriptionError,
    ):
        """Handle application-specific exceptions."""
        from src.core.exceptions import to_http_exception
        
        http_exc = to_http_exception(exc)
        
        return JSONResponse(
            status_code=http_exc.status_code,
            content=http_exc.detail,
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request,
        exc: Exception,
    ):
        """Handle unexpected exceptions."""
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
# Health Check Endpoint
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


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=settings.workers,
    )
