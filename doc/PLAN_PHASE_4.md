# Smart Goblin — Phase 4: Smart Photo Routing, /draft E2E Test & Conversation Mode

## How to Use
Mark completed tasks by changing `[ ]` to `[x]`.

---

## Task P4-1: Smart Photo Routing — Single Card vs Deck Detection
- [x] **Done**

**Description:**
Зараз фото без команди `/analyze` ігнорується (TC-14.2). Треба змінити поведінку: бот аналізує що зображено на фото — одна карта або дека. Якщо одна карта — повертає грейд і вінрейт. Якщо дека — запускає повний аналіз як `/analyze`.

**Деталі реалізації:**
1. У `src/vision/recognizer.py` додати метод `recognize_photo_type()` або розширити `RecognitionResult` полем `photo_type: Literal["deck", "single_card", "unknown"]`.
2. Логіка класифікації: якщо після розпізнавання `len(main_deck) == 1` і `sideboard` порожній — це одна карта; якщо `len(main_deck) >= 3` — дека; інакше `unknown` (запитати уточнення).
3. Новий хендлер у `src/bot/handlers/analyze.py`: `@router.message(F.photo)` без стану FSM — перехоплює всі фото без команди та запускає роутинг.
4. Для одиночної карти — шукати в БД за `db_user.active_set_code`, повертати відповідь у форматі:
   ```
   🃏 *Назва Карти*
   📊 Грейд: B+ | WR: 57.2% | CMC: 3
   🎨 Кольори: U | Тип: Creature — Merfolk
   ```
5. Якщо карта не знайдена в БД або сет не встановлений — повідомити юзера з підказкою `/set <код>`.

**Acceptance Criteria:**
- [x] TC-P4-1.1: Фото з одною картою (розпізнано 1 карта) → відповідь з грейдом і вінрейтом, без повного аналізу деки.
- [x] TC-P4-1.2: Фото з декою (розпізнано 3+ карти) → повний аналіз деки як `/analyze`.
- [x] TC-P4-1.3: Якщо розпізнано 2 карти або розпізнавання невизначене → повідомлення "Не вдалося визначити тип фото, спробуйте /analyze або /draft".
- [x] TC-P4-1.4: Одиночна карта без активного сету → повідомлення з підказкою встановити сет через `/set`.
- [x] TC-P4-1.5: Одиночна карта знайдена в БД — відображається грейд, вінрейт (якщо є), mana cost, тип.
- [x] TC-P4-1.6: Одиночна карта не знайдена в БД — повідомлення "Карта не знайдена в базі для сету <код>".
- [x] TC-P4-1.7: Фото у стані FSM (наприклад, `DraftState.waiting_sideboard`) не перехоплюється цим хендлером — FSM хендлери мають вищий пріоритет.

---

## Task P4-2: E2E Test — /draft Command with Two Photos
- [x] **Done**

**Description:**
Написати E2E інтеграційний тест для повного флоу команди `/draft` з двома фотографіями:
- `tests/fixtures/ecl_deck.jpg` — main deck
- `tests/fixtures/ecl_sideboard.jpg` — sideboard

Тест seeds дані з реальних Scryfall + 17lands API (через існуючий `_seed_from_apis()`), виконує реальне GPT-4o розпізнавання обох фото, генерує репорт та рекомендації, і виводить результат у stdout.

**Аналог:** існуючий `test_e2e_real_llm_full_validation` у `tests/integration/test_photo_analysis.py`.

**Деталі реалізації:**
Додати новий тест-клас `TestDraftE2E` у `tests/integration/test_photo_analysis.py`:

```
Step 1: Skip conditions (як в існуючому E2E тесті)
Step 2: Seed DB з реальних Scryfall + 17lands API (_seed_from_apis())
Step 3: Розпізнати ecl_deck.jpg → main_deck (реальний GPT-4o Vision)
Step 4: Розпізнати ecl_sideboard.jpg → sideboard (реальний GPT-4o Vision)
Step 5: Fuzzy matching обох списків до known_cards
Step 6: run_analysis_pipeline() → report + rendered_text
Step 7: DeckAdvisor.generate_advice(session_mode=True) → advice_text
Step 8: Вивести в stdout: розпізнані карти, повний репорт, поради
Step 9: Assertions: main_deck > 0, sideboard > 0, грейди без "?"
```

**Запуск:**
```bash
E2E_SET_CODE=ECL pytest tests/integration/test_photo_analysis.py -k draft_e2e -s
```

**Acceptance Criteria:**
- [x] TC-P4-2.1: Тест пропускається якщо немає `OPENAI_API_KEY`, або він є `sk-test`.
- [x] TC-P4-2.2: Тест пропускається якщо немає `E2E_SET_CODE` у `.env` або env var.
- [x] TC-P4-2.3: Тест пропускається якщо не існує `tests/fixtures/ecl_deck.jpg` або `tests/fixtures/ecl_sideboard.jpg`.
- [x] TC-P4-2.4: Після розпізнавання `ecl_deck.jpg` — `len(main_deck) > 0`.
- [x] TC-P4-2.5: Після розпізнавання `ecl_sideboard.jpg` — `len(sideboard) > 0`.
- [x] TC-P4-2.6: Репорт генерується без помилок, `len(report.main_deck_cards) > 0`.
- [x] TC-P4-2.7: Для всіх карт з `win_rate is not None` — `grade not in UNRATED_GRADES`.
- [x] TC-P4-2.8: `generate_advice(session_mode=True)` виконується без помилок і повертає непорожній текст.
- [x] TC-P4-2.9: Stdout містить: список карт main deck, список карт sideboard, повний рендер репорту, текст порад.
- [x] TC-P4-2.10: `pytest tests/integration/test_photo_analysis.py -k draft_e2e -s` запускає тільки цей тест.

---

## Task P4-5: Better Advice Generation Status Indicator
- [x] **Done**

**Description:**
Поточний індикатор генерації порад — це Telegram popup (`callback.answer("⏳ Генерую поради...")`), який зникає через ~5 секунд і може бути не помічений юзером, якщо він не дивиться на екран. Треба замінити на стійкий, видимий індикатор стану.

**Деталі реалізації:**
1. У `handle_get_advice` (`src/bot/handlers/analyze.py`) після `await callback.answer("⏳ Генерую поради...")`:
   - Додати `await callback.message.edit_text("⏳ *Генерую рекомендації...*\n\nЦе може зайняти 10–20 секунд.", parse_mode="Markdown")` — редагує повідомлення-репорт, вимикаючи кнопки поки йде запит
   - Або відправити окреме повідомлення-плейсхолдер: `processing_msg = await callback.message.answer("⏳ Генерую рекомендації...")`, а після генерації видалити його та надіслати поради
2. Обрати підхід, який не ламає повторне натискання кнопки (кешований advice):
   - **Рекомендований підхід**: надіслати нове повідомлення `"⏳ Генерую рекомендації..."`, потім відредагувати його з порадами (або видалити і надіслати поради окремо)
3. Для `handle_get_advice` у `draft.py` — аналогічний підхід.

**Acceptance Criteria:**
- [x] TC-P4-5.1: Після натискання "Отримати поради" в чаті з'являється повідомлення з індикатором завантаження (не тільки popup, який зникає).
- [x] TC-P4-5.2: Після завершення генерації повідомлення-індикатор замінюється або зникає, і відображаються поради.
- [x] TC-P4-5.3: Якщо advice вже закешований — popup залишається, нове повідомлення-індикатор НЕ надсилається (відповідь миттєва).
- [x] TC-P4-5.4: При помилці LLM — повідомлення-індикатор оновлюється або видаляється, відображається friendly error message.
- [x] TC-P4-5.5: Unit тест перевіряє що `message.answer` викликається для показу індикатора перед LLM-викликом.

---

## Task P4-6: Card Price Button for Single Card Recognition
- [x] **Done**

**Description:**
Після розпізнавання однієї карти додати inline-кнопку "💰 Актуальна ціна". При натисканні бот отримує поточну ціну карти з Scryfall API і відображає її у відповіді.

**Ресьорч маркетплейсів:**
| Варіант | Статус | Висновок |
|---------|--------|----------|
| **Scryfall API** | Безкоштовний, без API-ключа, вже використовується | ✅ **Рекомендовано** |
| TCGPlayer API | Закритий для нових реєстрацій | ❌ |
| Cardmarket API | Закрита реєстрація | ❌ |
| MTGGoldfish | Немає публічного API, тільки скрейпінг | ❌ |
| TCGAPIs | Безкоштовний, але третя сторона | ⚠️ fallback |

**Використовуємо Scryfall** — вже є `src/parsers/scryfall.py`, безкоштовний, без ключа, оновлюється раз на день.
Endpoint: `GET https://api.scryfall.com/cards/named?exact={name}&set={set_code}`
Поле відповіді: `prices.usd` (TCGPlayer), `prices.eur` (Cardmarket), `purchase_uris.tcgplayer`, `purchase_uris.cardmarket`.

**Деталі реалізації:**
1. **Нова inline-кнопка** у `src/bot/keyboards.py`:
   ```python
   def build_single_card_keyboard(card_name: str, set_code: str) -> InlineKeyboardMarkup:
       return InlineKeyboardMarkup(inline_keyboard=[[
           InlineKeyboardButton(
               text="💰 Актуальна ціна",
               callback_data=f"card_price:{set_code}:{card_name}"
           )
       ]])
   ```
2. **`_handle_single_card`** у `analyze.py` — додати `reply_markup=build_single_card_keyboard(card_name, set_code)` до `edit_text`.
3. **Новий callback handler** `handle_card_price`:
   ```python
   @router.callback_query(F.data.startswith("card_price:"))
   async def handle_card_price(callback: CallbackQuery) -> None:
       _, set_code, card_name = callback.data.split(":", 2)
       await callback.answer("⏳ Отримую ціну...")
       price_msg = await callback.message.answer("⏳ Отримую актуальну ціну...")
       # GET https://api.scryfall.com/cards/named?exact={card_name}&set={set_code}
       # parse prices.usd, prices.eur, purchase_uris.tcgplayer, purchase_uris.cardmarket
       # format and send
   ```
4. **Формат відповіді:**
   ```
   💰 *Назва Карти* (ECL)

   🇺🇸 TCGPlayer: $2.80
   🇪🇺 Cardmarket: €1.47

   [🛒 Купити на TCGPlayer] [🛒 Купити на Cardmarket]
   ```
   Якщо `prices.usd` або `prices.eur` = `null` → "Ціна недоступна".
5. **HTTP запит** через `httpx.AsyncClient` (вже є у проекті через `src/parsers/scryfall.py`):
   ```python
   async with httpx.AsyncClient() as client:
       resp = await client.get(
           "https://api.scryfall.com/cards/named",
           params={"exact": card_name, "set": set_code.lower()},
           timeout=10.0,
       )
   ```
6. **Обмеження довжини callback_data**: Telegram обмежує callback_data до 64 байт. Якщо `set_code + card_name` > ~55 символів — використати хеш або скорочення.

**Acceptance Criteria:**
- [x] TC-P4-6.1: При показі результату розпізнавання однієї карти — відображається кнопка "💰 Актуальна ціна".
- [x] TC-P4-6.2: Натискання кнопки → HTTP запит до Scryfall `GET /cards/named?exact={name}&set={code}`.
- [x] TC-P4-6.3: Відповідь містить USD ціну (якщо `prices.usd` не null) і EUR ціну (якщо `prices.eur` не null).
- [x] TC-P4-6.4: Якщо обидві ціни null — повідомлення "Ціна недоступна для цієї карти".
- [x] TC-P4-6.5: Відповідь містить посилання (кнопки) на TCGPlayer та Cardmarket (якщо `purchase_uris` не null).
- [x] TC-P4-6.6: При помилці мережі або timeout (>10 сек) — friendly error message, не crash.
- [x] TC-P4-6.7: callback_data не перевищує 64 байт (Telegram обмеження).
- [x] TC-P4-6.8: Якщо карта не знайдена на Scryfall (404) — повідомлення "Карту не знайдено на Scryfall".
- [x] TC-P4-6.9: Unit тест перевіряє формування тексту відповіді (USD, EUR, посилання) при mock HTTP відповіді.

---

## Task P4-7: Update Bot Command List and Help/Start Messages
- [x] **Done**

**Description:**
Поточні повідомлення `/help` та `/start` не відображають реального функціоналу бота. Бракує команд `/draft`, `/set`. Також відсутня реєстрація команд через `bot.set_my_commands()` — через це в меню Telegram відображаються застарілі або відсутні команди.

**Поточний стан** (`src/bot/messages.py`):
- `/start` — не згадує `/draft`, smart photo routing, single card
- `/help` — є `/analyze`, `/history`, `/stats`, `/set`, але немає `/draft`
- `src/main.py` — немає виклику `bot.set_my_commands()`

**Деталі реалізації:**
1. **Оновити `format_start()`** у `messages.py`:
   - Прибрати вимогу надсилати з `/analyze` — тепер фото без команди розпізнається автоматично
   - Додати згадку про `draft`-режим
   - Більш стислий та точний опис
2. **Оновити `format_help()`** у `messages.py`:
   - Додати `/draft — Аналіз деки з двох фото (main + sideboard)`
   - Оновити опис `/analyze` — тепер фото можна надсилати без команди
   - Актуалізувати опис фото-роутингу (одна карта → грейд, дека → аналіз)
3. **Додати `bot.set_my_commands()`** у `src/main.py` перед `dp.start_polling()`:
   ```python
   from aiogram.types import BotCommand
   commands = [
       BotCommand(command="start", description="Розпочати роботу"),
       BotCommand(command="help", description="Довідка та команди"),
       BotCommand(command="analyze", description="Аналіз колоди (надіслати з фото)"),
       BotCommand(command="draft", description="Режим драфту: main deck + sideboard"),
       BotCommand(command="history", description="Мої попередні аналізи"),
       BotCommand(command="stats", description="Статистика карти: /stats назва"),
       BotCommand(command="set", description="Встановити активний сет: /set ECL"),
   ]
   await bot.set_my_commands(commands)
   ```

**Acceptance Criteria:**
- [x] TC-P4-7.1: `format_help()` містить опис команди `/draft`.
- [x] TC-P4-7.2: `format_help()` оновлений опис `/analyze` — фото можна надсилати без команди.
- [x] TC-P4-7.3: `format_start()` не містить інструкцію обов'язково використовувати `/analyze` з фото.
- [x] TC-P4-7.4: `format_start()` згадує smart photo routing (фото без команди → автоматичний аналіз).
- [x] TC-P4-7.5: `src/main.py` викликає `bot.set_my_commands()` перед стартом polling.
- [x] TC-P4-7.6: Список команд у `set_my_commands()` містить усі 7 команд: start, help, analyze, draft, history, stats, set.
- [x] TC-P4-7.7: Unit тест перевіряє що `format_help()` містить слово "draft".
- [x] TC-P4-7.8: Unit тест перевіряє що `format_start()` згадує можливість надсилати фото без команди.

---

## Task P4-3: /draft Conversation Mode — Chat After Advice
- [x] **Done**

**Description:**
Розширити режим `/draft`: після того як юзер отримав поради (натиснув кнопку "Отримати поради"), FSM залишається у стані `DraftState.chatting`. Будь-яке текстове повідомлення юзера у цьому стані відповідається в контексті поточної сесії `/draft`, допомагаючи з декбілдінгом.

**Деталі реалізації:**

1. **Новий FSM стан** у `draft.py`:
   ```python
   class DraftState(StatesGroup):
       waiting_main = State()
       waiting_sideboard = State()
       chatting = State()       # новий
   ```

2. **Зберігання контексту в FSM** після генерації порад:
   ```python
   await state.update_data(
       draft_main_deck=deck.main_deck,
       draft_sideboard=deck.sideboard,
       draft_set_code=set_code,
       draft_advice=advice_text,           # перші поради як контекст
       draft_conversation=[],              # історія повідомлень [{role, content}]
   )
   await state.set_state(DraftState.chatting)
   ```

3. **Новий хендлер** `@router.message(DraftState.chatting, F.text)`:
   - Читає з FSM: deck, sideboard, set_code, попередні поради, історію розмови
   - Будує system prompt з контекстом деки (як у `build_session_advice_prompt()`)
   - Додає до messages: системний контекст + попередні поради + conversational history + нове повідомлення юзера
   - Викликає `LLMClient.call_completion()`
   - Зберігає пару `[{role: user, content: ...}, {role: assistant, content: ...}]` у FSM
   - Надсилає відповідь юзеру
   - Обрізає історію до останніх `N` (наприклад, 10) обмінів щоб не перевищувати токени

4. **Системний промпт** для chat-режиму — додати `DRAFT_CHAT_SYSTEM_PROMPT` у `src/llm/prompts.py`:
   - Контекст: ти асистент з MTG Draft, знаєш конкретну деку юзера
   - Знаєш карти main deck, sideboard, грейди, вінрейти, рекомендації що вже давав
   - Відповідай на запитання, пропонуй заміни, пояснюй вибір карт

5. **Завершення сесії**: будь-яка нова команда (`/draft`, `/analyze`, `/start`) автоматично скидає FSM — aiogram робить це стандартно.

6. **Кнопка "Завершити сесію"** (опціонально, якщо потрібно явне завершення) — або просто інформувати юзера що новий `/draft` починає нову сесію.

**Acceptance Criteria:**
- [x] TC-P4-3.1: Після генерації порад FSM переходить у стан `DraftState.chatting`.
- [x] TC-P4-3.2: Текстове повідомлення у стані `chatting` отримує відповідь від LLM в контексті деки.
- [x] TC-P4-3.3: Відповідь містить контекст деки — LLM знає карти юзера (перевіряється mock тестом: у prompt є назви карт з деки).
- [x] TC-P4-3.4: Кілька повідомлень підряд — LLM отримує всю попередню розмову (conversational history зберігається у FSM).
- [x] TC-P4-3.5: Команда `/draft` у стані `chatting` — FSM скидається, починається нова сесія.
- [x] TC-P4-3.6: Нова команда `/analyze` у стані `chatting` — FSM скидається коректно, `/analyze` виконується нормально.
- [x] TC-P4-3.7: Помилка LLM під час чату → friendly error message, FSM залишається у стані `chatting` (юзер може написати ще раз).
- [x] TC-P4-3.8: Conversational history обрізається до останніх 10 обмінів (20 повідомлень), щоб не перевищувати контекст.
- [x] TC-P4-3.9: `DRAFT_CHAT_SYSTEM_PROMPT` у `src/llm/prompts.py` містить інструкцію відповідати українською та знати контекст деки.
- [x] TC-P4-3.10: Unit тест перевіряє що prompt для chat-режиму містить назви карт з main deck.

---

## Task P4-4: Production Deployment на Railway
- [x] **Done**

**Description:**
Підготувати проект до деплою на [Railway](https://railway.app). Railway запускає Docker-контейнер і надає managed PostgreSQL. Основні зміни: `railway.toml` конфіг, entrypoint-скрипт що запускає Alembic міграції перед стартом бота, обробка Railway-формату `DATABASE_URL` (`postgresql://` → `postgresql+asyncpg://`) у `src/config.py`.

**Деталі реалізації:**

1. **`railway.toml`** — конфіг у корені проекту:
   ```toml
   [build]
   dockerfile = "Dockerfile"

   [deploy]
   startCommand = "sh scripts/start.sh"
   healthcheckPath = "/healthz"
   healthcheckTimeout = 30
   restartPolicyType = "on_failure"
   restartPolicyMaxRetries = 3
   ```
   Примітка: Railway не підтримує `CMD`-style healthcheck як Docker — замість цього він перевіряє HTTP endpoint або просто restart on failure.

2. **`scripts/start.sh`** — entrypoint, що запускає міграції і бот:
   ```sh
   #!/bin/sh
   set -e
   echo "Running database migrations..."
   python -m alembic upgrade head
   echo "Starting Smart Goblin bot..."
   exec python -m src.main
   ```
   Оновити `Dockerfile`: замінити `CMD ["python", "-m", "src.main"]` на `CMD ["sh", "scripts/start.sh"]`.

3. **`src/config.py` — DATABASE_URL нормалізація:**
   Railway надає `DATABASE_URL` у форматі `postgresql://user:pass@host:port/db` (або `postgres://...`). asyncpg потребує `postgresql+asyncpg://`. Додати validator у `DatabaseSettings`:
   ```python
   @field_validator("database_url", mode="before")
   @classmethod
   def normalize_db_url(cls, v: str) -> str:
       if v.startswith("postgres://"):
           v = v.replace("postgres://", "postgresql+asyncpg://", 1)
       elif v.startswith("postgresql://"):
           v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
       return v
   ```

4. **`.env.example`** — додати коментар для Railway:
   ```
   # Railway автоматично надає DATABASE_URL через змінну середовища.
   # Підтримуються формати: postgres://, postgresql://, postgresql+asyncpg://
   ```

5. **Змінні середовища на Railway** — задокументувати які змінні треба встановити вручну у Railway dashboard:
   - `TELEGRAM_BOT_TOKEN` — токен бота (обов'язково)
   - `OPENAI_API_KEY` — ключ OpenAI (обов'язково)
   - `OPENAI_MODEL=gpt-4o` (опціонально, за замовчуванням)
   - `DATABASE_URL` — надається Railway автоматично при додаванні PostgreSQL сервісу
   - `LOG_LEVEL=INFO` (опціонально)
   - `PARSER_SCHEDULE_ENABLED=true` (опціонально)

6. **Початкове наповнення БД** — скрипт `scripts/add_set.py` виконується як Railway one-off job або вручну через Railway console після першого деплою:
   ```sh
   # У Railway console (one-time setup):
   python scripts/add_set.py ECL
   ```
   Документувати цей крок у README.

**Acceptance Criteria:**
- [x] TC-P4-4.1: `railway.toml` присутній у корені проекту з коректними `[build]` та `[deploy]` секціями.
- [x] TC-P4-4.2: `scripts/start.sh` запускає `alembic upgrade head` перед `python -m src.main`, зупиняється при помилці міграції (`set -e`).
- [x] TC-P4-4.3: `Dockerfile` використовує `scripts/start.sh` як CMD (або ENTRYPOINT).
- [x] TC-P4-4.4: `src/config.py` коректно нормалізує `postgres://...` → `postgresql+asyncpg://...`.
- [x] TC-P4-4.5: `src/config.py` коректно нормалізує `postgresql://...` → `postgresql+asyncpg://...`.
- [x] TC-P4-4.6: Вже валідний `postgresql+asyncpg://...` не змінюється validator-ом.
- [x] TC-P4-4.7: Unit тест перевіряє всі три варіанти нормалізації URL (TC-P4-4.4, 4.5, 4.6).
- [x] TC-P4-4.8: `docker build -t smart-goblin .` виконується без помилок локально.
- [x] TC-P4-4.9: `.env.example` містить коментар про Railway DATABASE_URL.
- [x] TC-P4-4.10: README містить секцію "Railway Deployment" з покроковою інструкцією: створення проекту, додавання PostgreSQL, встановлення env vars, перший деплой, запуск `add_set.py`.

---

## Execution Order

```
Task P4-1 (Smart Photo Routing)     ← [x] DONE

Task P4-2 (E2E /draft Test)         ← незалежний (тільки тести)

Task P4-5 (Better Status Indicator) ← незалежний, UX-покращення advice flow
Task P4-6 (Card Price Button)       ← залежить від P4-1 (single card handler)
Task P4-7 (Update Help/Start/Menu)  ← незалежний, але краще після P4-1

Task P4-3 (/draft Conversation)     ← незалежний від P4-1 (різні файли)

Task P4-4 (Railway Deployment)      ← незалежний, але краще після P4-1..P4-7
                                       щоб деплоїти вже повну версію
```

P4-2, P4-5, P4-7 — повністю незалежні, можна паралельно.
P4-6 — залежить від P4-1 (вже реалізовано), можна починати.
P4-3 — незалежний від P4-5/P4-6/P4-7.
P4-4 — інфраструктурна задача, краще після всіх функціональних задач.
