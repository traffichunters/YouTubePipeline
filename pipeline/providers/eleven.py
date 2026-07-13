"""ElevenLabs TTS — premium option. Built on BaseTTS, so it gets the rate
limiter, retries, resume, and parallel chunk synthesis for free."""
from __future__ import annotations

import os
from pathlib import Path

from ..util import die
from .tts_base import BaseTTS


class ElevenTTS(BaseTTS):
    name = "elevenlabs"
    ext = "mp3"
    chunk_chars = 4500
    rpm = 20
    workers = 3
    cost_per_1k_chars = 0.11

    def __init__(self, voice_cfg: dict) -> None:
        super().__init__()
        from elevenlabs.client import ElevenLabs
        self._client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
        vid = voice_cfg.get("voice_id", "")
        if isinstance(vid, str) and vid.startswith("env:"):
            vid = os.environ.get(vid[4:], "")
        if not vid:
            die("ELEVENLABS_VOICE_ID is empty — pick a voice and set it in .env")
        self._voice = vid
        self._model = voice_cfg.get("model", "eleven_multilingual_v2")
        self._settings = {
            "stability": voice_cfg.get("stability", 0.5),
            "similarity_boost": voice_cfg.get("similarity_boost", 0.75),
        }
        self.speed = float(voice_cfg.get("tts_speed", 1.0))

    def _synth_chunk(self, text: str, out_path: Path) -> None:
        audio = self._client.text_to_speech.convert(
            voice_id=self._voice, model_id=self._model, text=text,
            voice_settings=self._settings, output_format="mp3_44100_128",
        )
        with open(out_path, "wb") as fh:
            for b in audio:
                fh.write(b)
