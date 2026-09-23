---
last_mapped_commit: 8366eb8
---

# Technology Stack

**Analysis Date:** 2026-09-23

## Languages

**Primary:**
- Python >=3.11 (per `pyproject.toml` `requires-python`) - entire codebase (`src/`, `tests/`, `scripts/`)
- Docker image pins `python:3.11-slim` (`Dockerfile`)

**Secondary:**
- SQL - Alembic migrations in `migrations/`
- Shell (bash/PowerShell) - `scripts/*.sh`, `scripts/*.ps1` for dev DB, deploy, healthcheck

## Runtime

**Environment:**
- Python 3.11 (production/Docker); local `.venv` on the dev machine may be a different interpreter version (see `CLAUDE.md` for exact venv invocation instructions)
- Async-first: `asyncio` event loop drives the bot (aiogram polling), scheduler (APScheduler), and DB access (SQLAlchemy async + asyncpg)

**Package Manager:**
- `pip` with `requirements.txt` (runtime deps) and `requirements-dev.txt` (dev/test deps)
- `pyproject.toml` also declares the project as a setuptools package (`[project]` + `[project.optional-dependencies].dev`) — dependencies are declared in both `pyproject.toml` and `requirements.txt`; keep them in sync when adding packages
- Lockfile: none present (no `requirements.lock`/`poetry.lock`/`Pipfile.lock`) — versions are floor-pinned with `>=`

## Frameworks

**Core:**
- `aiogram` >=3.4 - Telegram Bot framework (async, router-based handlers) — `src/bot/`
- `SQLAlchemy[asyncio]` >=2.0 - ORM / async data layer — `src/db/models.py`, `src/db/session.py`
- `asyncpg` >=0.29 - PostgreSQL async driver, used under SQLAlchemy's `postgresql+asyncpg://` dialect
- `pydantic-settings` >=2.2 - typed configuration loaded from environment/`.env` — `src/config.py`
- `apscheduler` >=3.10 - cron-style daily scheduler for the card/rating parser — `src/parsers/scheduler.py`
- `alembic` >=1.13 - DB schema migrations — `alembic.ini`, `migrations/`

**Testing:**
- `pytest` >=8.0 with `pytest-asyncio` >=0.23 (`asyncio_mode = "auto"`, session-scoped loop) — configured in `pyproject.toml` `[tool.pytest.ini_options]`
- `testcontainers` >=4.0 - spins a real PostgreSQL container per test run (no DB mocking) — used via fixtures in `tests/conftest.py`
- `pytest-cov` >=4.1 - coverage reporting

**Build/Dev:**
- `setuptools` >=61.0 - build backend (`[build-system]` in `pyproject.toml`), packages discovered under `src*`
- Docker multi-stage build — `Dockerfile` (builder stage installs deps via pip into `/install`, runtime stage copies them plus `src/`, `migrations/`, `alembic.ini`, `scripts/`, runs as non-root `appuser`)

## Key Dependencies

**Critical:**
- `openai` >=1.12 (`AsyncOpenAI` client) - GPT-4o Vision card recognition and GPT-4o text advice generation — `src/llm/client.py`
- `httpx` >=0.27 - async HTTP client for Scryfall/17lands parsers — `src/parsers/scryfall.py`, `src/parsers/seventeen_lands.py`
- `beautifulsoup4` >=4.12 + `lxml` >=5.1 - HTML parsing of 17lands pages — `src/parsers/seventeen_lands.py`

**Infrastructure:**
- `sqlalchemy[asyncio]` + `asyncpg` - all persistence (`src/db/models.py` defines `Set`, `Card`, `CardRating`, `User`, `Analysis` tables on a `DeclarativeBase`)
- `apscheduler` - drives the daily 03:00 UTC parser refresh job in production (`src/parsers/scheduler.py`, `create_scheduler`)

## Configuration

**Environment:**
- Loaded via `pydantic-settings` in `src/config.py`: `Settings` aggregates `DatabaseSettings`, `TelegramSettings`, `OpenAISettings`, `ParserSettings`, plus top-level `log_level`
- `.env` is read automatically (`env_file=".env"`) when present; `.env.example` documents all supported variables (values not committed — see `.env`/`.env.example` existence-only note)
- `DatabaseSettings` normalizes Railway-style `postgres://`/`postgresql://` URLs to `postgresql+asyncpg://` and validates the scheme
- `get_settings()` is `lru_cache`d — settings are read once per process
- Secrets (`DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`) are typed as `pydantic.SecretStr`; `Settings.__repr__` is overridden to avoid leaking them in logs

**Build:**
- `pyproject.toml` - project metadata, dependency list, pytest config
- `alembic.ini` + `migrations/` - schema migration config
- `Dockerfile`, `docker-compose.yml` (prod-like local run), `docker-compose.dev.yml` (dev Postgres + optional pgAdmin), `railway.toml` (Railway build/deploy config: `startCommand = "sh scripts/start.sh"`, `restartPolicyType = "on_failure"`)
- `.dockerignore` - build context exclusions

## Platform Requirements

**Development:**
- Windows dev machine: all Python/pytest/alembic commands must run through `powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\<tool>.exe ..."` (venv is not activated in the Bash shell) — see `CLAUDE.md`
- Local PostgreSQL via `scripts/dev-db.ps1` (Windows) or `scripts/dev-db.sh` (Linux/Mac), or `docker-compose.dev.yml`
- Tests require Docker (testcontainers auto-provisions PostgreSQL) — no test DB mocking

**Production:**
- Deployed on Railway (project `motivated-illumination`, service `smart-goblin`), two environments: `production` (branch `main`) and `staging` (branch `stage`), each with its own Postgres plugin and its own Telegram bot token
- Container built from `Dockerfile`, started via `scripts/start.sh` (must have LF line endings — CRLF breaks the Linux container's `sh` invocation)
- `railway.toml` configures on-failure restarts (max 3 retries)

---

*Stack analysis: 2026-09-23*
