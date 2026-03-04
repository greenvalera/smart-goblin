# Smart Goblin — Architecture

## Technology Stack

| Component | Technology |
|-----------|------------|
| Programming language | Python 3.11+ |
| Telegram Bot | aiogram 3.x (async) |
| LLM Provider | OpenAI API (GPT-4o for vision та text) |
| Database | PostgreSQL 15+ (asyncpg driver) |
| ORM | SQLAlchemy 2.x (async) |
| HTTP Client | httpx (async) |
| HTML Parsing | BeautifulSoup4, lxml |
| Configuration | pydantic-settings (.env) |
| Containerization | Docker + docker-compose |
| Migrations | Alembic |

## Project Structure

```
smart-goblin/
├── src/
│   ├── __init__.py
│   ├── main.py                     # Entry point, bot startup
│   ├── config.py                   # Pydantic settings, env loading
│   │
│   ├── bot/                        # Telegram bot layer
│   │   ├── __init__.py
│   │   ├── handlers/
│   │   │   ├── __init__.py
│   │   │   ├── start.py            # /start, /help commands
│   │   │   ├── analyze.py          # /analyze + photo handling
│   │   │   ├── history.py          # /history commands
│   │   │   └── stats.py            # /stats, /set commands
│   │   ├── keyboards.py            # Inline keyboards builder
│   │   ├── middlewares.py          # User registration middleware
│   │   └── messages.py             # Message templates (Ukrainian)
│   │
│   ├── core/                       # Core business logic (interface-agnostic)
│   │   ├── __init__.py
│   │   ├── analyzer.py             # Main deck analysis orchestrator
│   │   ├── advisor.py              # LLM-based advice generator
│   │   └── deck.py                 # Deck/Sideboard data structures
│   │
│   ├── reports/                    # Report generation (shared by bot & HTML)
│   │   ├── __init__.py
│   │   ├── models.py               # Report data structures (DeckReport)
│   │   ├── telegram.py             # Telegram markdown formatter
│   │   └── html.py                 # HTML report generator
│   │
│   ├── vision/                     # Image recognition module
│   │   ├── __init__.py
│   │   ├── recognizer.py           # GPT-4o Vision card recognition
│   │   ├── layouts.py              # Layout detection (Arena/physical)
│   │   └── prompts.py              # Vision prompts for card extraction
│   │
│   ├── parsers/                    # Data source parsers
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract parser interface
│   │   ├── scryfall.py             # Scryfall API parser (card metadata)
│   │   ├── seventeen_lands.py      # 17lands.com parser (statistics)
│   │   └── scheduler.py            # Periodic update scheduler
│   │
│   ├── db/                         # Database layer
│   │   ├── __init__.py
│   │   ├── models.py               # SQLAlchemy models
│   │   ├── repository.py           # CRUD operations
│   │   └── session.py              # Async session factory
│   │
│   └── llm/                        # LLM integration
│       ├── __init__.py
│       ├── client.py               # OpenAI client wrapper
│       └── prompts.py              # Prompt templates for advice
│
├── migrations/                     # Alembic migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Fixtures, test DB setup
│   ├── test_vision/
│   │   └── test_recognizer.py      # Vision module tests
│   ├── test_parsers/
│   │   ├── test_scryfall.py
│   │   └── test_seventeen_lands.py
│   ├── test_core/
│   │   ├── test_analyzer.py
│   │   └── test_advisor.py
│   └── test_db/
│       └── test_repository.py
│
├── doc/
│   ├── CONCEPT.md
│   ├── ARCHITECTURE.md
│   └── PLAN.md
│
├── .env.example                    # Environment template
├── .gitignore
├── alembic.ini                     # Alembic config
├── pyproject.toml                  # Project config
├── requirements.txt                # Production dependencies
├── requirements-dev.txt            # Development dependencies
├── Dockerfile
└── docker-compose.yml
```

## Database Schema

### Table `sets`
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Unique identifier |
| code | VARCHAR(10) UNIQUE NOT NULL | Set code (e.g., "MKM", "OTJ") |
| name | VARCHAR(255) NOT NULL | Full set name |
| release_date | DATE | Set release date |
| created_at | TIMESTAMP | Record creation time |

### Table `cards`
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Unique identifier |
| scryfall_id | UUID UNIQUE | Scryfall unique ID |
| name | VARCHAR(255) NOT NULL | Card name (English) |
| set_id | INTEGER FK | Reference to sets.id |
| mana_cost | VARCHAR(50) | Mana cost string |
| cmc | DECIMAL(3,1) | Converted mana cost |
| colors | VARCHAR(10)[] | Array of colors (W,U,B,R,G) |
| type_line | VARCHAR(255) | Card type line |
| rarity | VARCHAR(20) | common/uncommon/rare/mythic |
| image_uri | TEXT | Scryfall image URL |
| created_at | TIMESTAMP | Record creation time |

**Unique index:** `(name, set_id)` — карта унікальна в межах сету.

### Table `card_ratings`
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Unique identifier |
| card_id | INTEGER FK NOT NULL | Reference to cards.id |
| source | VARCHAR(50) NOT NULL | Data source (e.g., "17lands") |
| rating | DECIMAL(2,1) | Rating 1.0-5.0 |
| win_rate | DECIMAL(5,2) | Win rate % (e.g., 55.50) |
| games_played | INTEGER | Sample size |
| format | VARCHAR(20) | Draft format (e.g., "PremierDraft") |
| fetched_at | TIMESTAMP | When data was fetched |

**Unique index:** `(card_id, source, format)` — одна оцінка на карту/джерело/формат.

### Table `users`
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Unique identifier |
| telegram_id | BIGINT UNIQUE NOT NULL | Telegram user ID |
| username | VARCHAR(255) | Telegram username |
| language | VARCHAR(10) DEFAULT 'uk' | Interface language |
| created_at | TIMESTAMP | First interaction time |

### Table `analyses`
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Unique identifier |
| user_id | INTEGER FK NOT NULL | Reference to users.id |
| set_id | INTEGER FK | Detected/specified set |
| image_url | TEXT | Stored image (optional) |
| main_deck | JSONB NOT NULL | Array of recognized card names |
| sideboard | JSONB NOT NULL | Array of sideboard card names |
| total_score | DECIMAL(4,2) | Overall deck score |
| estimated_win_rate | DECIMAL(5,2) | Estimated win rate % |
| advice | TEXT | LLM-generated advice |
| created_at | TIMESTAMP | Analysis time |

**Index:** `(user_id, created_at DESC)` — для швидкого отримання історії.

## Data Flows

### Analyze Deck (`/analyze` + photo)
```
User → sends photo with /analyze command
  → bot/handlers/analyze.py :: handle_analyze()
    → vision/recognizer.py :: recognize_cards(image)
      → llm/client.py :: call_vision(image, prompt)
        → returns: {main_deck: [...], sideboard: [...], detected_set: "..."}
    → core/analyzer.py :: analyze_deck(cards, set_code)
      → db/repository.py :: get_cards_with_ratings(names, set_code)
        → if cards found → enrich with ratings
        → if cards not found → log warning, use defaults
      → calculates total_score, estimated_win_rate
    → core/advisor.py :: generate_advice(deck, ratings)
      → llm/client.py :: call_completion(context_prompt)
        → returns: text advice in Ukrainian
    → db/repository.py :: save_analysis(user_id, analysis)
  → bot/messages.py :: format_analysis_response()
  → sends formatted message with inline keyboard
```

### Get Card Stats (`/stats {card_name}`)
```
User → /stats "Lightning Bolt"
  → bot/handlers/stats.py :: handle_stats()
    → db/repository.py :: search_card_by_name(name)
      → if found → get ratings from card_ratings
      → if not found → return "card not found"
    → bot/messages.py :: format_card_stats()
  → sends card info with ratings from all sources
```

### View History (`/history`)
```
User → /history
  → bot/handlers/history.py :: handle_history()
    → db/repository.py :: get_user_analyses(user_id, limit=10)
  → bot/messages.py :: format_history_list()
  → sends list with inline buttons for each analysis
```

### Parser Update (scheduled)
```
Scheduler → triggers daily at 03:00 UTC
  → parsers/scheduler.py :: run_updates()
    → parsers/scryfall.py :: fetch_set_cards(set_code)
      → db/repository.py :: upsert_cards(cards)
    → parsers/seventeen_lands.py :: fetch_ratings(set_code)
      → db/repository.py :: upsert_ratings(ratings)
  → logs update summary
```

## Message Format

### Analysis Response
```
📊 Аналіз колоди ({set_name})

🃏 Main Deck ({count} карт):
• Card Name 1 — ⭐ 4.2 (58% WR)
• Card Name 2 — ⭐ 3.8 (52% WR)
...

📦 Sideboard ({count} карт):
• Card Name A — ⭐ 2.5 (45% WR)
...

📈 Загальна оцінка: 3.7/5.0
🎯 Очікуваний win rate: ~54%

💡 Рекомендації:
{LLM-generated advice in Ukrainian}

---
🔄 Рекомендую замінити:
• ❌ Card X → ✅ Card Y (з sideboard)
```

### Inline Keyboards
- History list: `[Аналіз #1 - 02.02.2026] [Аналіз #2 - 01.02.2026]`
- Analysis actions: `[🔄 Повторити] [📋 Деталі] [🗑 Видалити]`

## Configuration

Environment variables (`.env` file):

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | required |
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o | required |
| `DATABASE_URL` | PostgreSQL connection string | required |
| `OPENAI_MODEL` | Model for text generation | gpt-4o |
| `OPENAI_VISION_MODEL` | Model for image analysis | gpt-4o |
| `LOG_LEVEL` | Logging level | INFO |
| `SCRYFALL_API_BASE` | Scryfall API base URL | https://api.scryfall.com |
| `SEVENTEENLANDS_BASE` | 17lands base URL | https://www.17lands.com |
| `PARSER_SCHEDULE_HOUR` | Hour for daily parser run (UTC) | 3 |

## Deployment

### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY migrations/ migrations/
COPY alembic.ini .

CMD ["python", "-m", "src.main"]
```

### docker-compose.yml
```yaml
version: "3.9"
services:
  bot:
    build: .
    env_file: .env
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: smart_goblin
      POSTGRES_USER: goblin
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  pgdata:
```

### Startup Commands
```bash
# Apply migrations
alembic upgrade head

# Run bot
python -m src.main
```

## Testing

- **Framework**: pytest + pytest-asyncio
- **Test DB**: PostgreSQL test container via testcontainers-python
- **Mocking**: unittest.mock for LLM calls, responses for HTTP
- **Coverage target**: 80%+
- **Virtual environment**: venv (standard library)

### Test Levels
| Level | Scope | DB | LLM |
|-------|-------|-----|-----|
| Unit | Deck scoring, prompt building | Mocked | Mocked |
| Integration | Repository, parsers | Test container | Mocked |
| E2E | Full flow via bot handlers | Test container | Mocked with fixtures |

### Setup
```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/Mac)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install dev dependencies
pip install -r requirements-dev.txt
```

### Running Tests
```bash
# All tests
pytest

# With coverage
pytest --cov=src --cov-report=html

# Specific module
pytest tests/test_vision/
```
