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

## Распределение лидов между менеджерами (round-robin)

Новые заявки с сайта (`POST /lead` с Telegram) закрепляются за аккаунтами `fnr-acc-*` **по кругу**: первый новый клиент — первому менеджеру из списка, следующий — второму, … после последнего снова первый. Очередь хранится в `data/fnr_state.json` в поле `lead_rr_idx` (перезапуск сервиса порядок не обнуляет).

Состав очереди задаётся в админке: **`lead_active_account_ids`** в синхронизации sales (`fnr_sales_sync.json`) — только эти подключённые аккаунты участвуют в распределении. Если список пустой, новые лиды не маршрутизируются по RR (см. код: fallback на первый аккаунт с предупреждением в логах).

Повторное обращение **того же** пользователя Telegram идёт тому же менеджеру, пока он в отпуске не снят с линии — тогда срабатывает переназначение (`resolve_account_for_lead_dialog`).

Реализация: `app/manager_router.py` (`pick_account_for_new_lead`), списки допустимых id — `app/sales_sync.py` (`lead_eligible_account_ids`, `eligible_active_account_ids`).

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
