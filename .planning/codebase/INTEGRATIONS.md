---
last_mapped_commit: 8366eb8
---

# External Integrations

**Analysis Date:** 2026-09-23

## APIs & External Services

**AI / LLM:**
- OpenAI (GPT-4o) - card recognition from screenshots/photos (Vision) and text-based deck advice generation
  - SDK/Client: `openai` (`AsyncOpenAI`) wrapped in `src/llm/client.py` (`LLMClient`)
  - Models configured separately for text (`OPENAI_MODEL`, default `gpt-4o`) and vision (`OPENAI_VISION_MODEL`, default `gpt-4o`) via `src/config.py` `OpenAISettings`
  - Auth: `OPENAI_API_KEY` env var
  - Retry logic: exponential backoff (base 1s, max 10s, up to 3 retries) for `APIConnectionError`/`APITimeoutError`/`APIStatusError`/rate limits — `src/llm/client.py`
  - Prompts: `src/llm/prompts.py`, `src/vision/prompts.py`

**Card / Draft Data (scraped, not official APIs):**
- Scryfall - card metadata (names, sets, images, mana cost, etc.)
  - Client: `httpx.AsyncClient` with a custom token-bucket `RateLimiter` (default 10 req/s) — `src/parsers/scryfall.py`
  - Base URL: `SCRYFALL_API_BASE` (default `https://api.scryfall.com`)
  - No auth required (public API)
- 17lands.com - card win-rate ratings, used to compute letter grades (F through A+) via a z-score formula mirroring 17lands' own frontend
  - Client: `httpx` + `BeautifulSoup`/`lxml` HTML parsing — `src/parsers/seventeen_lands.py`
  - Base URL: `SEVENTEENLANDS_BASE` (default `https://www.17lands.com`)
  - No auth required (public site/API); grading methodology documented in the module docstring
  - Post-fetch validation: `src/parsers/grade_validator.py`

**Messaging:**
- Telegram Bot API - primary user interface (photo upload, deck analysis replies)
  - SDK/Client: `aiogram` 3.x — `src/bot/` (handlers in `src/bot/handlers/`, middlewares in `src/bot/middlewares.py`, keyboards)
  - Auth: `TELEGRAM_BOT_TOKEN` env var (`TelegramSettings` in `src/config.py`)
  - Two separate bot tokens exist: one for `production`, one for `staging` (different BotFather bots — required because a single token can only sustain one long-poll consumer; sharing causes Telegram `409 Conflict`)

## Data Storage

**Databases:**
- PostgreSQL 15+ (single database, 5 tables: `sets`, `cards`, `card_ratings`, `users`, `analyses` — `src/db/models.py`)
  - Connection: `DATABASE_URL` env var, normalized to `postgresql+asyncpg://` scheme by `DatabaseSettings` in `src/config.py` (accepts Railway-style `postgres://`/`postgresql://` too)
  - Client/ORM: SQLAlchemy 2.x async engine (`src/db/session.py`, `get_engine`/`get_session`/`close_engine`) + `asyncpg` driver; repository pattern in `src/db/repository.py`
  - Dev instance: `postgresql+asyncpg://goblin:password@localhost:5432/smart_goblin` via `scripts/dev-db.ps1`/`.sh` or `docker-compose.dev.yml`
  - Production and staging each have their own independent Postgres plugin/volume on Railway (no shared data)

**File Storage:**
- Local filesystem only for build artifacts; no object storage (S3/GCS) integration detected. User-submitted deck photos are processed in-memory and sent directly to OpenAI Vision (not persisted to disk/bucket), per `src/vision/recognizer.py` flow

**Caching:**
- None — no Redis/Memcached dependency present

## Authentication & Identity

**Auth Provider:**
- None (no OAuth/Auth0/Firebase). User identity is scoped to Telegram's own user IDs
  - Implementation: `src/db/models.py` `User` table keyed by Telegram user id; `src/bot/middlewares.py` `UserRegistrationMiddleware` upserts users on first interaction

## Monitoring & Observability

**Error Tracking:**
- None detected (no Sentry/Rollbar/Bugsnag SDK in dependencies)

**Logs:**
- Standard library `logging`, configured in `src/main.py` `setup_logging()` (stdout, timestamped format); noisy loggers (`apscheduler`, `httpx`, `aiogram`) leveled down to WARNING/INFO
- `LOG_LEVEL` env var: `INFO` in production, `DEBUG` in staging
- Runtime log inspection in production/staging is done via Railway CLI (`railway logs`), not a dedicated log aggregation service

## CI/CD & Deployment

**Hosting:**
- Railway (project `motivated-illumination`), service `smart-goblin`, two environments:
  - `production` — deploys from `main`, prod Telegram token, parser scheduler enabled, `LOG_LEVEL=INFO`
  - `staging` — deploys from `stage` (a force-pushed pointer branch), separate Telegram token, parser scheduler disabled, `LOG_LEVEL=DEBUG`
- Deploy config: `railway.toml` (`startCommand = "sh scripts/start.sh"`, restart on failure, max 3 retries)
- Staging deploys are one-command via `scripts/deploy-stage.ps1` / `scripts/deploy-stage.sh` (force-pushes current branch to `origin/stage`, switches Railway link, streams build logs, waits for startup signal)

**CI Pipeline:**
- No CI config detected in-repo (no `.github/workflows/`) — release workflow is manual: PR into `main` (production release), scripted staging deploy for pre-merge testing (see `CLAUDE.md` "Release workflow")

## Environment Configuration

**Required env vars (see `.env.example` for the full documented list; values never captured here):**
- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY` (+ optional `OPENAI_MODEL`, `OPENAI_VISION_MODEL`)
- `DATABASE_URL` (+ dev-only `POSTGRES_PASSWORD`, `PGADMIN_EMAIL`, `PGADMIN_PASSWORD`)
- `LOG_LEVEL`
- `SCRYFALL_API_BASE`, `SEVENTEENLANDS_BASE`
- `PARSER_SCHEDULE_ENABLED`, `PARSER_SCHEDULE_HOUR`

**Secrets location:**
- Local: `.env` (present, gitignored, contents never read/quoted in this analysis)
- Production/staging: Railway environment variables, set via `railway variables --set ...` (per-environment, never both bots sharing a token)

## Webhooks & Callbacks

**Incoming:**
- None — Telegram updates are received via long-polling (`Dispatcher`/`Bot` in `src/main.py`), not a webhook endpoint

**Outgoing:**
- None beyond the direct API calls to OpenAI, Scryfall, and 17lands described above

---

*Integration audit: 2026-09-23*
