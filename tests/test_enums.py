"""Tests for v2hub_api.core.enums."""

import pytest

from v2hub_api.core.enums import ErrorCode, ProxyProtocol, SourceType


class TestSourceType:
    def test_values(self):
        assert SourceType.CONFIG.value == "config"
        assert SourceType.EXTERNAL_URL.value == "external_url"
        assert SourceType.INTERNAL_TOKEN.value == "internal_token"

    def test_str(self):
        assert str(SourceType.CONFIG) == "config"
        assert str(SourceType.EXTERNAL_URL) == "external_url"

    def test_is_str_subclass(self):
        assert isinstance(SourceType.CONFIG, str)
        assert SourceType.CONFIG == "config"


class TestProxyProtocol:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("vless", ProxyProtocol.VLESS),
            ("vmess", ProxyProtocol.VMESS),
            ("trojan", ProxyProtocol.TROJAN),
            ("ss", ProxyProtocol.SHADOWSOCKS),
            ("hysteria", ProxyProtocol.HYSTERIA),
            ("hysteria2", ProxyProtocol.HYSTERIA2),
            ("tuic", ProxyProtocol.TUIC),
        ],
    )
    def test_values(self, value, expected):
        assert expected.value == value

    def test_str(self):
        assert str(ProxyProtocol.VLESS) == "vless"

    @pytest.mark.parametrize(
        "uri,expected",
        [
            ("vless://uuid@host:443?type=tcp#name", ProxyProtocol.VLESS),
            ("vmess://base64data", ProxyProtocol.VMESS),
            ("trojan://pass@host:443", ProxyProtocol.TROJAN),
            ("ss://base64@host:8388", ProxyProtocol.SHADOWSOCKS),
            ("hysteria://host:443", ProxyProtocol.HYSTERIA),
            ("hysteria2://host:443", ProxyProtocol.HYSTERIA2),
            ("tuic://uuid:pass@host:443", ProxyProtocol.TUIC),
        ],
    )
    def test_from_uri_valid(self, uri, expected):
        assert ProxyProtocol.from_uri(uri) is expected

    def test_from_uri_case_insensitive(self):
        assert ProxyProtocol.from_uri("VLESS://uuid@host:443") is ProxyProtocol.VLESS
        assert ProxyProtocol.from_uri("VmEsS://data") is ProxyProtocol.VMESS

    @pytest.mark.parametrize(
        "uri",
        [
            "",
            None,
            "not-a-uri",
            "http://example.com",
            "unknown://host",
            "vless",  # no scheme separator
        ],
    )
    def test_from_uri_invalid(self, uri):
        assert ProxyProtocol.from_uri(uri) is None

    def test_from_uri_only_checks_scheme_prefix(self):
        # scheme is taken from before "://", regardless of what follows
        assert ProxyProtocol.from_uri("vless://") is ProxyProtocol.VLESS


class TestErrorCode:
    def test_str(self):
        assert str(ErrorCode.INVALID_TOKEN) == "invalid_token"
        assert str(ErrorCode.RATE_LIMIT_EXCEEDED) == "too_many_requests"

    def test_is_str_subclass(self):
        assert isinstance(ErrorCode.NOT_FOUND, str)
        assert ErrorCode.NOT_FOUND == "not_found"

    def test_unique_values(self):
        values = [e.value for e in ErrorCode]
        assert len(values) == len(set(values))
