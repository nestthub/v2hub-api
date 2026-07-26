"""Tests for src.utils.config_parser."""

import base64

import pytest

from src.utils.config_parser import (
    decode_base64_subscription,
    deduplicate_configs,
    detect_protocol,
    get_config_hash,
    get_url_hash,
    is_http_url,
    is_valid_proxy_uri,
    normalize_config,
    normalize_source,
    parse_subscription_content,
    split_config_and_comment,
    validate_proxy_config,
    validate_shadowsocks_config,
    validate_trojan_config,
    validate_vless_config,
    validate_vmess_config,
)

VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"


class TestDetectProtocol:
    def test_detects_known_protocols(self):
        assert detect_protocol(f"vless://{VALID_UUID}@host:443") is not None
        assert detect_protocol("vmess://data") is not None
        assert detect_protocol("trojan://pass@host:443") is not None
        assert detect_protocol("ss://data@host:8388") is not None

    def test_unknown_protocol_returns_none(self):
        assert detect_protocol("http://example.com") is None

    def test_empty_or_no_scheme(self):
        assert detect_protocol("") is None
        assert detect_protocol("not-a-uri") is None


class TestIsValidProxyUri:
    def test_valid(self):
        assert is_valid_proxy_uri(f"vless://{VALID_UUID}@host:443") is True

    def test_invalid(self):
        assert is_valid_proxy_uri("https://example.com") is False
        assert is_valid_proxy_uri("garbage") is False


class TestSplitConfigAndComment:
    def test_with_comment(self):
        base, comment = split_config_and_comment("vless://uuid@host:443?x=1#MyServer")
        assert base == "vless://uuid@host:443?x=1"
        assert comment == "MyServer"

    def test_without_comment(self):
        base, comment = split_config_and_comment("vless://uuid@host:443")
        assert base == "vless://uuid@host:443"
        assert comment is None

    def test_strips_whitespace(self):
        base, comment = split_config_and_comment("  vless://uuid@host:443#  My Server  ")
        assert base == "vless://uuid@host:443"
        assert comment == "My Server"

    def test_multiple_hashes_only_splits_on_first(self):
        base, comment = split_config_and_comment("vless://uuid@host:443#name#extra")
        assert base == "vless://uuid@host:443"
        assert comment == "name#extra"


class TestNormalizeConfig:
    def test_removes_fragment(self):
        assert normalize_config("vless://uuid@host:443#MyServer") == "vless://uuid@host:443"

    def test_no_fragment_unchanged(self):
        assert normalize_config("vless://uuid@host:443") == "vless://uuid@host:443"


class TestGetConfigHash:
    def test_is_deterministic(self):
        h1 = get_config_hash("vless://uuid@host:443#name1")
        h2 = get_config_hash("vless://uuid@host:443#name1")
        assert h1 == h2

    def test_ignores_fragment(self):
        h1 = get_config_hash("vless://uuid@host:443#name1")
        h2 = get_config_hash("vless://uuid@host:443#totally-different-name")
        assert h1 == h2

    def test_different_configs_differ(self):
        h1 = get_config_hash("vless://uuid1@host:443")
        h2 = get_config_hash("vless://uuid2@host:443")
        assert h1 != h2

    def test_hash_length(self):
        h = get_config_hash("vless://uuid@host:443")
        assert len(h) == 32  # 16 bytes -> 32 hex chars


class TestIsHttpUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/sub",
            "http://example.com",
            "http://sub.example.com:8080/path?x=1",
        ],
    )
    def test_valid(self, url):
        assert is_http_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "vless://uuid@host:443",
            "ftp://example.com",
            "not a url",
            "",
            "example.com",  # missing scheme
        ],
    )
    def test_invalid(self, url):
        assert is_http_url(url) is False


class TestGetUrlHash:
    def test_deterministic(self):
        assert get_url_hash("https://example.com/sub") == get_url_hash("https://example.com/sub")

    def test_strips_whitespace_before_hashing(self):
        assert get_url_hash("  https://example.com/sub  ") == get_url_hash("https://example.com/sub")

    def test_different_urls_differ(self):
        assert get_url_hash("https://a.com") != get_url_hash("https://b.com")


class TestDecodeBase64Subscription:
    def test_plain_text_with_scheme_returned_as_is(self):
        content = "vless://uuid@host:443"
        assert decode_base64_subscription(content) == content

    def test_plain_text_with_newline_returned_as_is(self):
        content = "line1\nline2"
        assert decode_base64_subscription(content) == content

    def test_decodes_valid_base64_subscription(self):
        original = "vless://uuid1@host:443?type=tcp#name1\nvmess://data2\n"
        encoded = base64.b64encode(original.encode()).decode()
        assert decode_base64_subscription(encoded) == original

    def test_decodes_url_safe_base64_without_padding(self):
        original = "trojan://pass@host:443\n"
        encoded = base64.b64encode(original.encode()).decode().rstrip("=")
        assert decode_base64_subscription(encoded) == original

    def test_returns_original_if_not_valid_base64(self):
        content = "just-some-random-text-not-base64!!!"
        assert decode_base64_subscription(content) == content

    def test_returns_original_if_base64_decodes_but_not_subscription(self):
        # Valid base64, but decoded content has no known protocol scheme
        random_text = "hello world this is not a proxy config"
        encoded = base64.b64encode(random_text.encode()).decode()
        assert decode_base64_subscription(encoded) == encoded


class TestParseSubscriptionContent:
    def test_parses_plain_newline_separated_configs(self):
        content = f"vless://{VALID_UUID}@host:443\ntrojan://pass@host2:443\n"
        configs = parse_subscription_content(content)
        assert len(configs) == 2
        assert configs[0].startswith("vless://")
        assert configs[1].startswith("trojan://")

    def test_skips_blank_lines_and_comments(self):
        content = (
            "# this is a comment\n"
            "\n"
            f"vless://{VALID_UUID}@host:443\n"
            "   \n"
            "# another comment\n"
        )
        configs = parse_subscription_content(content)
        assert configs == [f"vless://{VALID_UUID}@host:443"]

    def test_skips_invalid_lines(self):
        content = "not-a-valid-config\nvless://uuid@host:443\nhttp://example.com\n"
        configs = parse_subscription_content(content)
        assert configs == ["vless://uuid@host:443"]

    def test_decodes_base64_first(self):
        original = "vless://uuid@host:443\ntrojan://pass@host2:443\n"
        encoded = base64.b64encode(original.encode()).decode()
        configs = parse_subscription_content(encoded)
        assert len(configs) == 2

    def test_empty_content_returns_empty_list(self):
        assert parse_subscription_content("") == []


class TestDeduplicateConfigs:
    def test_removes_duplicates_by_hash_ignoring_fragment(self):
        configs = [
            "vless://uuid@host:443#name1",
            "vless://uuid@host:443#name2",  # same base config, different comment
            "trojan://pass@host2:443",
        ]
        result = deduplicate_configs(configs)
        assert len(result) == 2
        assert result[0] == "vless://uuid@host:443#name1"  # keeps first occurrence
        assert result[1] == "trojan://pass@host2:443"

    def test_preserves_order(self):
        configs = ["a://1", "b://2", "a://1", "c://3"]
        result = deduplicate_configs(configs)
        assert result == ["a://1", "b://2", "c://3"]

    def test_empty_list(self):
        assert deduplicate_configs([]) == []

    def test_no_duplicates(self):
        configs = ["a://1", "b://2", "c://3"]
        assert deduplicate_configs(configs) == configs


class TestValidateVlessConfig:
    def test_valid(self):
        ok, err = validate_vless_config(f"vless://{VALID_UUID}@host:443")
        assert ok is True
        assert err is None

    def test_invalid_scheme(self):
        ok, err = validate_vless_config("trojan://pass@host:443")
        assert ok is False
        assert err == "Invalid scheme"

    def test_missing_server_address(self):
        ok, err = validate_vless_config("vless://")
        assert ok is False

    def test_invalid_uuid_length(self):
        ok, err = validate_vless_config("vless://short-uuid@host:443")
        assert ok is False
        assert err == "Invalid UUID"

    def test_missing_uuid(self):
        ok, err = validate_vless_config("vless://host:443")
        assert ok is False
        assert err == "Invalid UUID"


class TestValidateVmessConfig:
    def test_valid_uri_format(self):
        ok, err = validate_vmess_config("vmess://somebase64data@host:443")
        assert ok is True
        assert err is None

    def test_missing_server_address(self):
        ok, err = validate_vmess_config("vmess://")
        assert ok is False

    def test_wrong_scheme(self):
        ok, err = validate_vmess_config("vless://data")
        assert ok is False
        assert err == "Invalid VMess format"


class TestValidateTrojanConfig:
    def test_valid(self):
        ok, err = validate_trojan_config("trojan://password@host:443")
        assert ok is True
        assert err is None

    def test_invalid_scheme(self):
        ok, err = validate_trojan_config("vless://uuid@host:443")
        assert ok is False
        assert err == "Invalid scheme"

    def test_missing_password(self):
        ok, err = validate_trojan_config("trojan://host:443")
        assert ok is False
        assert err == "Missing password"


class TestValidateShadowsocksConfig:
    def test_valid_ss_scheme(self):
        ok, err = validate_shadowsocks_config("ss://base64info@host:8388")
        assert ok is True

    def test_valid_shadowsocks_scheme(self):
        ok, err = validate_shadowsocks_config("shadowsocks://base64info@host:8388")
        assert ok is True

    def test_invalid_scheme(self):
        ok, err = validate_shadowsocks_config("vless://uuid@host:443")
        assert ok is False
        assert err == "Invalid scheme"

    def test_missing_server_address(self):
        ok, err = validate_shadowsocks_config("ss://")
        assert ok is False


class TestValidateProxyConfig:
    def test_unknown_protocol(self):
        ok, err = validate_proxy_config("http://example.com")
        assert ok is False
        assert err == "Unknown or invalid protocol"

    def test_delegates_to_vless_validator(self):
        ok, err = validate_proxy_config(f"vless://{VALID_UUID}@host:443")
        assert ok is True

    def test_delegates_to_trojan_validator_failure(self):
        ok, err = validate_proxy_config("trojan://host:443")  # no password
        assert ok is False
        assert err == "Missing password"

    def test_protocol_without_specific_validator_passes(self):
        # hysteria/hysteria2/tuic have no dedicated validator -> considered valid
        ok, err = validate_proxy_config("hysteria://host:443")
        assert ok is True
        assert err is None


class TestNormalizeSource:
    def test_returns_unchanged_without_hash(self):
        assert normalize_source("https://example.com/sub") == "https://example.com/sub"

    def test_decodes_url_encoded_comment(self):
        result = normalize_source("https://example.com/sub#My%20Server")
        assert result == "https://example.com/sub#My Server"

    def test_decodes_double_encoded_comment(self):
        result = normalize_source("https://example.com/sub#My%2520Server")
        assert result == "https://example.com/sub#My Server"

    def test_raises_when_comment_too_long(self):
        long_comment = "x" * 300
        with pytest.raises(ValueError):
            normalize_source(f"https://example.com/sub#{long_comment}", max_comment_length=255)

    def test_no_limit_when_max_comment_length_is_none(self):
        long_comment = "x" * 1000
        result = normalize_source(f"https://example.com/sub#{long_comment}", max_comment_length=None)
        assert result.endswith(long_comment)
