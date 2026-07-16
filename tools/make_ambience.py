"""Generate the procedural ambience-bed loops (shared/ambience/*.m4a).

One-time tool, like make_overlay.py: each profile is a seamless ~120s loop of
shaped noise, meant to sit ~18 dB under the narration ("feel it, don't hear
it"). Replace any file with prepped stock audio whenever the operator finds a
better source — s6 only cares that the path in channel.yaml exists.

Seam safety: every amplitude LFO frequency is chosen so its period divides the
loop length exactly, and the noise sources are steady-state — so the loop
boundary carries no phase jump. (Lesson from the overlay white-flash bug:
anything that repeats every 2 minutes WILL be noticed by a sleeper.)

Usage: .venv/bin/python tools/make_ambience.py [--out shared/ambience] [--dur 120]
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

LOOP_S = 120

def _lfo(period_s: float, depth: float) -> str:
    """Slow amplitude LFO as a volume expression (tremolo's minimum rate of
    0.1 Hz is too fast for wave/breath rhythms). period_s must divide the loop
    length so the boundary is phase-continuous."""
    return (f"volume='1-{depth / 2}*(1-cos(2*PI*t/{period_s}))':eval=frame")


# name -> (description, noise source, filter chain per channel)
# All LFO periods divide LOOP_S exactly -> seamless loop boundary.
PROFILES = {
    "soft_rain": (
        "steady soft rain hiss, no thunder",
        "anoisesrc=color=pink:seed={seed}:d={dur}",
        "highpass=f=350,lowpass=f=5500," + _lfo(10, 0.12) + ",volume=0.8",
    ),
    "warm_room": (
        "warm room tone / distant hearth, no sharp crackles",
        "anoisesrc=color=brown:seed={seed}:d={dur}",
        "lowpass=f=550,highpass=f=40," + _lfo(20, 0.15) + ",volume=1.1",
    ),
    "deep_space": (
        "deep smooth brown-noise drone",
        "anoisesrc=color=brown:seed={seed}:d={dur}",
        "lowpass=f=220,highpass=f=25," + _lfo(40, 0.10) + ",volume=1.2",
    ),
    "forest_night": (
        "soft night-forest air, leaves, no loud birds",
        "anoisesrc=color=pink:seed={seed}:d={dur}",
        "highpass=f=200,lowpass=f=3200," + _lfo(10, 0.2) + ",volume=0.7",
    ),
    "ocean": (
        "slow distant ocean swell",
        "anoisesrc=color=brown:seed={seed}:d={dur}",
        "lowpass=f=900,highpass=f=60," + _lfo(12, 0.55) + ",volume=1.0",
    ),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="shared/ambience")
    ap.add_argument("--dur", type=int, default=LOOP_S)
    ap.add_argument("--only", help="generate a single profile")
    a = ap.parse_args()
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)

    for name, (desc, src, chain) in PROFILES.items():
        if a.only and name != a.only:
            continue
        out = outdir / f"{name}.m4a"
        # two different seeds -> decorrelated L/R = a wide, natural stereo bed
        left = src.format(seed=hash(name) % 9973, dur=a.dur)
        right = src.format(seed=hash(name) % 9973 + 1, dur=a.dur)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", left,
            "-f", "lavfi", "-i", right,
            "-filter_complex",
            f"[0:a]{chain}[l];[1:a]{chain}[r];"
            f"[l][r]join=inputs=2:channel_layout=stereo,"
            f"loudnorm=I=-30:LRA=3:TP=-6[out]",
            "-map", "[out]", "-t", str(a.dur),
            "-ar", "44100", "-c:a", "aac", "-b:a", "128k", str(out),
        ], check=True)
        mb = out.stat().st_size / 1e6
        print(f"{name:14s} {desc}  -> {out} ({mb:.1f} MB, {a.dur}s loop)")


if __name__ == "__main__":
    main()
