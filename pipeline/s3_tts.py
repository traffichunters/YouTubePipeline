"""S3 — TTS. Synthesizes each script segment separately (per-phase settings possible,
and real segment durations drive both chapter timestamps and the exact go-dark cut).

In : script.json
Out: audio/<segment>.mp3 + timings.json
"""
from __future__ import annotations

from pathlib import Path

from .providers import get_tts_engine
from .util import ffprobe_duration, log, read_json, write_json


def run_stage(ctx) -> None:
    script = read_json(ctx.outdir / "script.json")
    audio_dir = ctx.outdir / "audio"
    tts = get_tts_engine(ctx.engine("tts"), ctx.channel["voice"])

    timings, t_cursor = [], 0.0
    for seg in script["segments"]:
        out = audio_dir / f"{seg['id']}.mp3"
        if not out.exists() or ctx.force:
            log(f"tts: {seg['id']} ({len(seg['text'].split())} words)")
            tts.synth(seg["text"], out)
        secs = ffprobe_duration(out)
        timings.append({
            "id": seg["id"], "phase": seg["phase"],
            "title": seg.get("title", ""),
            "file": f"audio/{out.name}", "seconds": round(secs, 2),
            "starts_at": round(t_cursor, 2),
        })
        t_cursor += secs

    hero_s = sum(t["seconds"] for t in timings if t["phase"] == "hero")
    dark_s = sum(t["seconds"] for t in timings if t["phase"] == "dark")
    write_json(ctx.outdir / "timings.json", {
        "segments": timings,
        "hero_seconds": round(hero_s, 2),
        "dark_seconds": round(dark_s, 2),
        "narration_seconds": round(hero_s + dark_s, 2),
    })
    ctx.costs.add_cost(getattr(tts, "cost_usd", 0.0))
    log(f"narration: {hero_s/60:.1f} min hero + {dark_s/60:.1f} min dark")
