"""S2 — script generation. Two-register narration per the Voice Spec prompt:
witty immersive hero (awake audience), plain-calm tails (sleeping audience).
One engine call per segment; word counts validated against wpm math.

In : topic_brief.json
Out: script.json  {segments:[{id, phase, title, text}], word_count}
"""
from __future__ import annotations

from .providers import get_script_engine
from .util import log, read_json, write_json

WORD_TOLERANCE = 0.25   # ±25% per segment before we ask for a rewrite
MAX_RETRIES = 1


def run_stage(ctx) -> None:
    brief = read_json(ctx.outdir / "topic_brief.json")
    st, sc = ctx.channel["structure"], ctx.channel["script"]
    wpm = sc["wpm"]
    total_min = ctx.minutes or st["target_minutes"]
    narration_min = total_min - st["silent_ember_tail_minutes"] * (0 if ctx.minutes else 1)
    hero_min = max(1.0, narration_min * st["hero_share"])
    n_tails = max(1, len(brief["tails"]))
    tail_min = max(1.0, (narration_min - hero_min) / n_tails)

    intro_words = 130                                   # the ~45s verbatim opener
    hero_words = max(250, int(hero_min * wpm) - intro_words)
    tail_words = max(250, int(tail_min * wpm))

    engine = get_script_engine(ctx.engine("script"))
    system = ctx.channel.prompt("script_system")
    segments = []

    def gen(seg_id: str, phase: str, title: str, words: int, task: str) -> None:
        user = (f"segment id={seg_id} phase={phase} target_words: {words}\n\n{task}")
        text = engine.text(system, user)
        got = len(text.split())
        for _ in range(MAX_RETRIES):
            if abs(got - words) <= words * WORD_TOLERANCE:
                break
            log(f"  {seg_id}: {got} words vs target {words} — regenerating")
            text = engine.text(system, user + f"\n\nYour previous draft was {got} "
                               f"words; the target is {words}. Match it closely.")
            got = len(text.split())
        segments.append({"id": seg_id, "phase": phase, "title": title, "text": text})
        log(f"  {seg_id}: {got} words (~{got/wpm:.1f} min)")

    hero = brief["hero"]
    gen("intro", "hero", "Intro",
        intro_words,
        f"Write ONLY the intro template, with the [TOPIC] sentence introducing: "
        f"{hero['topic']}. Give the topic sentence a dry twist.")
    gen("hero", "hero", hero["topic"], hero_words,
        f"Write the hero story: {hero['topic']}.\n"
        f"Factual talking points to build on:\n- "
        + "\n- ".join(hero.get("talking_points", [])))
    for i, tail in enumerate(brief["tails"], 1):
        gen(f"tail_{i}", "dark", tail["topic"], tail_words,
            f"Write tail story {i}: {tail['topic']}.\n"
            f"Factual talking points to build on:\n- "
            + "\n- ".join(tail.get("talking_points", [])))

    total_words = sum(len(s["text"].split()) for s in segments)
    write_json(ctx.outdir / "script.json", {
        "segments": segments,
        "word_count": total_words,
        "target_minutes": total_min,
        "estimated_minutes": round(total_words / wpm, 1),
    })
    ctx.costs.add_cost(getattr(engine, "cost_usd", 0.0))
    log(f"script: {total_words} words ≈ {total_words/wpm:.0f} min narration")
