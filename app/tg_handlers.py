"""Обработка личных сообщений Telethon: текст, голос, видео, фото, файлы."""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from telethon import TelegramClient, events

from .comet_client import complete_dialog
from .comet_media import analyze_image_relevance, transcribe_audio_file
from .media_utils import extract_audio_for_whisper
from .bitrix import sync_bitrix_chat_for_uid
from .state_store import append_history, get_history, is_tracked

log = logging.getLogger(__name__)

DOCUMENT_REPLY = "Передам нашим специалистам, спасибо за информацию 🤝"

OFF_TOPIC_MEDIA = (
    "Похоже, это не про нашу тему 🙂 Если нужна консультация по этикеткам и упаковке — "
    "пришлите релевантные фото или опишите задачу текстом."
)

STICKER_REPLY = (
    "Стикеры тут не помогут 🙂 Напишите вопрос или пришлите фото по теме этикеток и упаковки, если нужно."
)

TECH_FAIL = "Сейчас техническая заминка — напишите ещё раз через минуту или позвоните на номер с сайта."


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


async def _reply_boris(client: TelegramClient, event: events.NewMessage.Event, uid: int) -> None:
    try:
        await client.send_read_acknowledge(event.chat_id, max_id=event.id)
    except Exception as e:
        log.debug("read_ack: %s", e)
    try:
        hist = get_history(uid)
        async with client.action(event.chat_id, "typing"):
            reply = await asyncio.to_thread(complete_dialog, hist, 0)
        append_history(uid, "assistant", reply)
        await event.respond(reply)
        try:
            await sync_bitrix_chat_for_uid(uid)
        except Exception as sync_e:
            log.debug("bitrix sync uid=%s: %s", uid, sync_e)
    except Exception as e:
        log.exception("comet: %s", e)
        await event.respond(TECH_FAIL)


def register_private_handlers(client: TelegramClient) -> None:
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
                    append_history(uid, "user", line)
                finally:
                    Path(path).unlink(missing_ok=True)
                await _reply_boris(client, event, uid)
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
                    append_history(uid, "user", user_line)
                finally:
                    Path(path).unlink(missing_ok=True)
                    if extra_wav:
                        Path(extra_wav).unlink(missing_ok=True)
                await _reply_boris(client, event, uid)
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

            append_history(uid, "user", text)
            await _reply_boris(client, event, uid)

        except Exception as e:
            log.exception("on_pm: %s", e)
            try:
                await event.respond(TECH_FAIL)
            except Exception:
                pass
