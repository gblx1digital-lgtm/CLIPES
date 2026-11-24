"""Transcrição opcional (fala do streamer) com timestamps.

Provedores:
  none            -> sem transcrição; a IA analisa sinais de áudio + quadros do vídeo.
  faster_whisper  -> Whisper local (pip install -r requirements-transcription.txt).
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import get_settings
from .signals import TranscriptSegment

log = logging.getLogger("clipes.transcription")


class TranscriptionUnavailable(RuntimeError):
    pass


_model = None


def provider_status() -> dict:
    s = get_settings()
    if s.transcription_provider == "none":
        return {"provider": "none", "available": False, "detail": "Desativada (TRANSCRIPTION_PROVIDER=none)"}
    if s.transcription_provider == "faster_whisper":
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return {"provider": "faster_whisper", "available": False,
                    "detail": "Pacote faster-whisper não instalado (requirements-transcription.txt)"}
        return {"provider": "faster_whisper", "available": True, "detail": f"Modelo {s.whisper_model}"}
    return {"provider": s.transcription_provider, "available": False, "detail": "Provedor desconhecido"}


def transcribe(wav_path: str | Path) -> list[TranscriptSegment]:
    s = get_settings()
    if s.transcription_provider == "none":
        return []
    if s.transcription_provider != "faster_whisper":
        raise TranscriptionUnavailable(f"Provedor de transcrição desconhecido: {s.transcription_provider}")
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise TranscriptionUnavailable("faster-whisper não instalado. Rode: pip install -r requirements-transcription.txt") from e

    global _model
    if _model is None:
        device = s.whisper_device
        if device == "auto":
            device = "cuda" if _has_cuda() else "cpu"
        compute = "float16" if device == "cuda" else "int8"
        log.info("Carregando Whisper %s (%s/%s)", s.whisper_model, device, compute)
        _model = WhisperModel(s.whisper_model, device=device, compute_type=compute)

    segments, _info = _model.transcribe(str(wav_path), language=s.whisper_language or None, vad_filter=True)
    return [TranscriptSegment(start=float(seg.start), end=float(seg.end), text=seg.text) for seg in segments]


def _has_cuda() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False
