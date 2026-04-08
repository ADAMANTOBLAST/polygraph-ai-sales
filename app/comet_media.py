"""Whisper (аудио) и vision (фото) через тот же Comet API / OpenAI-клиент."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from .comet_client import get_client

log = logging.getLogger(__name__)

WHISPER_MODEL = os.environ.get("COMET_WHISPER_MODEL", "whisper-1")
VISION_MODEL = os.environ.get("COMET_VISION_MODEL", "gpt-4o-mini")

VISION_CLASSIFIER_PROMPT = """Ты модератор для B2B-чата компании по этикеткам и упаковке (Флекс-н-Ролл ПРО).

Посмотри на изображение. Ответь ОДНИМ JSON без markdown и без текста вокруг:
{"relevant": true или false, "summary": "кратко что на картинке одной фразой", "reason": "одно короткое предложение"}

relevant=true если изображение может относиться к: этикеткам, упаковке, полиграфии, печати, рулонам, макетам, образцам продукции, оборудованию типографии, логотипам на товаре, документам/скринам по заказу.
relevant=false если: мемы, личные фото, развлечения, явный оффтоп, шутка/розыгрыш, картинка без связи с заказом или производством этикеток."""


def transcribe_audio_file(path: str, language: str | None = "ru") -> str:
    """Расшифровка голоса/аудио/видео (дорожка) через Whisper."""
    client = get_client()
    path_obj = Path(path)

    def _one(lang: str | None) -> Any:
        with open(path_obj, "rb") as f:
            kw: dict[str, Any] = {"model": WHISPER_MODEL, "file": (path_obj.name, f)}
            if lang:
                kw["language"] = lang
            return client.audio.transcriptions.create(**kw)

    try:
        tr = _one(language)
    except Exception:
        tr = _one(None)
    return (getattr(tr, "text", None) or "").strip()


def _parse_json_loose(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def analyze_image_relevance(image_path: str) -> dict[str, Any]:
    """
    Возвращает: relevant (bool), summary (str), reason (str).
    При ошибке парсинга — relevant=False.
    """
    import base64

    client = get_client()
    p = Path(image_path)
    data = p.read_bytes()
    b64 = base64.standard_b64encode(data).decode("ascii")
    ext = p.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")
    url = f"data:{mime};base64,{b64}"

    completion = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_CLASSIFIER_PROMPT},
                    {"type": "image_url", "image_url": {"url": url, "detail": "low"}},
                ],
            }
        ],
        max_tokens=400,
        temperature=0.3,
    )
    raw = (completion.choices[0].message.content or "").strip()
    try:
        obj = _parse_json_loose(raw)
        return {
            "relevant": bool(obj.get("relevant")),
            "summary": str(obj.get("summary") or "").strip(),
            "reason": str(obj.get("reason") or "").strip(),
        }
    except Exception as e:
        log.warning("vision JSON parse: %s | raw=%s", e, raw[:200])
        return {"relevant": False, "summary": "", "reason": "parse_error"}
