"""Script generation via the local `claude` CLI (`claude -p`).

Uses the operator's existing Claude Code auth — no extra API key. Cost is billed to
the operator's Claude plan; we log 0 USD but note the engine in the summary.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

from ..util import die


class ClaudeScript:
    name = "claude"
    cost_usd = 0.0  # billed via the operator's Claude Code plan

    def __init__(self) -> None:
        if not shutil.which("claude"):
            die("script engine 'claude' needs the `claude` CLI on PATH "
                "(or switch engines / use --stub)")

    def _call(self, system: str, user: str, timeout: int = 600) -> str:
        res = subprocess.run(
            ["claude", "-p", "--append-system-prompt", system, user],
            capture_output=True, text=True, timeout=timeout,
        )
        if res.returncode != 0:
            die(f"claude CLI failed: {res.stderr[-1500:]}")
        return res.stdout.strip()

    def text(self, system: str, user: str) -> str:
        return self._call(system, user)

    def json(self, system: str, user: str, retries: int = 2) -> dict:
        prompt = user
        for attempt in range(retries + 1):
            out = self._call(system, prompt)
            try:
                return _extract_json(out)
            except ValueError:
                prompt = (user + "\n\nYour previous reply was not valid JSON. "
                          "Return ONLY the JSON object, nothing else.")
        die(f"claude returned invalid JSON after {retries + 1} attempts:\n{out[:800]}")


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object found")
    return json.loads(m.group(0))
