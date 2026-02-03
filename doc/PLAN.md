# Smart Goblin — Execution Plan

## How to Use
Mark completed tasks by changing `[ ]` to `[x]`.

---

## Task 1: Project Scaffolding
- [x] **Done**

**Description:**
Створити структуру директорій проекту згідно з ARCHITECTURE.md. Налаштувати `pyproject.toml` та `requirements.txt` з залежностями (aiogram, openai, sqlalchemy, asyncpg, httpx, beautifulsoup4, pydantic-settings, alembic). Створити `.env.example`, `.gitignore`, базові `__init__.py` файли.

**Acceptance Criteria:**
- [x] TC-1.1: `pip install -r requirements.txt` успішно встановлює всі залежності.
- [x] TC-1.2: Структура директорій відповідає ARCHITECTURE.md (src/, tests/, migrations/, doc/).
- [x] TC-1.3: `.env.example` містить всі змінні з таблиці Configuration.

---

## Task 2: Dev Database Setup (Docker)
- [x] **Done**

**Description:**
Налаштувати локальне dev-оточення для бази даних через Docker. Створити `docker-compose.dev.yml` з PostgreSQL 15 та pgAdmin (опціонально). Додати скрипт `scripts/dev-db.sh` (або `.ps1` для Windows) для швидкого запуску/зупинки dev БД. Оновити `.env.example` з коментарями для dev-налаштувань.

**Acceptance Criteria:**
- [x] TC-2.1: `docker-compose -f docker-compose.dev.yml up -d` запускає PostgreSQL контейнер на порту 5432.
- [x] TC-2.2: БД автоматично створюється з назвою `smart_goblin`, користувачем `goblin` та паролем з `.env`.
- [x] TC-2.3: Volume `pgdata-dev` зберігає дані між перезапусками контейнера.
- [x] TC-2.4: Скрипт `scripts/dev-db.ps1 start|stop|reset` керує dev БД (reset видаляє volume і створює чисту БД).
- [x] TC-2.5: Підключення до БД працює з `DATABASE_URL` з `.env.example` без змін.

---

## Task 3: Configuration Module
- [ ] **Done**

**Description:**
Реалізувати `src/config.py` з Pydantic Settings для завантаження конфігурації з `.env`. Класи: `DatabaseSettings`, `TelegramSettings`, `OpenAISettings`, `ParserSettings`. Головний клас `Settings` агрегує всі налаштування.

**Acceptance Criteria:**
- [ ] TC-3.1: Unit test — `Settings()` з валідним .env повертає всі поля.
- [ ] TC-3.2: Unit test — відсутній `TELEGRAM_BOT_TOKEN` викликає `ValidationError`.
- [ ] TC-3.3: Unit test — `DATABASE_URL` коректно парситься для asyncpg.
- [ ] TC-3.4: `Settings.model_dump()` не містить секретних значень у repr.

---

## Task 4: Database Models & Migrations
- [ ] **Done**

**Description:**
Реалізувати SQLAlchemy моделі в `src/db/models.py`: `Set`, `Card`, `CardRating`, `User`, `Analysis`. Створити `src/db/session.py` з async session factory. Налаштувати Alembic та створити початкову міграцію. Див. схему в ARCHITECTURE.md.

**Acceptance Criteria:**
- [ ] TC-4.1: `alembic upgrade head` створює всі 5 таблиць у тестовій БД.
- [ ] TC-4.2: Унікальні індекси працюють — повторний insert (name, set_id) для cards викликає IntegrityError.
- [ ] TC-4.3: Foreign keys працюють — видалення set каскадно видаляє пов'язані cards.
- [ ] TC-4.4: JSONB поля (main_deck, sideboard) коректно зберігають та читають списки.

---

## Task 5: Repository Layer
- [ ] **Done**

**Description:**
Реалізувати `src/db/repository.py` з CRUD операціями: `CardRepository` (get_by_name, get_by_set, search_by_name, upsert_cards, upsert_ratings), `UserRepository` (get_or_create, update), `AnalysisRepository` (create, get_by_user, get_by_id). Використовувати async методи.

**Acceptance Criteria:**
- [ ] TC-5.1: `get_cards_with_ratings(["Card A", "Card B"], "SET")` повертає карти з їх рейтингами.
- [ ] TC-5.2: `search_card_by_name("Lightning")` повертає карти з частковим збігом назви.
- [ ] TC-5.3: `upsert_cards()` оновлює існуючі карти замість дублювання.
- [ ] TC-5.4: `get_user_analyses(user_id, limit=10)` повертає останні 10 аналізів відсортованих за датою.
- [ ] TC-5.5: `get_or_create_user(telegram_id)` створює нового або повертає існуючого.

---

## Task 6: Scryfall Parser
- [ ] **Done**

**Description:**
Реалізувати `src/parsers/base.py` з абстрактним інтерфейсом `BaseParser`. Реалізувати `src/parsers/scryfall.py` для отримання метаданих карт через Scryfall API (назва, mana_cost, colors, type_line, rarity, image_uri). Обробка пагінації та rate limiting.

**Acceptance Criteria:**
- [ ] TC-6.1: `fetch_set_cards("MKM")` повертає список карт сету Murders at Karlov Manor.
- [ ] TC-6.2: Кожна карта містить поля: name, scryfall_id, mana_cost, colors, rarity, image_uri.
- [ ] TC-6.3: Rate limiting — не більше 10 запитів на секунду до Scryfall API.
- [ ] TC-6.4: Пагінація працює — сет з >175 картами отримує всі сторінки.

---

## Task 7: 17lands Parser
- [ ] **Done**

**Description:**
Реалізувати `src/parsers/seventeen_lands.py` для отримання статистики карт з 17lands.com. Парсити HTML або використовувати публічні endpoint-и для отримання rating, win_rate, games_played. Мапінг назв карт до існуючих записів у БД.

**Acceptance Criteria:**
- [ ] TC-7.1: `fetch_ratings("MKM", "PremierDraft")` повертає рейтинги для карт сету.
- [ ] TC-7.2: Кожен рейтинг містить: card_name, rating (1-5), win_rate (%), games_played.
- [ ] TC-7.3: Карти без достатньої статистики (< 200 ігор) позначаються як low_confidence.
- [ ] TC-7.4: Мапінг назв регістронезалежний та ігнорує спецсимволи.

---

## Task 8: LLM Client
- [ ] **Done**

**Description:**
Реалізувати `src/llm/client.py` з OpenAI клієнтом: `call_vision(image_bytes, prompt)` для розпізнавання карт, `call_completion(messages)` для генерації порад. Реалізувати `src/llm/prompts.py` з шаблонами промптів. Обробка помилок та retry logic.

**Acceptance Criteria:**
- [ ] TC-8.1: `call_vision()` приймає base64 зображення та повертає структурований JSON.
- [ ] TC-8.2: `call_completion()` з контекстом колоди повертає текст українською.
- [ ] TC-8.3: Timeout після 60 секунд викликає `LLMTimeoutError`.
- [ ] TC-8.4: API error (429, 500) викликає retry з exponential backoff (до 3 спроб).

---

## Task 9: Vision Module
- [ ] **Done**

**Description:**
Реалізувати `src/vision/recognizer.py` з `CardRecognizer` класом. Метод `recognize_cards(image)` повертає `{main_deck: [...], sideboard: [...], detected_set: "..."}`. Реалізувати `src/vision/layouts.py` для детекції типу розкладки (Arena screenshot vs physical cards). Реалізувати `src/vision/prompts.py` з оптимізованими промптами.

**Acceptance Criteria:**
- [ ] TC-9.1: Arena скріншот колоди розпізнається з accuracy > 90% назв карт.
- [ ] TC-9.2: Фото фізичних карт у рядках розпізнається з accuracy > 80%.
- [ ] TC-9.3: Main deck та sideboard коректно розділяються за позицією на зображенні.
- [ ] TC-9.4: Сет визначається автоматично за symbol/watermark або найчастішими картами.

---

## Task 10: Core Analyzer
- [ ] **Done**

**Description:**
Реалізувати `src/core/deck.py` з dataclass `Deck` (main_deck, sideboard, set_code). Реалізувати `src/core/analyzer.py` з `DeckAnalyzer` класом: `analyze(deck)` повертає score, estimated_win_rate, mana_curve, color_distribution. Формули розрахунку базуються на weighted average рейтингів.

**Acceptance Criteria:**
- [ ] TC-10.1: Колода з 40 карт середнього рейтингу 3.5 отримує score ~3.5.
- [ ] TC-10.2: `estimated_win_rate` = weighted average win rates карт (з урахуванням sample size).
- [ ] TC-10.3: Mana curve повертає розподіл карт по CMC: {0: 1, 1: 5, 2: 8, ...}.
- [ ] TC-10.4: Color distribution повертає відсоток карт кожного кольору.

---

## Task 11: Advisor Module
- [ ] **Done**

**Description:**
Реалізувати `src/core/advisor.py` з `DeckAdvisor` класом. Метод `generate_advice(deck, ratings, analysis)` формує контекст та викликає LLM для генерації порад українською. Поради включають: загальну оцінку, слабкі карти для заміни, сильні карти з sideboard для додавання, коментарі щодо mana curve та color balance.

**Acceptance Criteria:**
- [ ] TC-11.1: Порада містить конкретні назви карт для заміни (мін. 2 карти якщо є слабкі).
- [ ] TC-11.2: Якщо sideboard порожній, секція "додати з sideboard" відсутня.
- [ ] TC-11.3: Текст поради українською, без технічного жаргону (зрозумілий новачку).
- [ ] TC-11.4: Поради враховують mana curve (занадто багато дорогих/дешевих карт).

---

## Task 12: Bot Message Templates
- [ ] **Done**

**Description:**
Реалізувати `src/bot/messages.py` з функціями форматування: `format_analysis_response()`, `format_history_list()`, `format_card_stats()`, `format_error()`, `format_help()`. Всі повідомлення українською. Реалізувати `src/bot/keyboards.py` з inline keyboards.

**Acceptance Criteria:**
- [ ] TC-12.1: `format_analysis_response()` повертає markdown з емодзі та структурованими секціями.
- [ ] TC-12.2: Довгі списки карт (> 20) скорочуються з "та ще N карт...".
- [ ] TC-12.3: Inline keyboard для історії містить кнопки з датою та ID аналізу.
- [ ] TC-12.4: Всі тексти українською без граматичних помилок.

---

## Task 13: Bot Handlers
- [ ] **Done**

**Description:**
Реалізувати aiogram handlers: `src/bot/handlers/start.py` (/start, /help), `src/bot/handlers/analyze.py` (/analyze + photo), `src/bot/handlers/history.py` (/history), `src/bot/handlers/stats.py` (/stats, /set). Реалізувати `src/bot/middlewares.py` з middleware для auto-реєстрації користувачів.

**Acceptance Criteria:**
- [ ] TC-13.1: /start від нового користувача створює запис у БД та відправляє привітання.
- [ ] TC-13.2: Фото без /analyze ігнорується (або надсилає підказку).
- [ ] TC-13.3: /analyze без фото відповідає інструкцією надіслати фото.
- [ ] TC-13.4: /history без аналізів показує "У вас ще немає аналізів".
- [ ] TC-13.5: Помилка LLM відправляє користувачу friendly error message.

---

## Task 14: Entry Point & Parser Scheduler
- [ ] **Done**

**Description:**
Реалізувати `src/main.py` як entry point: ініціалізація бота, підключення до БД, запуск polling. Реалізувати `src/parsers/scheduler.py` з APScheduler для щоденного оновлення даних з 17lands та Scryfall.

**Acceptance Criteria:**
- [ ] TC-14.1: `python -m src.main` запускає бота без помилок.
- [ ] TC-14.2: Graceful shutdown при SIGTERM зберігає стан та закриває з'єднання.
- [ ] TC-14.3: Scheduler запускає парсери о 03:00 UTC щодня.
- [ ] TC-14.4: Помилка парсера логується але не зупиняє бота.

---

## Task 15: Docker & Deployment
- [ ] **Done**

**Description:**
Створити `Dockerfile` для production build. Створити `docker-compose.yml` з сервісами bot та db. Налаштувати volume для PostgreSQL. Додати health checks.

**Acceptance Criteria:**
- [ ] TC-15.1: `docker-compose up` запускає бота та БД без помилок.
- [ ] TC-15.2: Перезапуск контейнера не втрачає дані БД (volume persists).
- [ ] TC-15.3: Dockerfile використовує multi-stage build (production image < 500MB).
- [ ] TC-15.4: Health check для бота перевіряє з'єднання з Telegram API.

---

## Task 16: Integration Testing
- [ ] **Done**

**Description:**
Написати інтеграційні тести для повного flow: надсилання фото → розпізнавання → аналіз → порада → збереження в історію. Використовувати testcontainers для PostgreSQL, мокати LLM відповіді fixtures.

**Acceptance Criteria:**
- [ ] TC-16.1: E2E test — analyze flow від фото до збереження в БД (з mocked LLM).
- [ ] TC-16.2: History test — після 3 аналізів /history показує всі три.
- [ ] TC-16.3: Isolation test — аналізи різних користувачів не змішуються.
- [ ] TC-16.4: Clean run — `pip install -r requirements-dev.txt && pytest` проходить на чистій машині.
- [ ] TC-16.5: Parser integration — fetch + upsert cycle не створює дублікатів.

---

## Execution Order

```
Task 1 (Scaffolding)
    ↓
Task 2 (Dev DB Setup)
    ↓
Task 3 (Config)
    ↓
Task 4 (DB Models)
    ↓
Task 5 (Repository)
    ↓
┌─────────────────┬─────────────────┬─────────────────┐
│                 │                 │                 │
Task 6 (Scryfall) Task 7 (17lands)  Task 8 (LLM Client)
│                 │                 │
└────────┬────────┴────────┬────────┴────────┬────────┘
         │                 │                 │
         └────────────────┬┴─────────────────┘
                          ↓
                   Task 9 (Vision)
                          ↓
                   Task 10 (Analyzer)
                          ↓
                   Task 11 (Advisor)
                          ↓
                   Task 12 (Messages)
                          ↓
                   Task 13 (Handlers)
                          ↓
                   Task 14 (Entry Point)
                          ↓
                   Task 15 (Docker)
                          ↓
                   Task 16 (Integration Tests)
```
