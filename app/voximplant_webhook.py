"""
Входящие события от сценария VoxEngine (Net.httpRequest → ваш HTTPS).

В .env опционально:
  VOXIMPLANT_WEBHOOK_SECRET=...   — если задан, заголовок X-Voximplant-Secret должен совпадать.

POST JSON с полями записи звонка сохраняется в fnr_state.json → voice_calls.
Поддерживаются и camelCase (callerId), как в примерах Voximplant.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from aiohttp import web

from .state_store import append_voice_call

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


def _normalize_voice_body(body: dict[str, Any]) -> dict[str, Any]:
    """camelCase / синонимы → поля append_voice_call."""
    out = dict(body)
    pairs = [
        ("caller_id", ("callerId", "caller", "from", "cli")),
        ("session_id", ("sessionId", "call_id", "callId", "voximplant_session_id")),
        ("duration_sec", ("durationSec", "duration", "callDuration")),
        ("summary", ("shortSummary", "notes")),
        ("transcript", ("text", "fullTranscript")),
        ("destination", ("dialed", "to", "calledNumber")),
        ("elevenlabs_conversation_id", ("conversationId", "elevenlabsConversationId")),
        ("recording_url", ("recordUrl", "recordingUrl")),
    ]
    for snake, alts in pairs:
        if out.get(snake) not in (None, ""):
            continue
        for a in alts:
            v = body.get(a)
            if v is not None and v != "":
                out[snake] = v
                break
    return out


def _has_voice_signal(body: dict[str, Any]) -> bool:
    """Есть ли смысл сохранять запись (не пустой ping)."""
    if body.get("event") == "ping":
        return False
    n = _normalize_voice_body(body)
    if n.get("event") in ("call_ended", "CallEnded", "voice_session_end", "CallAlerting", "CallStart"):
        if any(
            n.get(k) not in (None, "")
            for k in ("caller_id", "session_id", "summary", "transcript", "destination")
        ):
            return True
    for k in (
        "session_id",
        "voximplant_session_id",
        "caller_id",
        "summary",
        "transcript",
        "recording_url",
        "elevenlabs_conversation_id",
        "duration_sec",
        "destination",
        "source",
    ):
        v = n.get(k)
        if v is not None and v != "":
            return True
    nested = body.get("call")
    if isinstance(nested, dict):
        return _has_voice_signal(nested)
    return False


async def handle_voximplant_webhook(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.json_response(
            {
                "ok": True,
                "hint": "POST JSON с caller_id/session_id/duration_sec/…; см. voximplant/VOICE_CALLS_WEBHOOK.md",
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

    stored_id: str | None = None
    if isinstance(body, dict):
        norm = _normalize_voice_body(body)
        if _has_voice_signal(norm):
            try:
                stored_id = append_voice_call(norm)
                log.info("voximplant webhook: stored voice_call id=%s", stored_id)
            except Exception as e:
                log.exception("append_voice_call: %s", e)
        else:
            log.info(
                "voximplant webhook: skip store (no signal keys): %s",
                {k: norm.get(k) for k in list(norm.keys())[:12]},
            )
    else:
        log.info(
            "voximplant webhook: non-dict body: %s",
            body if isinstance(body, (dict, list)) else repr(body)[:500],
        )

    return web.json_response({"ok": True, "stored_id": stored_id})


def setup_voximplant_routes(app: web.Application) -> None:
    for path in ("/voximplant/webhook", "/fnr-api/voximplant/webhook"):
        app.router.add_route("*", path, handle_voximplant_webhook)
