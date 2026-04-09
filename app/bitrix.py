"""Создание лида в Bitrix24 через входящий вебхук (REST crm.lead.add)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


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


def _method_labels() -> dict[str, str]:
    return {"telegram": "Telegram", "phone": "Телефон", "email": "E-mail"}


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
    contact_method = (data.get("contactMethod") or "").strip()
    contact_detail = (data.get("contactDetail") or "").strip()
    telegram = (data.get("telegram") or "").strip()

    method_label = _method_labels().get(contact_method, contact_method or "—")
    lines = [
        f"Предпочитаемая связь: {method_label}",
        f"Контакт: {contact_detail or '—'}",
    ]
    if telegram:
        lines.append(f"Telegram: {telegram}")

    fields: dict[str, Any] = {
        "TITLE": "Заявка с сайта Flex&Roll PRO",
        "NAME": name or "Без имени",
        "COMMENTS": "\n".join(lines),
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
