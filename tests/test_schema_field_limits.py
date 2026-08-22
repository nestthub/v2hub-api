"""
Tests for field-length validation introduced by the database-limits work
(`core/constants.py` + schema updates in `feat(schemas): tighten validation
and rename config_id to config_hash` / `refactor: centralize validation and
database field length constants`).

Covers:
- `SourceUpdateRequest.config_hash`: fixed 32-char length, and the
  `config_id` legacy alias still works.
- `ProviderNameUpdateRequest` / `ProviderInfoResponse`: provider_name
  bounds (4-16 chars) from `PROVIDER_NAME_MIN_LENGTH` / `_MAX_LENGTH`.
- `UpsertUserRequest`: fixed-length `user_hash` (36, UUID) and `api_token`
  (43, Base64URL) fields, plus the `user_id` upper bound.
- `SubscriptionCreateRequest`: `name` max length.

These schemas are the actual boundary enforcing the DB column sizes from
migration `0003_adjust_database_column_lengths`, so a regression here
(e.g. accidentally loosening a bound) would let invalid data reach the
database and fail at INSERT time instead of at the API boundary.
"""

import pytest
from pydantic import ValidationError

from v2hub_api.core.constants import (
    API_TOKEN_LENGTH,
    HASH_LENGTH,
    PROVIDER_NAME_MAX_LENGTH,
    PROVIDER_NAME_MIN_LENGTH,
    SUBSCRIPTION_NAME_MAX_LENGTH,
    URL_MAX_LENGTH,
    UUID_LENGTH,
)
from v2hub_api.schemas.admin_models.providers import (
    ProviderCreateRequest,
    ProviderNameUpdateRequest,
)
from v2hub_api.schemas.base_models.models import UpsertUserRequest
from v2hub_api.schemas.base_models.sources import SourceUpdateRequest
from v2hub_api.schemas.base_models.subscriptions import SubscriptionCreateRequest


class TestSourceUpdateRequestConfigHash:
    def test_accepts_config_hash_field(self):
        req = SourceUpdateRequest(config_hash="a" * HASH_LENGTH, comment="hi")
        assert req.config_hash == "a" * HASH_LENGTH

    def test_accepts_legacy_config_id_alias(self):
        """`config_id` must still validate for backward compatibility with
        older clients, populating the same `config_hash` field."""
        req = SourceUpdateRequest.model_validate({"config_id": "b" * HASH_LENGTH})
        assert req.config_hash == "b" * HASH_LENGTH

    def test_config_hash_takes_precedence_when_both_present(self):
        req = SourceUpdateRequest.model_validate(
            {"config_hash": "c" * HASH_LENGTH, "config_id": "d" * HASH_LENGTH}
        )
        assert req.config_hash == "c" * HASH_LENGTH

    def test_rejects_short_config_hash(self):
        with pytest.raises(ValidationError):
            SourceUpdateRequest(config_hash="a" * (HASH_LENGTH - 1))

    def test_rejects_long_config_hash(self):
        with pytest.raises(ValidationError):
            SourceUpdateRequest(config_hash="a" * (HASH_LENGTH + 1))

    def test_rejects_missing_config_hash(self):
        with pytest.raises(ValidationError):
            SourceUpdateRequest(comment="no hash provided")

    def test_comment_within_limit_is_accepted(self):
        req = SourceUpdateRequest(config_hash="a" * HASH_LENGTH, comment="x" * 255)
        assert req.comment == "x" * 255

    def test_comment_over_limit_is_rejected(self):
        with pytest.raises(ValidationError):
            SourceUpdateRequest(config_hash="a" * HASH_LENGTH, comment="x" * 256)

    def test_comment_is_optional(self):
        req = SourceUpdateRequest(config_hash="a" * HASH_LENGTH)
        assert req.comment is None


class TestProviderNameLimits:
    def test_accepts_minimum_length_name(self):
        req = ProviderNameUpdateRequest(provider_name="a" * PROVIDER_NAME_MIN_LENGTH)
        assert req.provider_name == "a" * PROVIDER_NAME_MIN_LENGTH

    def test_accepts_maximum_length_name(self):
        req = ProviderNameUpdateRequest(provider_name="a" * PROVIDER_NAME_MAX_LENGTH)
        assert req.provider_name == "a" * PROVIDER_NAME_MAX_LENGTH

    def test_rejects_name_below_minimum(self):
        with pytest.raises(ValidationError):
            ProviderNameUpdateRequest(provider_name="a" * (PROVIDER_NAME_MIN_LENGTH - 1))

    def test_rejects_name_above_maximum(self):
        with pytest.raises(ValidationError):
            ProviderNameUpdateRequest(provider_name="a" * (PROVIDER_NAME_MAX_LENGTH + 1))


class TestUpsertUserRequestLimits:
    def _valid_kwargs(self, **overrides):
        kwargs = {
            "user_hash": "a" * UUID_LENGTH,
            "user_id": 1,
            "api_token": "a" * API_TOKEN_LENGTH,
        }
        kwargs.update(overrides)
        return kwargs

    def test_accepts_well_formed_payload(self):
        req = UpsertUserRequest(**self._valid_kwargs())
        assert len(req.user_hash) == UUID_LENGTH
        assert len(req.api_token) == API_TOKEN_LENGTH

    def test_rejects_short_user_hash(self):
        with pytest.raises(ValidationError):
            UpsertUserRequest(**self._valid_kwargs(user_hash="a" * (UUID_LENGTH - 1)))

    def test_rejects_long_user_hash(self):
        with pytest.raises(ValidationError):
            UpsertUserRequest(**self._valid_kwargs(user_hash="a" * (UUID_LENGTH + 1)))

    def test_rejects_short_api_token(self):
        with pytest.raises(ValidationError):
            UpsertUserRequest(**self._valid_kwargs(api_token="a" * (API_TOKEN_LENGTH - 1)))

    def test_rejects_long_api_token(self):
        with pytest.raises(ValidationError):
            UpsertUserRequest(**self._valid_kwargs(api_token="a" * (API_TOKEN_LENGTH + 1)))

    def test_rejects_user_id_above_max(self):
        with pytest.raises(ValidationError):
            UpsertUserRequest(**self._valid_kwargs(user_id=1_000_000_000_000))

    def test_rejects_zero_or_negative_user_id(self):
        with pytest.raises(ValidationError):
            UpsertUserRequest(**self._valid_kwargs(user_id=0))
        with pytest.raises(ValidationError):
            UpsertUserRequest(**self._valid_kwargs(user_id=-1))

    def test_accepts_max_user_id(self):
        req = UpsertUserRequest(**self._valid_kwargs(user_id=999_999_999_999))
        assert req.user_id == 999_999_999_999


class TestSubscriptionCreateRequestLimits:
    def test_accepts_name_within_limit(self):
        req = SubscriptionCreateRequest(name="x" * SUBSCRIPTION_NAME_MAX_LENGTH)
        assert req.name == "x" * SUBSCRIPTION_NAME_MAX_LENGTH

    def test_rejects_name_over_limit(self):
        with pytest.raises(ValidationError):
            SubscriptionCreateRequest(name="x" * (SUBSCRIPTION_NAME_MAX_LENGTH + 1))

    def test_strips_and_rejects_whitespace_only_name(self):
        with pytest.raises(ValidationError):
            SubscriptionCreateRequest(name="   ")

    def test_strips_surrounding_whitespace(self):
        req = SubscriptionCreateRequest(name="  My Sub  ")
        assert req.name == "My Sub"


class TestProviderNameFormat:
    def test_accepts_lowercase_letters(self):
        req = ProviderNameUpdateRequest(provider_name="abcd")
        assert req.provider_name == "abcd"

    def test_accepts_digits(self):
        req = ProviderNameUpdateRequest(provider_name="1234")
        assert req.provider_name == "1234"

    def test_accepts_hyphens_between_parts(self):
        req = ProviderNameUpdateRequest(provider_name="my-provider-2")
        assert req.provider_name == "my-provider-2"

    def test_rejects_uppercase_letters(self):
        with pytest.raises(ValidationError):
            ProviderNameUpdateRequest(provider_name="MyProvider")

    def test_rejects_underscore(self):
        with pytest.raises(ValidationError):
            ProviderNameUpdateRequest(provider_name="my_provider")

    def test_rejects_dot(self):
        with pytest.raises(ValidationError):
            ProviderNameUpdateRequest(provider_name="my.provider")

    def test_rejects_space(self):
        with pytest.raises(ValidationError):
            ProviderNameUpdateRequest(provider_name="my provider")

    def test_rejects_leading_hyphen(self):
        with pytest.raises(ValidationError):
            ProviderNameUpdateRequest(provider_name="-my-provider")

    def test_rejects_trailing_hyphen(self):
        with pytest.raises(ValidationError):
            ProviderNameUpdateRequest(provider_name="my-provider-")

    def test_rejects_consecutive_hyphens(self):
        with pytest.raises(ValidationError):
            ProviderNameUpdateRequest(provider_name="my--provider")


class TestProviderCreateRequestProviderName:
    def test_rejects_invalid_provider_name(self):
        with pytest.raises(ValidationError):
            ProviderCreateRequest(
                owner_hash="00000000-0000-4000-8000-000000000000",
                provider_name="my_provider",
                provider_url=None,
            )


class TestProviderURLValidation:
    def test_accepts_none(self):
        req = ProviderCreateRequest(
            owner_hash="00000000-0000-4000-8000-000000000000",
            provider_name="vpn123",
            provider_url=None,
        )
        assert req.provider_url is None

    def test_accepts_https_url(self):
        req = ProviderCreateRequest(
            owner_hash="00000000-0000-4000-8000-000000000000",
            provider_name="vpn123",
            provider_url="https://example.com",
        )
        assert req.provider_url == "https://example.com"

    def test_accepts_http_url(self):
        req = ProviderCreateRequest(
            owner_hash="00000000-0000-4000-8000-000000000000",
            provider_name="vpn123",
            provider_url="http://example.com",
        )
        assert req.provider_url == "http://example.com"

    def test_rejects_non_http_scheme(self):
        with pytest.raises(ValidationError):
            ProviderCreateRequest(
                owner_hash="00000000-0000-4000-8000-000000000000",
                provider_name="vpn123",
                provider_url="ftp://example.com",
            )

    def test_rejects_localhost(self):
        with pytest.raises(ValidationError):
            ProviderCreateRequest(
                owner_hash="00000000-0000-4000-8000-000000000000",
                provider_name="vpn123",
                provider_url="http://localhost:8080",
            )

    def test_rejects_loopback_ip(self):
        with pytest.raises(ValidationError):
            ProviderCreateRequest(
                owner_hash="00000000-0000-4000-8000-000000000000",
                provider_name="vpn123",
                provider_url="http://127.0.0.1:8080",
            )

    def test_rejects_private_ip(self):
        with pytest.raises(ValidationError):
            ProviderCreateRequest(
                owner_hash="00000000-0000-4000-8000-000000000000",
                provider_name="vpn123",
                provider_url="http://192.168.1.1",
            )

    def test_rejects_link_local_ip(self):
        with pytest.raises(ValidationError):
            ProviderCreateRequest(
                owner_hash="00000000-0000-4000-8000-000000000000",
                provider_name="vpn123",
                provider_url="http://169.254.169.254",
            )

    def test_rejects_url_without_hostname(self):
        with pytest.raises(ValidationError):
            ProviderCreateRequest(
                owner_hash="00000000-0000-4000-8000-000000000000",
                provider_name="vpn123",
                provider_url="https://",
            )

    def test_rejects_url_over_maximum_length(self):
        with pytest.raises(ValidationError):
            ProviderCreateRequest(
                owner_hash="00000000-0000-4000-8000-000000000000",
                provider_name="vpn123",
                provider_url=f"https://example.com/{'a' * URL_MAX_LENGTH}",
            )
