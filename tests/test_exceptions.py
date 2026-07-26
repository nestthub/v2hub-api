"""Tests for v2hub_api.core.exceptions."""

from fastapi import HTTPException

from v2hub_api.core.enums import ErrorCode
from v2hub_api.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    CacheError,
    CircularReferenceError,
    ConflictError,
    DuplicateNameError,
    ExternalFetchError,
    InvalidConfigError,
    InvalidURLError,
    NestingTooDeepError,
    NotFoundError,
    RateLimitError,
    SourceNotFoundError,
    SubscriptionNotFoundError,
    TooManyConfigsError,
    TooManySourcesError,
    TooManySubscriptionsError,
    ValidationError,
    VPNSubscriptionError,
    to_http_exception,
)


class TestVPNSubscriptionErrorBase:
    def test_basic_construction(self):
        exc = VPNSubscriptionError("something failed")
        assert exc.message == "something failed"
        assert exc.error_code is None
        assert exc.details == {}
        assert str(exc) == "something failed"

    def test_with_error_code_and_details(self):
        exc = VPNSubscriptionError("bad", error_code=ErrorCode.NOT_FOUND, details={"a": 1})
        assert exc.error_code is ErrorCode.NOT_FOUND
        assert exc.details == {"a": 1}


class TestSpecificExceptions:
    def test_authentication_error_defaults(self):
        exc = AuthenticationError()
        assert exc.message == "Authentication failed"
        assert exc.error_code is ErrorCode.INVALID_TOKEN

    def test_authorization_error_defaults(self):
        exc = AuthorizationError()
        assert exc.message == "Access forbidden"
        assert exc.error_code is ErrorCode.FORBIDDEN

    def test_not_found_error_without_identifier(self):
        exc = NotFoundError(resource="Widget")
        assert exc.message == "Widget not found"
        assert exc.details == {"resource": "Widget", "identifier": None}

    def test_not_found_error_with_identifier(self):
        exc = NotFoundError(resource="Widget", identifier="abc123")
        assert exc.message == "Widget 'abc123' not found"

    def test_subscription_not_found_error(self):
        exc = SubscriptionNotFoundError(token="tok123")
        assert "Subscription" in exc.message
        assert "tok123" in exc.message
        assert exc.error_code is ErrorCode.SUBSCRIPTION_NOT_FOUND

    def test_source_not_found_error(self):
        exc = SourceNotFoundError(source_id="src1")
        assert exc.error_code is ErrorCode.SOURCE_NOT_FOUND

    def test_invalid_config_error_truncates_config(self):
        long_config = "vless://" + "a" * 100
        exc = InvalidConfigError(config=long_config, errors=["bad uuid"])
        assert exc.details["config"] == long_config[:50]
        assert exc.details["errors"] == ["bad uuid"]
        assert exc.error_code is ErrorCode.INVALID_CONFIG

    def test_invalid_url_error(self):
        exc = InvalidURLError(url="ftp://example.com")
        assert exc.error_code is ErrorCode.INVALID_URL
        assert exc.details["url"] == "ftp://example.com"

    def test_duplicate_name_error(self):
        exc = DuplicateNameError(name="my-sub")
        assert "my-sub" in exc.message
        assert exc.error_code is ErrorCode.DUPLICATE_NAME
        assert exc.details["conflicting_field"] == "name"

    def test_circular_reference_error_without_chain(self):
        exc = CircularReferenceError()
        assert exc.message == "Circular subscription reference detected"
        assert exc.details["chain"] is None

    def test_circular_reference_error_with_chain(self):
        exc = CircularReferenceError(chain=["a", "b", "a"])
        assert "a → b → a" in exc.message

    def test_nesting_too_deep_error(self):
        exc = NestingTooDeepError(current_depth=5, max_depth=3)
        assert "5" in exc.message and "3" in exc.message
        assert exc.error_code is ErrorCode.NESTING_TOO_DEEP

    def test_too_many_configs_error(self):
        exc = TooManyConfigsError(count=200, max_count=150)
        assert exc.error_code is ErrorCode.TOO_MANY_CONFIGS
        assert exc.details == {"count": 200, "max_count": 150}

    def test_too_many_sources_error(self):
        exc = TooManySourcesError(count=200, max_count=150)
        assert exc.error_code is ErrorCode.TOO_MANY_SOURCES

    def test_too_many_subscriptions_error(self):
        exc = TooManySubscriptionsError(count=5, max_count=3)
        assert exc.error_code is ErrorCode.TOO_MANY_SUBSCRIPTIONS

    def test_external_fetch_error_minimal(self):
        exc = ExternalFetchError(url="https://example.com/sub")
        assert exc.message == "Failed to fetch external subscription: https://example.com/sub"
        assert exc.error_code is ErrorCode.FETCH_ERROR

    def test_external_fetch_error_with_reason(self):
        exc = ExternalFetchError(url="https://example.com/sub", reason="timeout", status_code=504)
        assert "timeout" in exc.message
        assert exc.details["status_code"] == 504

    def test_cache_error(self):
        exc = CacheError(operation="get", reason="connection refused")
        assert "get" in exc.message
        assert "connection refused" in exc.message
        assert exc.error_code is ErrorCode.CACHE_ERROR

    def test_rate_limit_error_defaults(self):
        exc = RateLimitError()
        assert exc.message == "Too many requests"
        assert exc.error_code is ErrorCode.RATE_LIMIT_EXCEEDED
        assert exc.retry_after is None

    def test_rate_limit_error_with_retry_after(self):
        exc = RateLimitError(retry_after=30)
        assert exc.retry_after == 30
        assert exc.details["retry_after"] == 30

    def test_validation_error(self):
        exc = ValidationError("bad field", field="name", errors=["too short"])
        assert exc.error_code is ErrorCode.INVALID_CONFIG
        assert exc.details == {"field": "name", "errors": ["too short"]}

    def test_conflict_error(self):
        exc = ConflictError("conflict!", conflicting_field="name")
        assert exc.error_code is ErrorCode.DUPLICATE_NAME


class TestToHttpException:
    def test_authentication_error_maps_to_401(self):
        result = to_http_exception(AuthenticationError())
        assert isinstance(result, HTTPException)
        assert result.status_code == 401
        assert result.detail["error"] == "invalid_token"

    def test_authorization_error_maps_to_403(self):
        result = to_http_exception(AuthorizationError())
        assert result.status_code == 403

    def test_subscription_not_found_maps_to_404(self):
        result = to_http_exception(SubscriptionNotFoundError(token="t1"))
        assert result.status_code == 404
        assert result.detail["error"] == "subscription_not_found"

    def test_invalid_config_error_maps_to_422(self):
        result = to_http_exception(InvalidConfigError(config="vless://bad"))
        assert result.status_code == 422

    def test_duplicate_name_error_maps_to_409(self):
        result = to_http_exception(DuplicateNameError(name="x"))
        assert result.status_code == 409

    def test_external_fetch_error_maps_to_400(self):
        result = to_http_exception(ExternalFetchError(url="https://x.com"))
        assert result.status_code == 400

    def test_cache_error_maps_to_500(self):
        result = to_http_exception(CacheError(operation="set"))
        assert result.status_code == 500

    def test_rate_limit_error_maps_to_429(self):
        result = to_http_exception(RateLimitError())
        assert result.status_code == 429

    def test_generic_vpn_error_defaults_to_500(self):
        result = to_http_exception(VPNSubscriptionError("plain error"))
        assert result.status_code == 500
        assert result.detail["error"] == "unknown_error"

    def test_unknown_generic_exception_falls_back_to_500(self):
        result = to_http_exception(ValueError("boom"))
        assert isinstance(result, HTTPException)
        assert result.status_code == 500
        assert result.detail["error"] == "internal_error"
        assert "boom" in result.detail["message"]

    def test_detail_shape_for_domain_error(self):
        result = to_http_exception(NotFoundError(resource="Item", identifier="42"))
        assert set(result.detail.keys()) == {"error", "message", "details"}
        assert result.detail["message"] == "Item '42' not found"
