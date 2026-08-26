# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Provider connection authorization flow with pending, approval, and rejection states.
- HMAC-signed provider connection invite links for securely authorizing new users.
- Admin endpoints for retrieving, approving, and rejecting provider authorization requests.
- Configurable limit of approved providers per user (`MAX_PROVIDERS_PER_USER`, default 5).
- Alembic migration `0004_provider_authorization_pending_default`, adding `PENDING` to the `providerauthorizationstatus` database enum and switching the `provider_authorizations.status` column default from `APPROVED` to `PENDING`.
- Centralized `core/constants.py` module defining hash, token, and text-field lengths, shared by both SQLAlchemy models and Pydantic schemas.
- Alembic migration `0003_adjust_database_column_lengths`, aligning DB column sizes (`config_comments`, `external_cache`, `provider_authorizations`, etc.) with the actual data formats.

### Changed

- Provider connection endpoint now returns a connection link for users who have not yet been authorized.
- Revoked provider authorizations are reinitialized as pending when a new connection is requested.
- Provider authorization limits are now enforced per user instead of per provider.
- `provider_authorizations.status` now defaults to `PENDING` instead of `APPROVED`, both in the `ProviderAuthorization` model and at the database schema level (migration `0004`). A newly created authorization no longer grants provider access until it is explicitly approved.
- Added provider URL validation using the existing external URL safety checks. Provider URLs are limited to 255 characters and must use a safe HTTP(S) URL without localhost, private, link-local, or other restricted addresses.
- Restricted `provider_name` to 4–16 characters using only lowercase letters (`a-z`), digits (`0-9`), and hyphens (`-`); leading, trailing, and consecutive hyphens are not allowed.
- Renamed the `config_id` field to `config_hash` in the comment/source-settings update request (the old name is still accepted as a legacy alias).
- API tokens and subscription tokens now have a fixed length (32 random bytes → 43 Base64URL characters) and are no longer configurable via the `API_TOKEN_LENGTH` environment variable.
- Tightened field validation: `provider_name` (4–16 chars), `subscription.name`/`description` (≤ 64), `comment` (≤ 255), `url` (≤ 255), `user_id` (1–999,999,999,999), and hashes (`config_hash`, `source_id`, `url_hash` — 32 chars; `user_hash`/`provider_hash`/`owner_hash` — 36 chars, UUID format).
- Narrowed URL columns in the database from `TEXT` to `VARCHAR(255)` to match the validation limit.

### Fixed

- Creating a provider authorization for an already-known user via `POST /providers/{user_id}` no longer risks defaulting to `APPROVED` — it now always requests `PENDING` explicitly, and the underlying column default was corrected to match (see migration `0004`). Previously this path could silently grant a provider full access without user confirmation and without going through the `MAX_PROVIDERS_PER_USER` quota check.
- Admin endpoint `POST /admin/providers/auth` no longer creates a user record as a side effect of a request naming a nonexistent provider; the provider-exists check now runs before any user is created.

### Removed

- Removed the previous maximum approved users per provider limit (`MAX_PROVIDER_USERS`).
- The `API_TOKEN_LENGTH` setting from `.env.example`, the README, and `Settings` — token length is no longer configurable.

### Docs

- Added `CHANGELOG.md`, documenting the full project history grouped by release tag.

### Tests

- Added coverage for the maximum approved providers per user, including rejection of a sixth provider.
- Added `test_admin_security.py`: HTTP-level coverage for the admin HMAC request-signature dependency and the IP-allowlist dependency, including a regression test for the query-string signature fix (commit `57c7cb3`).
- Added `test_me_endpoints.py`: HTTP-level coverage for the `/me` self-service router (current user info, connection listing/lookup/revocation).
- Added `test_schema_field_limits.py`: Pydantic-level coverage for the new field-length limits, including the `config_id` → `config_hash` legacy alias.
- Added `test_length_consistency.py`: cross-layer consistency checks tying together token/hash generators, `core/constants.py`, Pydantic schemas, SQLAlchemy column metadata, and real database round-trips — including an explicit test documenting that the SQLite test backend does not enforce `VARCHAR(n)` length the way production PostgreSQL does.
- Extended `test_provider_service.py` with coverage for `ProviderService.update_provider_name` (rename, idempotency, not-found, duplicate-name, and no-partial-apply-on-conflict cases).

---

## [1.1.1] — 2026-08-18

### Added

- `/me` endpoints — information about the current user and their provider connections (#18).

### Changed

- Admin endpoints split into separate modules for easier navigation.

### Fixed

- Fixed provider loading during subscription resolution.
- Admin request signature (HMAC) now includes the query string, closing a gap that allowed parameter tampering without invalidating the signature.
- Failed deployments no longer leave the system in an intermediate state; production now deploys the exact commit that passed CI (closes #15) (#16).

### Docs

- Updated Provider API and provider authentication documentation (#14).

---

## [1.1.0] — 2026-08-09

### Added

- Provider integrations: external services (bots, resellers) can request per-user authorization to manage a user's subscriptions on their behalf, subject to a configurable approved-user cap per provider (#12).
- Endpoint for updating a provider's name.
- Provider router registered with the application.
- Secured admin endpoint exposing business metrics and statistics (#10).
- Index-reset option for the replace-sources operation.

### Changed

- Subscription resolution moved to async I/O for better performance.
- External source refresh is now lazy — triggered on demand instead of only on a schedule (#9).
- CI pipeline migrated from pip to uv.
- Updated project dependency configuration.

### Fixed

- Normalized paths for admin and refresh-token endpoints in metrics.
- Correctly handle an empty provider list in the admin service.
- Database migrations now run before the API service starts during deployment.
- API health check now runs directly before restarting Nginx.
- Source replacement now looks up the existing record by `Source.id` instead of a stale key.
- `is_hidden`/`max_depth` flags are no longer silently overwritten when a source is re-added.
- `is_hidden` now applies only within the subscription scope the source belongs to, instead of globally.

---

## [1.0.3] — 2026-07-27

### Changed

- Project renamed from `v2hub-server` to `v2hub-api`, repository structure standardized; imports updated from `src` to `v2hub_api`.
- Database migrated to named Docker volumes; deployment defaults updated.
- Updated container names and `docker-compose.yml` configuration.
- Updated deployment workflow and refreshed the landing page.

### Added

- CI workflow and container deployment setup.
- Project license (LICENSE).

### Tests

- Added test coverage; resolved test-suite warnings.
- Migrated tests to the new project structure; removed the obsolete smoke test.

### Docs

- Updated README.md.

---

## [1.0.2] — 2026-07-20

### Added

- Documentation: README, API docs, types schema, and docs viewer.
- Observability stack based on Prometheus, Loki, Alloy, and Grafana.
- Per-source visibility and nesting control (`is_hidden`, `max_depth`) and a `PATCH /config` endpoint to manage them.
- IP whitelist for Nginx-level rate limits.

### Changed

- Replaced per-line argument-count validation with direct comment-length validation in the type schemas; improved comment handling.
- Config comments are now normalized on subscription creation.
- Metrics: replaced the `Info` metric with a `Gauge` for `fastapi_app_info` (dashboard compatibility), fixed `APP_NAME` to `v2hub` for consistent metric labeling, added request-path normalization (`/sub/{token}`, `/api/v1/subs/{token}`, etc.), and added bot/scanner path filtering to reduce metric cardinality.
- Grafana monitoring disabled by default.
- Updated certbot renewal configuration.
- Bumped API version from `0.1.0` to `1.0.1`.

### Fixed

- Fixed missing comments when resolving nested (internal) subscriptions.
- Cleaned up Redis/PostgreSQL health checks, removed dead redirect code, added Redis reconnect handling.
- Anchored the Alembic migration chain to the actual production baseline (`ba8245a056b5`).

### Database

- Added an Alembic migration for the `sources.is_hidden` / `sources.max_depth` columns.

---

## Reading this history

- Entries are grouped by version tag (`v1.0.2` through `v1.1.1`) and by mainline commits; early commits that predate any tag (including the very first `initial commit`) are folded into the **[1.0.2]** section as the project's foundation.
- The **[Unreleased]** section reflects changes on the `issue/5-database-limits` branch, which is not yet merged into `main` and has no tag.
- Merged pull requests and commits such as "Update deploy.yml" or "Merge pull request …" that carry no independent user-facing value are not listed separately; they're folded into the description of the related change.
