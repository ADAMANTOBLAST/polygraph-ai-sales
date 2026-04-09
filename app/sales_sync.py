"""Синхронизация с админки: кто отвечает на заявки и тексты (первое сообщение, доп. контекст для ИИ)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SYNC_PATH = Path(__file__).resolve().parents[1] / "data" / "fnr_sales_sync.json"

ROLE_KEY_TO_LABEL = {
    "seller": "Активный продавец",
    "lead": "Руководитель",
    "tech": "Технолог",
    "economist": "Экономист",
    "dispatcher": "Диспетчер",
}
ROLE_LABEL_TO_KEY = {
    "активный продавец": "seller",
    "руководитель": "lead",
    "технолог": "tech",
    "экономист": "economist",
    "диспетчер": "dispatcher",
    "менеджер отдела продаж": "seller",
    "менеджер": "lead",
}


def _default_blob() -> dict[str, Any]:
    return {"lead_active_account_ids": None, "accounts": {}}


def load_sales_sync() -> dict[str, Any]:
    if not _SYNC_PATH.is_file():
        return _default_blob()
    try:
        with open(_SYNC_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return _default_blob()
        if "accounts" not in raw or not isinstance(raw["accounts"], dict):
            raw["accounts"] = {}
        return raw
    except Exception as e:
        log.warning("fnr_sales_sync load: %s", e)
        return _default_blob()


def write_sales_sync(data: dict[str, Any]) -> None:
    _SYNC_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SYNC_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(_SYNC_PATH)


def people_entries() -> list[dict[str, Any]]:
    """Снимок команды с админки (синхронизация), только метаданные по fnr-acc-*."""
    blob = load_sales_sync()
    raw = blob.get("people")
    return raw if isinstance(raw, list) else []


def _person_row_id(e: dict[str, Any]) -> str:
    """id в people может быть 'fnr-acc-12' или ошибочно '12'."""
    raw = e.get("id")
    if raw is None:
        return ""
    s = str(raw).strip()
    if s.isdigit():
        return f"fnr-acc-{int(s)}"
    return s


def normalize_role_key(role: str | None) -> str | None:
    s = (role or "").strip().lower()
    if not s:
        return None
    return ROLE_LABEL_TO_KEY.get(s) or (s if s in ROLE_KEY_TO_LABEL else None)


def role_label(role_key: str | None) -> str:
    key = normalize_role_key(role_key)
    if not key:
        return "Специалист"
    return ROLE_KEY_TO_LABEL.get(key, "Специалист")


def account_role_key(account_id: int) -> str | None:
    pid = f"fnr-acc-{int(account_id)}"
    for e in people_entries():
        if not isinstance(e, dict):
            continue
        if _person_row_id(e) != pid:
            continue
        return normalize_role_key(str(e.get("role") or ""))
    return None


def people_for_role(role_key: str, active_only: bool = True) -> list[dict[str, Any]]:
    want = normalize_role_key(role_key)
    if not want:
        return []
    out: list[dict[str, Any]] = []
    for e in people_entries():
        if not isinstance(e, dict):
            continue
        if normalize_role_key(str(e.get("role") or "")) != want:
            continue
        if active_only and (e.get("status") or "Активен").strip() != "Активен":
            continue
        out.append(e)
    return out


def active_connected_account_ids_for_role(connected_ids: list[int], role_key: str) -> list[int]:
    want = normalize_role_key(role_key)
    if not want:
        return []
    connected = {int(x) for x in connected_ids}
    out: list[int] = []
    for e in people_for_role(want, active_only=True):
        pid = _person_row_id(e)
        if not pid.startswith("fnr-acc-"):
            continue
        try:
            aid = int(pid.split("-")[-1])
        except (TypeError, ValueError):
            continue
        if aid not in connected:
            continue
        out.append(aid)
    return sorted(set(out))


def bitrix_user_id_for_role(role_key: str) -> int | None:
    for e in people_for_role(role_key, active_only=True):
        raw = e.get("bitrix_user_id")
        if raw in (None, ""):
            raw = e.get("bitrixUserId")
        if raw in (None, ""):
            continue
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid > 0:
            return uid
    return None


def is_account_active(account_id: int) -> bool:
    """
    Доступен для ведения лида. Главный источник — lead_active_account_ids с админки
    (туда попадают только со статусом «Активен» при синхронизации); не зависит от people[].
    Если lead_active_account_ids == null (старые данные) — смотрим people, иначе считаем активным.
    """
    blob = load_sales_sync()
    raw = blob.get("lead_active_account_ids")
    if raw is not None and isinstance(raw, list):
        if len(raw) == 0:
            return False
        return int(account_id) in {int(x) for x in raw}

    pid = f"fnr-acc-{int(account_id)}"
    for e in people_entries():
        if not isinstance(e, dict):
            continue
        if _person_row_id(e) != pid:
            continue
        st = (e.get("status") or "Активен").strip()
        return st == "Активен"
    return True


def eligible_active_account_ids(connected_ids: list[int]) -> list[int]:
    """Как lead_eligible, но только аккаунты со статусом «Активен» в команде. Иначе fallback на lead_eligible."""
    base = lead_eligible_account_ids(connected_ids)
    active_only = [a for a in base if is_account_active(a)]
    return active_only if active_only else base


def lead_eligible_account_ids(connected_ids: list[int]) -> list[int]:
    """
    Список аккаунтов для round-robin на /lead.
    - lead_active_account_ids == null или отсутствует: все подключённые.
    - непустой список: пересечение с подключёнными (только «активные» из админки).
    - пустой список []: никто (заявки через TG не идут).
    """
    blob = load_sales_sync()
    raw = blob.get("lead_active_account_ids")
    conn = sorted(set(int(x) for x in connected_ids))
    if raw is None:
        return conn
    if not isinstance(raw, list):
        return conn
    want = {int(x) for x in raw}
    return [x for x in conn if x in want]


def account_blob(account_id: int) -> dict[str, Any]:
    blob = load_sales_sync()
    acc = blob.get("accounts") or {}
    key = str(int(account_id))
    raw = acc.get(key) or acc.get(account_id)
    if not isinstance(raw, dict):
        return {}
    return raw


def agent_blob_for_account(account_id: int) -> dict[str, Any]:
    b = account_blob(account_id)
    raw = b.get("agent")
    return raw if isinstance(raw, dict) else {}


def handoff_rules_for_account(account_id: int) -> dict[str, str]:
    agent = agent_blob_for_account(account_id)
    raw = agent.get("handoff")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key in ROLE_KEY_TO_LABEL.keys():
        val = (raw.get(key) or "").strip()
        if val:
            out[key] = val
    # Совместимость со старым ключом lead -> manager.
    legacy_lead = (raw.get("lead") or "").strip()
    if legacy_lead:
        out["lead"] = legacy_lead
    return out


def first_message_for_account(account_id: int) -> str | None:
    b = account_blob(account_id)
    t = (b.get("first_message") or "").strip()
    return t if t else None


def second_message_for_account(account_id: int) -> str | None:
    """Второе приветствие — отдельное сообщение в Telegram после первого."""
    b = account_blob(account_id)
    t = (b.get("second_message") or "").strip()
    return t if t else None


def use_two_telegram_messages_for_replies(account_id: int) -> bool:
    """Если в настройках аккаунта есть второе приветствие — ответы ИИ тоже в 2 TG-сообщения (разделитель \\n\\n)."""
    return second_message_for_account(account_id) is not None


def system_extra_for_account(account_id: int) -> str | None:
    b = account_blob(account_id)
    t = (b.get("system_extra") or "").strip()
    return t if t else None
