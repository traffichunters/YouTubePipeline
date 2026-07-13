"""Shared TTS machinery — ported from the battle-tested sleepcast predecessor:

  - sliding-window RateLimiter (spans retries; a retry storm is exactly what
    caused the original outage this guards against)
  - per-chunk retries that honor the server's suggested retryDelay
  - RESUME: existing non-empty part files are kept, only missing chunks synth
  - parallel chunk synthesis (ThreadPoolExecutor), assembled in order
  - optional speed adjustment (atempo) applied once at concat time

Providers subclass BaseTTS and implement `_synth_chunk(text, out_path)`.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..util import FFMPEG, log, run

_RETRY_DELAY_RE = re.compile(
    r"retry(?:Delay['\"]?\s*[:=]\s*['\"]?|\s+in\s+)(\d+(?:\.\d+)?)s")


class RateLimiter:
    """Sliding-window requests-per-minute limiter shared across workers."""

    def __init__(self, rpm: int, window_s: float = 60.0):
        self.rpm, self.window = rpm, window_s
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._times and now - self._times[0] > self.window:
                    self._times.popleft()
                if len(self._times) < self.rpm:
                    self._times.append(now)
                    return
                wait = self.window - (now - self._times[0]) + 0.05
            time.sleep(max(wait, 0.05))


def _suggested_retry_delay(err: Exception) -> float | None:
    m = _RETRY_DELAY_RE.search(str(err))
    return float(m.group(1)) if m else None


def split_chunks(text: str, limit: int) -> list[str]:
    """Sentence-boundary chunking under a per-request character limit."""
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


class BaseTTS:
    name = "base"
    ext = "mp3"              # per-chunk container a provider writes
    chunk_chars = 4500
    rpm = 30                 # provider requests/minute budget
    workers = 4
    retries = 4
    cost_per_1k_chars = 0.0
    speed = 1.0              # >1 = faster narration, applied via atempo

    def __init__(self) -> None:
        self.cost_usd = 0.0

    # -- provider hook ---------------------------------------------------------
    def _synth_chunk(self, text: str, out_path: Path) -> None:
        raise NotImplementedError

    # -- shared pipeline -------------------------------------------------------
    def synth(self, text: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        chunks = split_chunks(text, self.chunk_chars)
        parts = [out_path.with_suffix(f".part{i:03d}.{self.ext}")
                 for i in range(len(chunks))]
        limiter = RateLimiter(self.rpm)

        todo = [(i, c, p) for i, (c, p) in enumerate(zip(chunks, parts))
                if not (p.exists() and p.stat().st_size > 0)]      # resume
        if len(todo) < len(chunks):
            log(f"  resume: {len(chunks) - len(todo)}/{len(chunks)} chunks cached")

        if todo:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futs = {pool.submit(self._with_retries, c, p, limiter): i
                        for i, c, p in todo}
                for fut in as_completed(futs):
                    fut.result()   # surface the first failure
            self.cost_usd += sum(len(c) for _, c, _ in todo) / 1000 \
                * self.cost_per_1k_chars

        self._concat(parts, out_path)
        for p in parts:
            p.unlink(missing_ok=True)
        return out_path

    def _with_retries(self, text: str, part: Path,
                      limiter: RateLimiter) -> None:
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            limiter.acquire()
            try:
                self._synth_chunk(text, part)
                if part.exists() and part.stat().st_size > 0:
                    return
                raise RuntimeError("provider returned empty audio")
            except Exception as e:  # noqa: BLE001 — transient API failures
                last = e
                part.unlink(missing_ok=True)
                delay = _suggested_retry_delay(e) or min(8.0 * attempt, 30.0)
                log(f"  tts chunk retry {attempt}/{self.retries} in {delay:.0f}s: "
                    f"{str(e)[:120]}")
                time.sleep(delay)
        raise RuntimeError(f"TTS chunk failed after {self.retries} tries: {last}")

    def _concat(self, parts: list[Path], out_path: Path) -> None:
        lst = out_path.with_suffix(".concat.txt")
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
        af = f"atempo={self.speed:.3f}" if abs(self.speed - 1.0) > 1e-3 else "anull"
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-af", af, "-ar", "44100", "-ac", "2", "-b:a", "128k",
             str(out_path)])
        lst.unlink()
