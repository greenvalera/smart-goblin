# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Goblin is a Telegram bot that analyzes MTG Draft decks via image recognition (GPT-4o Vision) and provides AI-powered advice. All user-facing text is in Ukrainian.

## Task Tracker

Tasks live in Notion: [Smart Goblin → Tasks Tracker](https://www.notion.so/Smart-Goblin-34e5c1393d3680e8bf47f3b6ef1ed4fb).
Use the Notion MCP tools (`mcp__claude_ai_Notion__*`) to read, create, and update tasks. Don't add new task files under `doc/`.

## Running Python (venv)

The project uses a virtual environment at `.venv/`. On Windows, all Python/pytest/alembic commands must be run through PowerShell via `powershell.exe -Command`:

```bash
# Pattern for running any command through venv on Windows
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m <module> <args>"

# Or for tools installed in venv (pytest, alembic)
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\<tool>.exe <args>"
```

Direct invocation (`python`, `pytest`) will fail because the venv is not activated in the Bash shell.

## Commands

```bash
# Run the bot
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m src.main"

# Run all tests (uses testcontainers - auto-spins PostgreSQL)
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m pytest"

# Run tests with coverage
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m pytest --cov=src --cov-report=html"

# Run specific test file
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m pytest tests/test_vision/test_recognizer.py"

# Run tests verbose
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m pytest tests/ -v"

# Dev database management (Windows)
.\scripts\dev-db.ps1 start
.\scripts\dev-db.ps1 stop
.\scripts\dev-db.ps1 reset

# Dev database management (Linux/Mac)
./scripts/dev-db.sh start

# Database migrations
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m alembic upgrade head"
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m alembic revision --autogenerate -m 'description'"
```

## Railway CLI Workflow

Use Railway CLI for production checks, data refreshes, and log inspection.

```bash
# One-time auth on a machine
railway login

# Link this repo to the production project/service
railway link
# Workspace: greenvalera's Projects
# Project: motivated-illumination
# Environment: production
# Service: smart-goblin

# Confirm the active link
railway status

# Inspect recent deploys and logs
railway deployment list
railway logs --deployment --lines 50 --latest
railway logs --lines 100

# Run a command inside the production service container
railway ssh python --version

# Refresh production card data and verify grade validation end-to-end
railway ssh python -m src.parsers.scheduler --strict
```

Notes:

- `railway ssh python -m src.parsers.scheduler --strict` updates production set data and also runs the post-update grade validation hook added in PR `#6`.
- If `railway status` says `No linked project found`, run `railway link` again from repo root.
- Before `railway up` from Windows, make sure `scripts/start.sh` is checked out with LF, not CRLF, or the Linux container may fail on startup with `set: Illegal option -`.
- Quick check for line endings:
  `git ls-files --eol scripts/start.sh`
  Expected working tree state: `w/lf`

### Environments: production vs staging

The `motivated-illumination` project has two environments inside one Railway project, each with its own `smart-goblin` service and its own `Postgres` plugin (separate volumes, separate data):

| Environment  | Source branch | Telegram bot         | Parser scheduler | LOG_LEVEL |
|--------------|---------------|----------------------|------------------|-----------|
| `production` | `main`        | prod BotFather token | enabled          | INFO      |
| `staging`    | `stage`       | staging BotFather token (separate bot — required, see below) | disabled | DEBUG |

Why a separate Telegram bot for staging: a single bot token can only have one active long-poll consumer. If staging and prod share a token, both fight over `getUpdates` and Telegram returns `409 Conflict`.

Switching environments via CLI:

```bash
railway environment production   # or: staging
railway service smart-goblin     # link service in current env
railway status                   # confirm current env + service
```

Be careful: `railway ssh ...` runs against whichever environment is currently linked. Always check `railway status` before destructive or data-touching commands.

Release workflow:

1. For each new task, create a dev branch off `stage` (e.g. `feat/<slug>`, `fix/<slug>`).
2. Implement the change on the dev branch and open a PR into `stage` for review.
3. Merge the dev branch into `stage` and push `stage` → Railway auto-deploys to `staging`.
4. Open a PR from `stage` → `main` so the pending release is visible.
5. Test via the staging Telegram bot. Iterate on the dev branch (or follow-up dev branches into `stage`) until green.
6. Release: merge the `stage` → `main` PR → Railway auto-deploys to `production`.

Setting / rotating the staging Telegram token (do this once after creating a bot in @BotFather):

```bash
railway environment staging
railway service smart-goblin
railway variables --set TELEGRAM_BOT_TOKEN=<staging_token>
# Triggers a redeploy. The staging container will crash on startup until a real token is set.
```

Seeding the staging Postgres after first deploy:

`src.parsers.scheduler` only refreshes sets that already exist in the DB — on a fresh staging Postgres it logs `No sets in database, skipping update` and exits. Use `scripts.add_set` per set to seed; it pulls cards from Scryfall and ratings from 17lands.

```bash
railway environment staging
railway service smart-goblin

# Seed each set you want to mirror from prod
railway ssh python -m scripts.add_set ECL
railway ssh python -m scripts.add_set TMT
railway ssh python -m scripts.add_set SOS

# Afterwards, the scheduler can refresh ratings on demand
railway ssh python -m src.parsers.scheduler --strict
```

To list sets currently in prod (to know what to seed), switch to production first and query:

```bash
railway environment production && railway service smart-goblin
railway ssh "python -c \"
import asyncio
from src.db.session import get_session
from sqlalchemy import text
async def m():
    async with get_session() as s:
        r = await s.execute(text('SELECT code FROM sets ORDER BY release_date'))
        print(','.join(c for (c,) in r.all()))
asyncio.run(m())\""
```

## Architecture

**Layered async architecture with interface-agnostic core:**

- `src/bot/` - Telegram interface (aiogram 3.x handlers, middlewares, keyboards)
- `src/core/` - Business logic (deck analysis, advice generation) - no Telegram dependencies
- `src/vision/` - GPT-4o Vision card recognition from screenshots/photos
- `src/llm/` - OpenAI client wrapper with retry logic
- `src/parsers/` - Scryfall + 17lands data fetchers (scheduled daily at 03:00 UTC)
- `src/db/` - SQLAlchemy 2.x async models + repository pattern
- `src/reports/` - Report generation (Telegram markdown, HTML)

**Main data flow for `/analyze`:**
Photo → `vision/recognizer.py` (GPT-4o Vision) → `core/analyzer.py` (enriches with DB ratings) → `core/advisor.py` (GPT-4o text advice) → `db/repository.py` (save) → formatted response

## Database

PostgreSQL 15+ with 5 tables: `sets`, `cards`, `card_ratings`, `users`, `analyses`.

Dev DB: `postgresql+asyncpg://goblin:password@localhost:5432/smart_goblin`

## Testing

- pytest-asyncio with `asyncio_mode = "auto"`
- Real PostgreSQL via testcontainers (no mocking DB)
- Key fixtures in `tests/conftest.py`:
  - `db_session` - per-test session with rollback
  - `clean_session` - truncates all tables first
  - `sample_deck_data`, `sample_card_names`, `sample_image_bytes`
  - `create_mock_vision_response()`, `create_mock_advice_response()` - for mocking LLM

## Environment Variables

Required: `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `DATABASE_URL`

See `.env.example` for all options.
