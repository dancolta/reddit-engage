"""Render the subscope hero GIF in pure Python + Pillow.

Aesthetic: 8-bit purple terminal. Deep-purple background with a faint grid,
hot-magenta scan-line, chunky monospace. The hero demonstrates the product:
a /subscope-run that returns two labeled tracks (BUYER SIGNALS + AUTHORITY
PLAYS), revealed row by row under a descending scan-line, then HELD on the
full list (the resting end-frame is what most viewers actually see).

Output: assets/hero.gif (1280x800, plays once then holds, <2MB target)

Design notes:
- 1280x800, a two-section ranked list needs vertical room.
- ~18 frames at 6 fps, last frames are the full static list (the hold).
- No fake footer, no version badge, no emoji. Both section headers mandatory.
- Monospace via Menlo for the 8-bit feel.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# === 8-bit purple terminal palette ===
BG       = (14, 10, 30)         # #0e0a1e  deep space purple
BG_GRID  = (28, 20, 56)         # #1c1438  subtle grid lines
PANEL    = (20, 15, 40)         # row panel fill

PURPLE   = (181, 102, 255)      # #b566ff  primary purple (subreddit)
PURPLE_D = (110, 60, 180)       # #6e3cb4  scan-line trail
MAGENTA  = (255, 92, 244)       # #ff5cf4  hot pink (buyer accent + scanline)
CYAN     = (0, 240, 255)        # #00f0ff  cyan (authority accent)
GREEN    = (90, 230, 150)       # #5ae696  buyer tag
CREAM    = (245, 237, 255)      # #f5edff  text highlight
LAVENDER = (170, 150, 210)      # #aa96d2  muted text / meta

W, H = 1280, 800
PAD = 64
OUT_DIR = Path(__file__).resolve().parent
FRAMES_DIR = OUT_DIR / "_frames"
FRAMES_DIR.mkdir(exist_ok=True)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in ("/System/Library/Fonts/Menlo.ttc",
                 "/System/Library/Fonts/Monaco.ttf",
                 "/Library/Fonts/Andale Mono.ttf"):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


F_BRAND = load_font(34)     # subscope wordmark
F_PROMPT = load_font(30)    # > /subscope-run
F_HEAD = load_font(28)      # section headers
F_SUBHEAD = load_font(19)   # section subtitle
F_TAG = load_font(20)       # [T1] / [A]
F_SUB = load_font(23)       # r/RevOps
F_META = load_font(18)      # 14h / 92 / pricing-rage
F_TITLE = load_font(22)     # the quoted thread title


# rows: (tag, tag_color, sub, meta, title)
BUYER = [
    ("T1", GREEN, "r/RevOps",      "14h · 92 · pricing-rage", "\"HubSpot renewal +28%, anyone moved off?\""),
    ("T1", GREEN, "r/SalesOps",    "6h · 88 · churn",         "\"Canceling Apollo, what do you use instead?\""),
    ("T2", GREEN, "r/B2BSaaS",     "3h · 74 · alternative",   "\"Alternative to Salesforce under 25 seats?\""),
]
AUTHORITY = [
    ("A", CYAN, "r/Entrepreneur",  "5h · 61 · question", "\"How do you handle multi-entity invoicing?\""),
    ("A", CYAN, "r/smallbusiness", "9h · 58 · question", "\"Best way to track recurring client work?\""),
]

# Reveal timeline (one element per step):
#   0 prompt, 1 buyer header, 2-4 buyer rows, 5 authority header, 6-7 authority rows
REVEAL_STEPS = 8
HOLD_FRAMES = 7            # static full-list frames at the end (the resting state)
TOTAL_FRAMES = REVEAL_STEPS + HOLD_FRAMES

ROW_H = 64
PROMPT_Y = 128
BUYER_HEAD_Y = 196
BUYER_ROW_Y = 248
AUTH_HEAD_Y = 248 + 3 * ROW_H + 36
AUTH_ROW_Y = AUTH_HEAD_Y + 52


def draw_grid(d: ImageDraw.ImageDraw) -> None:
    for x in range(0, W, 40):
        d.line([(x, 0), (x, H)], fill=BG_GRID, width=1)
    for y in range(0, H, 40):
        d.line([(0, y), (W, y)], fill=BG_GRID, width=1)


def draw_brand(d: ImageDraw.ImageDraw) -> None:
    d.text((PAD, 48), "subscope", font=F_BRAND, fill=CREAM)
    # small purple cursor block after the wordmark
    bb = d.textbbox((0, 0), "subscope", font=F_BRAND)
    d.rectangle([(PAD + bb[2] + 12, 52), (PAD + bb[2] + 28, 82)], fill=PURPLE)


def draw_prompt(d: ImageDraw.ImageDraw, typed: str, cursor: bool) -> None:
    d.text((PAD, PROMPT_Y), "> ", font=F_PROMPT, fill=MAGENTA)
    bb = d.textbbox((0, 0), "> ", font=F_PROMPT)
    d.text((PAD + (bb[2] - bb[0]), PROMPT_Y), typed, font=F_PROMPT, fill=CREAM)
    if cursor:
        tb = d.textbbox((0, 0), "> " + typed, font=F_PROMPT)
        d.rectangle([(PAD + (tb[2] - tb[0]) + 6, PROMPT_Y + 2),
                     (PAD + (tb[2] - tb[0]) + 22, PROMPT_Y + 32)], fill=MAGENTA)


def draw_section_head(d: ImageDraw.ImageDraw, y: int, label: str, sub: str,
                      accent: tuple[int, int, int]) -> None:
    d.rectangle([(PAD, y + 4), (PAD + 6, y + 30)], fill=accent)  # accent tab
    d.text((PAD + 18, y), label, font=F_HEAD, fill=accent)
    bb = d.textbbox((0, 0), label, font=F_HEAD)
    d.text((PAD + 18 + (bb[2] - bb[0]) + 22, y + 7), sub, font=F_SUBHEAD, fill=LAVENDER)


def draw_row(d: ImageDraw.ImageDraw, y: int, row: tuple) -> None:
    tag, tag_color, sub, meta, title = row
    d.rectangle([(PAD, y), (W - PAD, y + ROW_H - 12)], fill=PANEL)
    d.rectangle([(PAD, y), (PAD + 4, y + ROW_H - 12)], fill=tag_color)
    # line 1: [tag]  sub   meta
    x = PAD + 22
    d.text((x, y + 6), f"[{tag}]", font=F_TAG, fill=tag_color)
    bb = d.textbbox((0, 0), f"[{tag}]", font=F_TAG)
    x += (bb[2] - bb[0]) + 20
    d.text((x, y + 5), sub, font=F_SUB, fill=PURPLE)
    bb = d.textbbox((0, 0), sub, font=F_SUB)
    x += (bb[2] - bb[0]) + 24
    d.text((x, y + 8), meta, font=F_META, fill=LAVENDER)
    # line 2: the quoted thread title, indented under the tag
    d.text((PAD + 22, y + 32), title, font=F_TITLE, fill=CREAM)


def draw_scanline(d: ImageDraw.ImageDraw, y: int) -> None:
    d.rectangle([(0, y), (W, y + 3)], fill=MAGENTA)
    d.rectangle([(0, y - 10), (W, y - 9)], fill=PURPLE_D)


def make_frame(i: int) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    draw_grid(d)
    draw_brand(d)

    reveal = min(i, REVEAL_STEPS)  # how many elements are shown
    holding = i >= REVEAL_STEPS

    # prompt typing on the very first frames
    prompt_full = "/subscope-run"
    if i == 0:
        draw_prompt(d, prompt_full[:7], cursor=True)
        return img
    draw_prompt(d, prompt_full, cursor=not holding)

    # buyer header (step 1)
    if reveal >= 1:
        draw_section_head(d, BUYER_HEAD_Y, "BUYER SIGNALS",
                          "someone is shopping, a reply moves a deal", MAGENTA)
    # buyer rows (steps 2-4)
    for r in range(3):
        if reveal >= 2 + r:
            draw_row(d, BUYER_ROW_Y + r * ROW_H, BUYER[r])
    # authority header (step 5)
    if reveal >= 5:
        draw_section_head(d, AUTH_HEAD_Y, "AUTHORITY PLAYS",
                          "no buyer yet, answer to build presence", CYAN)
    # authority rows (steps 6-7)
    for r in range(2):
        if reveal >= 6 + r:
            draw_row(d, AUTH_ROW_Y + r * ROW_H, AUTHORITY[r])

    # descending scan-line sits at the frontier of the row being revealed
    if not holding and i >= 1:
        frontier_map = {
            1: BUYER_HEAD_Y + 38,
            2: BUYER_ROW_Y + ROW_H - 6,
            3: BUYER_ROW_Y + 2 * ROW_H - 6,
            4: BUYER_ROW_Y + 3 * ROW_H - 6,
            5: AUTH_HEAD_Y + 38,
            6: AUTH_ROW_Y + ROW_H - 6,
            7: AUTH_ROW_Y + 2 * ROW_H - 6,
        }
        if i in frontier_map:
            draw_scanline(d, frontier_map[i])

    return img


def render_all() -> Path:
    print(f"Rendering {TOTAL_FRAMES} frames to {FRAMES_DIR}/ at {W}x{H}")
    # purge stale frames from the old renderer
    for old in FRAMES_DIR.glob("f*.png"):
        old.unlink()
    for i in range(TOTAL_FRAMES):
        make_frame(i).save(FRAMES_DIR / f"f{i:03d}.png")
    print("Frames rendered. Assembling via ffmpeg...")

    out = OUT_DIR / "hero.gif"
    palette = FRAMES_DIR / "palette.png"
    # Per-frame durations: brisk reveal, long hold on the final full-list frame.
    subprocess.run([
        "ffmpeg", "-y", "-framerate", "6", "-i", str(FRAMES_DIR / "f%03d.png"),
        "-vf", "palettegen=max_colors=64:stats_mode=full", str(palette)
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-y", "-framerate", "6", "-i", str(FRAMES_DIR / "f%03d.png"),
        "-i", str(palette),
        "-lavfi", "[0:v][1:v]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
        "-loop", "-1",  # play once, hold on the last (full-list) frame
        str(out)
    ], check=True, capture_output=True)
    print(f"Output: {out}")
    print(f"Size: {out.stat().st_size / 1024:.1f} KB")
    return out


if __name__ == "__main__":
    render_all()
