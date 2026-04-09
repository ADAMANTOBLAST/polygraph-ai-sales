"""Обработка личных сообщений Telethon: текст, голос, видео, фото, файлы."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

from telethon import TelegramClient, events

from .comet_client import complete_dialog, complete_dialog_two_chunks, detect_handoff
from .comet_media import analyze_image_relevance, transcribe_audio_file
from .media_utils import extract_audio_for_whisper
from .bitrix import apply_deal_outcome, sync_bitrix_chat_for_uid, sync_bitrix_handoff_for_uid
from .manager_router import force_assign_uid_to_role, resolve_account_for_lead_dialog
from .sales_sync import (
    account_role_key,
    handoff_rules_for_account,
    role_label,
    use_two_telegram_messages_for_replies,
)
from .state_store import append_history, get_history, is_tracked

log = logging.getLogger(__name__)

REASSIGN_NOTICE = (
    "Сейчас вас консультирует другой специалист команды — продолжим по вашей задаче."
)

DOCUMENT_REPLY = "Передам нашим специалистам, спасибо за информацию 🤝"

OFF_TOPIC_MEDIA = (
    "Похоже, это не про нашу тему 🙂 Если нужна консультация по этикеткам и упаковке — "
    "пришлите релевантные фото или опишите задачу текстом."
)

STICKER_REPLY = (
    "Стикеры тут не помогут 🙂 Напишите вопрос или пришлите фото по теме этикеток и упаковки, если нужно."
)

TECH_FAIL = "Сейчас техническая заминка — напишите ещё раз через минуту или позвоните на номер с сайта."

MARKER_RE = re.compile(r"\[\[\s*(FNR_EVENT|FNR_ROUTE)\s*:\s*([A-Za-z_]+)\s*\]\]", re.I)


def _extract_service_markers(text: str) -> tuple[str, str | None, str | None]:
    event_name: str | None = None
    route_name: str | None = None

    def _replace(match: re.Match[str]) -> str:
        nonlocal event_name, route_name
        kind = (match.group(1) or "").strip().upper()
        value = (match.group(2) or "").strip()
        if kind == "FNR_EVENT" and not event_name:
            upper_value = value.upper()
            if upper_value in {"WON", "LOST"}:
                event_name = upper_value
        elif kind == "FNR_ROUTE" and not route_name:
            lower_value = value.lower()
            if lower_value in {"seller", "manager", "tech", "economist", "dispatcher"}:
                route_name = lower_value
        return ""

    cleaned = MARKER_RE.sub(_replace, text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, event_name, route_name


def _handoff_note(account_id: int, route_name: str | None) -> str | None:
    if not route_name:
        return None
    rules = handoff_rules_for_account(account_id)
    key = "lead" if route_name == "manager" else route_name
    note = (rules.get(key) or "").strip()
    return note or None


def _handoff_notice(role_key: str) -> str:
    return f"Передаю ваш запрос специалисту роли «{role_label(role_key)}». Он продолжит диалог следующим сообщением."


async def _download_to_temp(client: TelegramClient, message, suffix: str) -> str | None:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        out = await client.download_media(message, file=path)
        return str(out) if out else path
    except Exception as e:
        log.exception("download_media: %s", e)
        Path(path).unlink(missing_ok=True)
        return None


async def _reply_boris(
    client: TelegramClient, event: events.NewMessage.Event, uid: int, account_id: int
) -> None:
    try:
        await client.send_read_acknowledge(event.chat_id, max_id=event.id)
    except Exception as e:
        log.debug("read_ack: %s", e)
    try:
        hist = get_history(uid, account_id)
        handoff_role = await asyncio.to_thread(detect_handoff, hist, account_id)
        if handoff_role:
            prev_role = account_role_key(account_id)
            target_account_id, changed = force_assign_uid_to_role(uid, handoff_role)
            if target_account_id and (changed or handoff_role != prev_role):
                notice = _handoff_notice(handoff_role)
                append_history(uid, "assistant", notice, account_id=target_account_id)
                await event.respond(notice)
                try:
                    await sync_bitrix_handoff_for_uid(
                        uid,
                        from_role_key=prev_role,
                        to_role_key=handoff_role,
                        target_account_id=target_account_id,
                    )
                    await sync_bitrix_chat_for_uid(uid)
                except Exception as sync_e:
                    log.debug("bitrix handoff uid=%s: %s", uid, sync_e)
                return
            log.warning(
                "handoff uid=%s role=%s не выполнен: нет активного аккаунта или роль уже текущая",
                uid,
                handoff_role,
            )
        async with client.action(event.chat_id, "typing"):
            if use_two_telegram_messages_for_replies(account_id):
                part1, part2 = await asyncio.to_thread(complete_dialog_two_chunks, hist, account_id)
                parts = [part1, part2]
            else:
                reply = await asyncio.to_thread(complete_dialog, hist, account_id)
                parts = [reply]
        last_event: str | None = None
        last_route: str | None = None
        clean_parts: list[str] = []
        for part in parts:
            clean_part, event_name, route_name = _extract_service_markers(part)
            if event_name:
                last_event = event_name
            if route_name:
                last_route = route_name
            if clean_part:
                clean_parts.append(clean_part)
        if not clean_parts:
            clean_parts = ["Сейчас не смог сформулировать ответ — напишите, пожалуйста, ещё раз чуть короче."]
        for i, part in enumerate(clean_parts):
            append_history(uid, "assistant", part, account_id=account_id)
            if i == 0:
                await event.respond(part)
            else:
                await asyncio.sleep(0.35)
                await client.send_message(uid, part)
        try:
            await sync_bitrix_chat_for_uid(uid)
        except Exception as sync_e:
            log.debug("bitrix sync uid=%s: %s", uid, sync_e)
        if last_event or last_route:
            try:
                note = _handoff_note(account_id, last_route)
                outcome_err = await apply_deal_outcome(uid, last_event, last_route, note=note)
                if outcome_err:
                    log.warning(
                        "apply_deal_outcome uid=%s event=%s route=%s: %s",
                        uid,
                        last_event,
                        last_route,
                        outcome_err,
                    )
            except Exception as outcome_e:
                log.exception(
                    "deal outcome uid=%s event=%s route=%s: %s",
                    uid,
                    last_event,
                    last_route,
                    outcome_e,
                )
    except Exception as e:
        log.exception("comet: %s", e)
        await event.respond(TECH_FAIL)


def register_private_handlers(client: TelegramClient, session_account_id: int) -> None:
    @client.on(events.NewMessage(incoming=True))
    async def on_pm(event: events.NewMessage.Event) -> None:
        if not event.is_private:
            return
        sender = await event.get_sender()
        if sender is None:
            return
        uid = int(sender.id)
        if not is_tracked(uid):
            return

        account_id, reassigned = resolve_account_for_lead_dialog(uid)
        if int(account_id) != int(session_account_id):
            log.warning(
                "uid=%s закреплён за fnr-acc-%s, входящее на сессии %s (ответ с той сессии, история по закреплению)",
                uid,
                account_id,
                session_account_id,
            )
        if reassigned:
            try:
                await client.send_message(uid, REASSIGN_NOTICE)
            except Exception as e:
                log.debug("reassign notice uid=%s: %s", uid, e)

        msg = event.message
        caption = (event.raw_text or "").strip()

        try:
            # --- Стикер ---
            if msg.sticker:
                try:
                    await client.send_read_acknowledge(event.chat_id, max_id=event.id)
                except Exception:
                    pass
                await event.respond(STICKER_REPLY)
                return

            # --- Фото ---
            if msg.photo:
                path = await _download_to_temp(client, msg, ".jpg")
                if not path:
                    await event.respond(TECH_FAIL)
                    return
                try:
                    async with client.action(event.chat_id, "typing"):
                        info = await asyncio.to_thread(analyze_image_relevance, path)
                    if not info.get("relevant"):
                        try:
                            await client.send_read_acknowledge(event.chat_id, max_id=event.id)
                        except Exception:
                            pass
                        await event.respond(OFF_TOPIC_MEDIA)
                        return
                    summary = info.get("summary") or "изображение"
                    line = f"[Фото: {summary}]"
                    if caption:
                        line += f"\nПодпись: {caption}"
                    append_history(uid, "user", line, account_id=account_id)
                finally:
                    Path(path).unlink(missing_ok=True)
                await _reply_boris(client, event, uid, account_id)
                return

            # --- Голос / аудио / видео / кружок ---
            media_suffix = None
            if msg.voice:
                media_suffix = ".ogg"
            elif msg.audio:
                media_suffix = ".bin"
            elif msg.video or msg.video_note:
                media_suffix = ".mp4"

            if media_suffix:
                path = await _download_to_temp(client, msg, media_suffix)
                if not path:
                    await event.respond(TECH_FAIL)
                    return
                extra_wav: str | None = None
                try:
                    if msg.video or msg.video_note:
                        text_try = ""
                        try:
                            text_try = transcribe_audio_file(path)
                        except Exception as e:
                            log.info("whisper по видеофайлу: %s", e)
                        if not (text_try or "").strip():
                            extra_wav = extract_audio_for_whisper(path)
                            if extra_wav:
                                text_try = transcribe_audio_file(extra_wav)
                    else:
                        text_try = transcribe_audio_file(path)

                    text_try = (text_try or "").strip()
                    if not text_try:
                        try:
                            await client.send_read_acknowledge(event.chat_id, max_id=event.id)
                        except Exception:
                            pass
                        await event.respond(
                            "Не удалось распознать речь — попробуйте ещё раз или напишите текстом."
                        )
                        return
                    user_line = f"[Голосовое сообщение]: {text_try}"
                    if caption:
                        user_line += f"\nПодпись: {caption}"
                    append_history(uid, "user", user_line, account_id=account_id)
                finally:
                    Path(path).unlink(missing_ok=True)
                    if extra_wav:
                        Path(extra_wav).unlink(missing_ok=True)
                await _reply_boris(client, event, uid, account_id)
                return

            # --- Файл (документ), не голос/видео ---
            if msg.document and not msg.photo:
                try:
                    await client.send_read_acknowledge(event.chat_id, max_id=event.id)
                except Exception:
                    pass
                await event.respond(DOCUMENT_REPLY)
                return

            # --- Только текст ---
            text = (event.raw_text or "").strip()
            if not text:
                return

            append_history(uid, "user", text, account_id=account_id)
            await _reply_boris(client, event, uid, account_id)

        except Exception as e:
            log.exception("on_pm: %s", e)
            try:
                await event.respond(TECH_FAIL)
            except Exception:
                pass
