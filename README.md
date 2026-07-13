# youtube-pipeline

One command → an upload-ready "boring history for sleep" YouTube video: topic research →
script → TTS → images → thumbnail → two-phase video assembly → copy-paste metadata.

**Channels are config, not code.** `channels/<slug>/` holds everything brand-specific
(YAML + prompts + assets); `pipeline/` never references a channel by name. Adding a
channel = adding a folder.

Specs this implements (in the parent folder): `PIPELINE-GOAL.md` (build brief),
`VIDEO-STRUCTURE.md` (measured video spec — the assembler follows it exactly),
`TONE-OF-VOICE.md` (the script prompt).

## Setup (once)

```bash
/opt/homebrew/bin/python3.14 -m venv .venv        # system python is 3.9 — too old
.venv/bin/pip install -r requirements.txt
cp .env.example .env                               # then fill in your keys
```

`.env` needs `GOOGLE_API_KEY` — that one key covers images AND the default
Gemini TTS narration (~€1 per 90-min video, steerable via `tts_instructions`
in the channel profile). Optional: `OPENAI_API_KEY` (gpt-4o-mini-tts) or
`ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` (premium, ~€10+/video) for
channels that switch `engines.tts`. The default script engine is the local
`claude` CLI (no extra key). ffmpeg must be on PATH.

Each channel needs two one-time assets (already generated for the bundled channels):

```bash
.venv/bin/python tools/make_overlay.py --out channels/<slug>/assets/ember_overlay.mp4
.venv/bin/python tools/make_logo.py    --out channels/<slug>/assets/logo.png   # placeholder
```

## Make a video

```bash
# fully automatic (auto topic research):
.venv/bin/python -m pipeline.run --channel sleepless-historian

# choose the hero topic yourself:
.venv/bin/python -m pipeline.run --channel sleepless-historian \
    --topic "What SLEEP Was Like in Medieval Times"

# cheap dev run (short video, small render):
.venv/bin/python -m pipeline.run --channel sleepless-historian --minutes 25

# keyless smoke test (stub script/voice/images, 640x360):
.venv/bin/python -m pipeline.run --channel sleepless-historian --stub --preview --minutes 3

# re-run one stage / resume from a stage:
.venv/bin/python -m pipeline.run --channel sleepless-historian --only s6 --force
.venv/bin/python -m pipeline.run --channel sleepless-historian --from s4
```

Stages: `s1` topic · `s2` script · `s3` tts · `s4` images · `s5` thumbnail ·
`s6` assemble · `s7` metadata. Each stage caches on its output artifact in
`output/<channel>/<slug>/` and is skipped when present (`--force` overrides).

The run ends with a `READY TO UPLOAD` block. The only manual work is:
upload `final.mp4`, set `thumbnail.png`, paste title/description/tags from
`metadata.txt`, category Entertainment, publish.

## Add a channel

1. `cp -r channels/demo-nature-sleep channels/<new-slug>` and edit `channel.yaml`
   (name, brand text, structure, art styles, boilerplate, tags).
2. Rewrite the four files in `prompts/` for the new niche/voice.
3. Generate its `assets/ember_overlay.mp4` + `assets/logo.png` (or drop in real branding).
4. `python -m pipeline.run --channel <new-slug> --stub --preview --minutes 3` to smoke-test.

No code changes. `channels/demo-nature-sleep/` exists as the working proof.

## Notes

- The ember overlay is ONE seamless 120s loop reused on every video (measured drift
  ~30° up-left, twinkling embers, warm haze breathing ±10 luma). Never regenerate per
  video. Two styles exist: `--style embers` (SLH look) and `--style dust` (grey-white
  motes, same smoke — `shared/dust_overlay.mp4`, used by demo-nature-sleep). Point any
  channel at either via `visuals.ember_overlay` (paths resolve relative to the channel
  dir, so `../../shared/…` works).
- The dark ⅔ of every video is encoded once per loop and repeated with `-c copy` —
  that's why a 2-hour video renders fast.
- Costs are logged per stage in the run summary. A full 130-min video ≈ ~90
  images (~$3.60) + ~95k chars TTS (gemini ~€1 / openai ~€1.3 / elevenlabs
  ~€10+). The TTS layer has a rate limiter, per-chunk retries honoring server
  retryDelay, resume, and parallel synthesis (ported from sleepcast).
- Long segments (>1500 words) are written chapter-by-chapter (outline first,
  continuity guidance, no re-greetings) — single-shot 5k-word generations are
  unreliable.
- Encoding uses Apple's h264_videotoolbox hardware encoder when available.
- Policy note (PIPELINE-GOAL.md §10): the SLH clone is deliberate and temporary;
  differentiation later = editing that channel folder, nothing else.
