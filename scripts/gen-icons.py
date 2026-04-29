"""Generate TokenWatcher icon assets from assets/icon-source.png.

Outputs:
  assets/icon.png         512x512 (general / window icon)
  assets/icon.ico         multi-resolution (16, 24, 32, 48, 64, 128, 256)
  assets/icon-tray.png    32x32 (explicit fallback for the tray)
  build/appx/*.png        Microsoft Store (MSIX/AppX) tile assets
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

    # Multi-resolution ICO. Pillow generates each requested frame from the
    # base image, so the base must be at least as large as the largest size.
    # electron-builder requires a 256x256 frame; we provide one explicitly.
    base = img.resize((max(ICO_SIZES), max(ICO_SIZES)), Image.LANCZOS)
    base.save(
        ROOT / "assets" / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
    )
    print(f"wrote assets/icon.ico   sizes={ICO_SIZES}")

    # Microsoft Store / MSIX tile assets. electron-builder reads these from
    # build/appx/ and embeds them into the AppX manifest.
    appx_dir = ROOT / "build" / "appx"
    appx_dir.mkdir(parents=True, exist_ok=True)

    # Required tile / logo sizes per the MSIX spec. The Square150x150Logo and
    # Square44x44Logo are mandatory; the rest improve Store presentation.
    appx_sizes = {
        "StoreLogo.png":          (50, 50),
        "Square44x44Logo.png":    (44, 44),
        "Square71x71Logo.png":    (71, 71),
        "Square150x150Logo.png":  (150, 150),
        "Square310x310Logo.png":  (310, 310),
        "Wide310x150Logo.png":    (310, 150),  # wide tile: pad transparent
        "SplashScreen.png":       (620, 300),  # splash: pad transparent
    }

    for name, (w, h) in appx_sizes.items():
        if w == h:
            tile = img.resize((w, h), Image.LANCZOS)
        else:
            # Wide / splash: paste square icon centered on a transparent canvas.
            side = min(w, h)
            scaled = img.resize((side, side), Image.LANCZOS)
            tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            tile.paste(scaled, ((w - side) // 2, (h - side) // 2), scaled)
        tile.save(appx_dir / name, optimize=True)
    print(f"wrote build/appx/  ({len(appx_sizes)} tile assets for Microsoft Store)")


if __name__ == "__main__":
    main()
