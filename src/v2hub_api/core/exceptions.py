"""
Custom exception classes for VPN Subscription API.

Provides a hierarchy of exceptions with proper HTTP status code mapping
and error code assignment for client-facing error messages.
"""

from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import SQLAlchemyError

from v2hub_api.core.enums import ErrorCode


class VPNSubscriptionError(Exception):
    """
    Base exception for all application-specific errors.

    All custom exceptions should inherit from this class.
    """

    def __init__(
        self,
        message: str,
        error_code: ErrorCode | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class RateLimitError(VPNSubscriptionError):
    """Raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Too many requests",
        retry_after: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
            details={
                "retry_after": retry_after,
                **(details or {}),
            },
        )
        self.retry_after = retry_after


# ═══════════════════════════════════════════════════════════════════════════
# Authentication & Authorization Errors
# ═══════════════════════════════════════════════════════════════════════════


class AuthenticationError(VPNSubscriptionError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message=message, error_code=ErrorCode.INVALID_TOKEN)


class AuthorizationError(VPNSubscriptionError):
    """Raised when user doesn't have permission for an operation."""

    def __init__(self, message: str = "Access forbidden") -> None:
        super().__init__(message=message, error_code=ErrorCode.FORBIDDEN)


# ═══════════════════════════════════════════════════════════════════════════
# Resource Not Found Errors
# ═══════════════════════════════════════════════════════════════════════════


class NotFoundError(VPNSubscriptionError):
    """Raised when a requested resource doesn't exist."""

    def __init__(self, resource: str = "Resource", identifier: str | None = None) -> None:
        message = f"{resource} not found"
        if identifier:
            message = f"{resource} '{identifier}' not found"
        super().__init__(
            message=message,
            error_code=ErrorCode.NOT_FOUND,
            details={"resource": resource, "identifier": identifier},
        )


class SubscriptionNotFoundError(NotFoundError):
    """Raised when a subscription doesn't exist."""

    def __init__(self, token: str) -> None:
        super().__init__(resource="Subscription", identifier=token)
        self.error_code = ErrorCode.SUBSCRIPTION_NOT_FOUND


class SourceNotFoundError(NotFoundError):
    """Raised when a source doesn't exist."""

    def __init__(self, source_id: str) -> None:
        super().__init__(resource="Source", identifier=source_id)
        self.error_code = ErrorCode.SOURCE_NOT_FOUND


# ═══════════════════════════════════════════════════════════════════════════
# Validation Errors
# ═══════════════════════════════════════════════════════════════════════════


class ValidationError(VPNSubscriptionError):
    """Raised when input validation fails."""

    def __init__(
        self, message: str, field: str | None = None, errors: list[str] | None = None
    ) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.INVALID_CONFIG,
            details={"field": field, "errors": errors},
        )


class InvalidConfigError(ValidationError):
    """Raised when a proxy configuration is invalid."""

    def __init__(self, config: str, errors: list[str] | None = None) -> None:
        super().__init__(message="Invalid proxy configuration", field="config", errors=errors)
        self.details["config"] = config[:50]  # Truncate for security


class InvalidURLError(ValidationError):
    """Raised when a URL is malformed or invalid."""

    def __init__(self, url: str) -> None:
        super().__init__(message="Invalid URL format", field="url")
        self.error_code = ErrorCode.INVALID_URL
        self.details["url"] = url


# ═══════════════════════════════════════════════════════════════════════════
# Conflict Errors
# ═══════════════════════════════════════════════════════════════════════════


class ConflictError(VPNSubscriptionError):
    """Raised when an operation conflicts with existing data."""

    def __init__(self, message: str, conflicting_field: str | None = None) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.DUPLICATE_NAME,
            details={"conflicting_field": conflicting_field},
        )


class DuplicateNameError(ConflictError):
    """Raised when a subscription name already exists for a user."""

    def __init__(self, name: str) -> None:
        super().__init__(
            message=f"Subscription name '{name}' already exists", conflicting_field="name"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Business Logic Errors
# ═══════════════════════════════════════════════════════════════════════════


class CircularReferenceError(VPNSubscriptionError):
    """Raised when a circular subscription reference is detected."""

    def __init__(self, chain: list[str] | None = None) -> None:
        message = "Circular subscription reference detected"
        if chain:
            message = f"Circular reference: {' → '.join(chain)}"
        super().__init__(
            message=message, error_code=ErrorCode.CIRCULAR_REFERENCE, details={"chain": chain}
        )


class NestingTooDeepError(VPNSubscriptionError):
    """Raised when subscription nesting exceeds maximum depth."""

    def __init__(self, current_depth: int, max_depth: int) -> None:
        super().__init__(
            message=(
                f"Subscription nesting depth ({current_depth}) exceeds "
                f"maximum allowed ({max_depth})"
            ),
            error_code=ErrorCode.NESTING_TOO_DEEP,
            details={"current_depth": current_depth, "max_depth": max_depth},
        )


class TooManyConfigsError(VPNSubscriptionError):
    """Raised when resolved configs exceed maximum limit."""

    def __init__(self, count: int, max_count: int) -> None:
        super().__init__(
            message=(
                f"Resolved configuration count ({count}) exceeds maximum allowed ({max_count})"
            ),
            error_code=ErrorCode.TOO_MANY_CONFIGS,
            details={"count": count, "max_count": max_count},
        )


class TooManySourcesError(VPNSubscriptionError):
    """Raised when a subscription has too many sources."""

    def __init__(self, count: int, max_count: int) -> None:
        super().__init__(
            message=(f"Source count ({count}) exceeds maximum allowed ({max_count})"),
            error_code=ErrorCode.TOO_MANY_SOURCES,
            details={"count": count, "max_count": max_count},
        )


class TooManySubscriptionsError(VPNSubscriptionError):
    """Raised when a user has too many subscriptions."""

    def __init__(self, count: int, max_count: int) -> None:
        super().__init__(
            message=(f"Subscription count ({count}) exceeds maximum allowed ({max_count})"),
            error_code=ErrorCode.TOO_MANY_SUBSCRIPTIONS,
            details={"count": count, "max_count": max_count},
        )


# ═══════════════════════════════════════════════════════════════════════════
# External Service Errors
# ═══════════════════════════════════════════════════════════════════════════


class ExternalFetchError(VPNSubscriptionError):
    """Raised when fetching external subscription fails."""

    def __init__(self, url: str, reason: str | None = None, status_code: int | None = None) -> None:
        message = f"Failed to fetch external subscription: {url}"
        if reason:
            message = f"{message} - {reason}"
        super().__init__(
            message=message,
            error_code=ErrorCode.FETCH_ERROR,
            details={"url": url, "reason": reason, "status_code": status_code},
        )


class CacheError(VPNSubscriptionError):
    """Raised when cache operations fail."""

    def __init__(self, operation: str, reason: str | None = None) -> None:
        message = f"Cache {operation} failed"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(
            message=message,
            error_code=ErrorCode.CACHE_ERROR,
            details={"operation": operation, "reason": reason},
        )


# ═══════════════════════════════════════════════════════════════════════════
# HTTP Exception Mapping
# ═══════════════════════════════════════════════════════════════════════════


def to_http_exception(exc: Exception) -> HTTPException:
    # 1) your domain errors
    if isinstance(exc, VPNSubscriptionError):
        status_map = {
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            NotFoundError: status.HTTP_404_NOT_FOUND,
            SubscriptionNotFoundError: status.HTTP_404_NOT_FOUND,
            SourceNotFoundError: status.HTTP_404_NOT_FOUND,
            ValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
            InvalidConfigError: status.HTTP_422_UNPROCESSABLE_CONTENT,
            InvalidURLError: status.HTTP_422_UNPROCESSABLE_CONTENT,
            ConflictError: status.HTTP_409_CONFLICT,
            DuplicateNameError: status.HTTP_409_CONFLICT,
            CircularReferenceError: status.HTTP_422_UNPROCESSABLE_CONTENT,
            NestingTooDeepError: status.HTTP_422_UNPROCESSABLE_CONTENT,
            TooManyConfigsError: status.HTTP_422_UNPROCESSABLE_CONTENT,
            TooManySourcesError: status.HTTP_422_UNPROCESSABLE_CONTENT,
            TooManySubscriptionsError: status.HTTP_422_UNPROCESSABLE_CONTENT,
            ExternalFetchError: status.HTTP_400_BAD_REQUEST,
            CacheError: status.HTTP_500_INTERNAL_SERVER_ERROR,
            RateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,
        }

        return HTTPException(
            status_code=status_map.get(type(exc), 500),
            detail={
                "error": exc.error_code.value if exc.error_code else "unknown_error",
                "message": exc.message,
                "details": exc.details,
            },
        )

    # 2) Pydantic validation
    if isinstance(exc, PydanticValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "validation_error",
                "message": "Request validation failed",
                "details": exc.errors(),
            },
        )

    # 3) SQLAlchemy / DB errors
    if isinstance(exc, SQLAlchemyError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "database_error",
                "message": str(exc),
                "details": {},
            },
        )

    # 4) fallback
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "error": "internal_error",
            "message": str(exc),
            "details": {},
        },
    )
