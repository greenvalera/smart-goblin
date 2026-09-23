# Technology Stack

**Mapped:** 2026-09-23

## Language & runtime
- **Python 3.11** (`requires-python >=3.11`; Docker image `python:3.11-slim`)
- Fully async (`asyncio`) — every I/O path (Telegram, OpenAI, Postgres, HTTP) is awaited

## Core dependencies (`requirements.txt` / `pyproject.toml`)
| Package | Role |
|---|---|
| `aiogram>=3.4` | Telegram bot framework (routers, FSM, middlewares, long polling) |
| `openai>=1.12` | `AsyncOpenAI` chat completions — vision + text (`src/llm/client.py`) |
| `sqlalchemy[asyncio]>=2.0` | ORM, typed `Mapped[...]` models, async sessions |
| `asyncpg>=0.29` | Postgres driver (`postgresql+asyncpg://`) |
| `alembic>=1.13` | Schema migrations (`migrations/`) |
| `httpx>=0.27` | HTTP client for Scryfall and 17lands |
| `pydantic-settings>=2.2` | Env-driven config (`src/config.py`) |
| `apscheduler>=3.10` | `AsyncIOScheduler` cron for daily data refresh |
| `beautifulsoup4`, `lxml` | Declared but **not imported anywhere in `src/`** (leftover from HTML scraping) |
| `python-dotenv` | Imported in `src/db/session.py` but only present transitively via `pydantic-settings` |

Only versions with `>=` floors are pinned — there is no lockfile.

## Dev / test
- `pytest>=8`, `pytest-asyncio>=0.23` (`asyncio_mode = "auto"`, session-scoped loop)
- `testcontainers>=4` — spins up `postgres:15-alpine` for tests
- `pytest-cov`
- No linter/formatter/type-checker config (no ruff, black, mypy settings in repo), although `.gitignore` mentions ruff/mypy caches

## Data store
- **PostgreSQL 15** — JSONB, `ARRAY(String)`, `UUID` column types are Postgres-specific

## Build & deploy
- `Dockerfile`: two-stage build, non-root `appuser`, `CMD sh scripts/start.sh` (runs `alembic upgrade head` then `python -m src.main`)
- `railway.toml`: Dockerfile builder, restart `on_failure` ×3
- `docker-compose.yml` (bot + Postgres, prod-like) and `docker-compose.dev.yml` (Postgres + optional pgAdmin)
- Hosting: **Railway**, project `motivated-illumination`, environments `production` (branch `main`) and `staging` (branch `stage`)

## Tooling scripts (`scripts/`)
- `start.sh` — container entry
- `add_set.py` — seed a set from Scryfall + 17lands (`python -m scripts.add_set ECL [--parent SOS] [--no-fetch]`)
- `healthcheck.py` — docker-compose healthcheck
- `dev-db.sh` / `dev-db.ps1` — local Postgres lifecycle
- `deploy-stage.sh` / `deploy-stage.ps1` — force-push branch to `stage` and poll Railway deploy
