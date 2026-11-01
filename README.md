# URL Shortener API

A backend service that creates short links, redirects quickly using a cache, and tracks click analytics.
Built with **FastAPI, PostgreSQL, Redis and Docker**.

<!-- After pushing, add a CI badge: ![CI](https://github.com/<your-username>/<repo-name>/actions/workflows/ci.yml/badge.svg) -->
<!-- After deploying, add your link here: **Live demo:** https://your-app.onrender.com/docs -->

## Features

- **Authentication**: sign up and log in with JWT access tokens; passwords hashed with bcrypt
- **Short links**: random base62 codes or custom aliases, optional expiry dates
- **Fast redirects**: link lookups cached in Redis (falls back to in-memory cache locally)
- **Click analytics**: total clicks, clicks per day, top referrers and device types
- **Rate limiting**: per-user limit on link creation and per-IP limit on login attempts
- **Interactive API docs**: Swagger UI at `/docs`
- **Tested and automated**: 18 pytest tests run on every push with GitHub Actions
- **Containerised**: one command starts the API, PostgreSQL and Redis

## Architecture

```
            +--------------------+
 Client --> |   FastAPI service  |
            +---------+----------+
                      |
          +-----------+-----------+
          |                       |
   +------v------+        +-------v------+
   |    Redis    |        |  PostgreSQL  |
   | link cache, |        | users, links |
   | rate limits |        | click events |
   +-------------+        +--------------+
```

**Redirect flow** (`GET /{code}`):
1. Look the code up in Redis. On a hit, no database query is needed.
2. On a miss, load the link from PostgreSQL, reject it if missing (404) or expired (410), and cache it.
3. Respond with a `302` redirect immediately.
4. Record the click (referrer, device) in a background task, after the response is sent.

## Quick start with Docker (recommended)

```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
docker compose up --build
```

Open http://localhost:8000/docs

## Run locally without Docker

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env             # Windows: copy .env.example .env
uvicorn app.main:app --reload
```

With the default `.env.example` it uses SQLite and an in-memory cache, so no other services are needed.

## Try it

```bash
# 1. Register and log in
curl -X POST localhost:8000/auth/register -H "Content-Type: application/json" \
  -d '{"email":"me@example.com","password":"password123"}'

TOKEN=$(curl -s -X POST localhost:8000/auth/login \
  -d "username=me@example.com&password=password123" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Create a short link
curl -X POST localhost:8000/links -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://github.com","custom_alias":"my-github"}'

# 3. Visit it (redirects to the original URL)
curl -i localhost:8000/my-github

# 4. See analytics
curl localhost:8000/links/1/stats -H "Authorization: Bearer $TOKEN"
```

## API overview

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Create an account |
| POST | `/auth/login` | Get a JWT (use your email as `username`) |
| GET | `/auth/me` | Current user |
| POST | `/links` | Create a short link (optional `custom_alias`, `expires_at`) |
| GET | `/links` | List your links (`limit`, `offset`) |
| GET | `/links/{id}/stats` | Click analytics for one of your links |
| DELETE | `/links/{id}` | Delete a link (also clears its cache entry) |
| GET | `/{code}` | Redirect to the original URL |
| GET | `/health` | Health check |

## Configuration

All settings are environment variables (see `.env.example`).

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL or SQLite connection string | `sqlite:///./app.db` |
| `REDIS_URL` | Redis connection; empty uses in-memory cache | empty |
| `SECRET_KEY` | Signs JWTs. **Set a long random value in production** | `change-me` |
| `BASE_URL` | Public URL used in `short_url` | `http://localhost:8000` |
| `CREATE_LIMIT_PER_MINUTE` | Link creations per user per minute | `20` |
| `LOGIN_LIMIT_PER_MINUTE` | Login attempts per IP per minute | `10` |

## Tests

```bash
pytest -q
```

Tests use a temporary SQLite database and the in-memory cache, so they need no external services.

## Project structure

```
app/
  main.py          # app setup, routers, health check
  config.py        # settings from environment variables
  database.py      # SQLAlchemy engine and sessions
  models.py        # User, Link, Click tables
  schemas.py       # request/response validation (Pydantic)
  security.py      # password hashing and JWT helpers
  deps.py          # current-user dependency
  cache.py         # Redis store with in-memory fallback
  rate_limit.py    # fixed-window rate limiter
  routers/
    auth.py        # register, login, me
    links.py       # create, list, stats, delete
    redirect.py    # the hot path: GET /{code}
tests/             # pytest suite
Dockerfile
docker-compose.yml # API + PostgreSQL + Redis
.github/workflows/ci.yml
```

## Design decisions

- **302 instead of 301 redirects**: browsers cache 301s, which would hide repeat clicks from analytics.
- **Cache TTL never exceeds link expiry**: expired links disappear from the cache on time.
- **Analytics in a background task**: the redirect is sent first, so tracking adds no latency.
- **Cache and rate limiter fail open**: if Redis is down, redirects still work from the database.
- **404 for other users' links**: avoids revealing that a link id exists.
- **Collision handling**: random codes rely on a unique index and retry on the rare collision.
- **Fixed-window rate limiting**: simple and fast, with the known trade-off of bursts at window edges.

## Roadmap

- [ ] Alembic database migrations (tables are currently created on startup)
- [ ] Async database access (async SQLAlchemy + asyncpg)
- [ ] Refresh tokens and logout
- [ ] Move click recording to a queue (Celery or RQ) for high traffic
- [ ] Sliding-window or token-bucket rate limiting
- [ ] Prometheus metrics and structured logging
- [ ] Deploy to Render / Railway / Fly.io
