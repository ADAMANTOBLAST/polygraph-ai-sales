"""Bitrix24: создание лида/сделки, обновление комментариев и автоматизация стадий."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp

from .sales_sync import bitrix_user_id_for_role, role_label
from .state_store import get_bitrix_lead_link, get_history, get_uid_account

log = logging.getLogger(__name__)

_MAX_COMMENTS = 63000


def _env_json(name: str) -> dict[str, Any]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("%s: invalid JSON", name)
        return {}
    return data if isinstance(data, dict) else {}


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


def _parse_deal_id_from_convert_result(result: Any) -> int | None:
    """crm.lead.convert возвращает структуру с DEAL_ID (формат зависит от портала)."""
    if result is None:
        return None
    if isinstance(result, int):
        return result if result > 0 else None
    if isinstance(result, dict):
        for key in ("DEAL_ID", "dealId", "deal_id", "ID"):
            raw = result.get(key)
            if raw is None or raw == "" or raw == 0:
                continue
            try:
                n = int(raw)
                if n > 0:
                    return n
            except (TypeError, ValueError):
                continue
        nested = result.get("result")
        if nested is not None and nested is not result:
            return _parse_deal_id_from_convert_result(nested)
    return None


async def convert_lead_to_deal(lead_id: int) -> tuple[int | None, str | None]:
    """
    Конвертация лида в сделку (crm.lead.convert).
    Вебхук должен иметь права CRM на этот метод; иначе вернётся ошибка.
    """
    j, err = await _crm_call_json(
        "crm.lead.convert",
        {
            "fields": {"LEAD_ID": int(lead_id)},
            "params": {"REGISTER_SONET_EVENT": "Y"},
        },
    )
    if err or not j:
        return None, err or "no_response"
    deal_id = _parse_deal_id_from_convert_result(j.get("result"))
    if deal_id:
        log.info("Bitrix lead %s → deal %s (convert)", lead_id, deal_id)
        return deal_id, None
    return None, "convert_no_deal_id"


async def create_deal_from_lead_fallback(
    lead_id: int, title: str, comments: str
) -> tuple[int | None, str | None]:
    """
    Если crm.lead.convert недоступен или не вернул ID — отдельная сделка с ссылкой на лид в COMMENTS.
    """
    body = f"Связанный лид CRM: {lead_id}\n\n{comments}"
    if len(body) > _MAX_COMMENTS:
        body = body[: _MAX_COMMENTS - 80] + "\n\n…"
    j, err = await _crm_call_json(
        "crm.deal.add",
        {
            "fields": {
                "TITLE": (title or "Заявка с сайта Flex&Roll PRO")[:255],
                "COMMENTS": body,
                "SOURCE_DESCRIPTION": "Сайт flex-n-roll, форма (fallback после лида)",
            },
            "params": {"REGISTER_SONET_EVENT": "Y"},
        },
    )
    if err or not j:
        return None, err or "deal_add_failed"
    raw = j.get("result")
    try:
        did = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return None, "bad_deal_result"
    if did <= 0:
        return None, "empty_deal_id"
    log.info("Bitrix deal created (fallback) %s для лида %s", did, lead_id)
    return did, None


async def crm_deal_get(deal_id: int) -> dict[str, Any] | None:
    j, err = await _crm_call_json("crm.deal.get", {"id": int(deal_id)})
    if err or not j:
        return None
    res = j.get("result")
    return res if isinstance(res, dict) else None


async def crm_deal_update_comments(deal_id: int, comments: str) -> str | None:
    url = bitrix_method_url("crm.deal.update")
    if not url:
        return "no_webhook"
    if len(comments) > _MAX_COMMENTS:
        comments = comments[: _MAX_COMMENTS - 80] + "\n\n… (текст обрезан по лимиту CRM)"
    payload: dict[str, Any] = {"id": int(deal_id), "fields": {"COMMENTS": comments}}
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            ok, err = await _bitrix_post(session, url, payload)
            if not ok:
                log.warning("Bitrix crm.deal.update %s: %s", deal_id, err)
                return err or "update_failed"
            log.info("Bitrix deal %s: COMMENTS updated", deal_id)
            return None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("Bitrix deal.update: %s", e)
        return str(e)[:200]


def bitrix_stage_for_event(event_name: str) -> str | None:
    event_key = (event_name or "").strip().upper()
    mapping = {
        "WON": (os.environ.get("BITRIX_DEAL_STAGE_WON") or "").strip(),
        "LOST": (os.environ.get("BITRIX_DEAL_STAGE_LOST") or "").strip(),
    }
    value = mapping.get(event_key) or ""
    return value or None


def bitrix_assigned_user_for_route(route_name: str) -> int | None:
    route_key = (route_name or "").strip().lower()
    mapping = _env_json("BITRIX_ROUTE_MAP")
    raw = mapping.get(route_key)
    if raw in (None, "", 0, "0"):
        return None
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        log.warning("BITRIX_ROUTE_MAP[%s] has invalid user id: %r", route_key, raw)
        return None
    return uid if uid > 0 else None


async def crm_deal_update_stage(
    deal_id: int,
    stage_id: str | None = None,
    assigned_by_id: int | None = None,
) -> str | None:
    fields: dict[str, Any] = {}
    if stage_id:
        fields["STAGE_ID"] = str(stage_id)
    if assigned_by_id:
        fields["ASSIGNED_BY_ID"] = int(assigned_by_id)
    if not fields:
        return None
    url = bitrix_method_url("crm.deal.update")
    if not url:
        return "no_webhook"
    payload: dict[str, Any] = {"id": int(deal_id), "fields": fields}
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            ok, err = await _bitrix_post(session, url, payload)
            if not ok:
                log.warning("Bitrix crm.deal.update stage %s: %s", deal_id, err)
                return err or "update_failed"
            log.info(
                "Bitrix deal %s updated: stage=%s assigned_by=%s",
                deal_id,
                stage_id,
                assigned_by_id,
            )
            return None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("Bitrix deal stage update: %s", e)
        return str(e)[:200]


async def apply_deal_outcome(
    uid: int,
    event_name: str | None = None,
    route_name: str | None = None,
    note: str | None = None,
) -> str | None:
    meta = get_bitrix_lead_link(uid)
    if not meta:
        return "no_bitrix_meta"
    raw_deal_id = meta.get("deal_id")
    if raw_deal_id in (None, "", 0, "0"):
        return "no_deal_id"
    try:
        deal_id = int(raw_deal_id)
    except (TypeError, ValueError):
        return "bad_deal_id"
    stage_id = bitrix_stage_for_event(event_name or "")
    assigned_by_id = bitrix_assigned_user_for_route(route_name or "")
    err = await crm_deal_update_stage(deal_id, stage_id=stage_id, assigned_by_id=assigned_by_id)
    if err:
        return err
    summary_parts = ["Автоматическое действие бота по сделке."]
    if event_name:
        summary_parts.append(f"Событие: {event_name.upper()}.")
    if stage_id:
        summary_parts.append(f"Стадия: {stage_id}.")
    if route_name:
        summary_parts.append(f"Маршрут: {route_name}.")
    if assigned_by_id:
        summary_parts.append(f"Ответственный Bitrix user id: {assigned_by_id}.")
    if note:
        summary_parts.append(f"Комментарий: {note}")
    tl_err = await crm_timeline_comment_add_deal(deal_id, " ".join(summary_parts))
    if tl_err:
        log.debug("Bitrix timeline outcome deal=%s: %s", deal_id, tl_err)
    return None


async def crm_timeline_comment_add_deal(deal_id: int, comment: str) -> str | None:
    if len(comment) > 6000:
        comment = comment[:5900] + "\n…"
    j, err = await _crm_call_json(
        "crm.timeline.comment.add",
        {
            "fields": {
                "ENTITY_ID": int(deal_id),
                "ENTITY_TYPE": "deal",
                "COMMENT": comment,
            }
        },
    )
    if err:
        log.debug("crm.timeline.comment.add deal=%s: %s", deal_id, err)
        return err
    return None


async def crm_lead_update_fields(
    lead_id: int, fields: dict[str, Any], register_sonet_event: bool = False
) -> str | None:
    """Обновляет произвольные поля лида. Возвращает текст ошибки или None."""
    url = bitrix_method_url("crm.lead.update")
    if not url:
        return "no_webhook"
    payload: dict[str, Any] = {"id": int(lead_id), "fields": fields}
    if register_sonet_event:
        payload["params"] = {"REGISTER_SONET_EVENT": "Y"}
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            ok, err = await _bitrix_post(session, url, payload)
            if not ok:
                log.warning("Bitrix crm.lead.update %s: %s", lead_id, err)
                return err or "update_failed"
            return None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("Bitrix lead.update fields: %s", e)
        return str(e)[:200]


async def crm_lead_update_comments(lead_id: int, comments: str) -> str | None:
    """Обновляет COMMENTS у лида. Возвращает текст ошибки или None."""
    if len(comments) > _MAX_COMMENTS:
        comments = comments[: _MAX_COMMENTS - 80] + "\n\n… (текст обрезан по лимиту CRM)"
    err = await crm_lead_update_fields(int(lead_id), {"COMMENTS": comments})
    if not err:
        log.info("Bitrix lead %s: COMMENTS updated", lead_id)
    return err


async def crm_lead_update_assigned_by(lead_id: int, bitrix_user_id: int) -> str | None:
    err = await crm_lead_update_fields(
        int(lead_id),
        {"ASSIGNED_BY_ID": int(bitrix_user_id)},
        register_sonet_event=True,
    )
    if not err:
        log.info("Bitrix lead %s: ASSIGNED_BY_ID -> %s", lead_id, bitrix_user_id)
    return err


async def sync_bitrix_chat_for_uid(uid: int) -> None:
    """Лид COMMENTS + запись в ленту лида + сделка (если есть) + COMMENTS контакта."""
    meta = get_bitrix_lead_link(uid)
    if not meta:
        return
    lead_id = meta.get("lead_id")
    deal_id = meta.get("deal_id")
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

    if deal_id:
        try:
            did = int(deal_id)
        except (TypeError, ValueError):
            did = 0
        if did > 0:
            d_err = await crm_deal_update_comments(did, full)
            if d_err:
                log.warning("Bitrix COMMENTS сделки uid=%s deal=%s: %s", uid, did, d_err)
            else:
                log.info("Bitrix deal %s: переписка в COMMENTS (telegram uid=%s)", did, uid)
            dt_err = await crm_timeline_comment_add_deal(did, tl)
            if dt_err:
                log.warning("Bitrix лента сделки deal=%s: %s", did, dt_err)

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

    if deal_id:
        try:
            d_obj = await crm_deal_get(int(deal_id))
        except Exception:
            d_obj = None
        if d_obj:
            raw_cid_d = d_obj.get("CONTACT_ID")
            cid_d: int | None = None
            if raw_cid_d not in (None, "", "0", 0):
                try:
                    cid_d = int(raw_cid_d)
                except (TypeError, ValueError):
                    cid_d = None
            if cid_d and cid_d > 0:
                c2 = await crm_contact_update_comments(cid_d, full)
                if c2:
                    log.debug("Bitrix COMMENTS контакта (из сделки) %s: %s", cid_d, c2)


async def sync_bitrix_handoff_for_uid(
    uid: int,
    from_role_key: str | None,
    to_role_key: str,
    target_account_id: int | None = None,
) -> None:
    """Синхронизирует автопередачу лида в Bitrix: ответственный + комментарий в таймлайне."""
    meta = get_bitrix_lead_link(uid)
    if not meta:
        return
    lead_id = meta.get("lead_id")
    if not lead_id:
        return
    assigned_err: str | None = None
    bitrix_uid = bitrix_user_id_for_role(to_role_key)
    if bitrix_uid:
        assigned_err = await crm_lead_update_assigned_by(int(lead_id), int(bitrix_uid))
    from_label = role_label(from_role_key)
    to_label = role_label(to_role_key)
    parts = [f"Автопередача лида из Telegram: {from_label} -> {to_label}."]
    if target_account_id is not None:
        parts.append(f"Telegram-аккаунт: fnr-acc-{int(target_account_id)}.")
    if bitrix_uid:
        parts.append(f"Bitrix ASSIGNED_BY_ID: {int(bitrix_uid)}.")
    else:
        parts.append("Bitrix ASSIGNED_BY_ID не обновлён: для роли не настроен Bitrix user id.")
    if assigned_err:
        parts.append(f"Ошибка смены ответственного: {assigned_err}.")
    comment = " ".join(parts)
    err = await crm_timeline_comment_add_lead(int(lead_id), comment)
    if err:
        log.warning("Bitrix handoff timeline lead=%s: %s", lead_id, err)


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
