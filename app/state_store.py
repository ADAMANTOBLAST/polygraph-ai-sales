"""Персистентность: кого ведём в диалоге и история для Comet."""
from __future__ import annotations

import json
import threading
from pathlib import Path

_STATE: dict | None = None
_LOCK = threading.Lock()

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "fnr_state.json"


def _default() -> dict:
    return {"tracked_user_ids": [], "histories": {}}


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


def get_history(uid: int) -> list[dict]:
    st = load_state()
    key = str(uid)
    return list(st["histories"].get(key, []))


def append_history(uid: int, role: str, content: str, max_pairs: int = 12) -> None:
    st = load_state()
    key = str(uid)
    h = st["histories"].setdefault(key, [])
    h.append({"role": role, "content": content})
    # держим последние max_pairs * 2 сообщения (пары user/assistant)
    max_len = max_pairs * 2
    if len(h) > max_len:
        st["histories"][key] = h[-max_len:]
    save_state()
