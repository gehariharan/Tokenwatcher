"""Generate TokenWatcher icon assets from assets/icon-source.png.

Outputs:
  assets/icon.png       512x512 (general / window icon)
  assets/icon.ico       multi-resolution (16, 24, 32, 48, 64, 128, 256) for installer + tray
  assets/icon-tray.png  32x32 (explicit fallback for the tray)
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "icon-source.png"

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> None:
    img = Image.open(SRC).convert("RGBA")

    # Trim any near-black border the source padding adds, keep it square.
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    img = canvas

    # 512x512 PNG for general use
    big = img.resize((512, 512), Image.LANCZOS)
    big.save(ROOT / "assets" / "icon.png", optimize=True)
    print("wrote assets/icon.png  (512x512)")

    # 32x32 PNG specifically for tray
    tray = img.resize((32, 32), Image.LANCZOS)
    tray.save(ROOT / "assets" / "icon-tray.png", optimize=True)
    print("wrote assets/icon-tray.png  (32x32)")

    # Multi-resolution ICO for Windows installer + window
    sized = [img.resize((s, s), Image.LANCZOS) for s in ICO_SIZES]
    sized[0].save(
        ROOT / "assets" / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=sized[1:],
    )
    print(f"wrote assets/icon.ico   sizes={ICO_SIZES}")


if __name__ == "__main__":
    main()
