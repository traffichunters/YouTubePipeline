"""Keyless dev providers — for `--stub` runs and CI. Clearly labeled: output is
placeholder quality, but exercises every real code path (chunking, timing, ffmpeg).

StubScript  -> deterministic filler prose at the exact requested word count
StubTTS     -> macOS `say` voice (falls back to a 220 Hz tone if `say` is absent)
StubImage   -> seeded painterly gradient PNGs (no text, era-tinted)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from ..util import run, FFMPEG

_FILLER = (
    "Long before anyone thought to write it down, the day began quietly. "
    "The morning was cold, which was not entirely a surprise. "
    "People rose with the light and set about their work, technically by choice. "
    "The bread was coarse, the ale was weak, and the neighbours were, to be fair, loud. "
    "It was, surprisingly, enough. "
    "And somewhere nearby, a rooster made his opinion known, as one does. "
)


class StubScript:
    name = "stub"
    cost_usd = 0.0

    def text(self, system: str, user: str) -> str:
        # honour "target_words: N" if present in the user prompt
        target = 400
        for tok in user.replace(",", " ").split():
            if tok.isdigit() and 100 <= int(tok) <= 50000:
                target = int(tok)
                break
        words = _FILLER.split()
        out = " ".join(words[i % len(words)] for i in range(target))
        if "id=intro" in user:
            out = ("Hey guys, tonight we explore a quiet corner of the past. "
                   "So before you get comfortable, take a moment, like the video and "
                   "subscribe, but only if you genuinely enjoy what I do here. "
                   "Now, dim the lights, and let's ease into tonight's journey together. ")
        return out

    def json(self, system: str, user: str, retries: int = 0) -> dict:
        n_tails = user.count('"tails"') or 3
        return {
            "hero": {
                "topic": "What Ordinary Mornings Were Like in a Medieval Village",
                "era_style_key": "medieval",
                "title_hook": "Why You Wouldn't Last a MORNING in a Medieval Village",
                "talking_points": ["dawn work bells", "coarse rye bread and weak ale",
                                   "shared field strips", "the village well",
                                   "curfew and candle costs"],
            },
            "tails": [
                {"topic": f"Stub tail story {i+1} from an unrelated era",
                 "era_style_key": "default",
                 "talking_points": ["point one", "point two", "point three"]}
                for i in range(3)
            ],
        }


class StubTTS:
    name = "stub"
    cost_usd = 0.0

    def __init__(self, voice_cfg: dict) -> None:
        self.wpm = 175  # `say` default-ish; timing realism isn't the stub's job

    def synth(self, text: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        aiff = out_path.with_suffix(".aiff")
        if shutil.which("say"):
            # feed text via file to dodge argv limits on long segments
            txt = out_path.with_suffix(".saytxt")
            txt.write_text(text)
            run(["say", "-r", str(self.wpm), "-o", str(aiff), "-f", str(txt)])
            txt.unlink()
            run([FFMPEG, "-y", "-i", str(aiff),
                 "-ar", "44100", "-ac", "2", "-b:a", "128k", str(out_path)])
            aiff.unlink()
        else:  # non-mac fallback: a quiet tone sized to the text length
            secs = max(2, len(text.split()) / (self.wpm / 60))
            run([FFMPEG, "-y", "-f", "lavfi", "-i",
                 f"sine=frequency=220:duration={secs:.1f}",
                 "-af", "volume=0.05", "-ar", "44100", "-ac", "2",
                 "-b:a", "128k", str(out_path)])
        return out_path


class StubImage:
    name = "stub"
    cost_usd = 0.0

    _TINTS = {"medieval": (96, 74, 46), "tudor": (110, 84, 60),
              "rome_egypt": (128, 96, 56), "greek_myth": (140, 74, 32),
              "feudal_japan": (90, 78, 88), "default": (100, 84, 60)}

    def generate(self, prompt: str, out_path: Path, aspect: str = "16:9") -> Path:
        from PIL import Image, ImageDraw, ImageFilter
        out_path.parent.mkdir(parents=True, exist_ok=True)
        seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16)
        tint = next((v for k, v in self._TINTS.items() if k in prompt.lower()),
                    self._TINTS["default"])
        w, h = (1920, 1080) if aspect == "16:9" else (1280, 720)
        img = Image.new("RGB", (w, h))
        px = img.load()
        for y in range(h):  # vertical warm gradient
            f = y / h
            row = tuple(int(c * (0.55 + 0.9 * f)) for c in tint)
            for x in range(0, w, 4):
                for dx in range(4):
                    if x + dx < w:
                        px[x + dx, y] = row
        d = ImageDraw.Draw(img, "RGBA")
        rng = seed
        for i in range(7):  # seeded translucent shapes = per-image variety
            rng = (rng * 1103515245 + 12345) % (2 ** 31)
            cx, cy = rng % w, (rng >> 8) % h
            r = 80 + (rng >> 16) % 300
            shade = tuple(min(255, c + 40 + (rng % 60)) for c in tint) + (70,)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=shade)
        img = img.filter(ImageFilter.GaussianBlur(6))
        img.save(out_path)
        return out_path
