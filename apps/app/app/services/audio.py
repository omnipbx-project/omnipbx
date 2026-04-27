from __future__ import annotations

import io
from pathlib import Path
import re
import time
import wave

from fastapi import UploadFile

from app.core.settings import get_settings


def normalize_sound_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().replace("\\", "/")
    if not cleaned:
        return None
    cleaned = re.sub(r"\.(wav|WAV)$", "", cleaned)
    cleaned = cleaned.replace("/var/lib/asterisk/sounds/", "")
    return cleaned.strip("/")


def queue_musicclass(name: str) -> str:
    safe_name = re.sub(r"[^a-z0-9_-]", "_", name.strip().lower())
    return f"queue_{safe_name}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]", "_", value.strip().lower())
    return slug.strip("_") or "audio"


def _read_wav_bytes(upload: UploadFile) -> bytes:
    filename = (upload.filename or "").strip()
    if not filename.lower().endswith(".wav"):
        raise ValueError("Only .wav files are supported.")
    payload = upload.file.read()
    if not payload:
        raise ValueError("Uploaded audio file is empty.")
    try:
        with wave.open(io.BytesIO(payload), "rb"):
            pass
    except wave.Error as exc:
        raise ValueError("Uploaded file is not a valid WAV file.") from exc
    return payload


def save_custom_sound(upload: UploadFile, prefix: str, slug: str) -> str:
    settings = get_settings()
    payload = _read_wav_bytes(upload)
    target_dir = Path(settings.custom_sounds_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{prefix}_{_slugify(slug)}_{int(time.time())}.wav"
    target_path = target_dir / file_name
    target_path.write_bytes(payload)
    return f"custom/{Path(file_name).stem}"


def save_queue_moh(upload: UploadFile, queue_name: str) -> tuple[str, str]:
    settings = get_settings()
    payload = _read_wav_bytes(upload)
    musicclass = queue_musicclass(queue_name)
    target_dir = Path(settings.moh_root_dir) / musicclass
    target_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"moh_{_slugify(queue_name)}_{int(time.time())}.wav"
    (target_dir / file_name).write_bytes(payload)
    return file_name, musicclass


def delete_custom_sound(sound_name: str | None) -> None:
    normalized = normalize_sound_name(sound_name)
    if not normalized or not normalized.startswith("custom/"):
        return
    settings = get_settings()
    file_path = Path(settings.custom_sounds_dir) / f"{normalized.split('/')[-1]}.wav"
    file_path.unlink(missing_ok=True)


def delete_queue_moh(musicclass: str | None, file_name: str | None) -> None:
    if not musicclass or not file_name:
        return
    settings = get_settings()
    file_path = Path(settings.moh_root_dir) / musicclass / file_name
    file_path.unlink(missing_ok=True)
