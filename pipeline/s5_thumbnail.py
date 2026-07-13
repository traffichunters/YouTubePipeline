"""S5 — thumbnail. Branded template: generated comedic scene + deterministic
composited brand wordmark (always crisp/identical) + logo badge. 1280x720, <2MB.

In : topic_brief.json
Out: thumbnail.png
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .providers import get_image_engine
from .util import fill, log, read_json

FONTS = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
]


def run_stage(ctx) -> None:
    brief = read_json(ctx.outdir / "topic_brief.json")
    th = ctx.channel["thumbnail"]
    scene_prompt = fill(ctx.channel.prompt("thumbnail"),
        scene_prompt=fill(th["scene_prompt"], topic=brief["hero"]["topic"]))

    engine = get_image_engine(ctx.engine("image"))
    scene_path = ctx.outdir / "work" / "thumb_scene.png"
    if not scene_path.exists() or ctx.force:
        scene_path.parent.mkdir(exist_ok=True)
        engine.generate(scene_prompt, scene_path)

    W, H = 1280, 720
    img = Image.open(scene_path).convert("RGB")
    img = _cover(img, W, H)

    d = ImageDraw.Draw(img)
    text = th["brand_text"]
    font = _fit_font(d, text, int(W * 0.94))
    bbox = d.textbbox((0, 0), text, font=font)
    tw, thh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = (W - tw) // 2, int(H * 0.03)
    pad = 14
    d.rectangle([x - pad, y - pad, x + tw + pad, y + thh + pad * 2],
                fill=th.get("background", "#f5f1e8"))
    d.text((x, y), text, font=font, fill=th.get("text_color", "#111111"))

    logo = Image.open(ctx.channel.dir / ctx.channel["visuals"]["logo"]).convert("RGBA")
    lh = int(H * 0.22)
    logo = logo.resize((int(logo.width * lh / logo.height), lh))
    img.paste(logo, (16, H - lh - 16), logo)

    out = ctx.outdir / "thumbnail.png"
    img.save(out, optimize=True)
    if out.stat().st_size > 2_000_000:      # YouTube limit
        img.save(out.with_suffix(".jpg"), quality=88)
        out.unlink()
        log("thumbnail saved as JPG to stay under 2MB")
    ctx.costs.add_cost(getattr(engine, "cost_usd", 0.0))
    log(f"thumbnail: {out.name}")


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s + 0.5), int(img.height * s + 0.5)))
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _fit_font(d: ImageDraw.ImageDraw, text: str, max_w: int) -> ImageFont.FreeTypeFont:
    path = next((p for p in FONTS if Path(p).exists()), None)
    size = 120
    while size > 24:
        font = (ImageFont.truetype(path, size) if path
                else ImageFont.load_default(size))
        if d.textbbox((0, 0), text, font=font)[2] <= max_w:
            return font
        size -= 6
    return font
