"""Gemini + OpenAI TTS providers (ported from sleepcast). ~10x cheaper than
ElevenLabs per video, and steerable: a delivery-instructions prompt is the main
quality knob for calm narration.

Approx cost per 90-min video (mid-2026): gemini ~€1, openai ~€1.3,
elevenlabs ~€10+.
"""
from __future__ import annotations

import os
import wave
from pathlib import Path

from .tts_base import BaseTTS

DEFAULT_INSTRUCTIONS = (
    "Speak in a warm, calm, low voice. Relaxed, unhurried pace with gentle "
    "pauses. Soothing bedtime-narration delivery; never energetic."
)


class GeminiTTS(BaseTTS):
    name = "gemini"
    ext = "wav"               # raw 24 kHz PCM wrapped as WAV per chunk
    chunk_chars = 3500
    rpm = 9                   # flash-preview-tts free/low tier is tight
    workers = 3
    cost_per_1k_chars = 0.012

    def __init__(self, voice_cfg: dict) -> None:
        super().__init__()
        from google import genai
        key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        self._genai = genai
        self._client = genai.Client(api_key=key)
        self._model = voice_cfg.get("gemini_model", "gemini-2.5-flash-preview-tts")
        self._voice = voice_cfg.get("gemini_voice", "Charon")
        self._instructions = voice_cfg.get("tts_instructions", DEFAULT_INSTRUCTIONS)
        self.speed = float(voice_cfg.get("tts_speed", 1.0))

    def _synth_chunk(self, text: str, out_path: Path) -> None:
        from google.genai import types
        response = self._client.models.generate_content(
            model=self._model,
            contents=f"Say this — {self._instructions}:\n\n{text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=self._voice))),
            ),
        )
        pcm = None
        cand = (getattr(response, "candidates", None) or [None])[0]
        if cand is not None and getattr(cand, "content", None) is not None:
            for part in cand.content.parts or []:
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    pcm = inline.data
                    break
        if not pcm:
            reason = getattr(cand, "finish_reason", None) if cand else None
            raise RuntimeError(f"Gemini TTS returned no audio (finish_reason={reason})")
        with wave.open(str(out_path), "wb") as wf:   # 16-bit mono 24 kHz PCM
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm)


class OpenAITTS(BaseTTS):
    name = "openai"
    ext = "wav"
    chunk_chars = 4000
    rpm = 40
    workers = 4
    cost_per_1k_chars = 0.014

    def __init__(self, voice_cfg: dict) -> None:
        super().__init__()
        from openai import OpenAI
        self._client = OpenAI()
        self._model = voice_cfg.get("openai_model", "gpt-4o-mini-tts")
        self._voice = voice_cfg.get("openai_voice", "onyx")
        self._instructions = voice_cfg.get("tts_instructions", DEFAULT_INSTRUCTIONS)
        self.speed = float(voice_cfg.get("tts_speed", 1.0))

    def _synth_chunk(self, text: str, out_path: Path) -> None:
        with self._client.audio.speech.with_streaming_response.create(
            model=self._model, voice=self._voice, input=text,
            instructions=self._instructions, response_format="wav",
        ) as resp:
            resp.stream_to_file(out_path)
