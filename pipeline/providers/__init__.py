"""Provider registry. Engines are chosen per channel config (or --stub override).

Every provider is a thin callable-style class; keys are checked lazily (fail fast
with a clear message only when a live engine is actually used).
"""
from __future__ import annotations

from ..config import require_keys


def get_script_engine(name: str):
    require_keys(name)
    if name == "claude":
        from .claude_cli import ClaudeScript
        return ClaudeScript()
    if name == "gemini":
        from .gemini import GeminiScript
        return GeminiScript()
    if name == "stub":
        from .stub import StubScript
        return StubScript()
    raise ValueError(f"unknown script engine: {name}")


def get_image_engine(name: str):
    require_keys(name)
    if name in ("gemini-flash", "imagen-4"):
        from .gemini import GeminiImage
        return GeminiImage(model=name)
    if name == "stub":
        from .stub import StubImage
        return StubImage()
    raise ValueError(f"unknown image engine: {name}")


def get_tts_engine(name: str, voice_cfg: dict):
    require_keys(name)
    if name == "elevenlabs":
        from .eleven import ElevenTTS
        return ElevenTTS(voice_cfg)
    if name == "stub":
        from .stub import StubTTS
        return StubTTS(voice_cfg)
    raise ValueError(f"unknown tts engine: {name}")
