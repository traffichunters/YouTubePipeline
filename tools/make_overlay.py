"""Generate the ember/smoke overlay loop — ONE asset per channel, reused on every video.

Matches the measured spec (VIDEO-STRUCTURE.md §3d/§3d-bis):
  - amber embers drifting diagonally ~30° above horizontal toward the UPPER-LEFT
  - slow (~7.5% of frame width per second), parallel & laminar (no swirl)
  - embers twinkle on/off (<1.5s persistence), varied sizes, slight motion blur
  - soft warm haze drifting the same direction, slower (the "smoke")
  - global brightness "breathing" (~6s period) -> the ±10-luma firelight flicker
  - mathematically seamless loop (all motion/phases are integer-periodic over the
    duration), so a 2-hour dark tail never shows a seam

The result is PRELIT ON BLACK, intended for `blend=all_mode=screen` in the assembler
(screen-blend adds light only; the static edge vignette is applied to the hero images
in S6 instead — over the black tail a vignette is invisible anyway).

Styles (--style): "embers" (amber sparks, the SLH look) or "dust" (soft grey-white
motes — slower, dimmer, gently pulsing; same smoke layer). Same seed -> identical
smoke drift across styles.

Usage:
  .venv/bin/python tools/make_overlay.py --out channels/<slug>/assets/ember_overlay.mp4 \
      [--style embers|dust --width 1920 --height 1080 --fps 30 --seconds 120 --seed 7]
"""
from __future__ import annotations

import argparse
import subprocess
import sys

import numpy as np

DRIFT_DEG = 30.0          # above horizontal, toward upper-left
SPEED_FRAC = 0.075        # of frame width, per second
BREATH_PERIOD_S = 6.0     # firelight breathing

# Particle + smoke styles. The smoke drift pattern is identical across styles
# (same seed); its visibility/texture is per-style.
STYLES = {
    "embers": dict(
        density=60,               # particles per 1920x1080 (sparse, like the original)
        rgb=(1.0, 0.45, 0.12),    # amber
        speed_mul=1.0,
        angle_spread=2.5,         # laminar
        size=(1.2, 3.4),
        brightness=(0.5, 1.0),
        glow_scale=3.2, glow_gain=0.35,
        tw_freq=(0.35, 1.1),      # Hz — fast twinkle
        tw_gamma=3.0,             # sharp on/off
        tw_floor=0.0,             # fully dark between twinkles
        blur_taps=((0.0, 0.55), (-0.5, 0.3), (-1.0, 0.15)),
        haze_level=14.0,          # peak smoke luma (out of 255) — SLH-subtle
        haze_gamma=1.0,           # blotch contrast (1 = soft)
        haze_rgb=(1.0, 0.72, 0.45),   # warm grey-orange
    ),
    "dust": dict(
        density=95,               # more, finer specks
        rgb=(0.85, 0.82, 0.74),   # soft warm grey-white
        speed_mul=0.4,            # dust floats slower than sparks
        angle_spread=8.0,         # a little less regimented
        size=(0.8, 2.2),
        brightness=(0.25, 0.6),   # dimmer than embers
        glow_scale=2.2, glow_gain=0.18,
        tw_freq=(0.10, 0.35),     # slow fade in/out, no hard blinking
        tw_gamma=1.5,
        tw_floor=0.25,            # motes stay faintly visible between pulses
        blur_taps=((0.0, 0.7), (-0.5, 0.3)),
        haze_level=36.0,          # smoke clearly visible, drifting with the dust
        haze_gamma=1.7,           # more defined wisps/blotches, darker gaps
        haze_rgb=(0.88, 0.85, 0.78),  # neutral-warm grey smoke
    ),
}


def periodic_noise(size: int, rng: np.random.Generator, roughness: float = 2.2) -> np.ndarray:
    """Perfectly tileable smooth value noise via FFT low-pass of white noise."""
    white = rng.standard_normal((size, size))
    spec = np.fft.rfft2(white)
    fy = np.fft.fftfreq(size)[:, None]
    fx = np.fft.rfftfreq(size)[None, :]
    dist = np.sqrt(fx * fx + fy * fy) + 1e-6
    spec *= 1.0 / dist ** roughness
    spec[0, 0] = 0
    n = np.fft.irfft2(spec, s=(size, size))
    n -= n.min()
    n /= n.max()
    return n.astype(np.float32)


def gaussian_sprite(radius: float) -> np.ndarray:
    r = int(np.ceil(radius * 3))
    y, x = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    g = np.exp(-(x * x + y * y) / (2 * radius * radius))
    return g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--style", choices=sorted(STYLES), default="embers",
                    help="particle look; the smoke layer is identical across styles")
    a = ap.parse_args()

    W, H, FPS, T = a.width, a.height, a.fps, a.seconds
    frames = FPS * T
    st = STYLES[a.style]
    rng = np.random.default_rng(a.seed)

    # --- specks: quantized velocities => exact wrap over T (seamless loop) ---------
    n_emb = max(12, int(st["density"] * (W * H) / (1920 * 1080)))
    wrap_x, wrap_y = W + 80, H + 80          # wrap area with margin so blobs slide off
    ang = np.deg2rad(DRIFT_DEG + rng.normal(0, st["angle_spread"], n_emb))
    speed = SPEED_FRAC * W * st["speed_mul"] * rng.uniform(0.75, 1.25, n_emb)  # px/s
    vx = -np.cos(ang) * speed                                      # leftward
    vy = -np.sin(ang) * speed                                      # upward
    # quantize so v*T is an integer number of wraps (perfect loop)
    vx = np.round(vx * T / wrap_x) * wrap_x / T
    vy = np.round(vy * T / wrap_y) * wrap_y / T
    x0 = rng.uniform(0, wrap_x, n_emb).astype(np.float32)
    y0 = rng.uniform(0, wrap_y, n_emb).astype(np.float32)
    # twinkle/pulse: integer cycles over T for a seamless loop
    tw_freq = np.maximum(1.0, np.round(rng.uniform(*st["tw_freq"], n_emb) * T)) / T
    tw_phase = rng.uniform(0, 2 * np.pi, n_emb)
    size = rng.uniform(*st["size"], n_emb)
    brightness = rng.uniform(*st["brightness"], n_emb)
    sprites = {i: gaussian_sprite(s) for i, s in enumerate(size)}
    glows = {i: gaussian_sprite(s * st["glow_scale"]) for i, s in enumerate(size)}
    ember_rgb = np.array(st["rgb"], np.float32)

    # --- haze: two parallax layers of periodic noise, drifting the same way --------
    NS = 1024
    haze1 = periodic_noise(NS, rng)
    haze2 = periodic_noise(NS, rng, roughness=2.6)
    hv1 = SPEED_FRAC * W * 0.25                                    # slower than embers
    hv2 = SPEED_FRAC * W * 0.12
    # quantized to integer texture wraps over T
    hv1 = round(hv1 * T / NS) * NS / T
    hv2 = round(hv2 * T / NS) * NS / T or NS / T
    cy, cx = np.mgrid[0:H, 0:W]
    sy1, sx1 = (cy % NS), (cx % NS)
    haze_rgb = np.array(st["haze_rgb"], np.float32)

    breath_cycles = round(T / BREATH_PERIOD_S)

    # --- encode: pipe raw rgb24 to ffmpeg -------------------------------------------
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.out],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    print(f"rendering {frames} frames @ {W}x{H} ({n_emb} embers, {T}s seamless loop)")
    for f in range(frames):
        t = f / FPS
        frame = np.zeros((H, W, 3), np.float32)

        # haze (sampled from scrolling periodic textures) + breathing gain
        off1 = int(hv1 * t) % NS
        off2 = int(hv2 * t) % NS
        hz = (haze1[(sy1 + off1 // 3) % NS, (sx1 + off1) % NS] * 0.65
              + haze2[(sy1 + off2 // 3) % NS, (sx1 + off2) % NS] * 0.35)
        if st["haze_gamma"] != 1.0:
            hz = hz ** st["haze_gamma"]        # sharpen wisps, darken gaps
        breath = 1.0 + 0.35 * np.sin(2 * np.pi * breath_cycles * t / T)
        frame += (hz * st["haze_level"] * breath)[..., None] * haze_rgb

        # specks with motion blur; visibility curve depends on style
        px = (x0 + vx * t) % wrap_x - 40
        py = (y0 + vy * t) % wrap_y - 40
        tw = np.sin(2 * np.pi * tw_freq * t + tw_phase)
        pulse = np.clip(tw, 0, 1) ** st["tw_gamma"]
        vis = (st["tw_floor"] + (1 - st["tw_floor"]) * pulse) * brightness
        for i in np.nonzero(vis > 0.02)[0]:
            for tap, alpha in st["blur_taps"]:
                bx = int(px[i] + vx[i] / FPS * tap)
                by = int(py[i] + vy[i] / FPS * tap)
                for spr, gain in ((glows[int(i)], st["glow_gain"]), (sprites[int(i)], 1.0)):
                    r = spr.shape[0] // 2
                    x1, x2 = bx - r, bx + r + 1
                    y1, y2 = by - r, by + r + 1
                    if x2 <= 0 or y2 <= 0 or x1 >= W or y1 >= H:
                        continue
                    sx1_, sy1_ = max(0, -x1), max(0, -y1)
                    x1c, y1c = max(0, x1), max(0, y1)
                    x2c, y2c = min(W, x2), min(H, y2)
                    patch = spr[sy1_:sy1_ + (y2c - y1c), sx1_:sx1_ + (x2c - x1c)]
                    frame[y1c:y2c, x1c:x2c] += (
                        patch[..., None] * ember_rgb * (255 * vis[i] * alpha * gain))

        # dither: breaks 8-bit banding on the smooth smoke gradients
        frame += rng.uniform(-1.0, 1.0, (H, W, 1)).astype(np.float32)
        np.clip(frame, 0, 255, out=frame)
        enc.stdin.write(frame.astype(np.uint8).tobytes())
        if f % (FPS * 10) == 0:
            print(f"  {t:5.0f}s / {T}s", flush=True)

    enc.stdin.close()
    enc.wait()
    if enc.returncode != 0:
        print("ffmpeg encode failed", file=sys.stderr)
        return 1
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
