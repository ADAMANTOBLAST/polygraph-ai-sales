"""HTTP API для админки: список диалогов, переписка, отправка, флаг ИИ."""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from telethon import TelegramClient

from .state_store import append_history, get_history, load_state, save_state

log = logging.getLogger(__name__)


def _st() -> dict[str, Any]:
    return load_state()


def _ai_disabled(uid: int) -> bool:
    raw = _st().get("ai_disabled_uids") or []
    return uid in raw


def _set_ai_disabled(uid: int, disabled: bool) -> None:
    st = _st()
    lst = list(st.get("ai_disabled_uids") or [])
    if disabled:
        if uid not in lst:
            lst.append(uid)
    else:
        lst = [x for x in lst if x != uid]
    st["ai_disabled_uids"] = lst
    save_state()


async def handle_admin_chats(request: web.Request) -> web.Response:
    client: TelegramClient = request.app["telegram"]
    st = _st()
    chats: list[dict[str, Any]] = []
    for uid in st.get("tracked_user_ids") or []:
        uid = int(uid)
        hist = get_history(uid)
        preview = ""
        if hist:
            preview = (hist[-1].get("content") or "")[:160]
        title = str(uid)
        username = ""
        try:
            ent = await client.get_entity(uid)
            if ent:
                fn = getattr(ent, "first_name", None) or ""
                ln = getattr(ent, "last_name", None) or ""
                title = (fn + " " + ln).strip() or str(uid)
                un = getattr(ent, "username", None) or ""
                if un:
                    username = "@" + un
        except Exception as e:
            log.debug("get_entity %s: %s", uid, e)
        ua = st.get("uid_account") or {}
        aid = ua.get(str(uid), 0)
        try:
            aid = int(aid)
        except (TypeError, ValueError):
            aid = 0
        chats.append(
            {
                "uid": uid,
                "title": title,
                "username": username,
                "preview": preview,
                "account_id": aid,
                "ai_disabled": _ai_disabled(uid),
            }
        )
    failed = list(st.get("failed_leads") or [])
    return web.json_response({"ok": True, "chats": chats, "failed_leads": failed})


async def handle_admin_chat_thread(request: web.Request) -> web.Response:
    uid = int(request.match_info["uid"])
    messages = get_history(uid)
    return web.json_response(
        {"ok": True, "messages": messages, "ai_disabled": _ai_disabled(uid)}
    )


async def handle_admin_send(request: web.Request) -> web.Response:
    uid = int(request.match_info["uid"])
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
    text = (data.get("text") or "").strip()
    if not text:
        return web.json_response({"ok": False, "error": "empty"}, status=400)
    client: TelegramClient = request.app["telegram"]
    try:
        await client.send_message(uid, text)
    except Exception as e:
        log.exception("admin send %s: %s", uid, e)
        return web.json_response({"ok": False, "error": str(e)[:200]}, status=500)
    append_history(uid, "assistant", text)
    return web.json_response({"ok": True})


async def handle_admin_ai(request: web.Request) -> web.Response:
    uid = int(request.match_info["uid"])
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
    off = bool(data.get("ai_disabled"))
    _set_ai_disabled(uid, off)
    return web.json_response({"ok": True, "ai_disabled": off})


def setup_admin_routes(app: web.Application) -> None:
    app.router.add_get("/admin/chats", handle_admin_chats)
    app.router.add_get("/admin/chats/{uid}", handle_admin_chat_thread)
    app.router.add_post("/admin/chats/{uid}/send", handle_admin_send)
    app.router.add_post("/admin/chats/{uid}/ai", handle_admin_ai)
