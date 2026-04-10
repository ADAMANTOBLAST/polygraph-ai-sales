"""Персистентность: кого ведём в диалоге и история для Comet."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_STATE: dict | None = None
_LOCK = threading.Lock()

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "fnr_state.json"


def _default() -> dict:
    return {
        "tracked_user_ids": [],
        "histories": {},
        "bitrix_uid_meta": {},
        "uid_account": {},
        "lead_rr_idx": 0,
        "role_rr_idx": {},
        "voice_calls": [],
    }


def load_state() -> dict:
    global _STATE
    with _LOCK:
        if _STATE is not None:
            return _STATE
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        if DATA_PATH.is_file():
            try:
                with open(DATA_PATH, "r", encoding="utf-8") as f:
                    _STATE = json.load(f)
            except Exception:
                _STATE = _default()
        else:
            _STATE = _default()
        if "tracked_user_ids" not in _STATE:
            _STATE["tracked_user_ids"] = []
        if "histories" not in _STATE:
            _STATE["histories"] = {}
        if "bitrix_uid_meta" not in _STATE:
            _STATE["bitrix_uid_meta"] = {}
        if "uid_account" not in _STATE:
            _STATE["uid_account"] = {}
        if "lead_rr_idx" not in _STATE:
            _STATE["lead_rr_idx"] = 0
        if "role_rr_idx" not in _STATE:
            _STATE["role_rr_idx"] = {}
        if "voice_calls" not in _STATE:
            _STATE["voice_calls"] = []
        return _STATE


def save_state() -> None:
    with _LOCK:
        if _STATE is None:
            return
        tmp = DATA_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_STATE, f, ensure_ascii=False, indent=0)
        tmp.replace(DATA_PATH)


def is_tracked(uid: int) -> bool:
    st = load_state()
    return uid in st["tracked_user_ids"]


def add_tracked(uid: int) -> None:
    st = load_state()
    if uid not in st["tracked_user_ids"]:
        st["tracked_user_ids"].append(uid)
        save_state()


def _history_key(account_id: int, uid: int) -> str:
    """Переписка привязана к паре (аккаунт менеджера, Telegram uid лида)."""
    return f"{int(account_id)}:{int(uid)}"


def get_history(uid: int, account_id: int | None = None) -> list[dict]:
    st = load_state()
    aid = account_id if account_id is not None else get_uid_account(uid)
    if aid is not None:
        k = _history_key(int(aid), uid)
        h = st["histories"].get(k)
        if h:
            return list(h)
        # миграция со старого формата (только uid)
        leg = st["histories"].get(str(uid))
        if leg:
            st["histories"][k] = list(leg)
            save_state()
            return list(leg)
        return []
    leg = st["histories"].get(str(uid))
    return list(leg or [])


def set_bitrix_lead_link(
    uid: int, lead_id: int, comment_header: str, deal_id: int | None = None
) -> None:
    """Связь Telegram uid → лид CRM (и при конвертации — сделка); comment_header для COMMENTS."""
    st = load_state()
    row: dict = {
        "lead_id": int(lead_id),
        "header": comment_header,
    }
    if deal_id is not None:
        row["deal_id"] = int(deal_id)
    st.setdefault("bitrix_uid_meta", {})[str(int(uid))] = row
    save_state()


def get_bitrix_lead_link(uid: int) -> dict | None:
    st = load_state()
    raw = (st.get("bitrix_uid_meta") or {}).get(str(int(uid)))
    return raw if isinstance(raw, dict) else None


def get_uid_account(uid: int) -> int | None:
    """Закреплённый логический аккаунт fnr-acc-* для диалога с лидом."""
    st = load_state()
    raw = (st.get("uid_account") or {}).get(str(int(uid)))
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_uid_account(uid: int, account_id: int) -> None:
    st = load_state()
    st.setdefault("uid_account", {})[str(int(uid))] = int(account_id)
    save_state()


def append_history(
    uid: int, role: str, content: str, account_id: int | None = None, max_pairs: int = 12
) -> None:
    st = load_state()
    aid = account_id if account_id is not None else get_uid_account(uid)
    if aid is None:
        aid = 0
    key = _history_key(int(aid), uid)
    h = st["histories"].setdefault(key, [])
    h.append({"role": role, "content": content})
    max_len = max_pairs * 2
    if len(h) > max_len:
        st["histories"][key] = h[-max_len:]
    save_state()


def copy_history_on_reassign(uid: int, old_account_id: int, new_account_id: int) -> None:
    """При переназначении лида на другого менеджера переносим историю в новый ключ."""
    if int(old_account_id) == int(new_account_id):
        return
    st = load_state()
    ok = _history_key(int(old_account_id), uid)
    nk = _history_key(int(new_account_id), uid)
    if st["histories"].get(nk):
        return
    src = st["histories"].get(ok)
    if not src:
        src = st["histories"].get(str(uid))
    if not src:
        return
    st["histories"][nk] = list(src)
    save_state()


_VOICE_CALL_KEYS = frozenset(
    {
        "session_id",
        "voximplant_session_id",
        "caller_id",
        "destination",
        "duration_sec",
        "summary",
        "transcript",
        "recording_url",
        "elevenlabs_conversation_id",
        "caller_name",
        "hangup_reason",
        "event",
        "source",
        "transferred_to_specialist",
    }
)


def append_voice_call(payload: dict) -> str:
    """Добавить запись о голосовом звонке (вебхук из Voximplant). Возвращает id."""
    st = load_state()
    calls: list = st.setdefault("voice_calls", [])
    rid = str(uuid.uuid4())
    row: dict = {
        "id": rid,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    for k in _VOICE_CALL_KEYS:
        if k in payload and payload[k] is not None:
            v = payload[k]
            if k == "duration_sec":
                try:
                    row[k] = int(v)
                except (TypeError, ValueError):
                    row[k] = v
            else:
                row[k] = v if isinstance(v, (str, int, float, bool)) else str(v)[:8000]
    nested = payload.get("call")
    if isinstance(nested, dict):
        for k, v in nested.items():
            if k in _VOICE_CALL_KEYS and v is not None and k not in row:
                row[k] = v if isinstance(v, (str, int, float, bool)) else str(v)[:8000]
    calls.insert(0, row)
    max_keep = 500
    if len(calls) > max_keep:
        st["voice_calls"] = calls[:max_keep]
    save_state()
    return rid


def list_voice_calls(limit: int = 200) -> list[dict]:
    st = load_state()
    raw = st.get("voice_calls") or []
    if not isinstance(raw, list):
        return []
    lim = max(1, min(int(limit), 500))
    return list(raw[:lim])
