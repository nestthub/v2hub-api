"""
Enumeration types for VPN Subscription API.

Defines all enum types used across the application for type safety
and consistency.
"""

from enum import StrEnum, nonmember


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

    # URI scheme aliases that map to a canonical protocol value.
    #
    # Wrapped in nonmember() so the Enum metaclass treats this as a plain
    # class attribute instead of trying to turn it into another member.
    # Values are the raw string values (e.g. "hysteria2"), not member
    # references (e.g. HYSTERIA2) — inside the class body, at this point
    # in evaluation, enum members don't exist as such yet: "HYSTERIA2"
    # would just resolve to the plain str "hysteria2" that was assigned
    # above, not to the ProxyProtocol.HYSTERIA2 member object. from_uri()
    # below converts the raw string back into the real member via cls(),
    # so callers always get back a genuine enum member, never a bare str.
    #
    # These aliases are *input-only*: a URI with an aliased scheme is
    # recognized and parsed as the canonical protocol, but the protocol is
    # always stored, compared, and re-serialized using its single
    # canonical enum value. This keeps exactly one on-disk/in-memory
    # representation per protocol, so two subscriptions with sources
    # "hy2://..." and "hysteria2://..." are deduplicated, filtered, and
    # displayed identically instead of being treated as different
    # protocols.
    _SCHEME_ALIASES = nonmember({"hy2": "hysteria2"})

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_uri(cls, uri: str) -> "ProxyProtocol | None":
        """
        Extract protocol from a proxy URI.

        Recognizes both canonical scheme names (e.g. "hysteria2://") and
        known aliases (e.g. "hy2://"), always returning the canonical
        enum member — callers never need to know an alias was used.

        Args:
            uri: Proxy configuration URI (e.g., "vless://...")

        Returns:
            ProxyProtocol enum member or None if not recognized
        """
        if not uri or "://" not in uri:
            return None

        scheme = uri.split("://", 1)[0].lower()
        scheme = cls._SCHEME_ALIASES.get(scheme, scheme)

        try:
            return cls(scheme)
        except ValueError:
            return None

    @classmethod
    def known_uri_schemes(cls) -> frozenset[str]:
        """
        Every URI scheme string this enum recognizes as proxy content.

        Includes both canonical values (e.g. "hysteria2") and known
        aliases (e.g. "hy2") — use this instead of iterating over `cls`
        directly wherever you need to check "does this look like a proxy
        URI" against raw scheme text, so alias schemes like "hy2://" are
        recognized too. `from_uri()` is still the right choice whenever
        you need the actual protocol *member* back, not just a yes/no on
        whether a scheme string is recognized.
        """
        return frozenset({member.value for member in cls} | set(cls._SCHEME_ALIASES))


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
    TOO_MANY_PROVIDERS = "too_many_providers"

    INVALID_AUTHORIZATION_STATUS = "invalid_authorization_status"

    RATE_LIMIT_EXCEEDED = "too_many_requests"

    # External Service Errors
    FETCH_ERROR = "fetch_error"
    CACHE_ERROR = "cache_error"

    def __str__(self) -> str:
        return self.value


class ProviderAuthorizationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REVOKED = "revoked"
