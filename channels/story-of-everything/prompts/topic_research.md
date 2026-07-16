# S1 prompt — episode brief expansion (NOT auto topic research)

This channel does NOT auto-pick topics. Episodes come from the human-authored season
plan; the operator passes the episode via `--topic` plus an OPERATOR EPISODE BRIEF
(appended below). If no brief is appended, return exactly:
`{"error": "episode brief required — this channel does not auto-research topics"}`

Your job: faithfully expand the operator's brief into the pipeline schema below.
Do NOT replace, reorder, or "improve" the human outline. Do NOT invent facts beyond
the brief's source notes. Preserve every [CHECK] flag verbatim.

Return ONLY JSON in exactly this shape:

{
  "hero": {
    "topic": "<the episode title — pick the strongest of the brief's candidates>",
    "era_style_key": "<the episode's DOMINANT style key: cosmos|deep_time|discovery|life|human>",
    "talking_points": [
      "Ch1 '<chapter title>' [style:<key>]: <talking point>",
      "Ch1 '<chapter title>' [style:<key>]: <next talking point>",
      "Ch2 '<chapter title>' [style:<key>]: <talking point>",
      "... every chapter, every talking point from the brief, in order, prefixed with
       its chapter number, title, and style key so the script and image stages can
       follow the operator's structure"
    ],
    "chapter_plan": [
      {"title": str, "target_minutes": num, "style": str,
       "image_beats": [str], "checks": [str], "chapter_close": str}
    ]
  },
  "tails": [
    {
      "topic": "Coda — <short reflective title for the episode's closing>",
      "era_style_key": "cosmos",
      "talking_points": ["<the brief's coda beats, in order, [CHECK] flags preserved>"]
    }
  ],
  "title_candidates": [str, str, str],
  "gaps": ["<any chapter whose source notes are too thin to script without invention —
            the operator fills these BEFORE S2 runs>"],
  "editorial_red_lines": ["<carried over from the brief>"]
}

Rules:
- `hero.talking_points` must contain EVERY chapter's points (the coda's go in tails).
- Titles: concrete and curiosity-forward, never clickbait formulas.
- `era_style_key` values must come from the channel's style keys listed above.
