"""S6 — video assembly. Implements the measured two-phase model exactly
(VIDEO-STRUCTURE.md §6):

  hero:  static stills, intro-ramp holds then steady ~34s, 0.35s xfade=hblur
         dissolves, static vignette on the art, ember overlay screen-blended,
         logo bottom-left  (opens hard on image 1, no fade-in)
  cut:   single-frame hard cut to black (a plain concat boundary)
  tail:  black + the same looped overlay + logo — encoded ONCE per loop length,
         then repeated via concat -c copy (this is the stream-copy economics)
  end:   silent ember minutes, then EOF (no outro, ever)
  audio: dry narration only, loudnorm to the measured −19.5 LUFS

In : timings.json, images/, channel assets
Out: final.mp4
"""
from __future__ import annotations

import math
from pathlib import Path

from .util import FFMPEG, ffprobe_duration, log, read_json, run


# ---------------------------------------------------------------- scheduling --
def plan_image_schedule(hero_seconds: float, vis: dict) -> list[float]:
    """Hold duration per image: intro ramp, then steady; last hold absorbs the
    remainder so sum(holds) == hero_seconds exactly."""
    ramp = list(vis.get("intro_ramp_holds", []))
    steady = float(vis["hero_image_seconds"])
    holds: list[float] = []
    remaining = hero_seconds
    for h in ramp:
        if remaining <= h * 1.5:
            break
        holds.append(float(h))
        remaining -= h
    while remaining > steady * 1.6:
        holds.append(steady)
        remaining -= steady
    holds.append(round(remaining, 3))          # final hold absorbs remainder
    return holds


def n_images_needed(hero_seconds: float, vis: dict) -> int:
    return len(plan_image_schedule(hero_seconds, vis))


# ------------------------------------------------------------------ helpers --
_HW: bool | None = None


def _hwaccel_available() -> bool:
    """Probe once whether h264_videotoolbox (Apple hardware encoder) actually
    works in this ffmpeg build — several times faster than libx264 on this Mac
    and frees the CPU. Ported from sleepcast."""
    global _HW
    if _HW is None:
        import subprocess
        try:
            proc = subprocess.run(
                [FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                 "-i", "color=black:s=64x64:d=0.1",
                 "-c:v", "h264_videotoolbox", "-f", "null", "-"],
                capture_output=True, timeout=15)
            _HW = proc.returncode == 0
        except Exception:  # noqa: BLE001
            _HW = False
        log(f"encoder: {'h264_videotoolbox (hardware)' if _HW else 'libx264'}")
    return _HW


def _enc_args(ctx) -> list[str]:
    if ctx.preview:
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-pix_fmt", "yuv420p"]
    if _hwaccel_available():
        # identical settings on every part so the final concat can stream-copy
        return ["-c:v", "h264_videotoolbox", "-b:v", "12M",
                "-pix_fmt", "yuv420p", "-video_track_timescale", "90000"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-video_track_timescale", "90000"]


def _res(ctx) -> tuple[int, int]:
    if ctx.preview:
        return 640, 360
    w, h = ctx.channel["visuals"]["resolution"].split("x")
    return int(w), int(h)


def _prep_img(idx: int, w: int, h: int) -> str:
    """Scale-to-cover + crop + static vignette (the darkening the screen-blended
    overlay can't provide) + conform."""
    return (f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,vignette=angle=PI/5,format=yuv420p[im{idx}]")


def _valid_duration(path: Path, expected_s: float, tol: float = 2.0) -> bool:
    """Guards against reusing partial files left by killed runs."""
    if not path.exists():
        return False
    try:
        return abs(ffprobe_duration(path) - expected_s) <= tol
    except SystemExit:
        return False


BATCH = 10  # images per ffmpeg invocation — keeps filtergraph memory bounded


def _build_hero_chunked(ctx, images, holds, trans, hero_s, overlay, logo,
                        logo_h, op_hero, W, H, fps, work: Path) -> Path:
    """Hero slideshow in resumable batches, then one lightweight file-level
    xfade join. Ember-loop offsets stay continuous across batch boundaries."""
    loop_len = ffprobe_duration(overlay)
    batches = [list(range(i, min(i + BATCH, len(images))))
               for i in range(0, len(images), BATCH)]
    seg_files, seg_durs, t_cursor = [], [], 0.0

    for b, idxs in enumerate(batches):
        last_batch = b == len(batches) - 1
        bh = [holds[i] for i in idxs]
        if not last_batch:
            bh[-1] += trans          # consumed by the batch-boundary xfade
        seg = work / f"hero_b{b:02d}.mp4"
        seg_dur = sum(bh)
        if not (_valid_duration(seg, seg_dur) and not ctx.force):
            n = len(idxs)
            inputs: list[str] = []
            for j, i in enumerate(idxs):
                dur = bh[j] + (trans if j < n - 1 else 0)
                inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-r", str(fps),
                           "-i", str(images[i])]
            ov_off = t_cursor % loop_len
            inputs += ["-ss", f"{ov_off:.3f}", "-stream_loop", "-1",
                       "-i", str(overlay)]
            inputs += ["-i", str(logo)]
            parts = [_prep_img(j, W, H) for j in range(n)]
            if n == 1:
                parts.append("[im0]copy[xf]")
            else:
                offset, cur = 0.0, "im0"
                for j in range(1, n):
                    offset += bh[j - 1]
                    nxt = f"xf{j}" if j < n - 1 else "xf"
                    parts.append(f"[{cur}][im{j}]xfade=transition=hblur:"
                                 f"duration={trans}:offset={offset:.3f}[{nxt}]")
                    cur = nxt
            parts += [
                f"[{n}:v]scale={W}:{H},setsar=1,format=gbrp,"
                f"lutrgb=r=val*{op_hero}:g=val*{op_hero}:b=val*{op_hero}[ov]",
                "[xf]format=gbrp[base]",
                "[base][ov]blend=all_mode=screen,format=yuv420p[lit]",
                f"[{n+1}:v]scale=-2:{logo_h}[lg]",
                "[lit][lg]overlay=24:H-h-24[vout]",
            ]
            run([FFMPEG, "-y", *inputs, "-filter_complex", ";".join(parts),
                 "-map", "[vout]", "-an", "-t", f"{seg_dur:.3f}", "-r", str(fps),
                 *_enc_args(ctx), str(seg)])
            log(f"  hero batch {b + 1}/{len(batches)} "
                f"({seg_dur/60:.1f} min)")
        seg_files.append(seg)
        seg_durs.append(seg_dur)
        t_cursor += seg_dur - (0 if last_batch else trans)

    hero = work / "hero.mp4"
    if len(seg_files) == 1:
        seg_files[0].rename(hero)
        return hero
    # file-level xfade join (few inputs, sequential decode — memory-light)
    inputs = []
    for s in seg_files:
        inputs += ["-i", str(s)]
    parts, offset, cur = [], 0.0, "0:v"
    for k in range(1, len(seg_files)):
        offset += seg_durs[k - 1] - trans
        nxt = f"j{k}" if k < len(seg_files) - 1 else "vout"
        parts.append(f"[{cur}][{k}:v]xfade=transition=hblur:"
                     f"duration={trans}:offset={offset:.3f}[{nxt}]")
        cur = nxt
    run([FFMPEG, "-y", *inputs, "-filter_complex", ";".join(parts),
         "-map", "[vout]", "-an", "-t", f"{hero_s:.3f}", "-r", str(fps),
         *_enc_args(ctx), str(hero)])
    return hero


# -------------------------------------------------------------------- stage --
def run_stage(ctx) -> None:
    vis = ctx.channel["visuals"]
    timings = read_json(ctx.outdir / "timings.json")
    W, H = _res(ctx)
    fps = int(vis.get("fps", 30))
    trans = float(vis["image_transition_seconds"])
    work = ctx.outdir / "work"
    work.mkdir(exist_ok=True)

    overlay = ctx.channel.dir / vis["ember_overlay"]
    logo = ctx.channel.dir / vis["logo"]
    if not overlay.exists():
        from .util import die
        die(f"missing overlay asset {overlay} — generate it once with "
            f"tools/make_overlay.py (see README)")

    hero_s = timings["hero_seconds"]
    tail_narr_s = timings["dark_seconds"]
    silent_s = ctx.channel["structure"]["silent_ember_tail_minutes"] * 60
    if ctx.minutes:  # dev override scales the silent tail down too
        silent_s = min(silent_s, 30)
    tail_s = tail_narr_s + silent_s
    logo_h = max(2, int(H * float(vis.get("logo_height_frac", 0.13)) / 2) * 2)
    op_hero = float(vis.get("overlay_opacity_hero", 0.85))

    images = sorted((ctx.outdir / "images").glob("img_*.png"))
    holds = plan_image_schedule(hero_s, vis)
    if len(images) < len(holds):  # tolerate a short image set: reuse from start
        images = (images * math.ceil(len(holds) / len(images)))[:len(holds)]
    images = images[:len(holds)]
    log(f"hero: {len(holds)} stills over {hero_s/60:.1f} min "
        f"(ramp {vis.get('intro_ramp_holds')}, steady {vis['hero_image_seconds']}s)")

    # ---- 1) hero.mp4: stills -> xfade hblur chain -> vignette art + overlay + logo
    # Built in BATCHES of ~10 images: a 75-input single filtergraph gets
    # memory-killed on macOS. Batches are resumable and duration-verified.
    hero_mp4 = work / "hero.mp4"
    if not _valid_duration(hero_mp4, hero_s) or ctx.force:
        hero_mp4 = _build_hero_chunked(ctx, images, holds, trans, hero_s,
                                       overlay, logo, logo_h, op_hero,
                                       W, H, fps, work)
        log(f"hero.mp4: {ffprobe_duration(hero_mp4):.1f}s")

    # ---- 2) dark loop: encoded once, repeated by stream copy ------------------
    loop_len = ffprobe_duration(overlay)
    dark_loop = work / "dark_loop.mp4"
    if not dark_loop.exists() or ctx.force:
        run([FFMPEG, "-y",
             "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r={fps}:d={loop_len:.3f}",
             "-i", str(overlay), "-i", str(logo),
             "-filter_complex",
             f"[1:v]scale={W}:{H},setsar=1,format=gbrp[ov];"
             f"[0:v]format=gbrp[bk];[bk][ov]blend=all_mode=screen,format=yuv420p[lit];"
             f"[2:v]scale=-2:{logo_h}[lg];[lit][lg]overlay=24:H-h-24[vout]",
             "-map", "[vout]", "-t", f"{loop_len:.3f}", "-r", str(fps),
             *_enc_args(ctx), "-an", str(dark_loop)])

    n_full = int(tail_s // loop_len)
    rem = tail_s - n_full * loop_len
    dark_rem = work / "dark_rem.mp4"
    if rem > 0.05:
        run([FFMPEG, "-y", "-i", str(dark_loop), "-t", f"{rem:.3f}",
             *_enc_args(ctx), "-an", str(dark_rem)])

    # ---- 3) hard cut = concat boundary; repeats are -c copy -------------------
    video_mp4 = work / "video.mp4"
    lst = work / "concat.txt"
    entries = [hero_mp4] + [dark_loop] * n_full + ([dark_rem] if rem > 0.05 else [])
    lst.write_text("".join(f"file '{p.name}'\n" for p in entries))
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(video_mp4)])
    log(f"tail: {n_full}x {loop_len:.0f}s loop stream-copied + {rem:.0f}s remainder "
        f"({silent_s/60:.0f} min silent ember outro)")

    # ---- 4) full narration, loudnormed; video keeps running after voice ends --
    final = ctx.outdir / "final.mp4"
    all_lst = work / "audio_all.txt"
    all_lst.write_text("".join(
        f"file '../audio/{Path(t['file']).name}'\n" for t in timings["segments"]))
    loud = ctx.channel["audio"]["loudnorm"]
    aac = work / "narration.m4a"
    video_dur = ffprobe_duration(video_mp4)
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(all_lst),
         "-af", f"loudnorm={loud},apad", "-t", f"{video_dur:.3f}",
         "-ar", "44100", "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(aac)])
    run([FFMPEG, "-y", "-i", str(video_mp4), "-i", str(aac),
         "-map", "0:v", "-map", "1:a", "-c", "copy",
         "-movflags", "+faststart", str(final)])
    log(f"final.mp4: {ffprobe_duration(final)/60:.1f} min "
        f"(narration ends {(ffprobe_duration(final)-timings['narration_seconds'])/60:.1f} "
        f"min before EOF — silent ember close, no outro)")
