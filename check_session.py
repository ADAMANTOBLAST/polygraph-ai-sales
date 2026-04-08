#!/usr/bin/env python3
"""Проверка: Telethon подключается с sessions/account_0.session без нового логина."""
import asyncio
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from telethon import TelegramClient
from accounts_registry import get_accounts, get_profile_for_account, get_api_credentials


async def main():
    accounts = get_accounts()
    if not accounts:
        print("Нет записей в accounts_registry.json")
        sys.exit(1)
    aid = sorted(accounts.keys())[0]
    acc = accounts[aid]
    profile = get_profile_for_account(aid)
    api_id, api_hash = get_api_credentials(aid)
    session_str = str(PROJECT_DIR / "sessions" / acc.get("session_path", f"account_{aid}"))
    sess_file = Path(session_str + ".session")
    if not sess_file.is_file():
        print("Нет файла:", sess_file)
        sys.exit(1)

    client = TelegramClient(
        session_str,
        int(api_id),
        str(api_hash),
        device_model=profile["device_model"],
        system_version=profile["system_version"],
        app_version=profile["app_version"],
        lang_code=profile["lang_code"],
    )
    await client.connect()
    if not await client.is_user_authorized():
        print("Сессия не авторизована — нужен новый логин (код).")
        await client.disconnect()
        sys.exit(2)
    me = await client.get_me()
    print("OK:", me.phone, me.id, getattr(me, "username", None))
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
