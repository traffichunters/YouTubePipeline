"""Shared helpers: subprocess, ffprobe, logging, cost tracking."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def die(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], quiet: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command; on failure show the command and its stderr tail."""
    res = subprocess.run(cmd, capture_output=quiet, text=True)
    if check and res.returncode != 0:
        tail = (res.stderr or "")[-2000:] if quiet else ""
        die(f"command failed ({res.returncode}): {shlex.join(cmd)}\n{tail}")
    return res


def ffprobe_duration(path: Path) -> float:
    res = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
               "-of", "json", str(path)])
    return float(json.loads(res.stdout)["format"]["duration"])


def fill(template: str, **kw) -> str:
    """Literal {key} substitution that tolerates braces elsewhere in the template
    (unlike str.format)."""
    for k, v in kw.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def read_json(path: Path):
    return json.loads(path.read_text())


class CostLog:
    """Per-stage duration + API-cost accumulator, printed in the run summary."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._t0: float | None = None
        self._stage: str | None = None
        self._pending: float = 0.0

    def start(self, stage: str) -> None:
        self._stage, self._t0, self._pending = stage, time.time(), 0.0

    def finish(self, cached: bool = False, cost_usd: float = 0.0, note: str = "") -> None:
        self.rows.append({
            "stage": self._stage,
            "seconds": 0.0 if cached else round(time.time() - self._t0, 1),
            "cached": cached,
            "cost_usd": round(cost_usd + self._pending, 4),
            "note": note,
        })
        self._pending = 0.0

    def add_cost(self, usd: float) -> None:
        # accumulate against the RUNNING stage; applied when finish() writes its row
        self._pending += usd

    def summary(self) -> str:
        lines = [f"{'stage':<14}{'time':>8}  {'cost':>8}  note"]
        total_s = total_c = 0.0
        for r in self.rows:
            t = "cached" if r["cached"] else f"{r['seconds']:.0f}s"
            lines.append(f"{r['stage']:<14}{t:>8}  ${r['cost_usd']:<7.2f}  {r['note']}")
            total_s += r["seconds"]
            total_c += r["cost_usd"]
        lines.append(f"{'TOTAL':<14}{total_s:>7.0f}s  ${total_c:<7.2f}")
        return "\n".join(lines)
