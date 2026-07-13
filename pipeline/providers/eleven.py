"""ElevenLabs TTS. Synthesizes per-segment mp3s; long texts are chunked at sentence
boundaries and concatenated losslessly."""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..util import die, log, run, FFMPEG

CHUNK_CHARS = 4500          # stay under request limits, split on sentences
COST_PER_1K_CHARS = 0.11    # indicative, for the cost summary


class ElevenTTS:
    name = "elevenlabs"

    def __init__(self, voice_cfg: dict) -> None:
        from elevenlabs.client import ElevenLabs
        self.client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
        vid = voice_cfg["voice_id"]
        if isinstance(vid, str) and vid.startswith("env:"):
            vid = os.environ.get(vid[4:], "")
        if not vid:
            die("ELEVENLABS_VOICE_ID is empty — pick a voice and set it in .env")
        self.voice_id = vid
        self.model = voice_cfg.get("model", "eleven_multilingual_v2")
        self.settings = {
            "stability": voice_cfg.get("stability", 0.5),
            "similarity_boost": voice_cfg.get("similarity_boost", 0.75),
        }
        self.cost_usd = 0.0

    def synth(self, text: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        chunks = _split_sentences(text, CHUNK_CHARS)
        parts: list[Path] = []
        for i, chunk in enumerate(chunks):
            p = out_path.with_suffix(f".part{i}.mp3")
            audio = self.client.text_to_speech.convert(
                voice_id=self.voice_id, model_id=self.model, text=chunk,
                voice_settings=self.settings,
                output_format="mp3_44100_128",
            )
            with open(p, "wb") as fh:
                for b in audio:
                    fh.write(b)
            self.cost_usd += len(chunk) / 1000 * COST_PER_1K_CHARS
            parts.append(p)
        if len(parts) == 1:
            parts[0].rename(out_path)
        else:
            lst = out_path.with_suffix(".txt")
            lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
            run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                 "-c", "copy", str(out_path)])
            for p in parts:
                p.unlink()
            lst.unlink()
        return out_path


def _split_sentences(text: str, limit: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > limit:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks
