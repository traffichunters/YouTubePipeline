"""Pipeline orchestrator. One command -> upload-ready video.

  python -m pipeline.run --channel sleepless-historian
  python -m pipeline.run --channel sleepless-historian --topic "What SLEEP Was Like..."
  python -m pipeline.run --channel sleepless-historian --minutes 25          # dev run
  python -m pipeline.run --channel sleepless-historian --stub --preview      # keyless
  python -m pipeline.run --channel sleepless-historian --from s4 --force

Stages cache on their output artifact: if it exists, the stage is skipped
(unless --force). --from/--only re-run a subset.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import s1_topic, s2_script, s3_tts, s4_images, s5_thumbnail, s6_assemble, \
    s7_metadata
from .config import Channel, OUTPUT_DIR, load_channel, load_env
from .util import CostLog, log

STAGES = [
    ("s1", "topic", s1_topic.run_stage, ["topic_brief.json"]),
    ("s2", "script", s2_script.run_stage, ["script.json"]),
    ("s3", "tts", s3_tts.run_stage, ["timings.json"]),
    ("s4", "images", s4_images.run_stage, ["images/.complete"]),
    ("s5", "thumbnail", s5_thumbnail.run_stage, ["thumbnail.png"]),
    ("s6", "assemble", s6_assemble.run_stage, ["final.mp4"]),
    ("s7", "metadata", s7_metadata.run_stage, ["metadata.txt"]),
]


@dataclass
class Ctx:
    channel: Channel
    outdir: Path
    costs: CostLog
    force: bool = False
    minutes: int | None = None
    topic: str | None = None
    preview: bool = False
    stub: bool = False
    engine_overrides: dict = field(default_factory=dict)

    def engine(self, kind: str) -> str:
        if kind in self.engine_overrides:
            return self.engine_overrides[kind]
        return "stub" if self.stub else self.channel.engine(kind)


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "video"


def main() -> None:
    ap = argparse.ArgumentParser(prog="pipeline.run")
    ap.add_argument("--channel", required=True)
    ap.add_argument("--topic", help="hero topic override (skips auto research)")
    ap.add_argument("--minutes", type=int,
                    help="dev override for total video length")
    ap.add_argument("--slug", help="output folder name (default: from topic)")
    ap.add_argument("--from", dest="from_stage", help="re-run from this stage")
    ap.add_argument("--only", help="run only this stage")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--stub", action="store_true",
                    help="keyless dev engines (say/PIL/filler text)")
    ap.add_argument("--preview", action="store_true",
                    help="640x360 ultrafast render")
    ap.add_argument("--script-engine", help="override script engine for this run")
    ap.add_argument("--image-engine", help="override image engine for this run")
    ap.add_argument("--tts-engine", help="override tts engine for this run")
    a = ap.parse_args()

    load_env()
    channel = load_channel(a.channel)

    slug = a.slug or (f"stub-{_slugify(a.topic)}" if a.stub and a.topic
                      else _slugify(a.topic) if a.topic
                      else time.strftime("video-%Y%m%d"))
    outdir = OUTPUT_DIR / a.channel / slug
    outdir.mkdir(parents=True, exist_ok=True)

    overrides = {k: v for k, v in (("script", a.script_engine),
                                   ("image", a.image_engine),
                                   ("tts", a.tts_engine)) if v}
    ctx = Ctx(channel=channel, outdir=outdir, costs=CostLog(), force=a.force,
              minutes=a.minutes, topic=a.topic, preview=a.preview, stub=a.stub,
              engine_overrides=overrides)

    names = [s[0] for s in STAGES]
    start_i = names.index(a.from_stage) if a.from_stage else 0
    print(f"\n=== {channel['channel']['display_name']} -> {outdir} ===")
    if a.stub:
        print("    (STUB engines: placeholder script/voice/images — dev run)")

    for i, (sid, label, fn, artifacts) in enumerate(STAGES):
        if a.only and sid != a.only:
            continue
        if not a.only and i < start_i:
            continue
        ctx.costs.start(sid)
        done = all((outdir / art).exists() for art in artifacts)
        force_this = a.force and (a.only == sid or a.from_stage or a.only is None)
        if done and not force_this:
            print(f"[{sid}] {label}: cached")
            ctx.costs.finish(cached=True)
            continue
        print(f"[{sid}] {label}…")
        ctx.force = bool(force_this)
        fn(ctx)
        ctx.costs.finish(note=f"engine={ctx.engine('script') if sid in ('s1','s2') else ctx.engine('image') if sid in ('s4','s5') else ctx.engine('tts') if sid=='s3' else 'ffmpeg'}")

    print("\n--- run summary " + "-" * 44)
    print(ctx.costs.summary())
    if (outdir / "final.mp4").exists() and (outdir / "metadata.txt").exists():
        print(f"""
================ READY TO UPLOAD ================
video:     {outdir / 'final.mp4'}
thumbnail: {outdir / 'thumbnail.png'}
metadata:  {outdir / 'metadata.txt'}   <- copy title/description/tags from here
=================================================""")


if __name__ == "__main__":
    sys.exit(main())
