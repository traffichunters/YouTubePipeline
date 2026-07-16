"""S1 — topic research. Picks a hero topic (proven formats) + unrelated-era tails,
with per-story factual talking points. Dedupes against channels/<slug>/history.jsonl.

Out: topic_brief.json
"""
from __future__ import annotations

import json

from .providers import get_script_engine
from .util import die, fill, log, write_json


def run_stage(ctx) -> None:
    n_tails = ctx.channel["structure"]["stories"].count("tail")
    era_keys = ", ".join(ctx.channel["visuals"]["era_art_styles"].keys())

    hist_path = ctx.channel.dir / "history.jsonl"
    used = []
    if hist_path.exists():
        used = [json.loads(l)["topic"] for l in hist_path.read_text().splitlines() if l]

    if ctx.topic:  # operator picked the hero topic on the CLI
        user_extra = f'\nThe hero topic MUST be: "{ctx.topic}". Build the brief around it.'
    else:
        user_extra = ""
    if getattr(ctx, "brief", None):  # operator-authored episode brief (authoritative)
        user_extra += (
            "\n\n--- OPERATOR EPISODE BRIEF (authoritative: follow its outline and "
            "use ONLY its source notes for factual talking points) ---\n"
            + ctx.brief
        )

    ambience = ctx.channel["audio"].get("ambience_profiles") or {}
    prompt = fill(ctx.channel.prompt("topic_research"),
        n_tails=n_tails,
        used_topics=json.dumps(used[-60:]) if used else "(none yet)",
        era_keys=era_keys,
        sound_keys=", ".join(ambience.keys()),
    ) + user_extra

    engine = get_script_engine(ctx.engine("script"))
    brief = engine.json("You are a precise strategist. Return only JSON.", prompt)

    for k in ("hero", "tails"):
        if k not in brief:
            die(f"topic brief missing '{k}': {brief}")
    brief["tails"] = brief["tails"][:n_tails]
    style_keys = ctx.channel["visuals"]["era_art_styles"]
    for story in [brief["hero"], *brief["tails"]]:
        if story.get("era_style_key") not in style_keys:
            story["era_style_key"] = "default"
    if ambience and brief["hero"].get("sound_profile") not in ambience:
        brief["hero"]["sound_profile"] = (
            ctx.channel["audio"].get("ambience_default")
            or next(iter(ambience)))

    write_json(ctx.outdir / "topic_brief.json", brief)
    ctx.costs.add_cost(getattr(engine, "cost_usd", 0.0))
    log(f"hero: {brief['hero']['topic']}")
    for t in brief["tails"]:
        log(f"tail: {t['topic']}")

    # record for future dedupe (idempotent per output dir)
    marker = ctx.outdir / ".history_recorded"
    if not marker.exists():
        with open(hist_path, "a") as fh:
            fh.write(json.dumps({"topic": brief["hero"]["topic"],
                                 "slug": ctx.outdir.name}) + "\n")
        marker.touch()
