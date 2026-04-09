"""
Распределение диалогов по аккаунтам менеджеров (fnr-acc-*): round-robin для новых лидов,
переназначение на активного, если закреплённый в отпуске / не на связи.
Сообщения идут с одной сессии Telethon — меняется логический account_id для промпта ИИ и метки в админке.
"""
from __future__ import annotations

import logging

from accounts_registry import get_accounts

from .sales_sync import eligible_active_account_ids, is_account_active, lead_eligible_account_ids
from .state_store import get_uid_account, load_state, save_state, set_uid_account

log = logging.getLogger(__name__)


def _connected_sorted() -> list[int]:
    return sorted(get_accounts().keys())


def pick_account_for_new_lead() -> int:
    """Round-robin среди активных и допущенных к лидам; иначе среди lead_eligible."""
    conn = _connected_sorted()
    if not conn:
        return 0
    ids = eligible_active_account_ids(conn)
    if not ids:
        ids = lead_eligible_account_ids(conn)
    if not ids:
        return conn[0]
    st = load_state()
    idx = int(st.get("lead_rr_idx") or 0) % len(ids)
    aid = ids[idx]
    st["lead_rr_idx"] = idx + 1
    save_state()
    return int(aid)


def _pick_replacement(old_id: int, conn: list[int]) -> int:
    ids = eligible_active_account_ids(conn)
    if not ids:
        ids = lead_eligible_account_ids(conn)
    if not ids:
        return old_id
    for a in ids:
        if int(a) != int(old_id):
            return int(a)
    return int(ids[0])


def resolve_account_for_lead_dialog(uid: int) -> tuple[int, bool]:
    """
    Актуальный account_id для ИИ и поля «Ответственный аккаунт» в админке.
    Возвращает (account_id, был_переназначен).
    """
    conn = _connected_sorted()
    if not conn:
        return 0, False

    current = get_uid_account(uid)
    if current is None:
        aid = pick_account_for_new_lead()
        set_uid_account(uid, aid)
        log.info("uid=%s закреплён за аккаунтом %s (без прежней привязки)", uid, aid)
        return aid, False

    cur = int(current)
    if is_account_active(cur):
        return cur, False

    new_id = _pick_replacement(cur, conn)
    set_uid_account(uid, new_id)
    log.info("uid=%s переназначен: %s → %s (ответственный не активен)", uid, cur, new_id)
    return new_id, True
