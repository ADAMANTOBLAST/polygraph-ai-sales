"""Bitrix24: создание лида и обновление комментария с перепиской Telegram."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp

from .state_store import get_bitrix_lead_link, get_history, get_uid_account

log = logging.getLogger(__name__)

_MAX_COMMENTS = 63000


def bitrix_lead_add_url() -> str:
    """
    Полный URL метода из .env, например:
    https://YOUR.bitrix24.ru/rest/1/xxxxxxxx/crm.lead.add.json
    Допустимо без суффикса — добавим /crm.lead.add.json
    """
    raw = (os.environ.get("BITRIX_INCOMING_WEBHOOK") or os.environ.get("BITRIX_WEBHOOK_URL") or "").strip()
    if not raw:
        return ""
    u = raw.rstrip("/")
    if "crm.lead.add" in u:
        return u if u.endswith(".json") else u + ".json"
    return u + "/crm.lead.add.json"


def bitrix_webhook_base() -> str:
    """База вебхука …/rest/USER/TOKEN/ для вызова любых методов REST."""
    raw = (os.environ.get("BITRIX_INCOMING_WEBHOOK") or os.environ.get("BITRIX_WEBHOOK_URL") or "").strip()
    if not raw:
        return ""
    u = raw.rstrip("/")
    if "/crm." in u:
        u = u[: u.index("/crm.")]
    return u.rstrip("/") + "/"


def bitrix_method_url(method: str) -> str:
    base = bitrix_webhook_base()
    if not base:
        return ""
    m = method.strip()
    if m.endswith(".json"):
        return base + m
    return base + m + ".json"


def _method_labels() -> dict[str, str]:
    return {"telegram": "Telegram", "phone": "Телефон", "email": "E-mail"}


def build_lead_comment_header(data: dict[str, Any]) -> str:
    """Текст для поля COMMENTS: данные заявки (без блока переписки)."""
    contact_method = (data.get("contactMethod") or "").strip()
    contact_detail = (data.get("contactDetail") or "").strip()
    telegram = (data.get("telegram") or "").strip()
    method_label = _method_labels().get(contact_method, contact_method or "—")
    lines = [
        "Источник: сайт Flex&Roll PRO",
        f"Предпочитаемая связь: {method_label}",
        f"Контакт: {contact_detail or '—'}",
    ]
    if telegram:
        lines.append(f"Telegram: {telegram}")
    return "\n".join(lines)


def build_lead_comments_initial(data: dict[str, Any]) -> str:
    """Тот же текст COMMENTS, что уходит в crm.lead.add (ФИО + заявка)."""
    name = (data.get("name") or "").strip()
    header_text = build_lead_comment_header(data)
    if name:
        return f"ФИО: {name}\n{header_text}"
    return header_text


def format_chat_for_bitrix(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for m in messages:
        role = (m.get("role") or "").lower()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"Клиент: {content}")
        else:
            lines.append(f"Менеджер: {content}")
    return "\n".join(lines) if lines else "(сообщений пока нет)"


async def _bitrix_post(session: aiohttp.ClientSession, url: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
    async with session.post(url, json=payload) as resp:
        text = await resp.text()
        if resp.status >= 400:
            return False, f"HTTP {resp.status}: {text[:400]}"
        try:
            j = json.loads(text)
        except json.JSONDecodeError:
            return False, "invalid_json"
        if j.get("error"):
            err = (j.get("error_description") or j.get("error") or "error")[:400]
            return False, err
        return True, None


async def _crm_call_json(method: str, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    url = bitrix_method_url(method)
    if not url:
        return None, "no_webhook"
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    return None, f"HTTP {resp.status}: {text[:300]}"
                try:
                    j = json.loads(text)
                except json.JSONDecodeError:
                    return None, "invalid_json"
                if j.get("error"):
                    err = (j.get("error_description") or j.get("error") or "error")[:400]
                    return None, err
                return j, None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return None, str(e)[:200]


async def crm_lead_get(lead_id: int) -> dict[str, Any] | None:
    """Поля лида (CONTACT_ID и т.д.)."""
    j, err = await _crm_call_json("crm.lead.get", {"id": int(lead_id)})
    if err or not j:
        log.debug("crm.lead.get %s: %s", lead_id, err)
        return None
    res = j.get("result")
    return res if isinstance(res, dict) else None


async def crm_timeline_comment_add_lead(lead_id: int, comment: str) -> str | None:
    """Запись в ленту лида (видно в CRM в таймлайне)."""
    if len(comment) > 6000:
        comment = comment[:5900] + "\n…"
    j, err = await _crm_call_json(
        "crm.timeline.comment.add",
        {
            "fields": {
                "ENTITY_ID": int(lead_id),
                "ENTITY_TYPE": "lead",
                "COMMENT": comment,
            }
        },
    )
    if err:
        log.debug("crm.timeline.comment.add lead=%s: %s", lead_id, err)
        return err
    return None


async def crm_contact_update_comments(contact_id: int, comments: str) -> str | None:
    """Поле COMMENTS у контакта (карточка контакта)."""
    url = bitrix_method_url("crm.contact.update")
    if not url:
        return "no_webhook"
    if len(comments) > _MAX_COMMENTS:
        comments = comments[: _MAX_COMMENTS - 80] + "\n\n… (текст обрезан по лимиту CRM)"
    payload: dict[str, Any] = {"id": int(contact_id), "fields": {"COMMENTS": comments}}
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            ok, err = await _bitrix_post(session, url, payload)
            if not ok:
                log.debug("crm.contact.update %s: %s", contact_id, err)
                return err or "update_failed"
            log.info("Bitrix contact %s: COMMENTS updated", contact_id)
            return None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("Bitrix contact.update: %s", e)
        return str(e)[:200]


async def crm_lead_update_comments(lead_id: int, comments: str) -> str | None:
    """Обновляет COMMENTS у лида. Возвращает текст ошибки или None."""
    url = bitrix_method_url("crm.lead.update")
    if not url:
        return "no_webhook"
    if len(comments) > _MAX_COMMENTS:
        comments = comments[: _MAX_COMMENTS - 80] + "\n\n… (текст обрезан по лимиту CRM)"
    payload: dict[str, Any] = {"id": int(lead_id), "fields": {"COMMENTS": comments}}
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            ok, err = await _bitrix_post(session, url, payload)
            if not ok:
                log.warning("Bitrix crm.lead.update %s: %s", lead_id, err)
                return err or "update_failed"
            log.info("Bitrix lead %s: COMMENTS updated", lead_id)
            return None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("Bitrix lead.update: %s", e)
        return str(e)[:200]


async def sync_bitrix_chat_for_uid(uid: int) -> None:
    """Лид COMMENTS + запись в ленту лида + COMMENTS контакта (если лид связан с контактом)."""
    meta = get_bitrix_lead_link(uid)
    if not meta:
        return
    lead_id = meta.get("lead_id")
    header = (meta.get("header") or "").strip()
    if not lead_id:
        return
    hist = get_history(uid, get_uid_account(uid))
    chat_block = format_chat_for_bitrix(hist)
    full = f"{header}\n\n--- Переписка Telegram ---\n{chat_block}"
    err = await crm_lead_update_comments(int(lead_id), full)
    if err:
        log.warning("Bitrix COMMENTS не обновлён uid=%s lead=%s: %s", uid, lead_id, err)
    else:
        log.info("Bitrix lead %s: переписка в COMMENTS обновлена (telegram uid=%s)", lead_id, uid)

    tl = f"Переписка Telegram:\n{chat_block}"
    if len(tl) > 5800:
        tl = tl[:5700] + "\n…"
    t_err = await crm_timeline_comment_add_lead(int(lead_id), tl)
    if t_err:
        log.warning("Bitrix лента лида lead=%s: %s", lead_id, t_err)

    ld = await crm_lead_get(int(lead_id))
    if ld:
        raw_cid = ld.get("CONTACT_ID")
        cid: int | None = None
        if raw_cid not in (None, "", "0", 0):
            try:
                cid = int(raw_cid)
            except (TypeError, ValueError):
                cid = None
        if cid and cid > 0:
            c_err = await crm_contact_update_comments(cid, full)
            if c_err:
                log.warning("Bitrix COMMENTS контакта %s: %s", cid, c_err)


async def bitrix_ping_crm() -> dict[str, Any]:
    """Проверка вебхука: crm.lead.fields (нужны права CRM; иначе увидите error)."""
    j, err = await _crm_call_json("crm.lead.fields", {})
    if err:
        if err == "no_webhook":
            return {
                "ok": False,
                "error": err,
                "hint": (
                    "На сервере с fnr-api в файле .env задайте BITRIX_INCOMING_WEBHOOK "
                    "(или BITRIX_WEBHOOK_URL) и перезапустите процесс API."
                ),
            }
        return {
            "ok": False,
            "error": err,
            "hint": "Проверьте URL вебхука и права crm в Bitrix24 (не только отдельный метод crm.lead.add).",
        }
    res = j.get("result") if j else None
    n = len(res) if isinstance(res, dict) else 0
    return {"ok": True, "lead_fields_count": n}


async def create_lead_from_form(data: dict[str, Any]) -> tuple[int | None, str | None]:
    """
    Возвращает (lead_id, error_message).
    Если вебхук не задан — (None, None).
    """
    url = bitrix_lead_add_url()
    if not url:
        return None, None

    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()

    comments = build_lead_comments_initial(data)

    fields: dict[str, Any] = {
        "TITLE": "Заявка с сайта Flex&Roll PRO",
        "NAME": name or "Без имени",
        "COMMENTS": comments,
        "SOURCE_DESCRIPTION": "Сайт flex-n-roll, форма обратной связи",
    }
    if phone:
        fields["PHONE"] = [{"VALUE": phone, "VALUE_TYPE": "WORK"}]
    if email:
        fields["EMAIL"] = [{"VALUE": email, "VALUE_TYPE": "WORK"}]

    payload = {"fields": fields, "params": {"REGISTER_SONET_EVENT": "Y"}}

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    log.warning("Bitrix HTTP %s: %s", resp.status, text[:500])
                    return None, f"HTTP {resp.status}"
                try:
                    j = json.loads(text)
                except json.JSONDecodeError:
                    log.warning("Bitrix non-JSON: %s", text[:400])
                    return None, "invalid_response"
                if j.get("error"):
                    err = (j.get("error_description") or j.get("error") or "bitrix_error")[:300]
                    log.warning("Bitrix crm.lead.add: %s", err)
                    return None, err
                result = j.get("result")
                if result is None:
                    return None, "empty_result"
                try:
                    lead_id = int(result)
                except (TypeError, ValueError):
                    return None, "bad_result"
                log.info("Bitrix lead created: %s", lead_id)
                return lead_id, None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("Bitrix request failed: %s", e)
        return None, str(e)[:200]
