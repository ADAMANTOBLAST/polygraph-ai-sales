# Журнал звонков в админке (fnr-api)

## Автоматически из Voximplant

В сценариях `scenario_elevenlabs_inbound_boris.js` и `scenario_elevenlabs_handoff_by.js` при **завершении звонка** отправляется POST с полями `call_ended`, `caller_id`, `duration_sec`, `session_id` и т.д.  
В начале файла задайте **`FNR_VOICE_WEBHOOK_URL`** (публичный URL вашего fnr-api, обычно `https://<домен>/fnr-api/voximplant/webhook`) и при необходимости **`FNR_VOICE_WEBHOOK_SECRET`** (тот же, что `VOXIMPLANT_WEBHOOK_SECRET` на сервере).

После **публикации** обновлённого сценария в Voximplant записи начнут появляться в админке без ручного `curl`.

---

Записи также появляются, если любой клиент шлёт **POST** с JSON телом на:

- `https://<ваш-домен>/fnr-api/voximplant/webhook`  
  (или тот же путь, что уже проксируется на fnr-api)

## Защита

Если в `.env` задан `VOXIMPLANT_WEBHOOK_SECRET`, добавьте к запросу один из вариантов:

- заголовок `X-Voximplant-Secret: <секрет>`
- или `?token=<секрет>`
- или `Authorization: Bearer <секрет>`

## Поля JSON (все опциональны, но нужно хоть что-то осмысленное)

Сохраняются ключи (при необходимости дополним список в коде):

| Поле | Описание |
|------|----------|
| `session_id` | id сессии Voximplant |
| `caller_id` | номер абонента (строка) |
| `duration_sec` | длительность в секундах |
| `summary` | краткое саммари разговора |
| `transcript` | полный или частичный транскрипт |
| `recording_url` | ссылка на запись, если есть |
| `elevenlabs_conversation_id` | id разговора ElevenLabs |
| `destination` | куда звонили |
| `caller_name` | имя, если известно |
| `hangup_reason` | причина завершения |
| `event` | служебно; `ping` не сохраняется |

Можно обернуть данные во вложенный объект `call: { ... }` — поля подтянутся.

## Пример тела POST

```json
{
  "session_id": "4138101031",
  "caller_id": "779051614193",
  "duration_sec": 110,
  "summary": "Интерес к этикеткам для молока, тираж ~10 тыс., нужен технолог по макетам.",
  "elevenlabs_conversation_id": "conv_9601kntmy30ee1gbmx4agzp5wc3d"
}
```

## Отправка из сценария Voximplant (идея)

В конце звонка (`Call.Disconnected` или после закрытия ElevenLabs) вызвать HTTP POST на URL вебхука с `Net.httpRequest` (см. документацию VoxEngine), тело — JSON строкой, заголовок `Content-Type: application/json`, при необходимости — секрет.

Собрать `duration` из `call.duration()` или таймера, `caller_id` из `call.callerid()`.

Саммари/транскрипт ElevenLabs не приходят автоматически в VoxEngine — их нужно получать **отдельно** (API ElevenLabs по `conversation_id`, если сохраняете id из WebSocket в сценарии) или пока слать только технические поля + короткий текст из своей логики.

## Что сделать на сервере

1. Прокси nginx: путь `/fnr-api/` → fnr-api (как для `/lead`).
2. Перезапуск fnr-api после обновления кода.
3. Не коммитить секрет вебхука в git.

Хранение: последние **500** записей в `data/fnr_state.json` → ключ `voice_calls`.
