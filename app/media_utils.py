"""Извлечение аудио из видео для Whisper (ffmpeg)."""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def extract_audio_for_whisper(video_path: str) -> str | None:
    """
    Сохраняет wav рядом с временным именем. Вызывающий удаляет оба файла.
    Возвращает путь к wav или None.
    """
    if not ffmpeg_available():
        log.warning("ffmpeg не найден — видео без отдельного извлечения аудио")
        return None
    fd, out = tempfile.mkstemp(suffix=".wav")
    import os

    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                out,
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        return out
    except Exception as e:
        log.warning("ffmpeg: %s", e)
        try:
            Path(out).unlink(missing_ok=True)
        except Exception:
            pass
        return None
