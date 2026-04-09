"""
HTTP POST /lead — заявка с сайта; при Telegram + @username — первое сообщение в TG.
Telethon: входящие в личку от отслеживаемых — read + typing + ответ через Comet API.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from typing import Any

from aiohttp import web
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.errors.rpcerrorlist import PeerFloodError

from accounts_registry import get_accounts
from ai_messaging.channels.telethon_client import build_client

from .admin_api import setup_admin_routes
from .bitrix import create_lead_from_form
from .state_store import add_tracked, append_history, load_state
from .telegram_profiles import greeting_for_account
from .tg_handlers import register_private_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

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


def _format_telegram_error(exc: BaseException) -> str:
    if isinstance(exc, FloodWaitError):
        return f"Лимит Telegram: подождите ~{exc.seconds} с и повторите отправку."
    if isinstance(exc, PeerFloodError):
        return (
            "Telegram временно ограничил исходящие сообщения. "
            "Попробуйте позже или напишите нам в Telegram сами."
        )
    s = str(exc)
    if "Too many requests" in s or "FLOOD_WAIT" in s.upper():
        return "Лимит сообщений Telegram. Попробуйте через несколько минут."
    if "USERNAME_NOT_OCCUPIED" in s or "No user has" in s or "not found" in s.lower():
        return "Такой username в Telegram не найден. Проверьте написание."
    if "can't write" in s.lower() or "write in this chat" in s.lower():
        return (
            "Не удалось написать первое сообщение в Telegram (ограничения аккаунта). "
            "Мы свяжемся по телефону из заявки."
        )
    return s[:220]


def _rate_ok(ip: str) -> bool:
    now = time.time()
    window_start = now - _RATE_WINDOW
    hits = [t for t in _rate[ip] if t > window_start]
    hits.append(now)
    _rate[ip] = hits
    return len(hits) <= _RATE_MAX


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
            greet = greeting_for_account(0)
            await client.send_message(entity, greet)
            append_history(uid, "assistant", greet)
            sent = True
            log.info("Первое сообщение отправлено %s (id=%s)", telegram, uid)
        except Exception as e:
            err = _format_telegram_error(e)
            log.exception("Не удалось написать в Telegram %s: %s", telegram, e)

    bitrix_lead_id = None
    bitrix_error = None
    try:
        bitrix_lead_id, bitrix_error = await create_lead_from_form(data)
    except Exception as e:
        log.exception("Bitrix: %s", e)
        bitrix_error = str(e)[:200]

    body: dict[str, Any] = {
        "ok": True,
        "telegram_started": sent,
        "telegram_error": err,
    }
    if bitrix_lead_id is not None:
        body["bitrix_lead_id"] = bitrix_lead_id
    if bitrix_error:
        body["bitrix_error"] = bitrix_error
    return web.json_response(body)


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "accounts": len(get_accounts())})


async def _init_app(app: web.Application) -> None:
    client = build_client(0)
    register_private_handlers(client)
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
    setup_admin_routes(app)
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
