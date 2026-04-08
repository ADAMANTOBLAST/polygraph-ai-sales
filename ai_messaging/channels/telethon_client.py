"""
Telegram-клиент (Telethon) для сессий из accounts_registry.json + sessions/*.session.

Правила (соблюдать при любых изменениях кода):
- Один процесс — одна сессия; не запускать два скрипта с одним и тем же .session.
- Паузы между отправками и массовыми действиями; при FloodWaitError ждать указанное время.
- Не спамить однотипными сообщениями; не дергать API в цикле без asyncio.sleep / лимитов.
- Не менять api_id/api_hash для уже созданной сессии (my.telegram.org).
- Параметры device_model, system_version, app_version, lang_code брать из профиля аккаунта
  и не менять после авторизации — иначе сессию может сбросить или пометить.
- При смене IP/VPN Telegram может запросить код — это нормально.
"""
from __future__ import annotations

import sys
from pathlib import Path

from telethon import TelegramClient

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from accounts_registry import (  # noqa: E402
    get_accounts,
    get_profile_for_account,
    get_api_credentials,
)


def build_client(account_id: int = 0) -> TelegramClient:
    """Собрать TelegramClient для account_id (путь к сессии без суффикса .session)."""
    accounts = get_accounts()
    acc = accounts.get(account_id)
    if not acc:
        raise ValueError(f"Нет аккаунта id={account_id} в accounts_registry.json")

    profile = get_profile_for_account(account_id)
    api_id, api_hash = get_api_credentials(account_id)
    if not api_id or not api_hash:
        raise ValueError(f"Пустые api_id/api_hash для account_id={account_id}")

    session_base = _PROJECT_ROOT / "sessions" / acc.get("session_path", f"account_{account_id}")
    return TelegramClient(
        str(session_base),
        int(api_id),
        str(api_hash),
        device_model=profile["device_model"],
        system_version=profile["system_version"],
        app_version=profile["app_version"],
        lang_code=profile["lang_code"],
    )
