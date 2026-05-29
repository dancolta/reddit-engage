"""Render the subscope GitHub social-preview card (static PNG, 1280x640).

GitHub auto-generates a repo link-preview card that stamps the OWNER AVATAR onto
it. To keep subscope's shared-link preview on-brand (no personal avatar / logo),
upload this card at: repo Settings > General > Social preview.

Same 8-bit purple aesthetic as the hero. No avatar, no external logo.
Output: assets/social-preview.png
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BG       = (14, 10, 30)
BG_GRID  = (28, 20, 56)
PANEL    = (20, 15, 40)
PURPLE   = (181, 102, 255)
MAGENTA  = (255, 92, 244)
CYAN     = (0, 240, 255)
GREEN    = (90, 230, 150)
CREAM    = (245, 237, 255)
LAVENDER = (170, 150, 210)

W, H = 1280, 640
PAD = 72
OUT = Path(__file__).resolve().parent / "social-preview.png"


def font(size: int) -> ImageFont.FreeTypeFont:
    for p in ("/System/Library/Fonts/Menlo.ttc",
              "/System/Library/Fonts/Monaco.ttf"):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


F_BRAND = font(86)
F_TAG = font(27)
F_HEAD = font(24)
F_ROW = font(22)
F_META = font(17)
F_FOOT = font(22)


def row(d, x, y, tag, tag_c, sub, meta, title):
    d.rectangle([(x, y), (W - PAD, y + 52)], fill=PANEL)
    d.rectangle([(x, y), (x + 4, y + 52)], fill=tag_c)
    d.text((x + 18, y + 6), f"[{tag}]", font=F_META, fill=tag_c)
    d.text((x + 70, y + 4), sub, font=F_ROW, fill=PURPLE)
    bb = d.textbbox((0, 0), sub, font=F_ROW)
    d.text((x + 70 + (bb[2] - bb[0]) + 20, y + 7), meta, font=F_META, fill=LAVENDER)
    d.text((x + 70, y + 28), title, font=F_META, fill=CREAM)


def render() -> Path:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 40):
        d.line([(x, 0), (x, H)], fill=BG_GRID, width=1)
    for y in range(0, H, 40):
        d.line([(0, y), (W, y)], fill=BG_GRID, width=1)

    d.text((PAD, 56), "subscope", font=F_BRAND, fill=CREAM)
    d.rectangle([(PAD + 470, 70), (PAD + 492, 132)], fill=PURPLE)
    d.text((PAD, 168), "Reddit buyer-intent threads, ranked. Keyless. Free. In Claude Code.",
           font=F_TAG, fill=LAVENDER)

    # mini two-track snippet
    d.rectangle([(PAD, 244), (PAD + 6, 270)], fill=MAGENTA)
    d.text((PAD + 18, 240), "BUYER SIGNALS", font=F_HEAD, fill=MAGENTA)
    row(d, PAD, 284, "T1", GREEN, "r/RevOps", "14h · 92 · pricing-rage",
        "\"HubSpot renewal +28%, anyone moved off?\"")
    row(d, PAD, 344, "T1", GREEN, "r/SalesOps", "6h · 88 · churn",
        "\"Canceling Apollo, what do you use instead?\"")

    d.rectangle([(PAD, 420), (PAD + 6, 446)], fill=CYAN)
    d.text((PAD + 18, 416), "AUTHORITY PLAYS", font=F_HEAD, fill=CYAN)
    row(d, PAD, 460, "A", CYAN, "r/Entrepreneur", "5h · 61 · question",
        "\"How do you handle multi-entity invoicing?\"")

    d.text((PAD, 560),
           "Buyer signals + Authority plays. You find the thread, you write the reply.",
           font=F_FOOT, fill=PURPLE)

    img.save(OUT)
    print(f"Output: {OUT}  ({OUT.stat().st_size // 1024} KB, {W}x{H})")
    return OUT


if __name__ == "__main__":
    render()
