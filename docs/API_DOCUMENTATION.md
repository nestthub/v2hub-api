# VPN Subscription API - Complete Documentation

## Table of Contents

- [Overview](#overview)
- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [API Endpoints](#api-endpoints)
  - [Public Endpoints](#public-endpoints)
  - [Subscription Management](#subscription-management)
  - [Provider API](#provider-api)
  - [Admin Endpoints](#admin-endpoints)
- [Data Models](#data-models)
- [Error Handling](#error-handling)
- [Examples](#examples)

---

## Overview

The VPN Subscription API provides a comprehensive solution for managing and aggregating VPN proxy subscriptions. It supports:

- **Multi-source aggregation**: Combine proxy configs from direct URIs, external URLs, and internal references
- **Per-subscription comments**: Add custom comments to configs within each subscription
- **Per-source visibility & nesting control**: Hide individual sources from resolved output and cap how deep internal references are followed (`is_hidden`, `max_depth`)
- **Recursive resolution**: Automatic resolution of nested subscription references
- **Two-tier caching**: Redis + PostgreSQL for optimal performance
- **Circular reference detection**: Prevents infinite loops in subscription chains
- **Rate limiting**: Configurable limits for different endpoint types
- **Security**: HMAC-SHA256 signature verification for admin endpoints
- **Provider integrations**: External services can request user consent to manage subscriptions on a user's behalf, subject to per-provider approved-user limits

**Base URL**: `https://your-domain.com`

**API Version**: v1 (`1.1.0`)

---

## Authentication

### User Authentication

Most endpoints require authentication via the `API-Token` header:

```http
API-Token: {provider_api_token}
```

**Example**:

```http
API-Token: a1b2c3d4e5f6g7h8i9j0
```

### Provider Authentication

Provider-scoped endpoints (`/api/v1/providers/...`) also authenticate via the `API-Token` header, but the token identifies a **provider** account rather than a user account. Unlike the user token, it is a single opaque string — it is not prefixed with the provider's hash or any other identifier:

```http
API-Token: {provider_api_token}
```

**Example**:

```http
API-Token: a1B2c3D4e5F6g7H8i9J0
```

The provider (and its `provider_hash`) is looked up from this token alone. A provider must additionally hold an **approved authorization** for the target `user_id` before it can manage that user's subscriptions (`/api/v1/providers/{user_id}/subs/...`). Authorization is established via `POST /api/v1/providers/{user_id}` and can be revoked at any time — see [Provider API](#provider-api).

### Admin Authentication

Admin endpoints require two security layers:

1. **IP Whitelist**: Request must originate from an allowed IP address
2. **HMAC Signature**: Request must include valid signature headers

**Required Headers**:

```http
X-Signature: {hmac_signature}
X-Timestamp: {unix_timestamp_ms}
```

**Signature Calculation**:

```python
import hmac
import hashlib
import time

timestamp = str(int(time.time() * 1000))
method = "POST"
path = "/api/v1/admin/users"
body = '{"user_id": 12345}'

payload = f"{timestamp}{method}{path}{body}"
signature = hmac.new(
    admin_secret_key.encode(),
    payload.encode(),
    hashlib.sha256
).hexdigest()
```

**Timestamp Validation**:

- Timestamps are valid within ±1 minute window
- Prevents replay attacks

---

## Rate Limiting

The API implements tiered rate limiting:

| Endpoint Type         | Rate Limit | Scope                 |
| --------------------- | ---------- | --------------------- |
| Public (`/sub/*`)     | 3 req/sec  | Per IP                |
| Internal (no token)   | 1 req/sec  | Per IP                |
| Internal (with token) | 3 req/sec  | Per IP                |
| Admin                 | No limit   | IP whitelist required |

**Rate Limit Headers** (returned on all requests):

```http
X-RateLimit-Limit: 3
X-RateLimit-Remaining: 2
X-RateLimit-Reset: 1714234567
```

**429 Response** (rate limit exceeded):

```json
{
  "error": "too_many_requests",
  "message": "Rate limit exceeded",
  "details": {
    "retry_after": 1.5
  }
}
```

---

## API Endpoints

### Public Endpoints

Public endpoints are accessible without authentication.

#### Get Resolved Subscription

Retrieve a fully resolved subscription with all configs aggregated.

**Endpoint**: `GET /sub/{token}`

**Parameters**:

- `token` (path, required): Subscription token

**Response Headers**:

```http
Content-Type: text/plain; charset=utf-8
profile-title: base64:{encoded_description}
profile-update-interval: 12
Content-Disposition: attachment; filename="subscription.txt"
Cache-Control: no-store
```

**Response Body**: Base64-encoded proxy configurations (one per line)

**Example Request**:

```bash
curl https://api.example.com/sub/abc123xyz456
```

**Example Response**:

```
dmxlc3M6Ly91dWlkQHNlcnZlcjoxMjM0NT9lbmNyeXB0aW9uPW5vbmUmc2VjdXJpdHk9dGxzJnNu
aT1leGFtcGxlLmNvbSZ0eXBlPXRjcCZoZWFkZXJUeXBlPW5vbmUjTXlTZXJ2ZXIK
...
```

**Error Responses**:

- `404 Not Found`: Subscription token not found
- `500 Internal Server Error`: Resolution failed (circular reference, nesting too deep, etc.)

---

### Subscription Management

All subscription endpoints require authentication via `API-Token` header.

**Base Path**: `/api/v1/subs`

#### Create Subscription

Create a new subscription with optional initial sources.

**Endpoint**: `POST /api/v1/subs`

**Request Body**:

```json
{
  "name": "My VPN Subscription",
  "description": "Personal VPN configs",
  "sources": [
    "vless://uuid@server:port?encryption=none#MyServer",
    "https://provider.com/subscription",
    {
      "data": "https://your-domain.com/sub/another-token",
      "is_hidden": true,
      "max_depth": 1
    }
  ]
}
```

**Request Schema**:

| Field         | Type                          | Required | Description       | Constraints                 |
| ------------- | ----------------------------- | -------- | ----------------- | --------------------------- |
| `name`        | string                        | Yes      | Subscription name | 1-64 chars, unique per user |
| `description` | string                        | No       | Description       | Max 64 chars                |
| `sources`     | array[string \| SourceObject] | No       | Initial sources   | Max 150 items               |

Each item in `sources` can be a plain string (shorthand for `{"data": "<string>"}`) or a source object:

| Field       | Type    | Required | Description                                            | Constraints      |
| ----------- | ------- | -------- | ------------------------------------------------------ | ---------------- |
| `data`      | string  | Yes      | Config URI, URL, or internal token                     | Non-empty        |
| `is_hidden` | boolean | No       | Omit this source's configs from resolved output        | Default `false`  |
| `max_depth` | integer | No       | Max recursion depth for nested subscription references | 0-3, default `3` |

**Response** (201 Created):

```json
{
  "token": "abc123xyz456",
  "name": "My VPN Subscription",
  "description": "Personal VPN configs",
  "sources": [
    {
      "id": "hash1",
      "source_type": "config",
      "data": "vless://uuid@server:port?encryption=none#MyServer",
      "order_index": 0,
      "is_hidden": false,
      "max_depth": 3,
      "created_at": "2026-04-27T10:00:00Z",
      "updated_at": "2026-04-27T10:00:00Z"
    },
    {
      "id": "hash2",
      "source_type": "external_url",
      "data": "https://provider.com/subscription",
      "order_index": 1,
      "is_hidden": false,
      "max_depth": 3,
      "created_at": "2026-04-27T10:00:00Z",
      "updated_at": "2026-04-27T10:00:00Z"
    },
    {
      "id": "hash3",
      "source_type": "internal_token",
      "data": "https://your-domain.com/sub/another-token",
      "order_index": 2,
      "is_hidden": true,
      "max_depth": 1,
      "created_at": "2026-04-27T10:00:00Z",
      "updated_at": "2026-04-27T10:00:00Z"
    }
  ],
  "sources_count": 15,
  "created_at": "2026-04-27T10:00:00Z",
  "updated_at": "2026-04-27T10:00:00Z"
}
```

**Error Responses**:

- `400 Bad Request`: Invalid input (validation failed)
- `409 Conflict`: Subscription name already exists
- `403 Forbidden`: Max subscriptions limit reached (default: 3)

---

#### List Subscriptions

Get all subscriptions for the authenticated user.

**Endpoint**: `GET /api/v1/subs`

**Response** (200 OK):

```json
[
  {
    "token": "abc123xyz456",
    "name": "My VPN Subscription",
    "description": "Personal VPN configs",
    "sources_count": 15,
    "created_at": "2026-04-27T10:00:00Z",
    "updated_at": "2026-04-27T10:00:00Z"
  },
  {
    "token": "def789uvw012",
    "name": "Work VPN",
    "description": null,
    "sources_count": 8,
    "created_at": "2026-04-26T15:30:00Z",
    "updated_at": "2026-04-27T09:00:00Z"
  }
]
```

---

#### Get Subscription Details

Retrieve detailed information about a specific subscription.

**Endpoint**: `GET /api/v1/subs/{token}`

**Parameters**:

- `token` (path, required): Subscription token

**Response** (200 OK):

```json
{
  "token": "abc123xyz456",
  "name": "My VPN Subscription",
  "description": "Personal VPN configs",
  "sources": [
    {
      "id": "hash1",
      "source_type": "config",
      "data": "vless://uuid@server:port#MyServer",
      "order_index": 0,
      "is_hidden": false,
      "max_depth": 3,
      "created_at": "2026-04-27T10:00:00Z",
      "updated_at": "2026-04-27T10:00:00Z"
    }
  ],
  "sources_count": 15,
  "created_at": "2026-04-27T10:00:00Z",
  "updated_at": "2026-04-27T10:00:00Z"
}
```

**Error Responses**:

- `404 Not Found`: Subscription not found
- `403 Forbidden`: Not owned by current user

---

#### Update Subscription Metadata

Update subscription name and/or description.

**Endpoint**: `PATCH /api/v1/subs/{token}`

**Parameters**:

- `token` (path, required): Subscription token

**Request Body**:

```json
{
  "name": "Updated Name",
  "description": "Updated description"
}
```

**Request Schema**:

| Field         | Type   | Required | Description     | Constraints                 |
| ------------- | ------ | -------- | --------------- | --------------------------- |
| `name`        | string | No       | New name        | 1-64 chars, unique per user |
| `description` | string | No       | New description | Max 64 chars                |

**Note**: At least one field must be provided.

**Response** (200 OK): Same as Get Subscription Details

**Error Responses**:

- `400 Bad Request`: No fields provided or validation failed
- `404 Not Found`: Subscription not found
- `409 Conflict`: Name already exists

---

#### Delete Subscription

Permanently delete a subscription and all its sources.

**Endpoint**: `DELETE /api/v1/subs/{token}`

**Parameters**:

- `token` (path, required): Subscription token

**Response** (204 No Content): Empty body

**Error Responses**:

- `404 Not Found`: Subscription not found
- `403 Forbidden`: Not owned by current user

---

#### Add Sources

Add new sources to an existing subscription.

**Endpoint**: `POST /api/v1/subs/{token}/sources`

**Parameters**:

- `token` (path, required): Subscription token

**Request Body**:

```json
{
  "sources": [
    "vless://uuid@server:port#NewServer",
    { "data": "https://new-provider.com/sub", "is_hidden": true }
  ]
}
```

**Request Schema**:

| Field     | Type                          | Required | Description    | Constraints |
| --------- | ----------------------------- | -------- | -------------- | ----------- |
| `sources` | array[string \| SourceObject] | Yes      | Sources to add | 1-150 items |

Each item can be a plain string or a source object with `data` (required), `is_hidden` (default `false`), and `max_depth` (default `3`, range 0-3) — see [Create Subscription](#create-subscription) for the object shape.

**Notes**:

- Duplicates are automatically filtered out (by `data`)
- Sources can include comments using `#` syntax
- URLs starting with `https://your-domain.com/sub/` are treated as internal references

**Response** (200 OK): Same as Get Subscription Details (with updated sources)

**Error Responses**:

- `400 Bad Request`: Invalid sources or validation failed
- `404 Not Found`: Subscription not found
- `413 Payload Too Large`: Too many sources

---

#### Replace All Sources

Replace all sources in a subscription atomically.

**Endpoint**: `PUT /api/v1/subs/{token}/sources`

**Parameters**:

- `token` (path, required): Subscription token

**Request Body**:

```json
{
  "sources": [
    "vless://uuid@server:port#Server1",
    { "data": "vmess://uuid@server:port#Server2", "max_depth": 0 }
  ]
}
```

**Request Schema**:

| Field     | Type                          | Required | Description | Constraints                        |
| --------- | ----------------------------- | -------- | ----------- | ---------------------------------- |
| `sources` | array[string \| SourceObject] | Yes      | New sources | Max 150 items, empty array allowed |

Same item shape as [Add Sources](#add-sources).

**Note**: This is an atomic operation - all existing sources are deleted before new ones are added.

**Response** (200 OK): Same as Get Subscription Details

**Error Responses**:

- `400 Bad Request`: Invalid sources
- `404 Not Found`: Subscription not found

---

#### Remove Sources

Remove specific sources by their IDs.

**Endpoint**: `DELETE /api/v1/subs/{token}/sources`

**Parameters**:

- `token` (path, required): Subscription token

**Request Body**:

```json
{
  "source_ids": ["hash1", "hash2", "hash3"]
}
```

**Request Schema**:

| Field        | Type          | Required | Description   | Constraints |
| ------------ | ------------- | -------- | ------------- | ----------- |
| `source_ids` | array[string] | Yes      | IDs to remove | Min 1 item  |

**Response** (200 OK): Same as Get Subscription Details (with sources removed)

**Error Responses**:

- `400 Bad Request`: Empty array or invalid IDs
- `404 Not Found`: Subscription or source IDs not found

---

#### Update Config

Partially update settings (comment, visibility, nesting depth) for a specific config source within a subscription.

**Endpoint**: `PATCH /api/v1/subs/{token}/config`

**Parameters**:

- `token` (path, required): Subscription token

**Request Body**:

```json
{
  "config_id": "config_hash_value",
  "comment": "My custom comment",
  "is_hidden": false,
  "max_depth": 2
}
```

**Request Schema**:

| Field       | Type    | Required | Description                                         | Constraints                         |
| ----------- | ------- | -------- | --------------------------------------------------- | ----------------------------------- |
| `config_id` | string  | Yes      | Config hash                                         | Min 1 char                          |
| `comment`   | string  | No       | Comment text                                        | Max 256 chars, no `#` prefix needed |
| `is_hidden` | boolean | No       | Hide this source's configs from resolved output     | -                                   |
| `max_depth` | integer | No       | Max nesting depth for source visibility propagation | 0-3                                 |

Only the fields provided in the request are modified; omitted fields are left unchanged.

**Notes**:

- Same proxy config can have different comments in different subscriptions
- If `comment` is set to null or empty, uses domain name as default
- Comments are appended to configs using `#` when resolving

**Response** (204 No Content): Empty body

**Error Responses**:

- `404 Not Found`: Subscription or config not found
- `400 Bad Request`: Invalid config_id

---

#### Update Config Comment <sup>Deprecated</sup>

> **Deprecated**: This endpoint still works and continues to be fully supported by the API and official client libraries, but it will not receive further updates and may be removed in a future major version. Use [Update Config](#update-config) instead, which supports the same comment update plus `is_hidden` and `max_depth`.

Update or set comment for a specific config within a subscription.

**Endpoint**: `PATCH /api/v1/subs/{token}/comments`

**Parameters**:

- `token` (path, required): Subscription token

**Request Body**:

```json
{
  "config_id": "config_hash_value",
  "comment": "My custom comment"
}
```

**Request Schema**:

| Field       | Type   | Required | Description  | Constraints                         |
| ----------- | ------ | -------- | ------------ | ----------------------------------- |
| `config_id` | string | Yes      | Config hash  | Min 1 char                          |
| `comment`   | string | No       | Comment text | Max 256 chars, no `#` prefix needed |

**Notes**:

- Same proxy config can have different comments in different subscriptions
- If `comment` is null or empty, uses domain name as default
- Comments are appended to configs using `#` when resolving

**Response** (204 No Content): Empty body

**Error Responses**:

- `404 Not Found`: Subscription or config not found
- `400 Bad Request`: Invalid config_id

---

#### Refresh Subscription

Manually refresh all external URL sources in a subscription.

**Endpoint**: `POST /api/v1/subs/{token}/refresh`

**Parameters**:

- `token` (path, required): Subscription token

**Response** (200 OK):

```json
{
  "refreshed": 5,
  "failed": 1,
  "skipped": 2,
  "total": 8,
  "message": "Refresh completed with some failures",
  "errors": ["https://dead-provider.com/sub: Connection timeout"]
}
```

**Response Schema**:

| Field       | Type          | Description                                        |
| ----------- | ------------- | -------------------------------------------------- |
| `refreshed` | integer       | Number of successfully refreshed sources           |
| `failed`    | integer       | Number of sources that failed to refresh           |
| `skipped`   | integer       | Number of sources skipped (CONFIG, INTERNAL_TOKEN) |
| `total`     | integer       | Total sources processed                            |
| `message`   | string        | Status message                                     |
| `errors`    | array[string] | List of error messages for failed sources          |

**Notes**:

- Only affects EXTERNAL_URL sources
- CONFIG and INTERNAL_TOKEN sources are skipped
- Updates cache for refreshed sources
- Background worker refreshes sources automatically every 15 minutes

**Error Responses**:

- `404 Not Found`: Subscription not found

---

### Provider API

Providers are external services (e.g. bots, resellers) that manage VPN subscriptions on behalf of a user. Using the Provider API involves two layers:

1. **Connection management** — a provider requests and manages authorization to act for a given `user_id`. Endpoints live under `/api/v1/providers/{user_id}`.
2. **Delegated subscription management** — once authorized, a provider performs the same subscription CRUD operations as a self-service user, scoped to that `user_id`. Endpoints live under `/api/v1/providers/{user_id}/subs`, mirror [Subscription Management](#subscription-management) endpoint-for-endpoint, and accept the same request/response schemas.

All Provider API endpoints require authentication via the `API-Token` header using a **provider** token (see [Provider Authentication](#provider-authentication)).

**Base Path**: `/api/v1/providers`

#### Get Connection Status

Get the current authorization status between the authenticated provider and a user.

**Endpoint**: `GET /api/v1/providers/{user_id}`

**Parameters**:

- `user_id` (path, required): Target user ID

**Response** (200 OK):

```json
{
  "user_id": 12345,
  "status": "approved"
}
```

**Response Schema**:

| Field     | Type    | Description             |
| --------- | ------- | ----------------------- |
| `user_id` | integer | User ID                 |
| `status`  | string  | `approved` or `revoked` |

**Error Responses**:

- `401 Unauthorized`: Invalid or missing provider token
- `404 Not Found`: User does not exist
- `403 Forbidden`: No authorization record exists yet for this user

---

#### Create Provider Connection

Create (or re-approve) an authorization allowing the provider to manage the given user's subscriptions. If the target `user_id` doesn't exist yet, a new user account is created automatically.

**Endpoint**: `POST /api/v1/providers/{user_id}`

**Parameters**:

- `user_id` (path, required): Target user ID

**Response** (201 Created):

```json
{
  "user_id": 12345,
  "status": "approved"
}
```

**Notes**:

- If the user doesn't exist, it is created as part of this call (temporary behavior — see caveat below)
- If no authorization exists yet, one is created and immediately approved
- If a `revoked` authorization already exists, it is re-approved
- Each provider has a maximum number of approved users (`MAX_PROVIDER_USERS`, default 1000); exceeding it returns `422`

> **Caveat**: User confirmation is currently not required before a connection is approved, and any provider can create a user account by calling this endpoint with an unused `user_id`. This is a temporary implementation — a proper user-facing consent flow (and restricting account creation to trusted callers) is planned for a future release.

**Error Responses**:

- `401 Unauthorized`: Invalid or missing provider token
- `422 Unprocessable Content`: Provider's approved-user limit reached

---

#### Revoke Provider Connection

Revoke the provider's authorization for a user without deleting the authorization record. The connection can later be re-approved via `POST /api/v1/providers/{user_id}`.

**Endpoint**: `POST /api/v1/providers/{user_id}/revoke`

**Parameters**:

- `user_id` (path, required): Target user ID

**Response** (200 OK):

```json
{
  "user_id": 12345,
  "status": "revoked"
}
```

**Error Responses**:

- `401 Unauthorized`: Invalid or missing provider token
- `404 Not Found`: User does not exist
- `400 Bad Request`: No authorization record exists for this user

---

#### Delete Provider Connection

Permanently remove the authorization between the provider and the user. Unlike revoke, this deletes the authorization record entirely, along with any subscriptions the provider created for that user.

**Endpoint**: `DELETE /api/v1/providers/{user_id}`

**Parameters**:

- `user_id` (path, required): Target user ID

**Response** (200 OK):

```json
{
  "detail": "Provider connection deleted"
}
```

**Error Responses**:

- `401 Unauthorized`: Invalid or missing provider token
- `404 Not Found`: User or authorization not found

---

#### Delegated Subscription Management

Once a provider holds an `approved` authorization for a user, it can perform the full subscription CRUD workflow on that user's behalf using the same request/response shapes documented under [Subscription Management](#subscription-management), with `/api/v1/subs` replaced by `/api/v1/providers/{user_id}/subs`:

| Operation            | Self-service                          | Provider                                                  |
| -------------------- | ------------------------------------- | --------------------------------------------------------- |
| Create subscription  | `POST /api/v1/subs`                   | `POST /api/v1/providers/{user_id}/subs`                   |
| List subscriptions   | `GET /api/v1/subs`                    | `GET /api/v1/providers/{user_id}/subs`                    |
| Get subscription     | `GET /api/v1/subs/{token}`            | `GET /api/v1/providers/{user_id}/subs/{token}`            |
| Update subscription  | `PATCH /api/v1/subs/{token}`          | `PATCH /api/v1/providers/{user_id}/subs/{token}`          |
| Delete subscription  | `DELETE /api/v1/subs/{token}`         | `DELETE /api/v1/providers/{user_id}/subs/{token}`         |
| Add sources          | `POST /api/v1/subs/{token}/sources`   | `POST /api/v1/providers/{user_id}/subs/{token}/sources`   |
| Replace sources      | `PUT /api/v1/subs/{token}/sources`    | `PUT /api/v1/providers/{user_id}/subs/{token}/sources`    |
| Remove sources       | `DELETE /api/v1/subs/{token}/sources` | `DELETE /api/v1/providers/{user_id}/subs/{token}/sources` |
| Update config        | `PATCH /api/v1/subs/{token}/config`   | `PATCH /api/v1/providers/{user_id}/subs/{token}/config`   |
| Refresh subscription | `POST /api/v1/subs/{token}/refresh`   | `POST /api/v1/providers/{user_id}/subs/{token}/refresh`   |

**Response differences**: subscriptions created or listed through the Provider API include a populated `provider_name` field (see [Subscription Object](#subscription-object)), identifying which provider manages that subscription. Self-service subscriptions have `provider_name: null`.

**Error Responses** (in addition to the standard subscription errors):

- `401 Unauthorized`: Invalid or missing provider token
- `403 Forbidden`: Provider does not have an `approved` authorization for this `user_id`
- `404 Not Found`: User does not exist

---

### Admin Endpoints

All admin endpoints require both IP whitelisting and HMAC signature verification.

**Base Path**: `/api/v1/admin`

**Security Requirements**:

- Request IP must be in `ADMIN_ALLOWED_IPS` list
- Must include valid `X-Signature` and `X-Timestamp` headers

#### Create User

Create a new user account with generated credentials.

**Endpoint**: `POST /api/v1/admin/users`

**Request Body**:

```json
{
  "user_id": 12345
}
```

**Request Schema**:

| Field     | Type    | Required | Description      | Constraints |
| --------- | ------- | -------- | ---------------- | ----------- |
| `user_id` | integer | Yes      | External user ID | > 0         |

**Response** (201 Created):

```json
{
  "user_hash": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "user_id": 12345,
  "api_token": "q1w2e3r4t5y6u7i8o9p0",
  "is_active": true
}
```

**Response Schema**:

| Field       | Type    | Description                            |
| ----------- | ------- | -------------------------------------- |
| `user_hash` | string  | Generated user hash (SHA-256)          |
| `user_id`   | integer | User ID                                |
| `api_token` | string  | Generated API token for authentication |
| `is_active` | boolean | Account active status                  |

**Error Responses**:

- `401 Unauthorized`: Invalid signature or timestamp
- `403 Forbidden`: IP not in whitelist
- `409 Conflict`: User ID already exists

---

#### Get User

Retrieve user account information.

**Endpoint**: `GET /api/v1/admin/users/{user_id}`

**Parameters**:

- `user_id` (path, required): User ID

**Response** (200 OK):

```json
{
  "user_hash": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "user_id": 12345,
  "api_token": "q1w2e3r4t5y6u7i8o9p0",
  "is_active": true
}
```

**Error Responses**:

- `404 Not Found`: User not found
- `401 Unauthorized`: Invalid signature
- `403 Forbidden`: IP not in whitelist

---

#### Delete User

Delete a user account and all associated data.

**Endpoint**: `DELETE /api/v1/admin/users/{user_id}`

**Parameters**:

- `user_id` (path, required): User ID

**Response** (204 No Content): Empty body

**Notes**:

- Deletes user and all their subscriptions
- This operation is permanent and cannot be undone

**Error Responses**:

- `404 Not Found`: User not found
- `401 Unauthorized`: Invalid signature
- `403 Forbidden`: IP not in whitelist

---

#### Update User Status

Enable or disable a user account.

**Endpoint**: `PATCH /api/v1/admin/users/{user_id}/status`

**Parameters**:

- `user_id` (path, required): User ID

**Request Body**:

```json
{
  "is_active": false
}
```

**Request Schema**:

| Field       | Type    | Required | Description        |
| ----------- | ------- | -------- | ------------------ |
| `is_active` | boolean | Yes      | New account status |

**Response** (200 OK):

```json
{
  "user_hash": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "user_id": 12345,
  "api_token": "q1w2e3r4t5y6u7i8o9p0",
  "is_active": false
}
```

**Notes**:

- Inactive users cannot authenticate or access API
- Existing sessions are immediately invalidated

---

#### Refresh User Token

Generate a new API token for a user.

**Endpoint**: `POST /api/v1/admin/users/{user_id}/token/refresh`

**Parameters**:

- `user_id` (path, required): User ID

**Request Body**:

```json
{
  "user_id": 12345
}
```

**Response** (200 OK):

```json
{
  "user_id": 12345,
  "new_api_token": "q1w2e3r4t5y6u7i8o9p0"
}
```

**Notes**:

- Old token is immediately invalidated
- User must update their credentials

---

#### List Providers

Get all provider accounts, mapped by name.

**Endpoint**: `GET /api/v1/admin/providers`

**Response** (200 OK):

```json
{
  "provider_hashes": {
    "Provider A": "a1b2c3d4e5f6...",
    "Provider B": "q9w8e7r6t5y4..."
  }
}
```

**Error Responses**:

- `401 Unauthorized`: Invalid signature or timestamp
- `403 Forbidden`: IP not in whitelist

---

#### Create Provider

Create a new provider account with a generated API token.

**Endpoint**: `POST /api/v1/admin/providers`

**Request Body**:

```json
{
  "owner_hash": "a1b2c3d4e5f6...",
  "provider_name": "vpn123",
  "provider_url": "https://t.me/examplebot"
}
```

**Request Schema**:

| Field           | Type   | Required | Description                  | Constraints |
| --------------- | ------ | -------- | ---------------------------- | ----------- |
| `owner_hash`    | string | Yes      | Hash of the provider's owner | -           |
| `provider_name` | string | Yes      | Provider display name        | -           |
| `provider_url`  | string | No       | Provider URL (e.g. bot link) | -           |

**Response** (201 Created):

```json
{
  "provider_hash": "a1b2c3d4e5f6...",
  "owner_hash": "q1w2e3r4t5y6...",
  "provider_name": "vpn123",
  "api_token": "a1b2c3d4e5f6...",
  "provider_url": "https://t.me/examplebot",
  "is_active": true
}
```

**Error Responses**:

- `401 Unauthorized`: Invalid signature or timestamp
- `403 Forbidden`: IP not in whitelist

---

#### Get Provider

Retrieve provider account information.

**Endpoint**: `GET /api/v1/admin/providers/{provider_hash}`

**Parameters**:

- `provider_hash` (path, required): Provider hash

**Response** (200 OK): Same shape as [Create Provider](#create-provider)

**Error Responses**:

- `404 Not Found`: Provider not found
- `401 Unauthorized`: Invalid signature
- `403 Forbidden`: IP not in whitelist

---

#### Delete Provider

Delete a provider account.

**Endpoint**: `DELETE /api/v1/admin/providers/{provider_hash}`

**Parameters**:

- `provider_hash` (path, required): Provider hash

**Response** (204 No Content): Empty body

**Error Responses**:

- `404 Not Found`: Provider not found
- `401 Unauthorized`: Invalid signature
- `403 Forbidden`: IP not in whitelist

---

#### Update Provider Status

Enable or disable a provider account.

**Endpoint**: `PATCH /api/v1/admin/providers/{provider_hash}/status`

**Parameters**:

- `provider_hash` (path, required): Provider hash

**Request Body**:

```json
{
  "is_active": false
}
```

**Response** (200 OK): Same shape as [Create Provider](#create-provider)

**Notes**:

- Inactive providers cannot authenticate or access the Provider API

---

#### Update Provider URL

Update a provider's URL.

**Endpoint**: `PATCH /api/v1/admin/providers/{provider_hash}/url`

**Parameters**:

- `provider_hash` (path, required): Provider hash

**Request Body**:

```json
{
  "provider_url": "https://t.me/newbot"
}
```

**Response** (200 OK): Same shape as [Create Provider](#create-provider)

---

#### Update Provider Name

Update a provider's display name.

**Endpoint**: `PATCH /api/v1/admin/providers/{provider_hash}/name`

**Parameters**:

- `provider_hash` (path, required): Provider hash

**Request Body**:

```json
{
  "provider_name": "vpn123-renamed"
}
```

**Response** (200 OK): Same shape as [Create Provider](#create-provider)

---

#### Refresh Provider Token

Generate a new API token for a provider.

**Endpoint**: `POST /api/v1/admin/providers/refresh-token`

**Request Body**:

```json
{
  "provider_hash": "a1b2c3d4e5f6..."
}
```

**Response** (200 OK):

```json
{
  "provider_hash": "a1b2c3d4e5f6...",
  "new_api_token": "q1w2e3r4t5y6u7i8o9p0"
}
```

**Notes**:

- Old token is immediately invalidated

---

#### Ban IP Address

Temporarily or permanently ban an IP address.

**Endpoint**: `POST /api/v1/admin/bans`

**Request Body**:

```json
{
  "ip_address": "192.168.1.100",
  "duration_seconds": 3600
}
```

**Request Schema**:

| Field              | Type    | Required | Description  | Constraints           |
| ------------------ | ------- | -------- | ------------ | --------------------- |
| `ip_address`       | string  | Yes      | IP to ban    | Valid IPv4/IPv6       |
| `duration_seconds` | integer | No       | Ban duration | > 0, null = permanent |

**Response** (201 Created):

```json
{
  "ip_address": "192.168.1.100",
  "is_banned": true,
  "banned_until": "2026-04-27T11:00:00Z",
  "remaining_seconds": 3600
}
```

**Notes**:

- Banned IPs cannot access any endpoint
- If `duration_seconds` is null, ban is permanent
- System automatically unbans after duration expires

---

#### Unban IP Address

Remove an IP address from the ban list.

**Endpoint**: `POST /api/v1/admin/unbans`

**Request Body**:

```json
{
  "ip_address": "192.168.1.100"
}
```

**Response** (200 OK):

```json
{
  "ip_address": "192.168.1.100",
  "was_banned": true,
  "message": "IP unbanned successfully"
}
```

**Response Schema**:

| Field        | Type    | Description                      |
| ------------ | ------- | -------------------------------- |
| `ip_address` | string  | Unbanned IP                      |
| `was_banned` | boolean | Whether IP was previously banned |
| `message`    | string  | Result message                   |

---

#### List Banned IPs

Get all currently banned IP addresses.

**Endpoint**: `GET /api/v1/admin/bans`

**Response** (200 OK):

```json
{
  "entries": [
    {
      "ip_address": "192.168.1.100",
      "banned_until": "2026-04-27T11:00:00Z"
    },
    {
      "ip_address": "10.0.0.50",
      "banned_until": null
    }
  ],
  "total": 2
}
```

**Notes**:

- `banned_until: null` indicates permanent ban
- Expired bans are automatically removed from the list

---

#### Check IP Ban Status

Check if an IP is banned and get ban details.

**Endpoint**: `GET /api/v1/admin/bans/{ip_address}`

**Parameters**:

- `ip_address` (path, required): IP address to check

**Response** (200 OK):

```json
{
  "ip_address": "192.168.1.100",
  "is_banned": true,
  "banned_until": "2026-04-27T11:00:00Z",
  "remaining_seconds": 1800
}
```

---

#### Add IP to Whitelist

Add an IP address or CIDR range to the whitelist.

**Endpoint**: `POST /api/v1/admin/whitelist`

**Request Body**:

```json
{
  "ip_address": "10.0.0.0/24",
  "description": "Internal office network"
}
```

**Request Schema**:

| Field         | Type   | Required | Description      | Constraints   |
| ------------- | ------ | -------- | ---------------- | ------------- |
| `ip_address`  | string | Yes      | IP or CIDR range | Valid format  |
| `description` | string | No       | Description      | Max 255 chars |

**Response** (201 Created):

```json
{
  "ip_address": "10.0.0.0/24",
  "description": "Internal office network",
  "message": "IP added to whitelist successfully"
}
```

**Notes**:

- Whitelisted IPs are exempt from rate limiting
- Supports CIDR notation for IP ranges

---

#### Remove IP from Whitelist

Remove an IP address from the whitelist.

**Endpoint**: `DELETE /api/v1/admin/whitelist`

**Request Body**:

```json
{
  "ip_address": "10.0.0.0/24"
}
```

**Response** (200 OK):

```json
{
  "ip_address": "10.0.0.0/24",
  "was_whitelisted": true,
  "message": "IP removed from whitelist"
}
```

---

#### List Whitelisted IPs

Get all whitelisted IP addresses.

**Endpoint**: `GET /api/v1/admin/whitelist`

**Response** (200 OK):

```json
{
  "entries": [
    {
      "ip_address": "10.0.0.0/24",
      "description": "Internal office network",
      "added_at": "2026-04-20T10:00:00Z"
    },
    {
      "ip_address": "192.168.1.1",
      "description": null,
      "added_at": "2026-04-21T15:30:00Z"
    }
  ],
  "total": 2
}
```

---

## Data Models

### Source Types

Sources are classified into three types:

```python
class SourceType(str, Enum):
    CONFIG = "config"           # Direct proxy URI
    EXTERNAL_URL = "external_url"  # HTTPS subscription URL
    INTERNAL_TOKEN = "internal_token"  # Reference to another subscription
```

**Type Detection**:

- Starts with proxy protocol (`vless://`, `vmess://`, etc.) → `CONFIG`
- Starts with `https://your-domain.com/sub/` → `INTERNAL_TOKEN`
- Otherwise → `EXTERNAL_URL`

### Proxy Protocols

Supported proxy protocols:

```python
class ProxyProtocol(str, Enum):
    VLESS = "vless"
    VMESS = "vmess"
    TROJAN = "trojan"
    SHADOWSOCKS = "ss"
    HYSTERIA = "hysteria"
    HYSTERIA2 = "hysteria2"
    TUIC = "tuic"
```

### Source Object

```typescript
interface Source {
  id: string; // Source hash (unique identifier)
  source_type: "config" | "external_url" | "internal_token";
  data: string; // Full source data (config URI, URL, or internal ref)
  order_index: number; // Display order (0-indexed)
  is_hidden: boolean; // Whether this source's configs are hidden from resolved output
  max_depth: number; // Max nesting depth for source visibility propagation (0-3)
  created_at: string; // ISO 8601 timestamp
  updated_at: string; // ISO 8601 timestamp
}
```

### Source Input Object

Shape used for items in `sources` arrays on `POST /subs`, `POST /subs/{token}/sources`, and `PUT /subs/{token}/sources`. A plain string is also accepted as shorthand for `{ data: "<string>" }`.

```typescript
interface SourceInput {
  data: string; // Config URI, URL, or internal token (required)
  is_hidden?: boolean; // Default: false
  max_depth?: number; // Default: 3, range: 0-3
}
```

### Subscription Object

```typescript
interface Subscription {
  token: string; // Unique subscription token
  name: string; // User-defined name (1-64 chars)
  provider_name: string | null; // Name of the managing provider, or null for self-service
  description: string | null; // Optional description (max 64 chars)
  sources: Source[]; // Array of sources
  sources_count: number; // Total resolved configs count
  created_at: string; // ISO 8601 timestamp
  updated_at: string; // ISO 8601 timestamp
}
```

### Subscription List Item

```typescript
interface SubscriptionListItem {
  token: string;
  name: string;
  provider_name: string | null; // Name of the managing provider, or null for self-service
  description: string | null;
  sources_count: number;
  created_at: string;
  updated_at: string;
}
```

### Provider Connection Response

Returned by the Provider API's connection-management endpoints (`GET`/`POST` `/api/v1/providers/{user_id}`, `POST /api/v1/providers/{user_id}/revoke`).

```typescript
interface ProviderConnectionResponse {
  user_id: number; // User ID
  status: "approved" | "revoked"; // Current authorization status
}
```

### Provider Connection Delete Response

Returned by `DELETE /api/v1/providers/{user_id}`.

```typescript
interface ProviderConnectionDeleteResponse {
  detail: string; // Operation result message
}
```

---

## Error Handling

### Error Response Format

All errors follow this structure:

```json
{
  "error": "error_code",
  "message": "Human-readable error message",
  "details": {
    "field": "additional context"
  }
}
```

### Error Codes

| Code                      | HTTP Status | Description                                            |
| ------------------------- | ----------- | ------------------------------------------------------ |
| `invalid_token`           | 401         | Invalid or missing API token                           |
| `forbidden`               | 403         | Access denied (wrong user or inactive account)         |
| `user_not_found`          | 404         | User does not exist                                    |
| `not_found`               | 404         | Generic resource not found                             |
| `subscription_not_found`  | 404         | Subscription does not exist                            |
| `source_not_found`        | 404         | Source ID not found                                    |
| `invalid_config`          | 400         | Invalid proxy configuration URI                        |
| `invalid_url`             | 400         | Invalid URL format                                     |
| `duplicate_name`          | 409         | Subscription name already exists                       |
| `circular_reference`      | 500         | Circular reference detected in subscription chain      |
| `nesting_too_deep`        | 500         | Subscription nesting exceeds max depth (default: 3)    |
| `too_many_configs`        | 413         | Resolved configs exceed limit (default: 150)           |
| `too_many_sources`        | 413         | Sources exceed limit (default: 150)                    |
| `too_many_subscriptions`  | 403         | User subscription limit reached (default: 3)           |
| `too_many_approved_users` | 422         | Provider's approved-user limit reached (default: 1000) |
| `too_many_requests`       | 429         | Rate limit exceeded                                    |
| `fetch_error`             | 502         | Failed to fetch external URL                           |
| `cache_error`             | 500         | Cache operation failed                                 |

### Validation Errors

Field validation errors return 422 status with detailed information:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "name"],
      "msg": "String should have at least 1 character",
      "input": "",
      "ctx": {
        "min_length": 1
      }
    }
  ]
}
```

---

## Examples

### Complete Workflow Example

#### 1. Create User (Admin)

```bash
# Calculate signature
timestamp=$(date +%s000)
method="POST"
path="/api/v1/admin/users"
body='{"user_id":12345}'
payload="${timestamp}${method}${path}${body}"
signature=$(echo -n "$payload" | openssl dgst -sha256 -hmac "$ADMIN_SECRET_KEY" | awk '{print $2}')

# Create user
curl -X POST https://api.example.com/api/v1/admin/users \
  -H "Content-Type: application/json" \
  -H "X-Signature: $signature" \
  -H "X-Timestamp: $timestamp" \
  -d "$body"
```

**Response**:

```json
{
  "user_hash": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "user_id": 12345,
  "api_token": "q1w2e3r4t5y6u7i8o9p0",
  "is_active": true
}
```

#### 2. Create Subscription (User)

```bash
curl -X POST https://api.example.com/api/v1/subs \
  -H "Content-Type: application/json" \
  -H "API-Token: q1w2e3r4t5y6u7i8o9p0" \
  -d '{
    "name": "My Servers",
    "description": "Personal VPN collection",
    "sources": [
      "vless://uuid@server1.com:443?encryption=none&security=tls#Server1",
      "vmess://base64config#Server2",
      "https://provider.com/subscription"
    ]
  }'
```

#### 3. Add More Sources

```bash
curl -X POST https://api.example.com/api/v1/subs/abc123xyz456/sources \
  -H "Content-Type: application/json" \
  -H "API-Token: q1w2e3r4t5y6u7i8o9p0" \
  -d '{
    "sources": [
      "trojan://password@server3.com:443#Server3"
    ]
  }'
```

#### 4. Update Config

```bash
curl -X PATCH https://api.example.com/api/v1/subs/abc123xyz456/config \
  -H "Content-Type: application/json" \
  -H "API-Token: q1w2e3r4t5y6u7i8o9p0" \
  -d '{
    "config_id": "config_hash_value",
    "comment": "Fast US Server",
    "is_hidden": false
  }'
```

> The older `PATCH /comments` endpoint (comment-only) still works and is documented under [Update Config Comment](#update-config-comment-deprecated), but is deprecated in favor of the endpoint above.

#### 5. Get Resolved Subscription (Public)

```bash
curl https://api.example.com/sub/abc123xyz456
```

**Response**: Base64-encoded configs ready for VPN client import

#### 6. Provider: Connect and Manage a User's Subscription

```bash
# Provider requests a connection for user_id 12345
curl -X POST https://api.example.com/api/v1/providers/12345 \
  -H "API-Token: prov_a1B2c3D4e5F6g7H8i9J0"
```

**Response**:

```json
{
  "user_id": 12345,
  "status": "approved"
}
```

```bash
# Provider creates a subscription on behalf of that user
curl -X POST https://api.example.com/api/v1/providers/12345/subs \
  -H "Content-Type: application/json" \
  -H "API-Token: q1w2e3r4t5y6u7i8o9p0" \
  -d '{
    "name": "Managed VPN",
    "sources": ["vless://uuid@server:port#Server1"]
  }'
```

---

### Python Client Example

```python
import hmac
import hashlib
import time
import requests

class VPNSubscriptionClient:
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url
        self.headers = {
            "API-Token": api_token,
            "Content-Type": "application/json"
        }

    def create_subscription(self, name: str, sources: list[str]):
        """Create a new subscription."""
        response = requests.post(
            f"{self.base_url}/api/v1/subs",
            headers=self.headers,
            json={
                "name": name,
                "sources": sources
            }
        )
        response.raise_for_status()
        return response.json()

    def list_subscriptions(self):
        """List all subscriptions."""
        response = requests.get(
            f"{self.base_url}/api/v1/subs",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

    def add_sources(self, token: str, sources: list[str]):
        """Add sources to a subscription."""
        response = requests.post(
            f"{self.base_url}/api/v1/subs/{token}/sources",
            headers=self.headers,
            json={"sources": sources}
        )
        response.raise_for_status()
        return response.json()

# Usage
client = VPNSubscriptionClient(
    base_url="https://api.example.com",
    api_token="q1w2e3r4t5y6u7i8o9p0"
)

# Create subscription
sub = client.create_subscription(
    name="My VPN",
    sources=[
        "vless://uuid@server:port#Server1",
        "https://provider.com/subscription"
    ]
)

print(f"Subscription created: {sub['token']}")
print(f"Public URL: https://api.example.com/sub/{sub['token']}")
```

### Admin Client Example

```python
import hmac
import hashlib
import time
import requests

class AdminClient:
    def __init__(self, base_url: str, admin_secret: str):
        self.base_url = base_url
        self.admin_secret = admin_secret

    def _sign_request(self, method: str, path: str, body: str) -> dict:
        """Generate HMAC signature for admin request."""
        timestamp = str(int(time.time() * 1000))
        payload = f"{timestamp}{method}{path}{body}"

        signature = hmac.new(
            self.admin_secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()

        return {
            "X-Signature": signature,
            "X-Timestamp": timestamp,
            "Content-Type": "application/json"
        }

    def create_user(self, user_id: int):
        """Create a new user."""
        method = "POST"
        path = "/api/v1/admin/users"
        body = f'{{"user_id":{user_id}}}'

        headers = self._sign_request(method, path, body)

        response = requests.post(
            f"{self.base_url}{path}",
            headers=headers,
            data=body
        )
        response.raise_for_status()
        return response.json()

    def ban_ip(self, ip: str, duration: int = 3600):
        """Ban an IP address."""
        method = "POST"
        path = "/api/v1/admin/bans"
        body = f'{{"ip_address":"{ip}","duration_seconds":{duration}}}'

        headers = self._sign_request(method, path, body)

        response = requests.post(
            f"{self.base_url}{path}",
            headers=headers,
            data=body
        )
        response.raise_for_status()
        return response.json()

# Usage
admin = AdminClient(
    base_url="https://api.example.com",
    admin_secret="your-admin-secret-key"
)

# Create user
user = admin.create_user(user_id=12345)
print(f"User created: {user['api_token']}")

# Ban IP
ban = admin.ban_ip(ip="192.168.1.100", duration=3600)
print(f"IP banned until: {ban['banned_until']}")
```

---

## Configuration Limits

Default configuration limits (can be customized via environment variables):

| Parameter                       | Default | Environment Variable           |
| ------------------------------- | ------- | ------------------------------ |
| Max subscriptions per user      | 3       | `MAX_SUBSCRIPTIONS_PER_USER`   |
| Max sources per subscription    | 150     | `MAX_SOURCES_PER_SUBSCRIPTION` |
| Max configs per subscription    | 150     | `MAX_CONFIGS_PER_SUBSCRIPTION` |
| Max nesting depth               | 3       | `MAX_NESTING_DEPTH`            |
| Fetch timeout                   | 3s      | `FETCH_TIMEOUT`                |
| Redis TTL                       | 600s    | `REDIS_TTL`                    |
| Max approved users per provider | 1000    | `MAX_PROVIDER_USERS`           |

---

## Best Practices

### Performance Optimization

1. **Use internal references**: Reference other subscriptions instead of duplicating configs
2. **Batch operations**: Use `PUT /sources` to replace all sources at once
3. **Cache strategy**: External URLs are cached for 10 minutes by default
4. **Pagination**: For large subscriptions, consider splitting into multiple smaller ones

### Security Recommendations

1. **Rotate API tokens**: Regularly refresh user tokens via admin endpoint
2. **Monitor rate limits**: Track `X-RateLimit-*` headers
3. **Validate sources**: Always validate proxy URIs before adding
4. **Use HTTPS**: Never transmit tokens over unencrypted connections

### Error Handling

1. **Retry logic**: Implement exponential backoff for 5xx errors
2. **Validate responses**: Always check HTTP status codes
3. **Handle rate limits**: Respect `429` responses and retry after delay
4. **Log errors**: Keep detailed logs of API interactions

---

## Support & Contact

For issues, questions, or feature requests, please contact the API maintainer or open an issue in the project repository.

**API Version**: 1.1.0
**Last Updated**: August 15, 2026
