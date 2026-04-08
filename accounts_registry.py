"""
Реестр Telegram-аккаунтов и путей к сессиям (данные из accounts_registry.json).
"""
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = PROJECT_DIR / "accounts_registry.json"
SESSIONS_DIR = PROJECT_DIR / "sessions"

_DEVICE_PROFILES = [
    {"device_model": "Desktop", "system_version": "Windows 11 Pro x64", "app_version": "5.10.4 x64", "lang_code": "ru"},
    {"device_model": "Desktop", "system_version": "Windows 10 Pro x64", "app_version": "5.10.3 x64", "lang_code": "ru"},
    {"device_model": "MacBookPro18,1", "system_version": "macOS 14.2.1", "app_version": "5.10.4 macOS", "lang_code": "ru"},
]


def load_registry() -> list[dict]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("accounts", [])
    except Exception:
        return []


def get_accounts() -> dict[int, dict]:
    out = {}
    for a in load_registry():
        aid = a.get("id")
        if aid is not None:
            out[int(aid)] = {
                "phone": a.get("phone", ""),
                "api_id": a.get("api_id", ""),
                "api_hash": a.get("api_hash", ""),
                "session_path": a.get("session_path", f"account_{aid}"),
            }
    return out


def get_profile_for_account(account_id: int) -> dict:
    return _DEVICE_PROFILES[account_id % len(_DEVICE_PROFILES)].copy()


def get_api_credentials(account_id: int) -> tuple[int | str, str]:
    a = get_accounts().get(account_id)
    if not a:
        return 0, ""
    try:
        return int(a["api_id"]), str(a["api_hash"] or "")
    except (ValueError, TypeError):
        return 0, ""


def session_file_path(account_id: int) -> Path:
    a = get_accounts().get(account_id)
    sp = (a or {}).get("session_path") or f"account_{account_id}"
    return SESSIONS_DIR / sp
