# 🧙 Smart Goblin

AI-помічник для аналізу та оптимізації MTG Draft колод.

Telegram-бот, який аналізує фото колоди (скріншот MTG Arena або фото фізичних карт), розпізнає карти за допомогою GPT-4o Vision, збагачує їх статистикою з 17lands та Scryfall, і генерує персоналізовані поради українською мовою.

## Можливості

- **Розпізнавання карт** — GPT-4o Vision аналізує зображення та ідентифікує карти
- **Підтримка двох форматів** — скріншоти MTG Arena та фото фізичних карт
- **Автоматичне визначення сету** — система розпізнає сет за картами на фото
- **Статистика карт** — рейтинги та win rate з 17lands
- **AI-поради** — рекомендації щодо оптимізації колоди від GPT-4o
- **Історія аналізів** — перегляд минулих аналізів

## Команди бота

| Команда | Опис |
|---------|------|
| `/start` | Привітання та інструкція |
| `/help` | Довідка по командах |
| `/analyze` + фото | Аналіз колоди з фотографії |
| `/history` | Список минулих аналізів |
| `/stats {card_name}` | Статистика конкретної карти |

## Встановлення

### Вимоги

- Python 3.11+
- PostgreSQL 15+
- Docker (опціонально)

### Локальне встановлення

```bash
# Клонування репозиторію
git clone https://github.com/your-username/smart-goblin.git
cd smart-goblin

# Створення віртуального середовища
python -m venv .venv

# Активація (Windows)
.venv\Scripts\activate

# Активація (Linux/Mac)
source .venv/bin/activate

# Встановлення залежностей
pip install -e .
pip install -e ".[dev]"
```

### Налаштування

```bash
# Копіювання прикладу конфігурації
cp .env.example .env
```

Відредагуйте `.env` та вкажіть:

```env
TELEGRAM_BOT_TOKEN=<ваш токен від @BotFather>
OPENAI_API_KEY=<ваш API ключ OpenAI>
DATABASE_URL=postgresql+asyncpg://goblin:password@localhost:5432/smart_goblin
```

### База даних

**Варіант 1: Docker (рекомендовано)**

```bash
# Windows
.\scripts\dev-db.ps1 start

# Linux/Mac
./scripts/dev-db.sh start
```

**Варіант 2: Існуюча PostgreSQL**

Створіть базу даних `smart_goblin` та оновіть `DATABASE_URL` у `.env`.

**Застосування міграцій:**

```bash
alembic upgrade head
```

### Запуск

```bash
python -m src.main
```

## Docker

### Production

```bash
# Збірка та запуск
docker-compose up -d

# Перегляд логів
docker-compose logs -f bot
```

### Development

```bash
# Тільки база даних
docker-compose -f docker-compose.dev.yml up -d

# З pgAdmin UI
docker-compose -f docker-compose.dev.yml --profile tools up -d
```

pgAdmin доступний на http://localhost:5050 (admin@local.dev / admin)

## Railway Deployment

[Railway](https://railway.app) — рекомендована платформа для деплою Smart Goblin. Надає managed PostgreSQL та автоматичний CI/CD з GitHub.

### Покрокова інструкція

**Крок 1: Створення проекту на Railway**

1. Зайдіть на [railway.app](https://railway.app) та увійдіть через GitHub.
2. Натисніть **New Project** → **Deploy from GitHub repo**.
3. Виберіть репозиторій `smart-goblin`.
4. Railway автоматично виявить `railway.toml` і збере Docker-образ.

**Крок 2: Додавання PostgreSQL**

1. У проекті натисніть **+ New** → **Database** → **PostgreSQL**.
2. Railway автоматично додасть змінну `DATABASE_URL` до вашого сервісу.
3. Формат `postgres://...` підтримується — бот нормалізує його автоматично.

**Крок 3: Встановлення змінних середовища**

У налаштуваннях сервісу → вкладка **Variables** додайте:

| Змінна | Значення | Обов'язково |
|--------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | токен від @BotFather | ✅ |
| `OPENAI_API_KEY` | ключ OpenAI | ✅ |
| `DATABASE_URL` | надається Railway автоматично | ✅ |
| `OPENAI_MODEL` | `gpt-4o` | за замовч. |
| `LOG_LEVEL` | `INFO` | за замовч. |
| `PARSER_SCHEDULE_ENABLED` | `true` | за замовч. |

**Крок 4: Перший деплой**

Railway автоматично запустить деплой після налаштування змінних. При старті контейнера `scripts/start.sh` автоматично виконає міграції:

```
Running database migrations...
Starting Smart Goblin bot...
```

**Крок 5: Початкове наповнення бази даних**

Після першого деплою потрібно завантажити дані карт для вашого MTG сету. У Railway відкрийте **консоль** вашого сервісу (вкладка **Shell**):

```sh
# Завантажити дані для сету (наприклад, Outlaws of Thunder Junction = OTJ)
python scripts/add_set.py OTJ

# Або для іншого сету:
python scripts/add_set.py BLB
python scripts/add_set.py DSK
```

Скрипт завантажить дані карт з Scryfall та статистику з 17lands (~2-5 хвилин).

### Оновлення

Railway автоматично перебудовує та перезапускає сервіс при кожному push до основної гілки. Міграції виконуються автоматично при старті.

### Перевірка роботи

```sh
# Переглянути логи у Railway dashboard або через CLI:
railway logs
```

## Тестування

```bash
# Всі тести
pytest

# З покриттям коду
pytest --cov=src --cov-report=html

# Конкретний модуль
pytest tests/test_vision/
```

Тести використовують [testcontainers](https://testcontainers.com/) для автоматичного створення PostgreSQL контейнера.

## Структура проекту

```
src/
├── main.py           # Точка входу
├── config.py         # Конфігурація (pydantic-settings)
├── bot/              # Telegram бот (aiogram 3.x)
│   ├── handlers/     # Обробники команд
│   ├── keyboards.py  # Inline клавіатури
│   └── messages.py   # Шаблони повідомлень
├── core/             # Бізнес-логіка
│   ├── analyzer.py   # Аналіз колоди
│   ├── advisor.py    # Генерація порад
│   └── deck.py       # Структури даних
├── vision/           # Розпізнавання карт (GPT-4o Vision)
├── llm/              # OpenAI клієнт
├── parsers/          # Парсери Scryfall та 17lands
├── db/               # База даних (SQLAlchemy 2.x async)
└── reports/          # Генерація звітів
```

## Технології

- **Python 3.11+** з async/await
- **aiogram 3.x** — Telegram Bot API
- **OpenAI GPT-4o** — Vision та генерація тексту
- **PostgreSQL 15+** — база даних
- **SQLAlchemy 2.x** — async ORM
- **Alembic** — міграції
- **APScheduler** — оновлення даних за розкладом

## Ліцензія

MIT
