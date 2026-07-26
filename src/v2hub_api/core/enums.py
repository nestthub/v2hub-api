"""
Enumeration types for VPN Subscription API.

Defines all enum types used across the application for type safety
and consistency.
"""

from enum import StrEnum


class SourceType(StrEnum):
    """
    Type of source entry in a subscription.

    CONFIG: Direct proxy configuration (vless://, vmess://, etc.)
    EXTERNAL_URL: HTTPS URL to third-party subscription provider
    INTERNAL_TOKEN: Token reference to another subscription (same user)
    """

    CONFIG = "config"
    EXTERNAL_URL = "external_url"
    INTERNAL_TOKEN = "internal_token"

    def __str__(self) -> str:
        return self.value


class ProxyProtocol(StrEnum):
    """
    Supported proxy protocols.

    These are the protocols we can parse and validate.
    """

    VLESS = "vless"
    VMESS = "vmess"
    TROJAN = "trojan"
    SHADOWSOCKS = "ss"
    HYSTERIA = "hysteria"
    HYSTERIA2 = "hysteria2"
    TUIC = "tuic"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_uri(cls, uri: str) -> "ProxyProtocol | None":
        """
        Extract protocol from a proxy URI.

        Args:
            uri: Proxy configuration URI (e.g., "vless://...")

        Returns:
            ProxyProtocol enum member or None if not recognized
        """
        if not uri or "://" not in uri:
            return None

        scheme = uri.split("://", 1)[0].lower()

        for protocol in cls:
            if protocol.value == scheme:
                return protocol

        return None


class ErrorCode(StrEnum):
    """
    Application-specific error codes.

    Used for consistent error handling and client error recognition.
    """

    # Authentication & Authorization
    INVALID_TOKEN = "invalid_token"
    FORBIDDEN = "forbidden"
    USER_NOT_FOUND = "user_not_found"

    # Resource Not Found
    NOT_FOUND = "not_found"
    SUBSCRIPTION_NOT_FOUND = "subscription_not_found"
    SOURCE_NOT_FOUND = "source_not_found"

    # Validation Errors
    INVALID_CONFIG = "invalid_config"
    INVALID_URL = "invalid_url"
    DUPLICATE_NAME = "duplicate_name"

    # Business Logic Errors
    CIRCULAR_REFERENCE = "circular_reference"
    NESTING_TOO_DEEP = "nesting_too_deep"
    TOO_MANY_CONFIGS = "too_many_configs"
    TOO_MANY_SOURCES = "too_many_sources"
    TOO_MANY_SUBSCRIPTIONS = "too_many_subscriptions"

    RATE_LIMIT_EXCEEDED = "too_many_requests"

    # External Service Errors
    FETCH_ERROR = "fetch_error"
    CACHE_ERROR = "cache_error"

    def __str__(self) -> str:
        return self.value
