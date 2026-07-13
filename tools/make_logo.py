"""Generate a PLACEHOLDER channel logo (policy-safe: deliberately NOT a copy of any
existing channel's mark). A dark disc with a white crescent moon + drifting z's.
Replace with real branding whenever the operator has one.

Usage: .venv/bin/python tools/make_logo.py --out channels/<slug>/assets/logo.png
"""
from __future__ import annotations

import argparse

from PIL import Image, ImageDraw, ImageFont

FONTS = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=512)
    a = ap.parse_args()
    S = a.size
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([8, 8, S - 8, S - 8], fill=(12, 12, 14, 235))
    # crescent: big white disc minus offset dark disc
    d.ellipse([S * 0.22, S * 0.22, S * 0.78, S * 0.78], fill=(245, 240, 228, 255))
    d.ellipse([S * 0.32, S * 0.16, S * 0.88, S * 0.72], fill=(12, 12, 14, 255))
    font = None
    for fp in FONTS:
        try:
            font = ImageFont.truetype(fp, int(S * 0.16))
            break
        except OSError:
            continue
    if font:
        for i, (x, y, s) in enumerate([(0.60, 0.52, 1.0), (0.70, 0.40, 0.75),
                                       (0.78, 0.30, 0.55)]):
            f = ImageFont.truetype(font.path, int(S * 0.16 * s))
            d.text((S * x, S * y), "z", font=f, fill=(245, 240, 228, 255))
    img.save(a.out)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
