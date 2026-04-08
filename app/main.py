"""
HTTP POST /lead — заявка с сайта; при Telegram + @username — первое сообщение в TG.
Telethon: входящие в личку от отслеживаемых — read + typing + ответ через Comet API.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import defaultdict
from typing import Any

from aiohttp import web
from telethon import TelegramClient, events

from accounts_registry import get_accounts
from ai_messaging.channels.telethon_client import build_client

from .comet_client import complete_dialog
from .state_store import add_tracked, append_history, get_history, is_tracked, load_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# Одно сообщение для всех — без подстановки имени из анкеты
GREETING = (
    "Приветствую! Меня зовут Борис, я руководитель отдела по работе с клиентами. "
    "С каким вопросом пришли?"
)

USER_RE = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{3,31}$")

# простой rate limit по IP (заявки)
_rate: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 3600
_RATE_MAX = 20


def _client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.transport:
        peer = request.transport.get_extra_info("peername")
        if peer:
            return peer[0]
    return "unknown"


def _rate_ok(ip: str) -> bool:
    now = time.time()
    window_start = now - _RATE_WINDOW
    hits = [t for t in _rate[ip] if t > window_start]
    hits.append(now)
    _rate[ip] = hits
    return len(hits) <= _RATE_MAX


def _register_handlers(client: TelegramClient) -> None:
    @client.on(events.NewMessage(incoming=True))
    async def on_pm(event: events.NewMessage.Event) -> None:
        if not event.is_private:
            return
        sender = await event.get_sender()
        if sender is None:
            return
        uid = int(sender.id)
        if not is_tracked(uid):
            return

        text = (event.raw_text or "").strip()
        if not text:
            return

        try:
            await client.send_read_acknowledge(event.chat_id, max_id=event.id)
        except Exception as e:
            log.debug("read_ack: %s", e)

        try:
            append_history(uid, "user", text)
            hist = get_history(uid)
            async with client.action(event.chat_id, "typing"):
                reply = await asyncio.to_thread(complete_dialog, hist)
            append_history(uid, "assistant", reply)
            await event.respond(reply)
        except Exception as e:
            log.exception("comet / send: %s", e)
            await event.respond(
                "Сейчас техническая заминка — напишите ещё раз через минуту или позвоните на номер с сайта."
            )


async def _handle_lead(request: web.Request) -> web.Response:
    if request.method == "OPTIONS":
        return web.Response(status=204)
    ip = _client_ip(request)
    if not _rate_ok(ip):
        return web.json_response({"ok": False, "error": "too_many_requests"}, status=429)

    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

    telegram = (data.get("telegram") or "").strip()
    contact_method = (data.get("contactMethod") or "").strip()
    client: TelegramClient = request.app["telegram"]
    sent = False
    err = None

    if contact_method == "telegram" and telegram and USER_RE.match(telegram):
        try:
            entity = await client.get_entity(telegram)
            uid = int(entity.id)
            add_tracked(uid)
            await client.send_message(entity, GREETING)
            append_history(uid, "assistant", GREETING)
            sent = True
            log.info("Первое сообщение отправлено %s (id=%s)", telegram, uid)
        except Exception as e:
            err = str(e)
            log.exception("Не удалось написать в Telegram %s: %s", telegram, e)

    return web.json_response(
        {
            "ok": True,
            "telegram_started": sent,
            "telegram_error": err,
        }
    )


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "accounts": len(get_accounts())})


async def _init_app(app: web.Application) -> None:
    client = build_client(0)
    _register_handlers(client)
    await client.start()
    app["telegram"] = client
    load_state()
    log.info("Telethon подключён, отслеживаем диалоги с лидов из state.")


async def _cleanup_app(app: web.Application) -> None:
    client: TelegramClient = app.get("telegram")
    if client:
        await client.disconnect()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/lead", _handle_lead)
    app.router.add_get("/health", _health)
    app.on_startup.append(_init_app)
    app.on_cleanup.append(_cleanup_app)
    return app


def main() -> None:
    from pathlib import Path

    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass

    port = int(os.environ.get("FNR_HTTP_PORT", "8765"))
    logging.info("Старт aiohttp на 127.0.0.1:%s", port)
    web.run_app(create_app(), host="127.0.0.1", port=port, print=None, access_log=log)


if __name__ == "__main__":
    main()
