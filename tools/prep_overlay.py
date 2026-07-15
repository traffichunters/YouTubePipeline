"""Prepare a stock/authored overlay video as a production channel asset.

Overlays are prelit-on-black particle/smoke clips that the assembler
screen-blends over both phases. This script normalizes a source (often 4K
stock) into the asset the pipeline actually uses:

  - scale to the master resolution (default 1920x1080) and fps (30)
  - optional slow-down (--slow 2.0 = half speed)
  - optional warm tint (--warm 0.3) to pull cool/magenta haze toward amber
  - optional loop crossfade (--loop-xfade 1.0) to hide a hard loop seam
  - reports the loop-seam quality (first vs last frame difference)

Keep the highest-resolution original archived; run this once per channel look.

Usage:
  .venv/bin/python tools/prep_overlay.py --src ~/Downloads/overlay-4k.mp4 \
      --out shared/youtube-overlay.mp4 [--slow 1] [--warm 0] [--loop-xfade 0]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{res.stderr[-1500:]}")
    return res


def duration_of(path: str) -> float:
    res = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "json", path])
    return float(json.loads(res.stdout)["format"]["duration"])


def seam_score(path: str) -> float:
    """Mean abs pixel difference between the first and last frame (0 = perfect
    loop). Under ~4 is visually seamless for dark particle overlays."""
    dur = duration_of(path)
    for t, name in ((0.0, "/tmp/_seam_a.png"), (max(0.0, dur - 0.05), "/tmp/_seam_b.png")):
        run(["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
             "-vf", "scale=320:180", name])
    res = run(["ffmpeg", "-i", "/tmp/_seam_a.png", "-i", "/tmp/_seam_b.png",
               "-filter_complex", "blend=all_mode=difference,signalstats,metadata=print",
               "-f", "null", "-"])
    import re
    m = re.search(r"YAVG=([0-9.]+)", res.stderr)
    return float(m.group(1)) if m else -1.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--slow", type=float, default=1.0,
                    help="2.0 = half speed (duration doubles)")
    ap.add_argument("--warm", type=float, default=0.0,
                    help="0..1: pull cool/magenta haze toward amber")
    ap.add_argument("--loop-xfade", type=float, default=0.0,
                    help="seconds: crossfade tail into head to hide a loop seam")
    ap.add_argument("--trim-start", type=float, default=0.0,
                    help="seconds to cut from the head (fade-ins/white flashes)")
    ap.add_argument("--trim-end", type=float, default=0.0,
                    help="seconds to cut from the tail")
    a = ap.parse_args()
    w, h = a.size.split("x")

    filters = []
    if a.slow != 1.0:
        filters.append(f"setpts={a.slow}*PTS")
    filters.append(f"fps={a.fps}")
    filters.append(f"scale={w}:{h}")
    if a.warm > 0:
        # shift blues/magentas toward warm amber, scaled by --warm
        rs = 0.25 * a.warm
        bs = -0.30 * a.warm
        filters.append(f"colorbalance=rs={rs:.3f}:gs={rs/3:.3f}:bs={bs:.3f}:"
                       f"rm={rs/2:.3f}:bm={bs/2:.3f}")
    vf = ",".join(filters)

    in_opts = []
    if a.trim_start > 0:
        in_opts += ["-ss", f"{a.trim_start:.3f}"]
    if a.trim_end > 0:
        in_opts += ["-t", f"{duration_of(a.src) - a.trim_start - a.trim_end:.3f}"]

    if a.loop_xfade > 0:
        dur = (duration_of(a.src) - a.trim_start - a.trim_end) * a.slow
        x = a.loop_xfade
        # main body crossfades into its own head -> mathematically seamless loop
        fc = (f"[0:v]{vf},split[a][b];"
              f"[a]trim=0:{dur - x:.3f},setpts=PTS-STARTPTS[body];"
              f"[b]trim={dur - x:.3f}:{dur:.3f},setpts=PTS-STARTPTS[tail];"
              f"[0:v]{vf},trim=0:{x:.3f},setpts=PTS-STARTPTS[head];"
              f"[tail][head]blend=all_expr='A*(1-T/{x})+B*(T/{x})':shortest=1[xf];"
              f"[body][xf]concat=n=2:v=1[vout]")
        run(["ffmpeg", "-y", *in_opts, "-i", a.src, "-filter_complex", fc,
             "-map", "[vout]", "-c:v", "libx264", "-preset", "medium",
             "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             "-an", a.out])
    else:
        run(["ffmpeg", "-y", *in_opts, "-i", a.src, "-vf", vf,
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", a.out])

    score = seam_score(a.out)
    verdict = "seamless" if 0 <= score < 4 else "VISIBLE SEAM — consider --loop-xfade 1.0"
    print(f"wrote {a.out} ({duration_of(a.out):.1f}s) — loop seam score "
          f"{score:.1f} ({verdict})")


if __name__ == "__main__":
    main()
