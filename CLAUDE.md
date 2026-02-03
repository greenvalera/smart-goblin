# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Goblin is a Telegram bot that analyzes MTG Draft decks using AI-powered card recognition. It accepts photos (Arena screenshots or physical cards), identifies cards via GPT-4o Vision, enriches them with statistics from 17lands/Scryfall, and generates deck optimization advice in Ukrainian.

## Commands

```bash
# Activate virtual environment
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run tests
pytest                                    # All tests
pytest --cov=src --cov-report=html       # With coverage
pytest tests/test_vision/                 # Specific module

# Database migrations
alembic upgrade head                      # Apply migrations
alembic revision --autogenerate -m "msg"  # Create migration

# Run the bot
python -m src.main
```

## Architecture

**Layered structure in `src/`:**
- `bot/` - Telegram interface layer (aiogram 3.x handlers, keyboards, messages)
- `core/` - Business logic, interface-agnostic (analyzer, advisor, deck structures)
- `vision/` - Card recognition using GPT-4o Vision (recognizer, layout detection, prompts)
- `parsers/` - Data source parsers (Scryfall API, 17lands scraping, scheduler)
- `db/` - Database layer (SQLAlchemy 2.x async models, repository pattern, session factory)
- `llm/` - OpenAI client wrapper (vision calls, completions, prompt templates)

**Key patterns:**
- Fully async (aiogram, asyncpg, httpx)
- Repository pattern for database operations
- Pydantic Settings for configuration (`.env` file)
- PostgreSQL with JSONB for deck storage

**Database tables:** `sets`, `cards`, `card_ratings`, `users`, `analyses`

## Configuration

Environment variables loaded from `.env` (see `.env.example`):
- `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `DATABASE_URL` (required)
- `OPENAI_MODEL`, `OPENAI_VISION_MODEL` (default: gpt-4o)
- `SCRYFALL_API_BASE`, `SEVENTEENLANDS_BASE`
- `PARSER_SCHEDULE_HOUR` (daily update time, UTC)

## Development Notes

- All user-facing messages are in Ukrainian
- Tests use testcontainers for PostgreSQL and mock LLM responses
- Parser runs daily at 03:00 UTC via APScheduler
- Detailed specs in `doc/CONCEPT.md`, `doc/ARCHITECTURE.md`, `doc/PLAN.md`
