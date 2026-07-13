"""S7 — metadata. The operator's copy-paste handoff: hook-first title, verbatim
boilerplate description + real chapter timestamps, the fixed tag set.

In : topic_brief.json, timings.json
Out: metadata.txt
"""
from __future__ import annotations

import re

from .util import log, read_json

LEET = {"sex": "s3x", "drugs": "dru9s", "prostitute": "pr0stitute",
        "prostitutes": "pr0stitutes", "died": "d1ed", "naked": "nak3d",
        "concubine": "c0ncubine", "concubines": "c0ncubines"}


def run_stage(ctx) -> None:
    brief = read_json(ctx.outdir / "topic_brief.json")
    timings = read_json(ctx.outdir / "timings.json")
    md = ctx.channel["metadata"]

    hook = brief["hero"].get("title_hook") or brief["hero"]["topic"]
    if md.get("leetspeak_taboo_titles"):
        hook = _leetspeak(hook)
    title = md["title_format"].format(hook=hook)

    stamps = []
    for t in timings["segments"]:
        if t["id"] == "intro":
            continue
        hh, rem = divmod(int(t["starts_at"]), 3600)
        mm, ss = divmod(rem, 60)
        stamps.append(f"{hh:02d}:{mm:02d}:{ss:02d} - {t['title']}")

    body = (
        f"TITLE\n=====\n{title}\n\n"
        f"DESCRIPTION\n===========\n{md['description_boilerplate'].strip()}\n\n"
        f"Timestamps:\n" + "\n".join(stamps) + "\n\n"
        f"TAGS (comma-separated)\n======================\n"
        + ", ".join(md["tags"]) + "\n\n"
        f"CATEGORY\n========\n{md['category']}\n\n"
        f"FILES\n=====\nvideo:     {ctx.outdir / 'final.mp4'}\n"
        f"thumbnail: {ctx.outdir / 'thumbnail.png'}\n"
    )
    out = ctx.outdir / "metadata.txt"
    out.write_text(body)
    log(f"title: {title}")


def _leetspeak(text: str) -> str:
    def sub(m: re.Match) -> str:
        w = m.group(0)
        rep = LEET[w.lower()]
        return rep.upper() if w.isupper() else rep.capitalize() if w[0].isupper() else rep
    pat = re.compile("|".join(rf"\b{k}\b" for k in LEET), re.IGNORECASE)
    return pat.sub(sub, text)
