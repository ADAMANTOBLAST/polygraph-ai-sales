"""
Закрепление лида (Telegram uid) за аккаунтом fnr-acc-*:
- если uid уже в uid_account — пишем с того же аккаунта (очередь не трогаем);
- иначе — следующий аккаунт из round-robin среди допущенных к лидам и активных;
- при отпуске — переназначение + перенос истории на новый ключ account_id:uid.
История Comet хранится отдельно по паре (аккаунт, uid).
"""
from __future__ import annotations

import logging

from accounts_registry import get_accounts

from .sales_sync import (
    active_connected_account_ids_for_role,
    eligible_active_account_ids,
    is_account_active,
    lead_eligible_account_ids,
    load_sales_sync,
)
from .state_store import copy_history_on_reassign, get_uid_account, load_state, save_state, set_uid_account

log = logging.getLogger(__name__)
_warned_empty_people = False


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


def pick_account_for_role(role_key: str) -> int | None:
    """Round-robin среди активных Telegram-аккаунтов нужной роли."""
    conn = _connected_sorted()
    if not conn:
        return None
    ids = active_connected_account_ids_for_role(conn, role_key)
    if not ids:
        return None
    st = load_state()
    rr = st.get("role_rr_idx")
    if not isinstance(rr, dict):
        rr = {}
        st["role_rr_idx"] = rr
    idx = int(rr.get(role_key) or 0) % len(ids)
    aid = int(ids[idx])
    rr[role_key] = idx + 1
    save_state()
    return aid


def force_assign_uid_to_account(uid: int, account_id: int) -> bool:
    current = get_uid_account(uid)
    if current is not None and int(current) == int(account_id):
        return False
    if current is not None:
        copy_history_on_reassign(uid, int(current), int(account_id))
    set_uid_account(uid, int(account_id))
    return True


def force_assign_uid_to_role(uid: int, role_key: str) -> tuple[int | None, bool]:
    aid = pick_account_for_role(role_key)
    if aid is None:
        return None, False
    changed = force_assign_uid_to_account(uid, int(aid))
    if changed:
        log.info("uid=%s переназначен вручную по роли %s -> %s", uid, role_key, aid)
    return int(aid), changed


def resolve_account_for_lead_dialog(uid: int) -> tuple[int, bool]:
    """
    Актуальный account_id для ИИ и поля «Ответственный аккаунт» в админке.
    Возвращает (account_id, был_переназначен).
    """
    global _warned_empty_people
    conn = _connected_sorted()
    if not conn:
        return 0, False

    if not _warned_empty_people:
        blob = load_sales_sync()
        pe = blob.get("people")
        la = blob.get("lead_active_account_ids")
        if la is None and (not isinstance(pe, list) or len(pe) == 0):
            _warned_empty_people = True
            log.warning(
                "В fnr_sales_sync нет lead_active_account_ids и people[] — отпуск не учитывается. "
                "Синхронизируйте конфиг агента с сервером из админки."
            )

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
    copy_history_on_reassign(uid, cur, new_id)
    set_uid_account(uid, new_id)
    log.info("uid=%s переназначен: %s → %s (ответственный не активен)", uid, cur, new_id)
    return new_id, True
