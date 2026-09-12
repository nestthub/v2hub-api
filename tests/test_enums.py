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
            ("hy2://host:443", ProxyProtocol.HYSTERIA2),
            ("tuic://uuid:pass@host:443", ProxyProtocol.TUIC),
        ],
    )
    def test_from_uri_valid(self, uri, expected):
        assert ProxyProtocol.from_uri(uri) is expected

    def test_from_uri_case_insensitive(self):
        assert ProxyProtocol.from_uri("VLESS://uuid@host:443") is ProxyProtocol.VLESS
        assert ProxyProtocol.from_uri("VmEsS://data") is ProxyProtocol.VMESS
        assert ProxyProtocol.from_uri("HY2://host:443") is ProxyProtocol.HYSTERIA2

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


class TestProxyProtocolSchemeAliases:
    """hy2:// is an alternate spelling of hysteria2://, not a separate
    protocol — these tests pin down that it's recognized on input but
    never introduces a second, distinct representation."""

    def test_hy2_resolves_to_canonical_hysteria2_member(self):
        assert ProxyProtocol.from_uri("hy2://host:443") is ProxyProtocol.HYSTERIA2

    def test_hy2_and_hysteria2_are_the_same_object(self):
        # Not just "equal" (which StrEnum vs. a bare str could satisfy via
        # value comparison) — genuinely the same member, so anything that
        # compares protocols with `is` (a common enum idiom) still works
        # regardless of which spelling the source URI used.
        from_alias = ProxyProtocol.from_uri("hy2://host:443")
        from_canonical = ProxyProtocol.from_uri("hysteria2://host:443")
        assert from_alias is from_canonical

    def test_alias_resolution_returns_real_enum_member_not_str(self):
        result = ProxyProtocol.from_uri("hy2://host:443")
        assert type(result) is ProxyProtocol

    def test_canonical_str_representation_ignores_original_spelling(self):
        # Regardless of which scheme the source URI used, the canonical
        # form is what gets stored/re-serialized.
        assert str(ProxyProtocol.from_uri("hy2://host:443")) == "hysteria2"

    def test_scheme_aliases_is_not_an_enum_member(self):
        assert "_SCHEME_ALIASES" not in ProxyProtocol.__members__

    def test_alias_does_not_change_member_count(self):
        # Exactly the 7 real protocols — the alias table doesn't add an
        # 8th "hy2" member alongside HYSTERIA2.
        assert len(ProxyProtocol) == 7

    def test_bare_alias_scheme_name_is_not_a_valid_direct_value(self):
        # "hy2" is only recognized via from_uri()'s alias resolution, not
        # as a value you can construct the enum from directly — there is
        # deliberately no ProxyProtocol("hy2").
        with pytest.raises(ValueError):
            ProxyProtocol("hy2")

    def test_known_uri_schemes_includes_canonical_and_alias_schemes(self):
        schemes = ProxyProtocol.known_uri_schemes()
        # All 7 canonical protocol values...
        assert {"vless", "vmess", "trojan", "ss", "hysteria", "hysteria2", "tuic"} <= schemes
        # ...plus known aliases.
        assert "hy2" in schemes

    def test_known_uri_schemes_does_not_include_internal_alias_table_name(self):
        # The alias table itself ("_SCHEME_ALIASES") must never leak into
        # the set of recognized scheme strings.
        assert "_SCHEME_ALIASES" not in ProxyProtocol.known_uri_schemes()

    def test_known_uri_schemes_returns_frozenset(self):
        assert isinstance(ProxyProtocol.known_uri_schemes(), frozenset)


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
