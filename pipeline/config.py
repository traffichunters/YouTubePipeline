"""Channel config loading + validation.

Channels are DATA: everything brand/voice/style-specific lives in
channels/<slug>/channel.yaml + prompts/ + assets/. This loader is the contract.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .util import die

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANNELS_DIR = REPO_ROOT / "channels"
OUTPUT_DIR = REPO_ROOT / "output"

# keys a live (non-stub) engine needs; checked lazily by providers
ENV_KEYS = {
    "gemini": ["GOOGLE_API_KEY"],
    "gemini-flash": ["GOOGLE_API_KEY"],
    "imagen-4": ["GOOGLE_API_KEY"],
    "elevenlabs": ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"],
    "claude": [],   # uses the local `claude` CLI's own auth
    "stub": [],
}

REQUIRED_TOP_KEYS = ["channel", "engines", "voice", "script", "structure",
                     "visuals", "audio", "thumbnail", "metadata"]


@dataclass
class Channel:
    slug: str
    dir: Path
    cfg: dict
    prompts: dict = field(default_factory=dict)

    # -- convenience accessors (fail loudly on typos) -------------------------
    def __getitem__(self, key: str) -> dict:
        return self.cfg[key]

    def engine(self, kind: str) -> str:
        return self.cfg["engines"][kind]

    def asset(self, name: str) -> Path:
        p = self.dir / self.cfg["visuals"][name] if name in self.cfg["visuals"] \
            else self.dir / name
        return p

    def prompt(self, name: str) -> str:
        if name not in self.prompts:
            p = self.dir / "prompts" / f"{name}.md"
            if not p.exists():
                die(f"channel '{self.slug}' is missing prompts/{name}.md")
            self.prompts[name] = p.read_text()
        return self.prompts[name]


def load_env() -> None:
    # .env in the repo root; a parent-dir .env also works for convenience
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(REPO_ROOT.parent / ".env")


def require_keys(engine: str) -> None:
    """Fail fast, with a clear message, when a live engine lacks its keys."""
    missing = [k for k in ENV_KEYS.get(engine, []) if not os.environ.get(k)]
    if missing:
        die(
            f"engine '{engine}' needs {', '.join(missing)} — copy .env.example to "
            f".env and fill it in (or run with --stub for a keyless dev run)"
        )


def load_channel(slug: str) -> Channel:
    cdir = CHANNELS_DIR / slug
    cpath = cdir / "channel.yaml"
    if not cpath.exists():
        avail = ", ".join(sorted(p.name for p in CHANNELS_DIR.iterdir() if p.is_dir()))
        die(f"unknown channel '{slug}' (available: {avail})")
    cfg = yaml.safe_load(cpath.read_text())

    missing = [k for k in REQUIRED_TOP_KEYS if k not in cfg]
    if missing:
        die(f"{cpath} is missing sections: {', '.join(missing)}")

    st = cfg["structure"]
    if not (0 < st["hero_share"] < 1):
        die(f"structure.hero_share must be in (0,1), got {st['hero_share']}")
    if st["stories"][0] != "hero":
        die("structure.stories must start with 'hero'")
    for k in ("target_minutes", "silent_ember_tail_minutes"):
        if st[k] <= 0:
            die(f"structure.{k} must be positive")
    if cfg["script"]["wpm"] < 100 or cfg["script"]["wpm"] > 220:
        die("script.wpm looks wrong (expected 100–220)")

    return Channel(slug=slug, dir=cdir, cfg=cfg)
