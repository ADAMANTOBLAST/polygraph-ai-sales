# Быстрый запуск PolygraphAiSales

Предполагается Linux (или macOS) и **Python 3.12+**. На production сервере процесс слушает только localhost; публикация наружу — через **nginx**.

## 1. Клонирование и виртуальное окружение

```bash
git clone <url> PolygraphAiSales
cd PolygraphAiSales
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.lock.txt
# Альтернатива без pin-версий: ./.venv/bin/pip install -r requirements.txt
```

## 2. Переменные окружения

```bash
cp .env.example .env
```

Минимально для диалогов с ИИ:

- **`COMET_API_KEY`** (или `COMETAPI_KEY`) — ключ Comet API.

Для CRM (на production обязательно):

- **`BITRIX_INCOMING_WEBHOOK`** — базовый URL входящего вебхука Bitrix24; полный чеклист методов REST — в **`.env.example`**. Режима отключения CRM в коде нет: без вебхука лиды создаются только в Telegram, в Bitrix не уходят.

Опционально:

- **`FNR_HTTP_PORT`** — порт (по умолчанию `8765`).
- **`VOXIMPLANT_WEBHOOK_SECRET`** — защита `POST` на вебхук телефонии.

## 3. Реестр аккаунтов и сессии Telegram

```bash
cp accounts_registry.json.example accounts_registry.json
```

Отредактируйте **`accounts_registry.json`**: `id`, `phone`, `api_id`, `api_hash`, `session_path` для каждого менеджерского аккаунта.

Каталог **`sessions/`** должен содержать файлы `*.session`, согласованные с `session_path` (авторизация Telethon — отдельной процедурой, см. `check_session.py` при необходимости).

**В git не коммитить:** `accounts_registry.json` с секретами, папку `sessions/`.

## 4. Данные runtime

При первом запуске создастся **`data/fnr_state.json`** (треки, истории, привязки uid → аккаунт, журнал звонков).

Настройки команды из админки — **`data/fnr_sales_sync.json`** (можно создать пустым или заполнить через UI после деплоя).

## 5. Запуск

```bash
./restart.sh
```

Лог по умолчанию: **`bot.log`** в корне проекта.

Проверка:

```bash
curl -s http://127.0.0.1:8765/health
```

Пока поднимается пул Telethon, возможен ответ **`503`** на `/lead` с телом `warming_up` — через короткое время повторите (см. `telegram_ready` в `/health`).

## 6. nginx (пример логики)

- Локация **`/fnr-api/`** → `proxy_pass http://127.0.0.1:8765/` (или иной порт из `FNR_HTTP_PORT`).
- Статику лендинга и админки размещает **`deploy.sh`** под `/var/www/...` — путь смотрите в скрипте.

## 7. Тесты

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

## 8. Частые проблемы

| Симптом | Что проверить |
|---------|----------------|
| `502` у nginx сразу после рестарта | Процесс уже слушает порт, но Telethon ещё подключается — смотреть `/health` и лог |
| Нет ответа ИИ | `COMET_API_KEY`, лимиты Comet |
| Лиды не в Bitrix | задан `BITRIX_INCOMING_WEBHOOK`, права REST по чеклисту в `.env.example` |
| Ни один Telegram не поднят | `sessions/`, `accounts_registry.json`, сеть до Telegram |

---

Далее: [ARCHITECTURE.md](ARCHITECTURE.md), [PROJECT.md](PROJECT.md).
