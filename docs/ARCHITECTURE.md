# Архитектура PolygraphAiSales (fnr-api)

## Назначение

- **HTTP API** (`aiohttp`): заявки с сайта (`POST /lead`), админка (`/admin/*`), синхронизация sales, Bitrix, вебхук Voximplant.
- **Telethon**: пул Telegram-аккаунтов из `accounts_registry.json` + `sessions/*.session`, входящие в личку, ответы через Comet.
- **Статика**: лендинг `flexn.html`, админка `admin/` (копируется на сервер через `deploy.sh`).

## Структура каталогов

| Путь | Роль |
|------|------|
| `app/` | Код приложения: `main.py` (роуты, lifecycle), `admin_api.py`, `tg_handlers.py`, `state_store.py`, `bitrix.py`, `comet_client.py`, `manager_router.py`, `sales_sync.py` |
| `admin/` | SPA админки (HTML + встроенный JS), без сборки |
| `assets/` | Общие CSS/JS для админки и лендинга |
| `data/` | `fnr_state.json` — треки, истории диалогов, журнал `voice_calls` (на сервере, не в git) |
| `sessions/` | Файлы сессий Telethon (не в git) |
| `voximplant/` | Примеры сценариев VoxEngine (копируются в панель Voximplant) |
| `accounts_registry.json` | Реестр Telegram-аккаунтов (на сервере, не в git) |

Поток данных: **сайт** → nginx `/fnr-api/` → **fnr-api** на `127.0.0.1:8765` → `.env`, `data/`, Bitrix, Telegram.

## Переменные окружения (ключи)

| Переменная | Обязательность | Назначение |
|------------|----------------|------------|
| `COMET_API_KEY` или `COMETAPI_KEY` | Да, для ИИ | API Comet (диалоги) |
| `BITRIX_INCOMING_WEBHOOK` или `BITRIX_WEBHOOK_URL` | Для CRM | Входящий вебхук Bitrix24 REST |
| `FNR_HTTP_PORT` | Нет (по умолчанию 8765) | Порт локального aiohttp |
| `VOXIMPLANT_WEBHOOK_SECRET` | Нет | Защита вебхука телефонии (заголовок / `?token=` ) |

Секреты в репозиторий не коммитить; шаблон — `.env.example`.

## Расширение

- Новые HTTP-эндпоинты: регистрация в `app/main.py` или `app/admin_api.py`, бизнес-логика в `app/`.
- Изменения в UI админки: `admin/index.html`, стили `assets/css/admin.css`, при необходимости `assets/js/`.
