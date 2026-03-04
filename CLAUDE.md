# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Goblin is a Telegram bot that analyzes MTG Draft decks via image recognition (GPT-4o Vision) and provides AI-powered advice. All user-facing text is in Ukrainian.

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
