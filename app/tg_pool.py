"""Выбор Telethon-клиента по account_id (fnr-acc-*); пул поднимается в main."""
from __future__ import annotations

import logging

from aiohttp import web
from telethon import TelegramClient

log = logging.getLogger(__name__)


def get_telegram_client(app: web.Application, account_id: int) -> TelegramClient:
    """Клиент для аккаунта из реестра; иначе fallback на основной (обычно 0)."""
    clients: dict[int, TelegramClient] = app.get("telegram_clients") or {}
    aid = int(account_id)
    c = clients.get(aid)
    if c is not None:
        return c
    fb: TelegramClient | None = app.get("telegram")
    if fb is not None:
        log.warning("Telegram: нет сессии для account_id=%s, отправка с fallback", aid)
        return fb
    raise RuntimeError("Нет подключённых Telegram-клиентов")
