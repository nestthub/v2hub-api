"""Tests for src.utils.url_validator (SSRF protection)."""

import pytest

from src.core.exceptions import InvalidURLError
from src.utils.url_validator import (
    extract_hostname,
    is_internal,
    is_private_ip,
    is_url_safe,
    validate_external_url,
)


class TestIsPrivateIp:
    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.1.1",
            "169.254.1.1",
            "0.0.0.0",
            "224.0.0.1",  # multicast
        ],
    )
    def test_private_ips(self, ip):
        assert is_private_ip(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "93.184.216.34",
        ],
    )
    def test_public_ips(self, ip):
        assert is_private_ip(ip) is False

    def test_invalid_ip_returns_false(self):
        assert is_private_ip("not-an-ip") is False
        assert is_private_ip("") is False


class TestValidateExternalUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/sub",
            "http://example.com",
            "https://sub.example.com:8443/path?query=1",
        ],
    )
    def test_valid_urls_pass(self, url):
        validate_external_url(url)  # should not raise

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com",
            "file:///etc/passwd",
            "gopher://example.com",
        ],
    )
    def test_invalid_scheme_rejected(self, url):
        with pytest.raises(InvalidURLError):
            validate_external_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/sub",
            "http://localhost:8080/sub",
            "http://127.0.0.1/sub",
            "http://127.0.0.1:9000/sub",
        ],
    )
    def test_localhost_rejected(self, url):
        with pytest.raises(InvalidURLError):
            validate_external_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://10.0.0.5/sub",
            "http://172.16.5.5/sub",
            "http://172.31.0.1/sub",
            "http://192.168.1.1/sub",
            "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        ],
    )
    def test_private_ip_rejected(self, url):
        with pytest.raises(InvalidURLError):
            validate_external_url(url)

    def test_public_ip_allowed(self):
        validate_external_url("http://8.8.8.8/sub")  # should not raise

    def test_missing_hostname_rejected(self):
        with pytest.raises(InvalidURLError):
            validate_external_url("https:///path")

    def test_malformed_url_raises(self):
        with pytest.raises(InvalidURLError):
            validate_external_url("http://[::1")  # unbalanced bracket -> parse error

    def test_ipv6_localhost_rejected(self):
        with pytest.raises(InvalidURLError):
            validate_external_url("http://[::1]/sub")

    @pytest.mark.parametrize(
        "hostname",
        ["0.0.0.0", "broadcasthost"],
    )
    def test_common_bypass_hostnames_rejected(self, hostname):
        with pytest.raises(InvalidURLError):
            validate_external_url(f"http://{hostname}/sub")


class TestIsUrlSafe:
    def test_safe_url_returns_true(self):
        assert is_url_safe("https://example.com") is True

    def test_unsafe_url_returns_false(self):
        assert is_url_safe("http://127.0.0.1") is False
        assert is_url_safe("not a url at all") is False

    def test_never_raises(self):
        # Should not raise even on garbage input
        assert is_url_safe("") is False


class TestExtractHostname:
    def test_extracts_from_full_url(self):
        assert extract_hostname("https://Example.com/path") == "example.com"

    def test_extracts_with_port(self):
        assert extract_hostname("https://example.com:8443/path") == "example.com"

    def test_fallback_without_scheme(self):
        assert extract_hostname("example.com/path") == "example.com"

    def test_returns_none_for_garbage(self):
        assert extract_hostname("") is None


class TestIsInternal:
    def test_same_host_is_internal(self):
        assert is_internal("https://example.com/sub/token", "example.com") is True

    def test_different_host_is_not_internal(self):
        assert is_internal("https://other.com/sub/token", "example.com") is False

    def test_case_insensitive(self):
        assert is_internal("https://EXAMPLE.com/sub", "example.com") is True
