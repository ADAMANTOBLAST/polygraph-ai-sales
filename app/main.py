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
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.errors.rpcerrorlist import PeerFloodError

from accounts_registry import get_accounts
from ai_messaging.channels.telethon_client import build_client

from .admin_api import setup_admin_routes
from .voximplant_webhook import setup_voximplant_routes
from .bitrix import create_lead_from_form, build_lead_comments_initial, sync_bitrix_chat_for_uid
from .manager_router import resolve_account_for_lead_dialog
from .state_store import add_tracked, append_history, load_state, set_bitrix_lead_link
from .telegram_profiles import first_and_second_greeting
from .tg_handlers import register_private_handlers
from .tg_pool import get_telegram_client

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
    sent = False
    err = None
    uid = None

    if contact_method == "telegram" and telegram and USER_RE.match(telegram):
        try:
            # uid узнаём с любого клиента; peer для send_message должен быть от того же клиента,
            # что отправляет (иначе Telethon: invalid Peer).
            client_any: TelegramClient = request.app["telegram"]
            entity = await client_any.get_entity(telegram)
            uid = int(entity.id)
            add_tracked(uid)
            aid, _ = resolve_account_for_lead_dialog(uid)
            client = get_telegram_client(request.app, aid)
            first_greet, second_greet = first_and_second_greeting(aid)
            try:
                peer = await client.get_entity(telegram)
            except Exception:
                peer = telegram
            await client.send_message(peer, first_greet)
            append_history(uid, "assistant", first_greet, account_id=aid)
            if second_greet:
                await asyncio.sleep(0.35)
                await client.send_message(peer, second_greet)
                append_history(uid, "assistant", second_greet, account_id=aid)
            sent = True
            log.info(
                "Приветствие отправлено %s (id=%s), второе сообщение: %s",
                telegram,
                uid,
                bool(second_greet),
            )
        except Exception as e:
            err = _format_telegram_error(e)
            log.exception("Не удалось написать в Telegram %s: %s", telegram, e)

    bitrix_lead_id = None
    bitrix_deal_id = None
    bitrix_error = None
    try:
        bitrix_lead_id, bitrix_error = await create_lead_from_form(data)
    except Exception as e:
        log.exception("Bitrix: %s", e)
        bitrix_error = str(e)[:200]

    lead_header = build_lead_comments_initial(data)
    if bitrix_lead_id is not None:
        conv_deal, conv_err = await convert_lead_to_deal(bitrix_lead_id)
        if conv_deal:
            bitrix_deal_id = conv_deal
        elif conv_err:
            log.warning(
                "Bitrix crm.lead.convert для лида %s не дал сделку: %s — пробуем crm.deal.add",
                bitrix_lead_id,
                conv_err,
            )
            fb_deal, fb_err = await create_deal_from_lead_fallback(
                bitrix_lead_id,
                "Заявка с сайта Flex&Roll PRO",
                lead_header,
            )
            if fb_deal:
                bitrix_deal_id = fb_deal
            elif fb_err:
                log.warning("Bitrix fallback сделки для лида %s: %s", bitrix_lead_id, fb_err)

    if bitrix_lead_id is not None and uid is not None:
        try:
            set_bitrix_lead_link(
                uid,
                bitrix_lead_id,
                lead_header,
                deal_id=bitrix_deal_id,
            )
            await sync_bitrix_chat_for_uid(uid)
        except Exception as e:
            log.exception("Bitrix sync link: %s", e)

    body: dict[str, Any] = {
        "ok": True,
        "telegram_started": sent,
        "telegram_error": err,
    }
    if bitrix_lead_id is not None:
        body["bitrix_lead_id"] = bitrix_lead_id
    if bitrix_deal_id is not None:
        body["bitrix_deal_id"] = bitrix_deal_id
    if bitrix_error:
        body["bitrix_error"] = bitrix_error
    return web.json_response(body)


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "accounts": len(get_accounts())})


async def _init_app(app: web.Application) -> None:
    clients: dict[int, TelegramClient] = {}
    for aid in sorted(get_accounts().keys()):
        try:
            c = build_client(aid)
            await c.start()
            register_private_handlers(c, int(aid))
            clients[int(aid)] = c
            log.info("Telethon аккаунт id=%s подключён", aid)
        except Exception as e:
            log.exception("Telethon аккаунт id=%s не поднят: %s", aid, e)
    if not clients:
        raise RuntimeError("Ни одна Telegram-сессия не авторизована (sessions/*.session)")
    app["telegram_clients"] = clients
    app["telegram"] = clients.get(0) or next(iter(clients.values()))
    load_state()
    log.info("Telethon: пул из %s сессий (лиды и ответы — с аккаунта ответственного)", len(clients))


async def _cleanup_app(app: web.Application) -> None:
    clients: dict[int, TelegramClient] = app.get("telegram_clients") or {}
    for c in clients.values():
        try:
            await c.disconnect()
        except Exception as e:
            log.debug("telethon disconnect: %s", e)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/lead", _handle_lead)
    app.router.add_get("/health", _health)
    setup_voximplant_routes(app)
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
