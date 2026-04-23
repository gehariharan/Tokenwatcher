from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont


def render_icon(text: str = "TW", size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, size - 2, size - 2), fill=(36, 132, 240, 255))
    try:
        font = ImageFont.truetype("arialbd.ttf", int(size * 0.45))
    except OSError:
        font = ImageFont.load_default()
    tw, th = d.textbbox((0, 0), text, font=font)[2:4]
    d.text(((size - tw) / 2, (size - th) / 2 - 2), text, fill=(255, 255, 255, 255), font=font)
    return img
