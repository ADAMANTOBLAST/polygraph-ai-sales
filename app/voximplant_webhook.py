"""
Входящие события от сценария VoxEngine (Net.httpRequest → ваш HTTPS).

В .env опционально:
  VOXIMPLANT_WEBHOOK_SECRET=...   — если задан, заголовок X-Voximplant-Secret должен совпадать.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)


def _secret_ok(request: web.Request) -> bool:
    expected = (os.environ.get("VOXIMPLANT_WEBHOOK_SECRET") or "").strip()
    if not expected:
        return True
    got = (request.headers.get("X-Voximplant-Secret") or "").strip()
    if got == expected:
        return True
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.startswith("Bearer ") and auth[7:].strip() == expected:
        return True
    q = request.rel_url.query.get("token", "")
    if q == expected:
        return True
    return False


async def handle_voximplant_webhook(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.json_response(
            {
                "ok": True,
                "hint": "Voximplant шлёт POST на этот URL; открытие в браузере — только проверка, что маршрут есть.",
            }
        )
    if request.method == "OPTIONS":
        return web.Response(status=204)
    if not _secret_ok(request):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    body: dict[str, Any] | list[Any] | str | None = None
    try:
        if request.can_read_body:
            body = await request.json()
    except Exception:
        try:
            raw = await request.text()
            body = raw[:8000] if raw else None
        except Exception:
            body = None

    log.info(
        "voximplant webhook: %s",
        body if isinstance(body, (dict, list)) else repr(body)[:500],
    )
    return web.json_response({"ok": True})


def setup_voximplant_routes(app: web.Application) -> None:
    # Обычно nginx проксирует /fnr-api/… → upstream /…, достаточно первого пути.
    # Второй — если где-то прокси без отрезания префикса.
    for path in ("/voximplant/webhook", "/fnr-api/voximplant/webhook"):
        app.router.add_route("*", path, handle_voximplant_webhook)
