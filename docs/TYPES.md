# Data Types and Schemas Reference

Complete reference for all data types, models, and schemas used in the VPN Subscription API.

---

## Table of Contents

- [Base Types](#base-types)
- [Request Models](#request-models)
- [Response Models](#response-models)
- [Admin Models](#admin-models)
- [Enumerations](#enumerations)
- [Validation Rules](#validation-rules)

---

## Base Types

### BaseModel

All Pydantic models inherit from a custom `BaseModel` with consistent configuration.

```python
class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
    )
```

**Configuration**:

- `from_attributes=True`: Enable ORM mode for SQLAlchemy models
- `str_strip_whitespace=True`: Automatically strip whitespace from strings
- `validate_assignment=True`: Validate on field assignment
- `use_enum_values=True`: Use enum values instead of enum objects

---

## Request Models

### SubscriptionCreateRequest

Create a new subscription.

```python
class SubscriptionCreateRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=64)]
    description: Annotated[str, Field(max_length=64)] | None = None
    sources: Annotated[list[SourceCreateRequest], Field(max_length=150)] = []
```

**Fields**:

| Field         | Type                         | Required | Constraints   | Description                             |
| ------------- | ---------------------------- | -------- | ------------- | --------------------------------------- |
| `name`        | `string`                     | Yes      | 1-64 chars    | Subscription name (unique per user)     |
| `description` | `string`                     | No       | Max 64 chars  | Optional description                    |
| `sources`     | `array[SourceCreateRequest]` | No       | Max 150 items | Initial sources (configs, URLs, tokens) |

Each item can be a plain string (shorthand) or a `SourceCreateRequest` object when you need to set `is_hidden` / `max_depth` at creation time.

**Example**:

```json
{
  "name": "My VPN Collection",
  "description": "Personal servers",
  "sources": [
    "vless://uuid@server:port#Server1",
    "https://provider.com/subscription",
    {
      "data": "vless://uuid2@server2:port#Server2",
      "is_hidden": true,
      "max_depth": 1
    }
  ]
}
```

**Validation**:

- Name must be unique per user
- Sources are automatically cleaned and deduplicated (by `data`)
- Invalid sources are rejected with validation error

---

### SubscriptionUpdateRequest

Update subscription metadata.

```python
class SubscriptionUpdateRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    description: Annotated[str, Field(max_length=64)] | None = None

    @model_validator(mode='after')
    def check_at_least_one_field(self) -> 'SubscriptionUpdateRequest':
        if self.name is None and self.description is None:
            raise ValueError("At least one field must be provided")
        return self
```

**Fields**:

| Field         | Type     | Required | Constraints  |
| ------------- | -------- | -------- | ------------ |
| `name`        | `string` | No*      | 1-64 chars   |
| `description` | `string` | No*      | Max 64 chars |

\*At least one field must be provided.

**Example**:

```json
{
  "name": "Updated Name"
}
```

---

### SourceCreateRequest

Object form for a source, used inside `sources` arrays of `SubscriptionCreateRequest`, `SourcesAddRequest`, and `SourcesReplaceRequest`. A plain string is also accepted as shorthand (equivalent to `{"data": "<string>"}`).

```python
class SourceCreateRequest(BaseModel):
    data: str
    is_hidden: bool = False
    max_depth: Annotated[int, Field(ge=0, le=3)] = 3
```

**Fields**:

| Field       | Type      | Required | Constraints | Description                                                      |
| ----------- | --------- | -------- | ----------- | ---------------------------------------------------------------- |
| `data`      | `string`  | Yes      | Non-empty   | Source data (config URI, URL, or internal token)                 |
| `is_hidden` | `boolean` | No       | -           | If true, this source's configs are omitted from resolved output  |
| `max_depth` | `integer` | No       | 0-3         | Max recursion depth for resolving nested subscription references |

**Example**:

```json
{
  "data": "https://provider.com/subscription",
  "is_hidden": false,
  "max_depth": 2
}
```

---

### SourcesAddRequest

Add sources to a subscription.

```python
class SourcesAddRequest(BaseModel):
    sources: Annotated[list[SourceCreateRequest], Field(min_length=1, max_length=150)]
```

**Fields**:

| Field     | Type                                   | Required | Constraints |
| --------- | -------------------------------------- | -------- | ----------- |
| `sources` | `array[string \| SourceCreateRequest]` | Yes      | 1-150 items |

**Example**:

```json
{
  "sources": [
    "vless://uuid@server:port#NewServer",
    { "data": "https://new-provider.com/sub", "is_hidden": true }
  ]
}
```

**Notes**:

- Duplicates are automatically filtered (by `data`)
- Each source is validated and classified (CONFIG, EXTERNAL_URL, or INTERNAL_TOKEN)
- String items are shorthand for `{"data": "<string>"}` with default `is_hidden`/`max_depth`

---

### SourcesReplaceRequest

Replace all sources atomically.

```python
class SourcesReplaceRequest(BaseModel):
    sources: Annotated[list[SourceCreateRequest], Field(max_length=150)]
```

**Fields**:

| Field     | Type                                   | Required | Constraints                 |
| --------- | -------------------------------------- | -------- | --------------------------- |
| `sources` | `array[string \| SourceCreateRequest]` | Yes      | Max 150 items, can be empty |

**Example**:

```json
{
  "sources": [
    "vless://uuid@server1:port#Server1",
    {
      "data": "vless://uuid@server2:port#Server2",
      "is_hidden": true,
      "max_depth": 0
    }
  ]
}
```

**Notes**:

- Empty array is allowed (removes all sources)
- This is an atomic operation - all existing sources deleted first

---

### SourcesRemoveRequest

Remove specific sources by ID.

```python
class SourcesRemoveRequest(BaseModel):
    source_ids: Annotated[list[str], Field(min_length=1)]
```

**Fields**:

| Field        | Type            | Required | Constraints |
| ------------ | --------------- | -------- | ----------- |
| `source_ids` | `array[string]` | Yes      | Min 1 item  |

**Example**:

```json
{
  "source_ids": ["hash1", "hash2", "hash3"]
}
```

**Validation**:

- All IDs must exist in the subscription
- Returns 404 if any ID not found

---

### SourceUpdateRequest

Partially update settings for a specific config source within a subscription. Used by both `PATCH /{token}/comments` (comment-only, sets `comment`) and `PATCH /{token}/config` (general update).

```python
class SourceUpdateRequest(BaseModel):
    config_id: Annotated[str, Field(min_length=1)]
    comment: Annotated[str, Field(max_length=256)] | None = None
    is_hidden: bool | None = None
    max_depth: Annotated[int, Field(ge=0, le=3)] | None = None
```

**Fields**:

| Field       | Type      | Required | Constraints   | Description                                         |
| ----------- | --------- | -------- | ------------- | --------------------------------------------------- |
| `config_id` | `string`  | Yes      | Min 1 char    | Hash of the config to update                        |
| `comment`   | `string`  | No       | Max 256 chars | Comment text (without `#` prefix)                   |
| `is_hidden` | `boolean` | No       | -             | Whether the source is hidden from end users         |
| `max_depth` | `integer` | No       | 0-3           | Max nesting depth for source visibility propagation |

Only fields explicitly provided in the request are modified; omitted fields are left unchanged.

**Example**:

```json
{
  "config_id": "abc123def456",
  "comment": "Fast US Server - Los Angeles",
  "is_hidden": false,
  "max_depth": 2
}
```

**Notes**:

- If `comment` is provided as null/empty on the `/comments` endpoint, uses domain name as default
- Same config can have different comments in different subscriptions
- Comment is appended to config using `#` when resolving
- `CommentUpdateRequest` is deprecated in favor of this model, but is kept for backward compatibility

---

### UpsertUserRequest

Create or update user (internal use).

```python
class UpsertUserRequest(BaseModel):
    user_id: Annotated[int, Field(gt=0)]
```

**Fields**:

| Field     | Type      | Required | Constraints |
| --------- | --------- | -------- | ----------- |
| `user_id` | `integer` | Yes      | > 0         |

---

### ProviderConnectionRequest

Internal shape describing the target user for provider connection endpoints. Path parameter only — not sent as a request body on any current endpoint.

```python
class ProviderConnectionRequest(BaseModel):
    user_id: Annotated[int, Field(gt=0)]
```

**Fields**:

| Field     | Type      | Required | Description    | Constraints |
| --------- | --------- | -------- | -------------- | ----------- |
| `user_id` | `integer` | Yes      | Target user ID | > 0         |

---

## Response Models

### SourceOut

Represents a source in responses.

```python
class SourceOut(BaseModel):
    id: str
    source_type: SourceType
    data: str
    order_index: int
    is_hidden: bool = False
    max_depth: int = 3
    created_at: datetime
    updated_at: datetime
```

**Fields**:

| Field         | Type       | Description                                               |
| ------------- | ---------- | --------------------------------------------------------- |
| `id`          | `string`   | Source hash (unique identifier)                           |
| `source_type` | `enum`     | Type: CONFIG, EXTERNAL_URL, or INTERNAL_TOKEN             |
| `data`        | `string`   | Full source data (config URI, URL, or token reference)    |
| `order_index` | `integer`  | Display order (0-indexed)                                 |
| `is_hidden`   | `boolean`  | Whether the source is hidden from end users               |
| `max_depth`   | `integer`  | Max nesting depth for source visibility propagation (0-3) |
| `created_at`  | `datetime` | ISO 8601 creation timestamp                               |
| `updated_at`  | `datetime` | ISO 8601 last update timestamp                            |

**Example**:

```json
{
  "id": "a1b2c3d4e5f6",
  "source_type": "config",
  "data": "vless://uuid@server:port?encryption=none#Server1",
  "order_index": 0,
  "is_hidden": false,
  "max_depth": 3,
  "created_at": "2026-04-27T10:00:00Z",
  "updated_at": "2026-04-27T10:00:00Z"
}
```

---

### SubscriptionListItem

Subscription in list view (without sources).

```python
class SubscriptionListItem(BaseModel):
    token: str
    name: str
    provider_name: str | None
    description: str | None
    sources_count: int
    created_at: datetime
    updated_at: datetime
```

**Fields**:

| Field           | Type           | Description                                               |
| --------------- | -------------- | --------------------------------------------------------- |
| `token`         | `string`       | Unique subscription token                                 |
| `name`          | `string`       | Subscription name                                         |
| `provider_name` | `string\|null` | Name of the managing provider, or `null` for self-service |
| `description`   | `string\|null` | Optional description                                      |
| `sources_count` | `integer`      | Total number of resolved configs                          |
| `created_at`    | `datetime`     | Creation timestamp                                        |
| `updated_at`    | `datetime`     | Last update timestamp                                     |

**Example**:

```json
{
  "token": "abc123xyz456",
  "name": "My VPN",
  "provider_name": null,
  "description": "Personal collection",
  "sources_count": 25,
  "created_at": "2026-04-27T10:00:00Z",
  "updated_at": "2026-04-27T12:30:00Z"
}
```

---

### SubscriptionResponse

Complete subscription details with sources.

```python
class SubscriptionResponse(BaseModel):
    token: str
    name: str
    provider_name: str | None
    description: str | None
    sources: list[SourceOut]
    sources_count: int
    created_at: datetime
    updated_at: datetime
```

**Fields**:
All fields from `SubscriptionListItem` plus:

| Field     | Type               | Description         |
| --------- | ------------------ | ------------------- |
| `sources` | `array[SourceOut]` | Full source details |

**Example**:

```json
{
  "token": "abc123xyz456",
  "name": "My VPN",
  "provider_name": null,
  "description": "Personal collection",
  "sources": [
    {
      "id": "hash1",
      "source_type": "config",
      "data": "vless://...",
      "order_index": 0,
      "is_hidden": false,
      "max_depth": 3,
      "created_at": "2026-04-27T10:00:00Z",
      "updated_at": "2026-04-27T10:00:00Z"
    }
  ],
  "sources_count": 25,
  "created_at": "2026-04-27T10:00:00Z",
  "updated_at": "2026-04-27T12:30:00Z"
}
```

---

### RefreshSubscriptionResponse

Result of subscription refresh operation.

```python
class RefreshSubscriptionResponse(BaseModel):
    refreshed: int
    failed: int
    skipped: int
    total: int
    message: str
    errors: list[str] = []
```

**Fields**:

| Field       | Type            | Description                              |
| ----------- | --------------- | ---------------------------------------- |
| `refreshed` | `integer`       | Successfully refreshed sources           |
| `failed`    | `integer`       | Sources that failed to refresh           |
| `skipped`   | `integer`       | Sources skipped (CONFIG, INTERNAL_TOKEN) |
| `total`     | `integer`       | Total sources processed                  |
| `message`   | `string`        | Status message                           |
| `errors`    | `array[string]` | Error messages for failed sources        |

**Example**:

```json
{
  "refreshed": 3,
  "failed": 1,
  "skipped": 2,
  "total": 6,
  "message": "Refresh completed with some failures",
  "errors": ["https://dead-provider.com/sub: Connection timeout"]
}
```

---

### ResolvedConfig

Resolved individual proxy config, produced by the resolver during subscription resolution (internal).

```python
class ResolvedConfig(BaseModel):
    hash: str
    config: str
    is_hidden: bool | None = None
    max_depth: int | None = 3
```

**Fields**:

| Field       | Type            | Description                                             |
| ----------- | --------------- | ------------------------------------------------------- |
| `hash`      | `string`        | Config hash (unique identifier)                         |
| `config`    | `string`        | Full proxy config URI, with comment appended if present |
| `is_hidden` | `boolean\|null` | Whether this config is hidden from end users            |
| `max_depth` | `integer\|null` | Max nesting depth inherited from the originating source |

**Notes**:

- Configs marked `is_hidden=true` are excluded from the final resolved subscription text (see `GET /sub/{token}`)
- `max_depth` controls how deep the resolver follows `INTERNAL_TOKEN` sources before stopping

---

### MeResponse

Returned by `GET /api/v1/me`.

```python
class MeResponse(BaseModel):
    user_id: int
    is_active: bool
```

**Fields**:

| Field       | Type      | Description                        |
| ----------- | --------- | ---------------------------------- |
| `user_id`   | `integer` | User identifier                    |
| `is_active` | `boolean` | Whether the user account is active |

**Example**:

```json
{
  "user_id": 12345,
  "is_active": true
}
```

---

### ConnectionResponse

Authorized (or authorizable) provider connection for the current user. Returned by `GET /api/v1/me/connections/{provider_name}`, `POST /api/v1/me/connections/{provider_name}/approve`, `POST /api/v1/me/connections/{provider_name}/reject`, and as list items in `ConnectionsResponse`.

```python
class ConnectionResponse(BaseModel):
    provider_name: str
    provider_url: str | None
    is_authorized: bool
    status: ProviderAuthorizationStatus | None = None
```

**Fields**:

| Field           | Type           | Description                                                                            | Constraints    |
| --------------- | -------------- | -------------------------------------------------------------------------------------- | -------------- |
| `provider_name` | `string`       | Provider name                                                                          | 4–16 chars     |
| `provider_url`  | `string\|null` | Provider API URL                                                                       | ≤ 255 chars    |
| `is_authorized` | `boolean`      | Whether the provider is currently authorized (`true` only when `status` is `approved`) |                |
| `status`        | `enum\|null`   | `pending`, `approved`, `revoked`, or `null` if no authorization exists yet             | default `null` |

**Example**:

```json
{
  "provider_name": "vpn123",
  "provider_url": "https://vpn123.example.com",
  "is_authorized": true,
  "status": "approved"
}
```

---

### ConnectionsResponse

Returned by `GET /api/v1/me/connections`. Only `pending` and `approved` connections are included — `revoked` authorizations are excluded.

```python
class ConnectionsResponse(BaseModel):
    connections: list[ConnectionResponse]
```

**Fields**:

| Field         | Type                        | Description                                             |
| ------------- | --------------------------- | ------------------------------------------------------- |
| `connections` | `array[ConnectionResponse]` | Provider connections authorized or pending for the user |

**Example**:

```json
{
  "connections": [
    {
      "provider_name": "vpn123",
      "provider_url": "https://vpn123.example.com",
      "is_authorized": true,
      "status": "approved"
    }
  ]
}
```

---

### ProviderConnectionResponse

Returned by `GET /api/v1/providers/{user_id}` and `POST /api/v1/providers/{user_id}/revoke`.

```python
class ProviderConnectionResponse(BaseModel):
    user_id: int
    status: ProviderAuthorizationStatus  # "pending" | "approved" | "revoked"
```

**Fields**:

| Field     | Type      | Description                         |
| --------- | --------- | ----------------------------------- |
| `user_id` | `integer` | User ID                             |
| `status`  | `enum`    | `pending`, `approved`, or `revoked` |

**Example**:

```json
{
  "user_id": 12345,
  "status": "approved"
}
```

---

### ProviderConnectionCreateResponse

Returned by `POST /api/v1/providers/{user_id}`. Extends `ProviderConnectionResponse` with a `connection_link` for the user to open and confirm the connection.

```python
class ProviderConnectionCreateResponse(ProviderConnectionResponse):
    connection_link: str | None
```

**Fields**:
All fields from `ProviderConnectionResponse` plus:

| Field             | Type           | Description                                                                  |
| ----------------- | -------------- | ---------------------------------------------------------------------------- |
| `connection_link` | `string\|null` | Link for the user to confirm the connection. `null` once already `approved`. |

**Example** (unknown user — HMAC-signed invite link):

```json
{
  "user_id": 12345,
  "status": "pending",
  "connection_link": "https://t.me/v2hubot?start=conn_3f9a1c7e0b4d2f6a8e1c9b3d_vpn123"
}
```

**Example** (known user — deep link, or already approved):

```json
{
  "user_id": 12345,
  "status": "approved",
  "connection_link": null
}
```

---

### ProviderConnectionDeleteResponse

Returned by `DELETE /api/v1/providers/{user_id}`.

```python
class ProviderConnectionDeleteResponse(BaseModel):
    detail: str
```

**Fields**:

| Field    | Type     | Description              |
| -------- | -------- | ------------------------ |
| `detail` | `string` | Operation result message |

**Example**:

```json
{
  "detail": "Provider connection deleted"
}
```

---

## Admin Models

### UserCreateRequest

Admin request to create user.

```python
class UserCreateRequest(AdminBaseModel):
    user_id: Annotated[int, Field(gt=0)]
```

**Fields**:

| Field     | Type      | Required | Constraints |
| --------- | --------- | -------- | ----------- |
| `user_id` | `integer` | Yes      | > 0         |

**Example**:

```json
{
  "user_id": 12345
}
```

---

### UserResponse

User account information.

```python
class UserResponse(AdminBaseModel):
    user_hash: str
    user_id: int
    api_token: str
    is_active: bool
```

**Fields**:

| Field       | Type      | Description                                 |
| ----------- | --------- | ------------------------------------------- |
| `user_hash` | `string`  | SHA-256 hash of user credentials            |
| `user_id`   | `integer` | External user ID                            |
| `api_token` | `string`  | Full API token (format: `{user_id}:{hash}`) |
| `is_active` | `boolean` | Account active status                       |

**Example**:

```json
{
  "user_hash": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "user_id": 12345,
  "api_token": "0i9u8y7t6r5e4w3q2p1",
  "is_active": true
}
```

---

### UserCreateResponse

Response after user creation.

```python
class UserCreateResponse(AdminBaseModel):
    user_hash: str
    user_id: int
    api_token: str
    is_active: bool
```

Same structure as `UserResponse`.

---

### UserStatusUpdateRequest

Update user account status.

```python
class UserStatusUpdateRequest(AdminBaseModel):
    is_active: bool
```

**Fields**:

| Field       | Type      | Required |
| ----------- | --------- | -------- |
| `is_active` | `boolean` | Yes      |

**Example**:

```json
{
  "is_active": false
}
```

---

### TokenRefreshRequest

Request to refresh user token.

```python
class TokenRefreshRequest(AdminBaseModel):
    user_id: Annotated[int, Field(gt=0)]
```

**Fields**:

| Field     | Type      | Required | Constraints |
| --------- | --------- | -------- | ----------- |
| `user_id` | `integer` | Yes      | > 0         |

---

### TokenRefreshResponse

New token after refresh.

```python
class TokenRefreshResponse(AdminBaseModel):
    user_id: int
    new_api_token: str
```

**Fields**:

| Field           | Type      | Description   |
| --------------- | --------- | ------------- |
| `user_id`       | `integer` | User ID       |
| `new_api_token` | `string`  | New API token |

**Example**:

```json
{
  "user_id": 12345,
  "new_api_token": "0i9u8y7t6r5e4w3q2p1"
}
```

---

### IPBanRequest

Request to ban an IP address.

```python
class IPBanRequest(AdminBaseModel):
    ip_address: Annotated[str, Field(min_length=7, max_length=45)]
    duration_seconds: Annotated[int, Field(gt=0)] | None = None
```

**Fields**:

| Field              | Type      | Required | Constraints           |
| ------------------ | --------- | -------- | --------------------- |
| `ip_address`       | `string`  | Yes      | Valid IPv4/IPv6       |
| `duration_seconds` | `integer` | No       | > 0, null = permanent |

**Example**:

```json
{
  "ip_address": "192.168.1.100",
  "duration_seconds": 3600
}
```

---

### IPBanStatusResponse

IP ban status information.

```python
class IPBanStatusResponse(AdminBaseModel):
    ip_address: str
    is_banned: bool
    banned_until: datetime | None
    remaining_seconds: int | None
```

**Fields**:

| Field               | Type             | Description                            |
| ------------------- | ---------------- | -------------------------------------- |
| `ip_address`        | `string`         | IP address                             |
| `is_banned`         | `boolean`        | Whether IP is banned                   |
| `banned_until`      | `datetime\|null` | Ban expiration (null = permanent)      |
| `remaining_seconds` | `integer\|null`  | Seconds until unban (null = permanent) |

**Example**:

```json
{
  "ip_address": "192.168.1.100",
  "is_banned": true,
  "banned_until": "2026-04-27T11:00:00Z",
  "remaining_seconds": 1800
}
```

---

### IPBanEntry

Single ban list entry.

```python
class IPBanEntry(AdminBaseModel):
    ip_address: str
    banned_until: datetime | None
```

**Example**:

```json
{
  "ip_address": "192.168.1.100",
  "banned_until": "2026-04-27T11:00:00Z"
}
```

---

### IPBanListResponse

List of banned IPs.

```python
class IPBanListResponse(AdminBaseModel):
    entries: list[IPBanEntry]
    total: int
```

**Fields**:

| Field     | Type                | Description         |
| --------- | ------------------- | ------------------- |
| `entries` | `array[IPBanEntry]` | List of ban entries |
| `total`   | `integer`           | Total count         |

**Example**:

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

---

### IPUnbanRequest

Request to unban an IP.

```python
class IPUnbanRequest(AdminBaseModel):
    ip_address: Annotated[str, Field(min_length=7, max_length=45)]
```

**Fields**:

| Field        | Type     | Required |
| ------------ | -------- | -------- |
| `ip_address` | `string` | Yes      |

---

### IPUnbanResponse

Result of unban operation.

```python
class IPUnbanResponse(AdminBaseModel):
    ip_address: str
    was_banned: bool
    message: str
```

**Fields**:

| Field        | Type      | Description                      |
| ------------ | --------- | -------------------------------- |
| `ip_address` | `string`  | IP address                       |
| `was_banned` | `boolean` | Whether IP was previously banned |
| `message`    | `string`  | Result message                   |

**Example**:

```json
{
  "ip_address": "192.168.1.100",
  "was_banned": true,
  "message": "IP unbanned successfully"
}
```

---

### WhitelistAddRequest

Add IP to whitelist.

```python
class WhitelistAddRequest(AdminBaseModel):
    ip_address: Annotated[str, Field(min_length=7, max_length=45)]
    description: Annotated[str, Field(max_length=255)] | None = None
```

**Fields**:

| Field         | Type     | Required | Constraints          |
| ------------- | -------- | -------- | -------------------- |
| `ip_address`  | `string` | Yes      | Valid IPv4/IPv6/CIDR |
| `description` | `string` | No       | Max 255 chars        |

**Example**:

```json
{
  "ip_address": "10.0.0.0/24",
  "description": "Office network"
}
```

---

### WhitelistEntry

Single whitelist entry.

```python
class WhitelistEntry(AdminBaseModel):
    ip_address: str
    description: str | None
    added_at: datetime
```

**Example**:

```json
{
  "ip_address": "10.0.0.0/24",
  "description": "Office network",
  "added_at": "2026-04-20T10:00:00Z"
}
```

---

### WhitelistListResponse

List of whitelisted IPs.

```python
class WhitelistListResponse(AdminBaseModel):
    entries: list[WhitelistEntry]
    total: int
```

**Example**:

```json
{
  "entries": [
    {
      "ip_address": "10.0.0.0/24",
      "description": "Office network",
      "added_at": "2026-04-20T10:00:00Z"
    }
  ],
  "total": 1
}
```

---

### WhitelistRemoveRequest

Remove IP from whitelist.

```python
class WhitelistRemoveRequest(AdminBaseModel):
    ip_address: Annotated[str, Field(min_length=7, max_length=45)]
```

---

### WhitelistRemoveResponse

Result of whitelist removal.

```python
class WhitelistRemoveResponse(AdminBaseModel):
    ip_address: str
    was_whitelisted: bool
    message: str
```

**Example**:

```json
{
  "ip_address": "10.0.0.0/24",
  "was_whitelisted": true,
  "message": "IP removed from whitelist"
}
```

---

### WhitelistAddResponse

Result of whitelist addition.

```python
class WhitelistAddResponse(AdminBaseModel):
    ip_address: str
    description: str | None
    message: str
```

**Example**:

```json
{
  "ip_address": "10.0.0.0/24",
  "description": "Office network",
  "message": "IP added to whitelist successfully"
}
```

---

### ProviderCreateRequest

Request to create a new provider account.

```python
class ProviderCreateRequest(AdminBaseModel):
    owner_hash: str
    provider_name: str
    provider_url: str | None = None
```

**Fields**:

| Field           | Type           | Required | Description                                                                                                                                     |
| --------------- | -------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `owner_hash`    | `string`       | Yes      | Hash identifying the provider's owner                                                                                                           |
| `provider_name` | `string`       | Yes      | Provider display name. 4–16 characters; lowercase a-z, digits 0-9, and - only. Hyphens cannot be leading, trailing, or consecutive.             |
| `provider_url`  | `string\|null` | No       | Provider URL (e.g. bot link) . Provider URLs must use a safe HTTP(S) URL without localhost, private, link-local, or other restricted addresses. |

**Example**:

```json
{
  "owner_hash": "a1b2c3d4e5f6...",
  "provider_name": "vpn123",
  "provider_url": "https://t.me/examplebot"
}
```

---

### ProviderResponse

Provider account details, including the API token.

```python
class ProviderResponse(AdminBaseModel):
    provider_hash: str
    owner_hash: str
    provider_name: str
    api_token: str
    provider_url: str | None
    is_active: bool
```

**Fields**:

| Field           | Type           | Description                |
| --------------- | -------------- | -------------------------- |
| `provider_hash` | `string`       | Generated provider hash    |
| `owner_hash`    | `string`       | Hash identifying the owner |
| `provider_name` | `string`       | Provider display name      |
| `api_token`     | `string`       | Provider's API token       |
| `provider_url`  | `string\|null` | Provider URL               |
| `is_active`     | `boolean`      | Account active status      |

**Example**:

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

---

### ProviderCreateResponse

Same shape as `ProviderResponse`, returned by `POST /api/v1/admin/providers`.

```python
class ProviderCreateResponse(ProviderResponse):
    pass
```

---

### AllProvidersResponse

Mapping of all provider names to their hashes.

```python
class AllProvidersResponse(AdminBaseModel):
    provider_hashes: dict[str, str]
```

**Fields**:

| Field             | Type                  | Description                              |
| ----------------- | --------------------- | ---------------------------------------- |
| `provider_hashes` | `dict[string,string]` | Mapping of provider name → provider hash |

**Example**:

```json
{
  "provider_hashes": {
    "Provider A": "a1b2c3d4e5f6...",
    "Provider B": "q9w8e7r6t5y4..."
  }
}
```

---

### ProviderStatusUpdateRequest

Request to enable or disable a provider account.

```python
class ProviderStatusUpdateRequest(AdminBaseModel):
    is_active: bool
```

**Fields**:

| Field       | Type      | Required | Description        |
| ----------- | --------- | -------- | ------------------ |
| `is_active` | `boolean` | Yes      | New account status |

---

### ProviderURLUpdateRequest

Request to update a provider's URL.

```python
class ProviderURLUpdateRequest(AdminBaseModel):
    provider_url: str | None
```

**Fields**:

| Field          | Type           | Required | Description                                                                                                                        |
| -------------- | -------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `provider_url` | `string\|null` | Yes      | New provider URL. Provider URLs must use a safe HTTP(S) URL without localhost, private, link-local, or other restricted addresses. |

---

### ProviderNameUpdateRequest

Request to update a provider's name.

```python
class ProviderNameUpdateRequest(AdminBaseModel):
    provider_name: str
```

**Fields**:

| Field           | Type     | Required | Description                                                                                                                           |
| --------------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `provider_name` | `string` | Yes      | New provider name. 4–16 characters; lowercase `a-z`, digits `0-9`, and `-` only. Hyphens cannot be leading, trailing, or consecutive. |

---

### ProviderTokenRefreshRequest

Request to refresh a provider's API token.

```python
class ProviderTokenRefreshRequest(AdminBaseModel):
    provider_hash: str
```

**Fields**:

| Field           | Type     | Required | Description   |
| --------------- | -------- | -------- | ------------- |
| `provider_hash` | `string` | Yes      | Provider hash |

**Example**:

```json
{
  "provider_hash": "a1b2c3d4e5f6..."
}
```

---

### ProviderTokenRefreshResponse

New token issued for a provider.

```python
class ProviderTokenRefreshResponse(AdminBaseModel):
    provider_hash: str
    new_api_token: str
```

**Fields**:

| Field           | Type     | Description           |
| --------------- | -------- | --------------------- |
| `provider_hash` | `string` | Provider hash         |
| `new_api_token` | `string` | Newly generated token |

**Example**:

```json
{
  "provider_hash": "a1b2c3d4e5f6...",
  "new_api_token": "0i9u8y7t6r5e4w3q2p1"
}
```

---

### ProviderAuthorizationInfoResponse

Returned by all four `/api/v1/admin/providers/auth/*` endpoints, describing the current state of a provider ↔ user authorization.

```python
class ProviderAuthorizationInfoResponse(AdminBaseModel):
    provider_name: str
    provider_url: str | None
    user_id: int
    status: ProviderAuthorizationStatus | None = None
```

**Fields**:

| Field           | Type           | Required | Description                                                                    | Constraints    |
| --------------- | -------------- | -------- | ------------------------------------------------------------------------------ | -------------- |
| `provider_name` | `string`       | Yes      | Provider name                                                                  |                |
| `provider_url`  | `string\|null` | Yes      | Provider URL                                                                   |                |
| `user_id`       | `integer`      | Yes      | User ID                                                                        | 1–999999999999 |
| `status`        | `enum\|null`   | No       | `pending`, `approved`, `revoked`, or `null` if no authorization row exists yet | default `null` |

**Example**:

```json
{
  "provider_name": "vpn123",
  "provider_url": "https://vpn123.example.com",
  "user_id": 12345,
  "status": "pending"
}
```

---

### ProviderAuthorizationBaseRequest

Shared base for the two admin decision endpoints (`/approve`, `/reject`) below — not used directly as a request body itself.

```python
class ProviderAuthorizationBaseRequest(AdminBaseModel):
    user_id: int
    provider_name: str
```

**Fields**:

| Field           | Type      | Required | Description    | Constraints                              |
| --------------- | --------- | -------- | -------------- | ---------------------------------------- |
| `user_id`       | `integer` | Yes      | Target user ID | 1–999999999999                           |
| `provider_name` | `string`  | Yes      | Provider name  | 4–16 chars, `^[a-z0-9]+(?:-[a-z0-9]+)*$` |

---

### ProviderAuthorizationRequest

Request body for `POST /api/v1/admin/providers/auth`. Extends `ProviderAuthorizationBaseRequest` with an optional `hmac`.

```python
class ProviderAuthorizationRequest(ProviderAuthorizationBaseRequest):
    hmac: str | None = None
```

**Fields**:
All fields from `ProviderAuthorizationBaseRequest` plus:

| Field  | Type           | Required | Description                                                                                     | Constraints               |
| ------ | -------------- | -------- | ----------------------------------------------------------------------------------------------- | ------------------------- |
| `hmac` | `string\|null` | No       | HMAC from a `conn_{hmac}_{provider_name}` invite link; required to create a _new_ authorization | Exactly 24 hex characters |

**Example**:

```json
{
  "user_id": 12345,
  "provider_name": "vpn123",
  "hmac": "3f9a1c7e0b4d2f6a8e1c9b3d"
}
```

---

### ProviderAuthorizationDecisionRequest

Request body for `POST /api/v1/admin/providers/auth/approve` and `POST /api/v1/admin/providers/auth/reject`. Identical shape to `ProviderAuthorizationBaseRequest` (no extra fields).

```python
class ProviderAuthorizationDecisionRequest(ProviderAuthorizationBaseRequest):
    pass
```

**Example**:

```json
{
  "user_id": 12345,
  "provider_name": "vpn123"
}
```

---

## Enumerations

### SourceType

Classification of subscription sources.

```python
class SourceType(str, Enum):
    CONFIG = "config"
    EXTERNAL_URL = "external_url"
    INTERNAL_TOKEN = "internal_token"
```

**Values**:

| Value            | Description                       | Example                            |
| ---------------- | --------------------------------- | ---------------------------------- |
| `CONFIG`         | Direct proxy configuration URI    | `vless://uuid@server:port`         |
| `EXTERNAL_URL`   | External subscription URL         | `https://provider.com/sub`         |
| `INTERNAL_TOKEN` | Reference to another subscription | `https://yourdomain.com/sub/token` |

**Detection Logic**:

```python
def detect_source_type(source: str, domain: str) -> SourceType:
    if source.startswith(tuple(ProxyProtocol)):
        return SourceType.CONFIG
    elif source.startswith(f"https://{domain}/sub/"):
        return SourceType.INTERNAL_TOKEN
    else:
        return SourceType.EXTERNAL_URL
```

---

### ProxyProtocol

Supported proxy protocols.

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

**Protocols**:

| Protocol    | URI Prefix     | Common Ports |
| ----------- | -------------- | ------------ |
| VLESS       | `vless://`     | 443, 80      |
| VMess       | `vmess://`     | 443, 80      |
| Trojan      | `trojan://`    | 443          |
| Shadowsocks | `ss://`        | 8388         |
| Hysteria    | `hysteria://`  | 36712        |
| Hysteria 2  | `hysteria2://` | 443          |
| TUIC        | `tuic://`      | 443          |

---

### ProviderAuthorizationStatus

Status of a provider ↔ user authorization relationship.

```python
class ProviderAuthorizationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REVOKED = "revoked"
```

**Values**:

| Value      | Description                                                                                                           |
| ---------- | --------------------------------------------------------------------------------------------------------------------- |
| `PENDING`  | Connection requested but not yet confirmed; the default for newly created authorizations. Provider has no access yet. |
| `APPROVED` | Provider is authorized to manage this user's subscriptions                                                            |
| `REVOKED`  | Authorization has been revoked; provider can no longer act for the user                                               |

**Lifecycle**:

```
PENDING ──(approve)──> APPROVED ──(revoke)──> REVOKED
   ^                                              │
   └──────────────(reinitialize/re-invite)────────┘
```

A new authorization row defaults to `PENDING` (both at the ORM level and, since migration `0004`, at the database schema level) and requires an explicit approval step — via `POST /api/v1/providers/{user_id}` followed by user confirmation, or the admin `POST /api/v1/admin/providers/auth/approve` endpoint — before it becomes `APPROVED`. It is never created as `APPROVED` implicitly.

---

## Validation Rules

### String Constraints

| Field                    | Min Length | Max Length | Pattern               |
| ------------------------ | ---------- | ---------- | --------------------- |
| Subscription name        | 1          | 64         | Any (unique per user) |
| Subscription description | 0          | 64         | Any                   |
| Config comment           | 0          | 256        | Any                   |
| IP address               | 7          | 45         | IPv4/IPv6/CIDR        |
| Whitelist description    | 0          | 255        | Any                   |

### Numeric Constraints

| Field                    | Min | Max | Default          |
| ------------------------ | --- | --- | ---------------- |
| User ID                  | 1   | -   | -                |
| Ban duration             | 1   | -   | null (permanent) |
| Sources per subscription | 0   | 150 | -                |
| Subscriptions per user   | 0   | 3   | -                |
| Nesting depth            | 0   | 3   | -                |

### Custom Validators

#### Source Normalization

`sources` fields accept a mix of plain strings and `SourceCreateRequest` objects. Both forms are normalized to objects before further validation:

```python
def _normalize_sources(values):
    cleaned = []
    seen = set()

    for item in values:
        if isinstance(item, str):
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append({"data": normalize_source(key, settings.max_comment_length)})
        elif isinstance(item, dict):
            key = (item.get("data") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            item = item.copy()
            item["data"] = normalize_source(key, settings.max_comment_length)
            cleaned.append(item)
        else:
            raise TypeError("Each source must be either a string or an object")

    return cleaned
```

- Deduplication is keyed on the (stripped) `data` value, preserving first occurrence order
- String items become `{"data": "<normalized string>"}` with default `is_hidden`/`max_depth`
- `SourcesRemoveRequest.source_ids` uses the simpler `_clean_sources` helper (plain string list dedup/strip only)

#### At Least One Field

```python
@model_validator(mode='after')
def check_at_least_one_field(self):
    if self.name is None and self.description is None:
        raise ValueError("At least one field must be provided")
    return self
```

---

## Type Aliases

Common type aliases used throughout the codebase:

```python
from typing import Annotated
from pydantic import Field

# Bounded strings
ShortString = Annotated[str, Field(max_length=64)]
MediumString = Annotated[str, Field(max_length=255)]
LongString = Annotated[str, Field(max_length=512)]

# IDs
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]

# Lists
SourceList = Annotated[list[SourceCreateRequest], Field(max_length=150)]
IPAddress = Annotated[str, Field(min_length=7, max_length=45)]
```

---

## JSON Schema Examples

### Complete Request/Response Cycle

**Request: Create Subscription**

```json
{
  "name": "My VPN Collection",
  "description": "Personal servers and providers",
  "sources": [
    "vless://uuid@server1.com:443?encryption=none&security=tls&sni=server1.com&type=tcp#Server1",
    "vmess://eyJhZGQiOi...base64...#Server2",
    "https://provider.com/subscription",
    {
      "data": "https://api.example.com/sub/another-token",
      "is_hidden": true,
      "max_depth": 1
    }
  ]
}
```

**Response: Subscription Created**

```json
{
  "token": "abc123xyz456",
  "name": "My VPN Collection",
  "description": "Personal servers and providers",
  "sources": [
    {
      "id": "d5e6f7a8b9c0",
      "source_type": "config",
      "data": "vless://uuid@server1.com:443?encryption=none&security=tls&sni=server1.com&type=tcp#Server1",
      "order_index": 0,
      "is_hidden": false,
      "max_depth": 3,
      "created_at": "2026-04-27T10:00:00.123456Z",
      "updated_at": "2026-04-27T10:00:00.123456Z"
    },
    {
      "id": "a1b2c3d4e5f6",
      "source_type": "config",
      "data": "vmess://eyJhZGQiOi...base64...#Server2",
      "order_index": 1,
      "is_hidden": false,
      "max_depth": 3,
      "created_at": "2026-04-27T10:00:00.234567Z",
      "updated_at": "2026-04-27T10:00:00.234567Z"
    },
    {
      "id": "x7y8z9a0b1c2",
      "source_type": "external_url",
      "data": "https://provider.com/subscription",
      "order_index": 2,
      "is_hidden": false,
      "max_depth": 3,
      "created_at": "2026-04-27T10:00:00.345678Z",
      "updated_at": "2026-04-27T10:00:00.345678Z"
    },
    {
      "id": "m3n4o5p6q7r8",
      "source_type": "internal_token",
      "data": "https://api.example.com/sub/another-token",
      "order_index": 3,
      "is_hidden": true,
      "max_depth": 1,
      "created_at": "2026-04-27T10:00:00.456789Z",
      "updated_at": "2026-04-27T10:00:00.456789Z"
    }
  ],
  "sources_count": 47,
  "created_at": "2026-04-27T10:00:00.123456Z",
  "updated_at": "2026-04-27T10:00:00.123456Z"
}
```

**API Version**: 1.1.2
**Last Updated**: August 25, 2026
