"""
Core configuration module for VPN Subscription API.

Manages all environment variables and application settings using Pydantic's
BaseSettings for type safety and validation.
"""

from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from v2hub_api import __version__


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # ═══ Application ═══════════════════════════════════════════════════════
    app_name: str = Field(default="VPN Subscription API", validation_alias="APP_NAME")
    app_version: str = Field(default=__version__, validation_alias="APP_VERSION")
    debug: bool = Field(default=False, validation_alias="DEBUG")
    environment: str = Field(default="production", validation_alias="ENVIRONMENT")

    # ═══ Server ════════════════════════════════════════════════════════════
    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=8000, validation_alias="PORT")
    workers: int = Field(default=1, validation_alias="WORKERS")

    # ═══ Domain ════════════════════════════════════════════════════════════
    domain: str = Field(default="127.0.0.1", validation_alias="DOMAIN")

    # ═══ Database ══════════════════════════════════════════════════════════
    database_url: PostgresDsn = Field(
        ..., validation_alias="DATABASE_URL", description="PostgreSQL connection URL"
    )
    db_pool_size: int = Field(default=10, validation_alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, validation_alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, validation_alias="DB_POOL_TIMEOUT")
    db_echo: bool = Field(default=False, validation_alias="DB_ECHO")

    # ═══ Redis ═════════════════════════════════════════════════════════════
    redis_url: RedisDsn = Field(
        ..., validation_alias="REDIS_URL", description="Redis connection URL"
    )
    redis_ttl: int = Field(
        default=600,
        validation_alias="REDIS_TTL",
        description="Default TTL for cached items in seconds",
    )

    # ═══ Security ══════════════════════════════════════════════════════════
    secret_key: str = Field(
        ..., validation_alias="SECRET_KEY", description="Secret key for token generation"
    )
    api_token_length: int = Field(default=16, validation_alias="API_TOKEN_LENGTH")

    # Admin security configuration
    admin_secret_key: str = Field(
        ...,
        validation_alias="ADMIN_SECRET_KEY",
        description="Secret key for admin request signatures",
    )
    admin_allowed_ips: list[str] = Field(
        default_factory=list,
        validation_alias="ADMIN_ALLOWED_IPS",
        description="List of IP addresses allowed to access admin endpoints",
    )

    # Security headers configuration
    enable_hsts: bool = Field(
        default=True,
        validation_alias="ENABLE_HSTS",
        description="Enable HTTP Strict Transport Security",
    )
    enable_csp: bool = Field(
        default=True, validation_alias="ENABLE_CSP", description="Enable Content Security Policy"
    )

    # api limits
    public_rps: int = Field(
        default=3, description="Rate limit (requests per second) for public endpoints"
    )

    internal_no_token_rps: int = Field(
        default=1,
        description="Rate limit (requests per second) for internal endpoints without authentication token",
    )

    internal_with_token_rps: int = Field(
        default=3,
        description="Rate limit (requests per second) for internal endpoints with valid authentication token",
    )

    # Input validation limits
    max_name_length: int = Field(
        default=64,
        validation_alias="MAX_NAME_LENGTH",
        description="Maximum length for subscription names",
    )
    max_description_length: int = Field(
        default=255,
        validation_alias="MAX_DESCRIPTION_LENGTH",
        description="Maximum length for descriptions",
    )
    max_comment_length: int = Field(
        default=255,
        validation_alias="MAX_COMMENT_LENGTH",
        description="Maximum length for config comments",
    )

    # ═══ Business Logic ════════════════════════════════════════════════════
    max_nesting_depth: int = Field(
        default=3,
        validation_alias="MAX_NESTING_DEPTH",
        description="Maximum depth for nested subscription references",
    )
    max_subscriptions_per_user: int = Field(
        default=3,
        validation_alias="MAX_SUBSCRIPTIONS_PER_USER",
        description="Maximum number of subscriptions allowed per user",
    )
    max_configs_per_subscription: int = Field(
        default=150,
        validation_alias="MAX_CONFIGS_PER_SUBSCRIPTION",
        description="Maximum number of configs in a resolved subscription",
    )
    max_sources_per_subscription: int = Field(
        default=150, validation_alias="MAX_SOURCES_PER_SUBSCRIPTION"
    )

    # ═══ External Fetching ═════════════════════════════════════════════════
    fetch_timeout: int = Field(
        default=3,
        validation_alias="FETCH_TIMEOUT",
        description="HTTP timeout for external subscriptions (seconds)",
    )
    fetch_user_agent: str = Field(default="v2hub/1.0", validation_alias="FETCH_USER_AGENT")
    fetch_max_redirects: int = Field(default=1, validation_alias="FETCH_MAX_REDIRECTS")

    # ═══ CORS ══════════════════════════════════════════════════════════════
    cors_origins: list[str] = Field(default_factory=lambda: ["*"], validation_alias="CORS_ORIGINS")
    cors_credentials: bool = Field(default=True, validation_alias="CORS_CREDENTIALS")
    cors_methods: list[str] = Field(default_factory=lambda: ["*"], validation_alias="CORS_METHODS")
    cors_headers: list[str] = Field(default_factory=lambda: ["*"], validation_alias="CORS_HEADERS")

    # ═══ Logging ═══════════════════════════════════════════════════════════
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        validation_alias="LOG_FORMAT",
    )

    # ═══ Celery (Optional) ═════════════════════════════════════════════════
    celery_broker_url: str | None = Field(default=None, validation_alias="CELERY_BROKER_URL")
    celery_result_backend: str | None = Field(
        default=None, validation_alias="CELERY_RESULT_BACKEND"
    )

    @field_validator(
        "cors_origins", "cors_methods", "cors_headers", "admin_allowed_ips", mode="before"
    )
    @classmethod
    def parse_cors_list(cls, v: str | list[str]) -> list[str]:
        """Parse comma-separated string into list."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @property
    def database_url_str(self) -> str:
        """Get database URL as string."""
        return str(self.database_url)

    @property
    def redis_url_str(self) -> str:
        """Get Redis URL as string."""
        return str(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings.

    Uses LRU cache to ensure settings are loaded only once.
    """
    return Settings()


# Global settings instance
settings = get_settings()
