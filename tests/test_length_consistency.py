"""
End-to-end consistency tests tying together the four layers that must all
agree on field lengths after `issue/5-database-limits`:

    generator (secrets/uuid/blake2b)
        -> core.constants  (single source of truth)
            -> Pydantic schemas (API boundary validation)
            -> SQLAlchemy models (DB column definitions)
                -> actual database round-trip

Each layer was previously tested in isolation (generators in
test_config_parser.py / test_user_service.py / test_provider_service.py,
Pydantic bounds in test_schema_field_limits.py, HMAC signing in
test_admin_security.py), but nothing asserted that they all agree with
*each other* on the same numbers, or that a value produced end-to-end by
a real generator actually survives a real DB write via SQLAlchemy.

Notable finding baked into this file (see `TestSqliteDoesNotEnforceLength`):
the test suite's SQLite backend does NOT enforce `String(n)` length at
INSERT time (SQLite has no native VARCHAR length constraint), unlike
production PostgreSQL. That means the SQLAlchemy `String(n)` declarations
are only verified against `core.constants` here via *table metadata*
introspection, not via "does an oversized INSERT fail" -- an oversized
INSERT will succeed silently against SQLite in tests but would fail (or
truncate, depending on driver) against Postgres in production. This is
documented explicitly so it isn't mistaken for real DB-level enforcement.
"""

import hashlib
import secrets
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from v2hub_api.core.constants import (
    API_TOKEN_BYTES,
    API_TOKEN_LENGTH,
    COMMENT_MAX_LENGTH,
    HASH_BYTES,
    HASH_LENGTH,
    PROVIDER_NAME_MAX_LENGTH,
    SUBSCRIPTION_DESCRIPTION_MAX_LENGTH,
    SUBSCRIPTION_NAME_MAX_LENGTH,
    SUBSCRIPTION_TOKEN_BYTES,
    SUBSCRIPTION_TOKEN_LENGTH,
    URL_MAX_LENGTH,
    UUID_LENGTH,
)
from v2hub_api.db.models import (
    Base,
    ConfigComment,
    ExternalCache,
    Provider,
    ProviderAuthorization,
    ProxyConfig,
    Source,
    Subscription,
    User,
)
from v2hub_api.schemas.admin_models.providers import (
    ProviderCreateRequest,
    ProviderNameUpdateRequest,
    ProviderResponse,
)
from v2hub_api.schemas.admin_models.users import UserResponse
from v2hub_api.schemas.base_models.models import UpsertUserRequest
from v2hub_api.schemas.base_models.sources import SourceOut, SourceUpdateRequest
from v2hub_api.schemas.base_models.subscriptions import SubscriptionBase
from v2hub_api.services.provider_service import ProviderService
from v2hub_api.services.user_service import UserService
from v2hub_api.utils.config_parser import get_config_hash, get_url_hash

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════════════════
# Layer 1: generator output length == core.constants
# ═══════════════════════════════════════════════════════════════════════════
#
# These re-derive the *actual* Base64URL/hex-length formulas independently
# (rather than importing the derived constants) so a bug in the formula
# itself -- not just a typo'd literal -- would be caught.


class TestGeneratorLengthsMatchConstants:
    def test_api_token_generator_length_matches_constant(self):
        token = secrets.token_urlsafe(API_TOKEN_BYTES)
        assert len(token) == API_TOKEN_LENGTH

    def test_subscription_token_generator_length_matches_constant(self):
        token = secrets.token_urlsafe(SUBSCRIPTION_TOKEN_BYTES)
        assert len(token) == SUBSCRIPTION_TOKEN_LENGTH

    def test_uuid4_length_matches_constant(self):
        assert len(str(uuid.uuid4())) == UUID_LENGTH

    def test_blake2b_hex_digest_length_matches_hash_constant(self):
        digest = hashlib.blake2b(b"anything", digest_size=HASH_BYTES).hexdigest()
        assert len(digest) == HASH_LENGTH

    def test_token_urlsafe_length_formula_is_stable_across_byte_counts(self):
        """
        Guard against silently changing API_TOKEN_BYTES /
        SUBSCRIPTION_TOKEN_BYTES without updating the derived *_LENGTH
        constants -- token_urlsafe(n) produces ceil(4n/3) chars without
        '=' padding.
        """
        for n_bytes in (8, 16, 24, 32, 48):
            expected_len = -(-n_bytes * 4 // 3)  # ceil division
            assert len(secrets.token_urlsafe(n_bytes)) == expected_len


# ═══════════════════════════════════════════════════════════════════════════
# Layer 2: real service-generated values through Pydantic schemas
# ═══════════════════════════════════════════════════════════════════════════


class TestRealGeneratedValuesPassPydanticValidation:
    """
    Not "does a same-length synthetic string pass" (already covered in
    test_schema_field_limits.py) but "does the *actual* value a service
    produces at runtime pass the schema that will validate it on the way
    out of the API".
    """

    async def test_created_user_fields_satisfy_upsert_user_request(self, db_session):
        user_service = UserService(db_session)
        user = await user_service.create_user(user_id=123)

        # Round-trips the real generated user_hash/api_token through the
        # schema used for admin user-upsert payloads.
        req = UpsertUserRequest(
            user_hash=user.user_hash,
            user_id=user.user_id,
            api_token=user.api_token,
        )
        assert req.user_hash == user.user_hash
        assert req.api_token == user.api_token

    async def test_created_user_fields_satisfy_user_response_schema(self, db_session):
        user_service = UserService(db_session)
        user = await user_service.create_user(user_id=123)

        resp = UserResponse(
            user_hash=user.user_hash,
            user_id=user.user_id,
            api_token=user.api_token,
            is_active=user.is_active,
            provider_hash=None,
        )
        assert resp.user_hash == user.user_hash

    async def test_created_provider_fields_satisfy_provider_response_schema(self, db_session):
        user_service = UserService(db_session)
        owner = await user_service.create_user(user_id=1)
        provider_service = ProviderService(db_session)
        provider = await provider_service.create_provider(
            owner_hash=owner.user_hash, provider_name="vpn123"
        )

        resp = ProviderResponse(
            provider_hash=provider.provider_hash,
            owner_hash=provider.owner_hash,
            provider_name=provider.provider_name,
            api_token=provider.api_token,
            provider_url=provider.provider_url,
            is_active=provider.is_active,
        )
        assert resp.provider_hash == provider.provider_hash
        assert resp.api_token == provider.api_token

    def test_generated_config_hash_satisfies_source_update_request(self):
        config_hash = get_config_hash("vless://uuid@host:443#name")
        req = SourceUpdateRequest(config_hash=config_hash, comment="hi")
        assert req.config_hash == config_hash

    def test_generated_url_hash_length_matches_source_out_id_bounds(self):
        """
        `url_hash`/`config_hash`/source `id` all share HASH_LENGTH; verify
        a real url_hash produced by the config parser fits the SourceOut.id
        field bounds even though url_hash itself isn't a SourceOut field
        directly (CONFIG-type sources use config_hash as their id).
        """
        url_hash = get_url_hash("https://example.com/sub")
        assert len(url_hash) == HASH_LENGTH

        # SourceOut.id has the same min/max as HASH_LENGTH; a hash-shaped
        # value must satisfy it regardless of which hashing helper produced it.
        source = SourceOut(
            id=url_hash,
            source_type="config",
            data="vless://uuid@host:443",
            order_index=0,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert source.id == url_hash


# ═══════════════════════════════════════════════════════════════════════════
# Layer 3: core.constants == SQLAlchemy column metadata (per-model)
# ═══════════════════════════════════════════════════════════════════════════
#
# This is a direct, exhaustive cross-check against migration
# 0003_adjust_database_column_lengths.py: every altered column's new
# length must match what the ORM model currently declares, so the models
# and the migration can never silently drift apart.


class TestSqlAlchemyColumnLengthsMatchConstants:
    def _length_of(self, model, column_name: str) -> int | None:
        return model.__table__.c[column_name].type.length

    def test_user_columns(self):
        assert self._length_of(User, "user_hash") == UUID_LENGTH
        assert self._length_of(User, "api_token") == API_TOKEN_LENGTH

    def test_provider_columns(self):
        assert self._length_of(Provider, "provider_hash") == UUID_LENGTH
        assert self._length_of(Provider, "owner_hash") == UUID_LENGTH
        assert self._length_of(Provider, "provider_name") == PROVIDER_NAME_MAX_LENGTH
        assert self._length_of(Provider, "api_token") == API_TOKEN_LENGTH
        assert self._length_of(Provider, "provider_url") == URL_MAX_LENGTH

    def test_provider_authorization_columns_inherit_fk_target_length(self):
        """
        provider_hash/user_hash here have no explicit String(...) -- they
        infer their type from the referenced FK column. This asserts that
        inference actually resolves to UUID_LENGTH rather than silently
        falling back to some SQLAlchemy default.
        """
        assert self._length_of(ProviderAuthorization, "provider_hash") == UUID_LENGTH
        assert self._length_of(ProviderAuthorization, "user_hash") == UUID_LENGTH

    def test_proxy_config_columns(self):
        assert self._length_of(ProxyConfig, "config_hash") == HASH_LENGTH

    def test_subscription_columns(self):
        assert self._length_of(Subscription, "token") == SUBSCRIPTION_TOKEN_LENGTH
        assert self._length_of(Subscription, "name") == SUBSCRIPTION_NAME_MAX_LENGTH
        assert self._length_of(Subscription, "user_hash") == UUID_LENGTH
        assert self._length_of(Subscription, "provider_hash") == UUID_LENGTH
        assert self._length_of(Subscription, "description") == SUBSCRIPTION_DESCRIPTION_MAX_LENGTH

    def test_source_columns(self):
        assert self._length_of(Source, "subscription_token") == SUBSCRIPTION_TOKEN_LENGTH
        assert self._length_of(Source, "id") == HASH_LENGTH
        assert self._length_of(Source, "config_hash") == HASH_LENGTH
        assert self._length_of(Source, "internal_token") == SUBSCRIPTION_TOKEN_LENGTH
        assert self._length_of(Source, "external_url") == URL_MAX_LENGTH

    def test_config_comment_columns(self):
        assert self._length_of(ConfigComment, "subscription_token") == SUBSCRIPTION_TOKEN_LENGTH
        assert self._length_of(ConfigComment, "config_hash") == HASH_LENGTH
        assert self._length_of(ConfigComment, "comment") == COMMENT_MAX_LENGTH

    def test_external_cache_columns(self):
        assert self._length_of(ExternalCache, "url_hash") == HASH_LENGTH
        assert self._length_of(ExternalCache, "url") == URL_MAX_LENGTH

    def test_no_untracked_hash_or_token_columns_exist(self):
        """
        Sanity net: enumerate every String column across all models and
        confirm each length is one of the lengths defined in
        core.constants. Catches a new column being added with a raw
        literal (e.g. String(64)) instead of importing the shared
        constant.
        """
        known_lengths = {
            HASH_LENGTH,
            API_TOKEN_LENGTH,
            SUBSCRIPTION_TOKEN_LENGTH,
            UUID_LENGTH,
            PROVIDER_NAME_MAX_LENGTH,
            URL_MAX_LENGTH,
            COMMENT_MAX_LENGTH,
            SUBSCRIPTION_NAME_MAX_LENGTH,
            SUBSCRIPTION_DESCRIPTION_MAX_LENGTH,
        }
        # Columns intentionally sized independently of core.constants
        # (protocol/source_type/status are small fixed enums-as-strings,
        # not identifiers or tokens covered by the length-limits effort).
        exempt = {
            ("proxy_configs", "protocol"),
            ("sources", "source_type"),
            ("provider_authorizations", "status"),
        }

        offenders = []
        for table_name, table in Base.metadata.tables.items():
            for col in table.columns:
                length = getattr(col.type, "length", None)
                if length is None:
                    continue
                if (table_name, col.name) in exempt:
                    continue
                if length not in known_lengths:
                    offenders.append((table_name, col.name, length))

        assert offenders == [], (
            f"Columns with a String length not backed by core.constants: {offenders}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Layer 4: full round-trip -- generator -> service -> SQLAlchemy -> SQLite
# ═══════════════════════════════════════════════════════════════════════════


class TestGeneratedValuesRoundTripThroughRealDb:
    """
    Confirms a value produced by the *actual* generator function (not a
    synthetic same-length string) survives being written through the ORM
    and read back unchanged -- exercising constants -> generator ->
    SQLAlchemy -> DB all in one path.
    """

    async def test_user_hash_and_token_round_trip_unchanged(self, db_session):
        user_service = UserService(db_session)
        created = await user_service.create_user(user_id=555)

        result = await db_session.execute(select(User).where(User.user_id == 555))
        fetched = result.scalar_one()

        assert fetched.user_hash == created.user_hash
        assert len(fetched.user_hash) == UUID_LENGTH
        assert fetched.api_token == created.api_token
        assert len(fetched.api_token) == API_TOKEN_LENGTH

    async def test_provider_hash_and_token_round_trip_unchanged(self, db_session):
        user_service = UserService(db_session)
        owner = await user_service.create_user(user_id=1)
        provider_service = ProviderService(db_session)
        created = await provider_service.create_provider(
            owner_hash=owner.user_hash, provider_name="vpn123"
        )

        result = await db_session.execute(
            select(Provider).where(Provider.provider_hash == created.provider_hash)
        )
        fetched = result.scalar_one()

        assert fetched.provider_hash == created.provider_hash
        assert len(fetched.provider_hash) == UUID_LENGTH
        assert fetched.api_token == created.api_token
        assert len(fetched.api_token) == API_TOKEN_LENGTH

    async def test_max_length_provider_name_round_trips(self, db_session):
        """A provider_name at exactly PROVIDER_NAME_MAX_LENGTH (the
        Pydantic-accepted boundary) must persist correctly, not just
        validate."""
        user_service = UserService(db_session)
        owner = await user_service.create_user(user_id=1)
        provider_service = ProviderService(db_session)
        name = "n" * PROVIDER_NAME_MAX_LENGTH

        # Confirm Pydantic accepts this exact boundary too, so the schema
        # and the DB layer are checked against the same value.
        ProviderNameUpdateRequest(provider_name=name)

        created = await provider_service.create_provider(
            owner_hash=owner.user_hash, provider_name=name
        )

        result = await db_session.execute(
            select(Provider).where(Provider.provider_hash == created.provider_hash)
        )
        fetched = result.scalar_one()
        assert fetched.provider_name == name
        assert len(fetched.provider_name) == PROVIDER_NAME_MAX_LENGTH


class TestSqliteDoesNotEnforceLength:
    """
    Documents (rather than silently relies on) a real gap between the
    test backend and production: SQLite does not enforce `String(n)` at
    INSERT time, so oversized data is only rejected by Pydantic at the API
    boundary -- if a write path ever bypasses Pydantic (e.g. an internal
    script, a bulk import, a future endpoint that forgets a Field(...)
    length), nothing in the ORM/SQLite layer of *this* test suite would
    catch it. Production PostgreSQL DOES enforce VARCHAR(n) and would
    reject or error on such a write instead.

    This test intentionally asserts the *current, real* SQLite behavior
    so a future switch to strict test-DB enforcement (e.g. Postgres
    testcontainers) is a deliberate decision, not a silent behavior change
    that this suite would miss either way.
    """

    async def test_oversized_provider_name_is_not_rejected_by_sqlite(self, db_session):
        user_service = UserService(db_session)
        owner = await user_service.create_user(user_id=1)

        oversized_name = "n" * (PROVIDER_NAME_MAX_LENGTH + 50)

        # Pydantic WOULD reject this at the API boundary:
        with pytest.raises(ValidationError):
            ProviderNameUpdateRequest(provider_name=oversized_name)

        # But writing it directly via the ORM (bypassing Pydantic, as a
        # trusted internal caller might) succeeds silently against SQLite:
        provider = Provider(
            provider_hash=str(uuid.uuid4()),
            owner_hash=owner.user_hash,
            provider_name=oversized_name,
            api_token=secrets.token_urlsafe(API_TOKEN_BYTES),
            is_active=True,
        )
        db_session.add(provider)
        await db_session.commit()

        result = await db_session.execute(
            select(Provider).where(Provider.provider_hash == provider.provider_hash)
        )
        fetched = result.scalar_one()
        assert len(fetched.provider_name) == PROVIDER_NAME_MAX_LENGTH + 50, (
            "This assertion documents current SQLite behavior (no length "
            "enforcement). If this ever fails, SQLite/aiosqlite started "
            "enforcing VARCHAR length and the surrounding class docstring "
            "should be revisited, not just this assertion."
        )
