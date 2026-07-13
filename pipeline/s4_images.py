"""S4 — hero images. Era-matched art for the bright phase only; count derives from
the REAL hero-narration duration (timings.json), so it needs S3 to have run.

In : topic_brief.json, script.json, timings.json
Out: images/img_NNN.png
"""
from __future__ import annotations

import re

from .providers import get_image_engine
from .s6_assemble import n_images_needed
from .util import fill, log, read_json


def run_stage(ctx) -> None:
    brief = read_json(ctx.outdir / "topic_brief.json")
    script = read_json(ctx.outdir / "script.json")
    timings = read_json(ctx.outdir / "timings.json")
    vis = ctx.channel["visuals"]

    n = n_images_needed(timings["hero_seconds"], vis)
    era_key = brief["hero"].get("era_style_key", "default")
    era_style = vis["era_art_styles"].get(era_key, vis["era_art_styles"]["default"])
    beats = _beats_from_script(script, brief, n)
    tmpl = ctx.channel.prompt("image_style")

    engine = get_image_engine(ctx.engine("image"))
    imgdir = ctx.outdir / "images"
    log(f"generating {n} hero images ({era_key})")
    for i, beat in enumerate(beats):
        out = imgdir / f"img_{i:03d}.png"
        if out.exists() and not ctx.force:
            continue
        try:
            engine.generate(fill(tmpl, era_style=era_style, beat=beat), out)
        except Exception as e:  # noqa: BLE001 — one bad image must not kill the run
            prev = imgdir / f"img_{i-1:03d}.png"
            if i > 0 and prev.exists():
                import shutil
                shutil.copy(prev, out)
                log(f"  WARNING img_{i:03d} failed permanently — reused previous "
                    f"still ({str(e)[:120]})")
            else:
                raise
        if (i + 1) % 10 == 0:
            log(f"  {i + 1}/{n}")
    ctx.costs.add_cost(getattr(engine, "cost_usd", 0.0))


def _beats_from_script(script: dict, brief: dict, n: int) -> list[str]:
    """One visual beat per image, walked through the hero narration in order —
    images loosely track the story."""
    hero_text = next(s["text"] for s in script["segments"] if s["id"] == "hero")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", hero_text)
                 if len(s.split()) > 6]
    topic = brief["hero"]["topic"]
    if not sentences:
        return [topic] * n
    beats = []
    for i in range(n):
        s = sentences[min(int(i * len(sentences) / n), len(sentences) - 1)]
        beats.append(f"{topic} — {s[:220]}")
    return beats
