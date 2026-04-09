"""HTTP API для админки: список диалогов, переписка, отправка, флаг ИИ."""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from telethon import TelegramClient

from accounts_registry import list_accounts_for_admin

from .bitrix import bitrix_ping_crm, sync_bitrix_chat_for_uid
from .sales_sync import load_sales_sync, write_sales_sync
from .state_store import append_history, get_history, get_uid_account, load_state, save_state
from .tg_pool import get_telegram_client

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


async def handle_team_accounts(_request: web.Request) -> web.Response:
    """Список Telegram-аккаунтов с сервера — чипы fnr-acc-* в переписках у всех браузеров."""
    return web.json_response({"ok": True, "accounts": list_accounts_for_admin()})


async def handle_admin_chats(request: web.Request) -> web.Response:
    st = _st()
    chats: list[dict[str, Any]] = []
    for uid in st.get("tracked_user_ids") or []:
        uid = int(uid)
        ua = st.get("uid_account") or {}
        aid_raw = ua.get(str(uid), 0)
        try:
            aid_ent = int(aid_raw)
        except (TypeError, ValueError):
            aid_ent = 0
        hist = get_history(uid, aid_ent)
        preview = ""
        if hist:
            preview = (hist[-1].get("content") or "")[:160]
        title = str(uid)
        username = ""
        client: TelegramClient = get_telegram_client(request.app, aid_ent)
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
    aid = get_uid_account(uid)
    messages = get_history(uid, aid)
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
    aid = get_uid_account(uid)
    if aid is None:
        aid = 0
    client: TelegramClient = get_telegram_client(request.app, int(aid))
    try:
        await client.send_message(uid, text)
    except Exception as e:
        log.exception("admin send %s: %s", uid, e)
        return web.json_response({"ok": False, "error": str(e)[:200]}, status=500)
    aid = get_uid_account(uid)
    append_history(uid, "assistant", text, account_id=aid)
    try:
        await sync_bitrix_chat_for_uid(uid)
    except Exception as e:
        log.debug("bitrix sync after admin send uid=%s: %s", uid, e)
    return web.json_response({"ok": True})


async def handle_admin_sales_sync_get(request: web.Request) -> web.Response:
    """Текущие настройки с сервера (fnr_sales_sync.json) для подтягивания в админку."""
    blob = load_sales_sync()
    people = blob.get("people")
    if not isinstance(people, list):
        people = []
    return web.json_response(
        {
            "ok": True,
            "lead_active_account_ids": blob.get("lead_active_account_ids"),
            "accounts": blob.get("accounts") if isinstance(blob.get("accounts"), dict) else {},
            "people": people,
        }
    )


async def handle_admin_sales_sync(request: web.Request) -> web.Response:
    """POST тело как в buildSalesSyncPayload(): lead_active_account_ids + accounts + people."""
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
    if not isinstance(data, dict):
        return web.json_response({"ok": False, "error": "invalid_body"}, status=400)
    # Не затирать people[], если клиент прислал пустой список (нет fnr-acc в localStorage) или ключ пропал.
    existing = load_sales_sync()
    incoming = data.get("people")
    if not isinstance(incoming, list) or len(incoming) == 0:
        prev = existing.get("people")
        if isinstance(prev, list) and len(prev) > 0:
            data["people"] = prev
    write_sales_sync(data)
    acc_n = len(data.get("accounts") or {})
    log.info("sales-sync: lead_active=%s, accounts=%s", data.get("lead_active_account_ids"), acc_n)
    return web.json_response({"ok": True})


async def handle_admin_bitrix_ping(request: web.Request) -> web.Response:
    """GET: проверка Bitrix вебхука (crm.lead.fields)."""
    payload = await bitrix_ping_crm()
    return web.json_response(payload)


async def handle_admin_bitrix_resync_all(request: web.Request) -> web.Response:
    """POST без тела: для всех Telegram uid с привязкой к лиду — заново отправить переписку в Bitrix."""
    st = load_state()
    meta = st.get("bitrix_uid_meta") or {}
    errors: list[str] = []
    n = 0
    for uid_str in meta.keys():
        try:
            uid = int(uid_str)
            await sync_bitrix_chat_for_uid(uid)
            n += 1
        except Exception as e:
            log.exception("bitrix resync uid=%s", uid_str)
            errors.append(f"{uid_str}: {e!s}"[:160])
    return web.json_response({"ok": True, "synced": n, "errors": errors[:30]})


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
    app.router.add_get("/team-accounts", handle_team_accounts)
    app.router.add_get("/admin/sales-sync", handle_admin_sales_sync_get)
    app.router.add_post("/admin/sales-sync", handle_admin_sales_sync)
    app.router.add_get("/admin/bitrix-ping", handle_admin_bitrix_ping)
    app.router.add_post("/admin/bitrix-resync-chats", handle_admin_bitrix_resync_all)
    app.router.add_get("/admin/chats", handle_admin_chats)
    app.router.add_get("/admin/chats/{uid}", handle_admin_chat_thread)
    app.router.add_post("/admin/chats/{uid}/send", handle_admin_send)
    app.router.add_post("/admin/chats/{uid}/ai", handle_admin_ai)
