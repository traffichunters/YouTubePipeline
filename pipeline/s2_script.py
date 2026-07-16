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
CHAPTER_THRESHOLD = 1500   # words; above this a segment is built chapter-by-chapter
CHAPTER_WORDS = 900        # target words per chapter (ported from sleepcast)


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

    def gen_single(seg_id: str, phase: str, words: int, task: str) -> str:
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
        return text

    def gen_chaptered(seg_id: str, phase: str, words: int, task: str) -> str:
        """Long segments (the hero, long tails): outline -> per-chapter calls with
        continuity guidance. Ported from sleepcast — single-shot 5k+ word
        generations are unreliable; ~900-word chapters are not."""
        n = max(2, round(words / CHAPTER_WORDS))
        outline = engine.json(
            system,
            f"Plan (do not write yet) the story below as exactly {n} chapters that "
            f"flow gently into each other. Return ONLY JSON: "
            f'{{"chapters": [{{"title": str, "summary": str}}]}}\n\n{task}')
        chapters = outline.get("chapters", [])[:n]
        if not chapters:
            return gen_single(seg_id, phase, words, task)
        per = words // len(chapters)
        titles = "\n".join(f"{i+1}. {c['title']}" for i, c in enumerate(chapters))
        prose = []
        for i, ch in enumerate(chapters):
            guidance = (
                f"segment id={seg_id} phase={phase} target_words: {per}\n\n"
                f"{task}\n\nWrite ONLY chapter {i+1} of {len(chapters)}: "
                f"\"{ch['title']}\" — {ch.get('summary','')}.\n"
                f"Full chapter list for context (do not restate it):\n{titles}\n\n")
            if i == 0:
                guidance += ("This opens the story (the video intro was already "
                             "spoken separately — do NOT greet the listener). ")
            else:
                guidance += ("Continue seamlessly. Do NOT re-introduce the topic, "
                             "greet the listener, or summarise earlier chapters — "
                             "pick up the thread quietly. ")
            if i == len(chapters) - 1:
                guidance += ("Close the whole story on a short, calm, reflective "
                             "line. No sign-off, no goodbye.")
            prose.append(engine.text(system, guidance).strip())
            log(f"    {seg_id} chapter {i+1}/{len(chapters)}: "
                f"{len(prose[-1].split())} words")
        return "\n\n".join(prose)

    def gen(seg_id: str, phase: str, title: str, words: int, task: str) -> None:
        if words > CHAPTER_THRESHOLD and not ctx.stub:
            text = gen_chaptered(seg_id, phase, words, task)
        else:
            text = gen_single(seg_id, phase, words, task)
        got = len(text.split())
        segments.append({"id": seg_id, "phase": phase, "title": title, "text": text})
        log(f"  {seg_id}: {got} words (~{got/wpm:.1f} min)")

    hero = brief["hero"]
    if sc.get("intro_template_verbatim", True):
        intro_task = (f"Write ONLY the intro template, with the [TOPIC] sentence "
                      f"introducing: {hero['topic']}. Give the topic sentence a dry twist.")
    else:  # cold-open channels: no template, no greeting — scene-first opening
        intro_task = (f"Write ONLY the COLD OPEN for: {hero['topic']}. A concrete "
                      f"scene or paradox in the first 25 words, per the system prompt. "
                      f"No greeting, no channel welcome, no 'today we'.")
    gen("intro", "hero", "Intro", intro_words, intro_task)
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
