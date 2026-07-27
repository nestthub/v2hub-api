# v2hub-api

> **Professional VPN subscription management and aggregation system**

A production-ready FastAPI-based service for managing, aggregating, and serving VPN proxy subscriptions with multi-source support, intelligent caching, and comprehensive security features.

### 🌐 Part of the [V2Hub Ecosystem](https://github.com/nestthub/nestthub/blob/main/ecosystems/v2hub/README.md)

This package is one component of V2Hub — see the full project overview, architecture, and all related repositories.

---

## 🌟 Features

### Core Functionality

- **Multi-Source Aggregation**: Combine proxy configs from direct URIs, external subscription URLs, and internal references
- **Per-Subscription Comments**: Add custom comments to individual configs within each subscription
- **Per-Source Visibility & Nesting Control**: Hide individual sources from resolved output and limit how deep internal references are followed (`is_hidden`, `max_depth`)
- **Recursive Resolution**: Automatically resolve nested subscription references with circular detection
- **Two-Tier Caching**: Redis + PostgreSQL for optimal performance and reliability
- **Background Refresh**: Celery workers automatically update external sources every 15 minutes

### Security & Protection

- **HMAC Signature Verification**: Secure admin endpoints with SHA-256 request signing
- **IP Whitelisting**: Restrict admin access to authorized IP addresses
- **Rate Limiting**: Configurable per-endpoint rate limits with Redis-backed counters
- **Ban System**: Automatic and manual IP banning with time-based expiration
- **Security Headers**: HSTS, CSP, and other production-ready security headers

### Performance & Reliability

- **Async Architecture**: Full async/await support with SQLAlchemy 2.0 and asyncpg
- **Connection Pooling**: Optimized database connection management
- **Graceful Degradation**: Continues operation even if Redis is unavailable
- **Health Checks**: Built-in health monitoring for all services
- **Production-Ready**: Docker Compose setup with Nginx reverse proxy

---

## 📋 Table of Contents

- [Quick Start](#-quick-start)
- [Architecture](#-architecture)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [API Documentation](#-api-documentation)
- [Usage Examples](#-usage-examples)
- [Monitoring](#-monitoring)
- [Development](#-development)
- [Deployment](#-deployment)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development)
- PostgreSQL 16+ (if running without Docker)
- Redis 7+ (if running without Docker)

### Run with Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/nestthub/v2hub-api.git
cd v2hub-api

# Create environment file
cp .env.example .env
# Edit .env with your configuration

# Start all services
docker-compose up -d

# Check service health
docker-compose ps

# View logs
docker-compose logs -f api
```

The API will be available at `http://localhost` (Nginx) or `http://localhost:8000` (direct API).

### Run Locally

```bash
# Install dependencies
pip install -e .

# Run database migrations
alembic upgrade head

# Start the API server
uvicorn v2hub_api.main:app --reload --host 0.0.0.0 --port 8000

# Start Celery worker (in another terminal)
celery -A worker.celery_app worker --loglevel=info

# Start Celery beat scheduler (in another terminal)
celery -A worker.celery_app beat --loglevel=info
```

---

## 🏗️ Architecture

### System Overview

```
┌─────────────┐
│   Nginx     │  ← Reverse proxy, SSL termination, /grafana/ proxy
└──────┬──────┘
       │
┌──────▼──────┐
│  FastAPI    │  ← Main API application
│  (Uvicorn)  │
└──────┬──────┘
       │
       ├─────────────────┬─────────────────┐
       │                 │                 │
┌──────▼──────┐   ┌──────▼──────┐   ┌─────▼─────┐
│ PostgreSQL  │   │    Redis    │   │  Celery   │
│   (Data)    │   │   (Cache)   │   │  Workers  │
└─────────────┘   └─────────────┘   └───────────┘

┌─────────────────────────────────────────────────┐
│              Monitoring Stack                   │
│  Prometheus → Grafana                           │
│  Docker logs → Alloy → Loki → Grafana           │
└─────────────────────────────────────────────────┘
```

### Technology Stack

| Component         | Technology     | Purpose                              |
| ----------------- | -------------- | ------------------------------------ |
| **API Framework** | FastAPI 0.136+ | High-performance async web framework |
| **Database**      | PostgreSQL 16  | Primary data storage                 |
| **Cache**         | Redis 7        | Fast caching and rate limiting       |
| **Task Queue**    | Celery 5.6     | Background jobs and scheduling       |
| **ORM**           | SQLAlchemy 2.0 | Async database access                |
| **Validation**    | Pydantic 2.13  | Request/response validation          |
| **HTTP Client**   | aiohttp 3.13   | Async external URL fetching          |
| **Migrations**    | Alembic 1.18   | Database schema management           |
| **Web Server**    | Uvicorn 0.45   | ASGI server                          |
| **Reverse Proxy** | Nginx 1.27     | Load balancing, SSL                  |
| **Metrics**       | Prometheus     | Metrics collection and storage       |
| **Logs**          | Loki + Alloy   | Log aggregation and shipping         |
| **Dashboards**    | Grafana        | Visualization and alerting           |

### Project Structure

```
v2hub-api/
├── src/
│   └── v2hub_api/
│       ├── api/
│       │   ├── dependencies.py          # FastAPI dependencies
│       │   └── endpoints/
│       │       ├── public.py            # Public endpoints (/sub/{token})
│       │       ├── subscriptions.py     # Subscription CRUD
│       │       └── admin.py             # Admin management
│       ├── core/
│       │   ├── config.py                # Settings & configuration
│       │   ├── enums.py                 # Enumerations
│       │   └── exceptions.py            # Custom exceptions
│       ├── db/
│       │   ├── models/                  # SQLAlchemy models
│       │   ├── repositories/            # Data access layer
│       │   └── session.py               # Database connection
│       ├── schemas/
│       │   ├── base_models/             # Pydantic models (user-facing)
│       │   └── admin_models/            # Pydantic models (admin)
│       ├── services/
│       │   ├── subscription_service.py  # Business logic
│       │   ├── resolver_service.py      # Subscription resolution
│       │   ├── cache_service.py         # Redis caching
│       │   ├── user_service.py          # User management
│       │   ├── ban_service.py           # IP banning
│       │   └── whitelist_service.py     # IP whitelisting
│       ├── middlewares/
│       │   ├── rate_limit_middleware.py # Rate limiting
│       │   └── security_headers_middleware.py  # Security headers
│       ├── utils/
│       │   ├── config_parser.py         # Proxy config parsing
│       │   ├── http_client.py           # HTTP client wrapper
│       │   ├── rate_limiter.py          # Redis-based rate limiting
│       │   ├── url_request_limiter.py   # External URL fetch limiting
│       │   └── url_validator.py         # URL / SSRF validation
│       ├── py.typed
│       └── main.py                      # Application entry point
├── worker/
│   ├── celery_app.py                    # Celery configuration
│   └── tasks/                           # Background tasks
├── alembic/
│   ├── env.py
│   └── versions/                        # Database migrations
├── monitoring/
│   ├── alloy/
│   │   └── config.alloy                 # Grafana Alloy log pipeline
│   ├── grafana/
│   │   └── datasources.yml              # Auto-provisioned datasources
│   ├── prometheus.yml                   # Scrape config
│   └── loki.yml                         # Log storage config
├── nginx/
│   ├── nginx.conf
│   ├── conf.d.templates/
│   │   └── api.conf.template            # Rendered via envsubst at container start
│   ├── conf-test.d/
│   │   └── api.conf                     # Domain-free config for local testing
│   ├── entrypoint/
│   │   └── 10-generate-limit-key-map.sh # Builds the rate-limit exemption map
│   └── grafana.htpasswd                 # Basic auth for /grafana/ (optional)
├── certbot-renew/
│   └── Dockerfile                       # SSL certificate renewal
├── .github/
│   └── workflows/
│       ├── ci.yml                       # Lint, type-check, tests, Docker build
│       └── deploy.yml                   # SSH deploy + migrations + health check
├── docs/
│   ├── API_DOCUMENTATION.md             # Complete API reference
│   ├── TYPES.md                         # Type reference
│   └── index.html
├── tests/                                # Test suite
├── serve_docs.py                         # Local docs server
├── docker-compose.yml                    # Docker orchestration
├── Dockerfile                            # Container definition
├── pyproject.toml                        # Project dependencies
├── alembic.ini                           # Alembic configuration
└── README.md                             # This file
```

### Data Flow

#### Subscription Resolution Flow

```
Client Request
      │
      ▼
┌─────────────────────┐
│  Public Endpoint    │  /sub/{token}
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Resolver Service   │  Recursive resolution engine
└──────────┬──────────┘
           │
           ├─── Check Redis Cache
           │
           ├─── Fetch from Database
           │
           ├─── Resolve INTERNAL_TOKEN references
           │         (recursive, with depth limit)
           │
           ├─── Fetch EXTERNAL_URL sources
           │         (with caching)
           │
           └─── Aggregate CONFIG sources
                      │
                      ▼
              ┌─────────────────┐
              │  Apply Comments │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ Base64 Encode   │
              └────────┬────────┘
                       │
                       ▼
                 Return to Client
```

---

## 🔧 Installation

### Docker Installation (Production)

1. **Clone the repository**:

   ```bash
   git clone https://github.com/nestthub/v2hub-api.git
   cd v2hub-api
   ```

2. **Configure environment**:

   ```bash
   cp .env.example .env
   nano .env  # Edit with your settings
   ```

3. **Start services**:

   ```bash
   docker-compose up -d
   ```

4. **Run migrations**:

   ```bash
   docker-compose exec api alembic upgrade head
   ```

5. **Verify installation**:
   ```bash
   curl http://localhost/health
   # Expected: {"status":"ok"}
   ```

### Local Development Installation

1. **Clone and setup**:

   ```bash
   git clone https://github.com/nestthub/v2hub-api.git
   cd v2hub-api
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**:

   ```bash
   pip install -e .
   ```

3. **Setup database**:

   ```bash
   # Create PostgreSQL database
   createdb v2hub

   # Run migrations
   alembic upgrade head
   ```

4. **Configure environment**:

   ```bash
   cp .env.example .env
   # Edit .env with local settings
   ```

5. **Start services**:

   ```bash
   # Terminal 1: API
   uvicorn v2hub_api.main:app --reload

   # Terminal 2: Celery Worker
   celery -A worker.celery_app worker --loglevel=info

   # Terminal 3: Celery Beat
   celery -A worker.celery_app beat --loglevel=info
   ```

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# ─────────────────────────────
# Core
# ─────────────────────────────
APP_NAME=v2hub
APP_VERSION=1.0.0
ENVIRONMENT=production
DEBUG=false

DOMAIN=YOURDOMAIN.com

# Comma-separated IPs exempt from nginx rate limiting (optional, e.g.
# a monitoring probe or internal health-checker). Consumed by
# nginx/entrypoint/10-generate-limit-key-map.sh at container start.
TRUSTED_NOLIMIT_IPS=

# ─────────────────────────────
# Server
# ─────────────────────────────
HOST=0.0.0.0
PORT=8000
WORKERS=2

# ─────────────────────────────
# Database (Docker service name)
# ─────────────────────────────
POSTGRES_PASSWORD=STRONG_PASSWORD
DATABASE_URL=postgresql+asyncpg://postgres:STRONG_PASSWORD@postgres:5432/v2hub
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
DB_POOL_TIMEOUT=30
DB_ECHO=false

# ─────────────────────────────
# Redis
# ─────────────────────────────
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
REDIS_TTL=600

# ─────────────────────────────
# Security
# ─────────────────────────────
SECRET_KEY=STRONG_PASSWORD
ADMIN_SECRET_KEY=STRONG_PASSWORD
API_TOKEN_LENGTH=32

ADMIN_ALLOWED_IPS=["127.0.0.1"]

# ─────────────────────────────
# Business rules
# ─────────────────────────────
MAX_NESTING_DEPTH=3
MAX_SUBSCRIPTIONS_PER_USER=3
MAX_CONFIGS_PER_SUBSCRIPTION=150
MAX_SOURCES_PER_SUBSCRIPTION=150

# ─────────────────────────────
# Fetching
# ─────────────────────────────
FETCH_TIMEOUT=3
FETCH_USER_AGENT=v2hub/1.0.0
FETCH_MAX_REDIRECTS=0

# ─────────────────────────────
# CORS
# ─────────────────────────────
CORS_ORIGINS=["https://YOURDOMAIN.com","https://www.YOURDOMAIN.com"]
CORS_CREDENTIALS=true
CORS_METHODS=["GET","POST","PUT","PATCH","DELETE","OPTIONS"]
CORS_HEADERS=["*"]

# ─────────────────────────────
# Logging
# ─────────────────────────────
LOG_LEVEL=INFO
LOG_FORMAT=%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

### Configuration Reference

| Category        | Variable                       | Default | Description                                         |
| --------------- | ------------------------------ | ------- | --------------------------------------------------- |
| **Limits**      | `MAX_SUBSCRIPTIONS_PER_USER`   | 3       | Max subscriptions per user                          |
|                 | `MAX_SOURCES_PER_SUBSCRIPTION` | 150     | Max sources per subscription                        |
|                 | `MAX_CONFIGS_PER_SUBSCRIPTION` | 150     | Max resolved configs                                |
|                 | `MAX_NESTING_DEPTH`            | 3       | Max depth for nested references                     |
| **Performance** | `DB_POOL_SIZE`                 | 10      | Database connection pool size                       |
|                 | `REDIS_TTL`                    | 600     | Cache TTL in seconds                                |
|                 | `FETCH_TIMEOUT`                | 3       | HTTP fetch timeout (seconds)                        |
| **Security**    | `API_TOKEN_LENGTH`             | 16      | Length of generated tokens                          |
|                 | `ADMIN_ALLOWED_IPS`            | -       | Comma-separated IP whitelist                        |
| **Rate Limits** | `PUBLIC_RPS`                   | 3       | Requests/second for public endpoints                |
|                 | `INTERNAL_WITH_TOKEN_RPS`      | 3       | Requests/second for authenticated                   |
|                 | `TRUSTED_NOLIMIT_IPS`          | -       | Comma-separated IPs exempt from nginx rate limiting |

---

## 📚 API Documentation

Comprehensive API documentation is available in [docs/API_DOCUMENTATION.md](./docs/API_DOCUMENTATION.md), with additional type reference in [docs/TYPES.md](./docs/TYPES.md).

A static rendering of the docs can also be served locally:

```bash
python serve_docs.py
```

### Quick Reference

**Base URL**: `https://api.example.com`

#### Public Endpoints

- `GET /sub/{token}` - Get resolved subscription (no auth required)

#### User Endpoints (require `API-Token` header)

- `POST /api/v1/subs` - Create subscription
- `GET /api/v1/subs` - List subscriptions
- `GET /api/v1/subs/{token}` - Get subscription details
- `PATCH /api/v1/subs/{token}` - Update subscription
- `DELETE /api/v1/subs/{token}` - Delete subscription
- `POST /api/v1/subs/{token}/sources` - Add sources
- `PUT /api/v1/subs/{token}/sources` - Replace sources
- `DELETE /api/v1/subs/{token}/sources` - Remove sources
- `PATCH /api/v1/subs/{token}/config` - Update config (comment, `is_hidden`, `max_depth`)
- `PATCH /api/v1/subs/{token}/comments` - Update config comment _(deprecated, use `/config` above)_
- `POST /api/v1/subs/{token}/refresh` - Refresh external sources

#### Admin Endpoints (require signature + IP whitelist)

- `POST /api/v1/admin/users` - Create user
- `GET /api/v1/admin/users/{user_id}` - Get user
- `DELETE /api/v1/admin/users/{user_id}` - Delete user
- `PATCH /api/v1/admin/users/{user_id}/status` - Update user status
- `POST /api/v1/admin/users/{user_id}/token/refresh` - Refresh token
- `POST /api/v1/admin/bans` - Ban IP
- `POST /api/v1/admin/unbans` - Unban IP
- `GET /api/v1/admin/bans` - List banned IPs
- `POST /api/v1/admin/whitelist` - Add to whitelist
- `DELETE /api/v1/admin/whitelist` - Remove from whitelist
- `GET /api/v1/admin/whitelist` - List whitelisted IPs

### Interactive Documentation

When running in debug mode (`DEBUG=true`), interactive API documentation is available at:

- **Scalar UI**: `http://localhost:8000/docs` (Modern, dark-themed)
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

---

## 💡 Usage Examples

### Creating and Using a Subscription

#### 1. Create User (Admin)

```bash
# Using curl with HMAC signature
timestamp=$(date +%s000)
body='{"user_id":12345}'
payload="${timestamp}POST/api/v1/admin/users${body}"
signature=$(echo -n "$payload" | openssl dgst -sha256 -hmac "$ADMIN_SECRET" | awk '{print $2}')

curl -X POST http://localhost/api/v1/admin/users \
  -H "Content-Type: application/json" \
  -H "X-Signature: $signature" \
  -H "X-Timestamp: $timestamp" \
  -d "$body"
```

**Response**:

```json
{
  "user_hash": "a1b2c3...",
  "user_id": 12345,
  "api_token": "12345:a1b2c3d4e5f6...",
  "is_active": true
}
```

#### 2. Create Subscription (User)

```bash
curl -X POST http://localhost/api/v1/subs \
  -H "API-Token: 12345:a1b2c3d4e5f6..." \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Servers",
    "description": "Personal collection",
    "sources": [
      "vless://uuid@server1.com:443?encryption=none&security=tls#Server1",
      "vmess://base64config#Server2",
      "https://provider.com/subscription"
    ]
  }'
```

**Response**:

```json
{
  "token": "abc123xyz",
  "name": "My Servers",
  "description": "Personal collection",
  "sources": [...],
  "sources_count": 15,
  "created_at": "2026-04-27T10:00:00Z",
  "updated_at": "2026-04-27T10:00:00Z"
}
```

#### 3. Get Subscription (Public)

```bash
curl http://localhost/sub/abc123xyz
```

The response is base64-encoded configs ready to import into VPN clients.

### Python Client Example

```python
import requests

class VPNClient:
    def __init__(self, base_url, api_token):
        self.base_url = base_url
        self.headers = {
            "API-Token": api_token,
            "Content-Type": "application/json"
        }

    def create_subscription(self, name, sources):
        response = requests.post(
            f"{self.base_url}/api/v1/subs",
            headers=self.headers,
            json={"name": name, "sources": sources}
        )
        return response.json()

    def add_sources(self, token, sources):
        response = requests.post(
            f"{self.base_url}/api/v1/subs/{token}/sources",
            headers=self.headers,
            json={"sources": sources}
        )
        return response.json()

# Usage
client = VPNClient("http://localhost", "12345:token...")

sub = client.create_subscription(
    name="My VPN",
    sources=["vless://...", "https://provider.com/sub"]
)

print(f"Created: {sub['token']}")
print(f"URL: http://localhost/sub/{sub['token']}")
```

---

## 📊 Monitoring

The monitoring stack runs as separate Docker services. All ports are internal — no monitoring service is exposed to the internet directly.

### Stack Overview

| Service    | Image             | Internal port | Description                           |
| ---------- | ----------------- | ------------- | ------------------------------------- |
| Prometheus | `prom/prometheus` | 9090          | Scrapes `/metrics` from the API       |
| Loki       | `grafana/loki`    | 3100          | Log storage, 7-day retention          |
| Alloy      | `grafana/alloy`   | 12345         | Log collector (successor to Promtail) |
| Grafana    | `grafana/grafana` | 3000          | Dashboards, exposed via nginx         |

### Accessing Grafana

Grafana is proxied through nginx at `/grafana/` and restricted by IP allowlist:

```
http://your-server/grafana/
```

Default credentials are configured via environment variables in `docker-compose.yml`:

```yaml
GF_SECURITY_ADMIN_USER=admin
GF_SECURITY_ADMIN_PASSWORD=your_password
GF_SERVER_ROOT_URL=http://your-server/grafana/
GF_SERVER_SERVE_FROM_SUB_PATH=true
```

> Grafana's built-in login screen is used for authentication. The nginx IP allowlist acts as the outer perimeter — unauthorized IPs receive 403 before reaching Grafana at all.

### Setting Up Grafana Basic Auth (Optional)

An additional Basic Auth layer can be added in nginx. It requires a password file inside the nginx container.

**Install `htpasswd`** (if not available):

```bash
apt install apache2-utils
```

**Create the password file**:

```bash
# First time — creates the file
htpasswd -c ./nginx/grafana.htpasswd admin

# Add or update a user
htpasswd ./nginx/grafana.htpasswd admin
```

The file is mounted into nginx as read-only:

```yaml
volumes:
  - ./nginx/grafana.htpasswd:/etc/nginx/grafana.htpasswd:ro
```

> **Warning:** Basic Auth and Grafana's own login conflict over the `Authorization` HTTP header. If you enable Basic Auth, Grafana may redirect to its login page and receive a 403 in return, creating a loop. It is recommended to use the **IP allowlist only** and skip Basic Auth.

### App Metrics

The API exposes Prometheus metrics at `/metrics`. This endpoint is:

- blocked externally via nginx (`deny all`)
- scraped internally by Prometheus over the Docker network

Metrics exposed:

| Metric                              | Type      | Labels                                         |
| ----------------------------------- | --------- | ---------------------------------------------- |
| `fastapi_requests_total`            | Counter   | `method`, `path`, `app_name`                   |
| `fastapi_responses_total`           | Counter   | `method`, `path`, `status_code`, `app_name`    |
| `fastapi_requests_duration_seconds` | Histogram | `method`, `path`, `app_name`                   |
| `fastapi_requests_in_progress`      | Gauge     | `method`, `path`, `app_name`                   |
| `fastapi_exceptions_total`          | Counter   | `method`, `path`, `exception_type`, `app_name` |
| `fastapi_app_info`                  | Info      | `app_name`                                     |

### Log Pipeline

Grafana Alloy collects Docker container logs and ships them to Loki:

```
Docker containers → Alloy (discovery.docker) → Loki → Grafana
```

Logs are labeled with `container_name` and `compose_service`. Query examples in Grafana Explore:

```logql
# All services
{compose_service=~"v2hub_.+"}

# Errors only
{compose_service=~"v2hub_.+", level="error"}

# API logs only
{compose_service="v2hub_api"}

# Nginx logs, non-200
{compose_service="v2hub_nginx"} | status != "200"
```

### Dashboard

Import dashboard **16110** from [grafana.com/dashboards](https://grafana.com/grafana/dashboards/16110) for a pre-built FastAPI observability view covering request rates, durations, error ratios, and live logs. The `$app_name` variable is auto-populated from the `fastapi_app_info` metric.

### Alloy Pipeline UI

The Alloy UI (port 12345) is not exposed publicly. Access it via SSH tunnel:

```bash
ssh -L 12345:localhost:12345 user@your-server
# Then open http://localhost:12345
```

### Useful Monitoring Commands

```bash
# Check all monitoring services
docker compose ps prometheus loki alloy grafana

# Prometheus logs
docker compose logs -f prometheus

# Loki logs
docker compose logs -f loki

# Alloy logs
docker compose logs -f alloy

# Grafana logs
docker compose logs -f grafana

# Verify nginx can reach Grafana
docker compose exec nginx wget -q -O- http://grafana:3000/api/health

# Verify Prometheus can reach the API
docker compose exec prometheus wget -q -O- http://api:8000/metrics | head -20
```

---

## 🛠️ Development

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run a specific test file
pytest tests/test_smoke.py

# Run with verbose output
pytest -v
```

### Code Quality

```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type checking
mypy src/
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "Add new table"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history
```

### Pre-commit Hooks

```bash
# Install pre-commit
pip install pre-commit

# Setup hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

---

## 🚢 Deployment

### Production Deployment Checklist

- [ ] Set `DEBUG=false`
- [ ] Use strong `SECRET_KEY`, `ADMIN_SECRET_KEY`, and `POSTGRES_PASSWORD` (min 32 chars)
- [ ] Set `DOMAIN` to your real domain — it's used to render the nginx config and request the SSL certificate
- [ ] Configure `ADMIN_ALLOWED_IPS` with specific IPs
- [ ] Configure proper CORS origins (not `*`)
- [ ] Set appropriate rate limits for your use case (`nginx/conf.d.templates/api.conf.template`)
- [ ] Set a real `TRUSTED_NOLIMIT_IPS` if you have monitoring/health-check IPs that shouldn't be rate-limited
- [ ] Issue SSL certificates with certbot before first start (see below)
- [ ] Set up `nginx/grafana.htpasswd` if the Grafana location is enabled
- [ ] Configure backup strategy for PostgreSQL
- [ ] Setup Redis persistence if needed (already configured via `--save 60 1`)
- [ ] Review and adjust resource limits (pool sizes, timeouts) for your traffic

### Docker Compose Services

The project ships a single `docker-compose.yml` covering the full stack — no separate prod override file is needed:

| Service         | Purpose                                                 |
| --------------- | ------------------------------------------------------- |
| `api`           | FastAPI app (Uvicorn), internal port 8000               |
| `worker`        | Celery worker — background refresh of external sources  |
| `beat`          | Celery beat — schedules periodic tasks                  |
| `postgres`      | PostgreSQL 16, data persisted to `./data/db_data`       |
| `redis`         | Redis 7, AOF-style persistence via `--save 60 1`        |
| `nginx`         | Reverse proxy, SSL termination, rate limiting           |
| `certbot-renew` | Automatic Let's Encrypt certificate renewal (every 12h) |

Monitoring services (Prometheus, Loki, Alloy, Grafana) are present but commented out in `docker-compose.yml` — uncomment them if you want the full observability stack (see [Monitoring](#-monitoring)).

```bash
# Start everything
docker compose up -d

# Start only what you need locally (e.g. no nginx/certbot for local dev)
docker compose up -d api worker beat postgres redis
```

### Nginx Configuration (templated)

Nginx configs live under `nginx/conf.d.templates/*.conf.template` and are **not** committed with real values baked in — they use placeholders (`${DOMAIN}`) that get filled in automatically at container start via nginx's built-in `envsubst`-on-templates entrypoint. You never need to hand-edit an nginx config file after cloning.

What you configure instead, in `.env`:

```bash
DOMAIN=YOURDOMAIN.com
# Comma-separated list of IPs exempt from rate limiting (optional)
TRUSTED_NOLIMIT_IPS=1.1.1.1,2.2.2.2
```

On container start:

1. `nginx/entrypoint/10-generate-limit-key-map.sh` reads `TRUSTED_NOLIMIT_IPS` and generates `/etc/nginx/conf.d/00-limit-key-map.conf` (the `map $remote_addr $limit_key { ... }` block).
2. Nginx's built-in entrypoint renders every `*.template` file in `nginx/conf.d.templates/` into `/etc/nginx/conf.d/`, substituting `${DOMAIN}` with the real value from your `.env`.
3. Nginx starts with the fully rendered config.

To inspect what was generated inside a running container:

```bash
docker compose exec nginx cat /etc/nginx/conf.d/api.conf
docker compose exec nginx cat /etc/nginx/conf.d/00-limit-key-map.conf
```

There's also `nginx/conf-test.d/api.conf` — a minimal, domain-free config (no SSL, `server_name localhost`) for quick local testing without certificates.

### Issuing SSL Certificates (first-time setup)

Before the HTTPS server block in `api.conf.template` will work, you need a real certificate at `/etc/letsencrypt/live/${DOMAIN}/`. A common bootstrap flow:

```bash
# 1. Start nginx with only the HTTP (port 80) block active, so certbot's
#    HTTP-01 challenge can be served via /.well-known/acme-challenge/
docker compose up -d nginx

# 2. Request the certificate (webroot method, matches the acme-challenge
#    location already present in api.conf.template)
docker compose run --rm certbot-renew \
  certbot certonly --webroot -w /var/www/certbot \
  -d ${DOMAIN} -d www.${DOMAIN} \
  --email you@example.com --agree-tos --no-eff-email

# 3. Reload nginx to pick up the new certificate, then start everything else
docker compose exec nginx nginx -s reload
docker compose up -d
```

After this, `certbot-renew` keeps the certificate current automatically (checks every 12 hours, reloads nginx via `docker exec nginx nginx -s reload` on renewal).

### Moving PostgreSQL Data to a Named Volume

By default, Postgres data is stored via a bind mount at `./data/db_data`. If you'd rather use the `postgres_data` named volume already declared in `docker-compose.yml`:

```bash
# 1. Dump the existing database (works regardless of Postgres version later)
docker compose exec -T postgres pg_dump -U postgres -d v2hub --format=custom --file=/tmp/v2hub.dump
docker compose cp postgres:/tmp/v2hub.dump ./v2hub.dump

# 2. Stop everything
docker compose down

# 3. In docker-compose.yml, change the postgres service's volume from
#    ./data/db_data:/var/lib/postgresql/data
#    to
#    postgres_data:/var/lib/postgresql/data

# 4. Start only postgres — it will initialize a fresh, empty volume
docker compose up -d postgres
docker compose logs -f postgres   # wait for "database system is ready to accept connections"

# 5. Restore the dump into the new volume
docker compose cp ./v2hub.dump postgres:/tmp/v2hub.dump
docker compose exec postgres pg_restore -U postgres -d v2hub --clean --if-exists /tmp/v2hub.dump

# 6. Bring everything back up
docker compose up -d
curl http://localhost/health
```

### CI/CD

GitHub Actions workflows live under `.github/workflows/`:

- **`ci.yml`** — runs on every push/PR to `main`. Spins up Postgres and Redis service containers, lints with `ruff`, type-checks with `mypy`, applies Alembic migrations, runs the test suite, and validates that the Docker image builds.
- **`deploy.yml`** — triggered automatically after a successful CI run on `main` (or manually via `workflow_dispatch`). SSHes into the production server, pulls the latest code, rebuilds and recreates containers, **runs `alembic upgrade head` inside the `api` container**, reloads nginx, and polls `/health` until it returns `200`.

Required repository secrets for deployment: `HOST`, `PORT`, `USER`, `SSH_KEY`.

---

## 🔐 Security Considerations

### Authentication & Authorization

1. **API Tokens**: Always transmitted over HTTPS
2. **Admin Endpoints**: Dual protection (IP + signature)
3. **Token Rotation**: Regularly refresh user tokens
4. **Inactive Accounts**: Automatically disable unused accounts

### Input Validation

- All inputs validated using Pydantic models
- URL validation prevents SSRF attacks
- Config parsing prevents injection attacks
- Length limits on all text fields

### Rate Limiting

- Configurable per-endpoint limits
- Redis-backed for distributed deployments
- Automatic ban on excessive violations
- Whitelist support for trusted IPs

### Security Headers

Automatically applied in production:

- `Strict-Transport-Security` (HSTS)
- `Content-Security-Policy` (CSP)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`

### Monitoring Security

- All monitoring ports (Prometheus :9090, Loki :3100, Alloy :12345, Grafana :3000) are **internal only** — declared with `expose`, not `ports`
- `/metrics` endpoint is blocked externally via `deny all` in nginx
- Grafana access is restricted by IP allowlist in nginx

---

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Commit changes**: `git commit -m 'Add amazing feature'`
4. **Push to branch**: `git push origin feature/amazing-feature`
5. **Open a Pull Request**

### Development Guidelines

- Follow PEP 8 style guide
- Write tests for new features
- Update documentation
- Add type hints to all functions
- Run linters before committing

### Code Review Process

- All PRs require review
- CI must pass (tests, linting)
- Documentation must be updated
- Changes must be backward compatible (unless major version)

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

Built with:

- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework
- [SQLAlchemy](https://www.sqlalchemy.org/) - SQL toolkit and ORM
- [Pydantic](https://docs.pydantic.dev/) - Data validation
- [Celery](https://docs.celeryq.dev/) - Distributed task queue
- [Redis](https://redis.io/) - In-memory data structure store
- [PostgreSQL](https://www.postgresql.org/) - Relational database
- [Prometheus](https://prometheus.io/) - Metrics and alerting
- [Grafana](https://grafana.com/) - Observability dashboards
- [Loki](https://grafana.com/oss/loki/) - Log aggregation
- [Grafana Alloy](https://grafana.com/oss/alloy/) - Telemetry collector

---

## 📞 Support

- **Documentation**: [docs/API_DOCUMENTATION.md](./docs/API_DOCUMENTATION.md)
- **Issues**: [GitHub Issues](https://github.com/nestthub/v2hub-api/issues)
- **Discussions**: [GitHub Discussions](https://github.com/nestthub/v2hub-api/discussions)

---

**Made with ❤️**
