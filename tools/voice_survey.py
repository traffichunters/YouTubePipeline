"""Survey narrator voices across the sleep-history YouTube niche.

Discovers channels via yt-dlp search, samples one long video per channel
(75s of mid-video audio + auto-captions), and measures each narrator:
F0 (pitch), pitch IQR (steadiness), spectral centroid (brightness), and
effective wpm (caption words / video duration).

Usage: .venv/bin/python tools/voice_survey.py --out /path/survey.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

YTDLP = str(Path(__file__).resolve().parent.parent / ".venv" / "bin" / "yt-dlp")

QUERIES = [
    "boring history for sleep",
    "history for sleep story",
    "fall asleep medieval history",
    "sleep story ancient history 2 hours",
    "why you wouldn't last a day history sleep",
    "calm history bedtime documentary",
]
MIN_DURATION = 1500          # only long-form (25+ min) videos
MAX_CHANNELS = 22
SAMPLE_AT = 600              # seconds into the video
SAMPLE_LEN = 75


def sh(cmd: list[str], timeout: int = 180) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return res.stdout


def discover() -> list[dict]:
    seen, channels = {}, []
    for q in QUERIES:
        out = sh([YTDLP, f"ytsearch25:{q}", "--flat-playlist", "-j",
                  "--no-warnings"], timeout=240)
        for line in out.splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ch = e.get("channel") or e.get("uploader")
            cid = e.get("channel_id") or ch
            dur = e.get("duration") or 0
            if not ch or not cid or cid in seen or dur < MIN_DURATION:
                continue
            seen[cid] = True
            channels.append({"channel": ch, "channel_id": cid,
                             "video_id": e.get("id"), "title": e.get("title"),
                             "duration": dur, "query": q})
            print(f"  + {ch}  ({dur/60:.0f} min: {e.get('title', '')[:60]})",
                  flush=True)
        if len(channels) >= MAX_CHANNELS:
            break
    return channels[:MAX_CHANNELS]


def fetch_sample(video_id: str, work: Path, tag: str) -> tuple[Path | None, Path | None]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    wav = work / f"{tag}.wav"
    sub = None
    sh([YTDLP, url, "--no-warnings", "-f", "bestaudio[abr<100]/bestaudio",
        "--download-sections", f"*{SAMPLE_AT}-{SAMPLE_AT + SAMPLE_LEN}",
        "-x", "--audio-format", "wav", "--postprocessor-args",
        "ffmpeg:-ac 1 -ar 16000", "-o", str(work / f"{tag}.%(ext)s")],
       timeout=300)
    sh([YTDLP, url, "--no-warnings", "--skip-download", "--write-auto-subs",
        "--sub-langs", "en", "--convert-subs", "srt",
        "-o", str(work / f"{tag}.%(ext)s")], timeout=120)
    srts = list(work.glob(f"{tag}*.srt"))
    if srts:
        sub = srts[0]
    return (wav if wav.exists() else None), sub


def analyze_wav(p: Path) -> dict | None:
    try:
        with wave.open(str(p)) as w:
            sr = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), np.int16)
            x = x.astype(np.float32) / 32768
    except Exception:
        return None
    if sr != 16000 or len(x) < sr * 20:
        return None
    fl, hop = 640, 160
    frames = [x[i:i + fl] for i in range(0, len(x) - fl, hop)]
    en = np.array([np.sqrt((f ** 2).mean()) for f in frames])
    gate = np.percentile(en, 60)
    f0s, cents = [], []
    for f, e in zip(frames, en):
        if e < gate:
            continue
        f = f - f.mean()
        ac = np.correlate(f, f, "full")[fl - 1:]
        ac /= (ac[0] + 1e-9)
        lo, hi = sr // 320, sr // 60          # 60–320 Hz (covers female voices)
        pk = np.argmax(ac[lo:hi]) + lo
        if ac[pk] < 0.45:
            continue
        f0s.append(sr / pk)
        spec = np.abs(np.fft.rfft(f * np.hanning(fl)))
        fr = np.fft.rfftfreq(fl, 1 / sr)
        m = fr < 5000
        cents.append((fr[m] * spec[m]).sum() / (spec[m].sum() + 1e-9))
    if len(f0s) < 200:
        return None
    f0s, cents = np.array(f0s), np.array(cents)
    ve = en[en >= gate]
    return {
        "f0": round(float(np.median(f0s))),
        "f0_iqr": round(float(np.percentile(f0s, 75) - np.percentile(f0s, 25))),
        "centroid": round(float(np.median(cents))),
        "energy_dyn": round(float(np.percentile(ve, 90) / (np.percentile(ve, 50) + 1e-9)), 2),
    }


def wpm_from_srt(sub: Path, video_dur: float) -> int | None:
    txt = sub.read_text(errors="ignore")
    lines, seen = [], set()
    for ln in txt.splitlines():
        s = ln.strip()
        if not s or s.isdigit() or "-->" in s:
            continue
        s = re.sub(r"<[^>]+>", "", s)
        if s and s not in seen:            # auto-subs repeat rolling lines
            seen.add(s)
            lines.append(s)
    words = sum(len(l.split()) for l in lines)
    if words < 200 or video_dur <= 0:
        return None
    return round(words / (video_dur / 60))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", default="/tmp/voice_survey")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)

    print("discovering channels…", flush=True)
    channels = discover()
    print(f"\n{len(channels)} channels; sampling…", flush=True)

    results = []
    for i, ch in enumerate(channels):
        tag = f"ch{i:02d}"
        print(f"[{i + 1}/{len(channels)}] {ch['channel']}", flush=True)
        try:
            wav, sub = fetch_sample(ch["video_id"], work, tag)
            voice = analyze_wav(wav) if wav else None
            wpm = wpm_from_srt(sub, ch["duration"]) if sub else None
            results.append({**ch, "voice": voice, "wpm": wpm})
        except Exception as e:  # noqa: BLE001 — skip broken channels, keep surveying
            print(f"    skipped: {str(e)[:100]}", flush=True)
            results.append({**ch, "voice": None, "wpm": None,
                            "error": str(e)[:200]})
        time.sleep(2)

    Path(a.out).write_text(json.dumps(results, indent=2))
    ok = sum(1 for r in results if r.get("voice"))
    print(f"\nwrote {a.out} — {ok}/{len(results)} with full voice analysis")


if __name__ == "__main__":
    main()
