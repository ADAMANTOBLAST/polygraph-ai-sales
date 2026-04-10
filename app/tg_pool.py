"""Выбор Telethon-клиента по account_id (fnr-acc-*); пул поднимается в main."""
from __future__ import annotations

import logging

from aiohttp import web
from telethon import TelegramClient

log = logging.getLogger(__name__)


class TgPoolState:
    """Один экземпляр на app, поля меняются в фоне после HTTP-starts — без app[key]=... после старта."""

    __slots__ = ("clients", "main", "ready")

    def __init__(self) -> None:
        self.clients: dict[int, TelegramClient] = {}
        self.main: TelegramClient | None = None
        self.ready = False


def get_telegram_client(app: web.Application, account_id: int) -> TelegramClient:
    """Клиент для аккаунта из реестра; иначе fallback на основной (обычно 0)."""
    pool: TgPoolState = app["tg_pool"]
    aid = int(account_id)
    c = pool.clients.get(aid)
    if c is not None:
        return c
    fb = pool.main
    if fb is not None:
        log.warning("Telegram: нет сессии для account_id=%s, отправка с fallback", aid)
        return fb
    raise RuntimeError("Нет подключённых Telegram-клиентов")
