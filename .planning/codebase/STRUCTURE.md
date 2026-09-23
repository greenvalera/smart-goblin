# Directory Structure

**Mapped:** 2026-09-23

```
smart-goblin/
├── src/
│   ├── main.py                 # entry: bot + scheduler
│   ├── config.py               # pydantic-settings
│   ├── bot/
│   │   ├── handlers/
│   │   │   ├── __init__.py      # get_handlers_router() — ORDER MATTERS (draft before analyze)
│   │   │   ├── start.py         # /start, /help
│   │   │   ├── analyze.py       # /analyze, bare photo routing, advice + price callbacks (largest module, ~840 lines)
│   │   │   ├── draft.py         # /draft FSM + chat mode
│   │   │   ├── history.py       # /history + detail/delete callbacks
│   │   │   └── stats.py         # /stats, /set
│   │   ├── keyboards.py        # inline keyboards; callback_data builders (64-byte limit handling)
│   │   ├── messages.py         # Ukrainian message formatters, format_error()
│   │   └── middlewares.py      # UserRegistrationMiddleware → data["db_user"]
│   ├── core/                   # pure business logic (no aiogram)
│   │   ├── deck.py, analyzer.py, advisor.py, lands.py
│   ├── vision/
│   │   ├── recognizer.py       # CardRecognizer
│   │   ├── prompts.py          # vision prompts, LayoutType enum
│   │   ├── layouts.py          # layout detection
│   │   └── card_matcher.py     # difflib fuzzy matching
│   ├── llm/
│   │   ├── client.py, exceptions.py
│   │   └── prompts.py          # advice / draft-chat system prompts, CardRecognitionResult
│   ├── parsers/
│   │   ├── base.py             # BaseParser + dataclasses + errors
│   │   ├── scryfall.py, scryfall_variants.py
│   │   ├── seventeen_lands.py  # ratings + grade math + embargo
│   │   ├── grade_validator.py
│   │   └── scheduler.py        # APScheduler + run_updates + CLI
│   ├── db/
│   │   ├── models.py, repository.py, session.py
│   └── reports/
│       ├── models.py           # DeckReport, CardSummary, rating_to_grade
│       ├── telegram.py         # Markdown renderer (what users see)
│       └── html.py             # HTML renderer (not wired to any handler)
├── migrations/                 # Alembic env + 3 versions
├── scripts/                    # start.sh, add_set.py, healthcheck.py, dev-db.*, deploy-stage.*
├── tests/
│   ├── conftest.py             # testcontainers Postgres, db_session/clean_session, LLM mock builders
│   ├── fixtures/               # ecl_deck.jpg, ecl_sideboard.jpg
│   ├── integration/            # e2e flow, photo analysis, parser integration, DFC lookup, parent set
│   └── test_{bot,core,db,llm,parsers,scripts,vision}/ + test_config.py
├── doc/                        # ARCHITECTURE.md, CONCEPT.md (older design docs)
├── .claude/                    # settings.json + SessionStart hook (installs railway CLI)
├── CLAUDE.md, AGENTS.md        # agent instructions (AGENTS.md is a near-copy for Codex)
├── Dockerfile, docker-compose*.yml, railway.toml
├── pyproject.toml, requirements*.txt, alembic.ini
└── .env.example
```

## Where to put things
| Adding… | Goes in |
|---|---|
| New bot command | new router module in `src/bot/handlers/`, include it in `handlers/__init__.py`; register the command in `main.py` `set_my_commands` |
| New user-facing text | `src/bot/messages.py` (Ukrainian) |
| Deck scoring / heuristics | `src/core/` (keep aiogram-free) |
| New DB query | method on the relevant repository in `src/db/repository.py` |
| Schema change | edit `src/db/models.py` + `alembic revision --autogenerate` |
| New external data source | subclass `BaseParser` in `src/parsers/`, wire into `scheduler.run_updates` |
| LLM prompt | `src/llm/prompts.py` (text) or `src/vision/prompts.py` (vision) |

## Naming
- Modules `snake_case.py`; classes `PascalCase`; private helpers `_leading_underscore`
- Handlers named `handle_<thing>`; routers are a module-level `router = Router()`
- Tests mirror `src/` as `tests/test_<package>/test_<module>.py`
