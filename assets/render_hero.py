"""Render the subscope hero GIF in pure Python + Pillow.

Aesthetic: 8-bit arcade scanner. Title bar, skill strip lighting up
left-to-right, layer chips appearing, three sample surfaces filling in,
end-frame hold.

Output: assets/hero.gif (1280x640, ~5s loop with hold, <2MB)

Design notes:
- No emoji — Menlo doesn't have those glyphs; bracket labels render cleanly
  and fit the 8-bit aesthetic better
- 32 total frames: 24 animation + 8 hold on the static end-frame
- End-frame shows FULL digest panel + the closing line — GitHub auto-pauses
  GIFs and that's what 70% of viewers see
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# === Brand palette ===
BG = (45, 45, 45)              # #2d2d2d
ORANGE = (241, 91, 37)         # #f15b25 — primary
ORANGE_DARK = (191, 62, 15)    # #bf3e0f
TEAL = (70, 204, 222)          # #46ccde
TEAL_DARK = (20, 123, 135)     # #147b87
LIGHT = (235, 232, 231)        # #ebe8e7
MUTED = (132, 132, 132)        # #848484
GREEN = (22, 163, 74)          # #16a34a

W, H = 1280, 640
OUT_DIR = Path(__file__).resolve().parent
FRAMES_DIR = OUT_DIR / "_frames"
FRAMES_DIR.mkdir(exist_ok=True)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
        "/Library/Fonts/Andale Mono.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


F_TITLE = load_font(54)
F_SUB = load_font(20)
F_BODY = load_font(20)
F_BODY_BOLD = load_font(22)
F_CHIP = load_font(15)
F_TAGLINE = load_font(20)
F_TAGLINE_BIG = load_font(26)


def chip(d, x, y, text, fill, text_color=None, h=30):
    text_color = text_color or LIGHT
    bbox = d.textbbox((0, 0), text, font=F_CHIP)
    tw = bbox[2] - bbox[0]
    w = tw + 20
    d.rounded_rectangle([(x, y), (x + w, y + h)], radius=4, fill=fill)
    # Center text vertically
    d.text((x + 10, y + (h - 18) // 2), text, font=F_CHIP, fill=text_color)
    return w


def draw_title_bar(d):
    d.text((60, 30), "SUBSCOPE", font=F_TITLE, fill=ORANGE)
    d.text((60, 96), "PATTERN-AWARE SUBREDDIT SCANNER", font=F_SUB, fill=MUTED)
    # Right side chips
    x = W - 60
    bbox_d = d.textbbox((0, 0), "DEDUP ON", font=F_CHIP)
    cw1 = (bbox_d[2] - bbox_d[0]) + 20
    chip(d, x - cw1, 44, "DEDUP ON", TEAL_DARK)
    bbox_v = d.textbbox((0, 0), "v0.1.0", font=F_CHIP)
    cw2 = (bbox_v[2] - bbox_v[0]) + 20
    chip(d, x - cw1 - cw2 - 8, 44, "v0.1.0", ORANGE)


def draw_skill_strip(d, y, lit_count):
    """8 sub-skill chips. lit_count in 0..8 activates them left-to-right."""
    skills = ["run", "stack-audit", "churn", "pricing-rage", "build-vs-buy",
              "rfp-bait", "resurrect", "rivals"]
    x = 60
    gap = 6
    for i, label in enumerate(skills):
        text = f":{label}"
        bbox = d.textbbox((0, 0), text, font=F_CHIP)
        tw = bbox[2] - bbox[0]
        w = tw + 20
        h = 30
        if i < lit_count:
            d.rounded_rectangle([(x, y), (x + w, y + h)], radius=4, fill=ORANGE)
            d.text((x + 10, y + 6), text, font=F_CHIP, fill=LIGHT)
        else:
            d.rounded_rectangle([(x, y), (x + w, y + h)], radius=4, outline=TEAL_DARK, width=2)
            d.text((x + 10, y + 6), text, font=F_CHIP, fill=TEAL_DARK)
        x += w + gap


def draw_layer_chips(d, y):
    """Layer status chips: REGEX OAUTH LLM NOTION OBSIDIAN SLACK."""
    layers = [
        ("REGEX ON", GREEN),
        ("OAUTH ON", TEAL_DARK),
        ("LLM ON", TEAL_DARK),
        ("NOTION ON", TEAL_DARK),
        ("OBSIDIAN ON", TEAL_DARK),
        ("SLACK ON", TEAL_DARK),
    ]
    x = 60
    gap = 6
    for label, color in layers:
        w = chip(d, x, y, label, color)
        x += w + gap


def draw_surface_row(d, x, y, tier, sub, age, score, pattern_tag, title, pain, fit):
    """One post row in the digest panel."""
    d.text((x, y), f"[{tier}]", font=F_BODY_BOLD, fill=TEAL)
    d.text((x + 56, y), f"r/{sub}", font=F_BODY_BOLD, fill=ORANGE)
    bbox = d.textbbox((0, 0), f"r/{sub}", font=F_BODY_BOLD)
    sub_w = bbox[2] - bbox[0]
    meta = f"  ·  {age}  ·  score {score}  ·  [{pattern_tag}]"
    d.text((x + 56 + sub_w, y), meta, font=F_BODY, fill=MUTED)
    d.text((x + 24, y + 28), title, font=F_BODY_BOLD, fill=LIGHT)
    d.text((x + 24, y + 56), f"PAIN: {pain}    FIT: {fit}", font=F_SUB, fill=TEAL)


def draw_digest_panel(d, rows_visible=3):
    PX, PY = 60, 232
    PW, PH = W - 120, 286
    d.rounded_rectangle([(PX, PY), (PX + PW, PY + PH)], radius=8,
                        outline=TEAL_DARK, width=2)
    rows = [
        ("T1", "RevOps", "14h", "92", "stack-audit",
         "HubSpot renewal +28%, anyone moved off?",
         "pricing-rage", "9/10"),
        ("T1", "SalesOps", "6h", "78", "churn",
         "Canceling Apollo, what do you use for sequence?",
         "churn-signal", "8/10"),
        ("T2", "B2BSaaS", "3h", "71", "pricing-rage",
         "Salesforce minimums went up to 50 seats — alternatives?",
         "pricing-rage", "8/10"),
    ]
    y = PY + 18
    for i, row in enumerate(rows[:rows_visible]):
        draw_surface_row(d, PX + 24, y, *row)
        y += 90


def draw_footer(d, pulse=False):
    """Closing line: a stat snapshot, not a tagline. Cycles the orange
    accent on the cap value at end-frame for subtle motion under the hold."""
    color = ORANGE if pulse else LIGHT
    text_main = "5 - 15 SURFACES / DAY      8 INTENT CLASSES      LOCAL SQLITE"
    bbox = d.textbbox((0, 0), text_main, font=F_TAGLINE_BIG)
    tw = bbox[2] - bbox[0]
    cx = (W - tw) // 2
    d.text((cx, 568), text_main, font=F_TAGLINE_BIG, fill=color)


def make_frame(i: int) -> Image.Image:
    """Frames 0..31. 0..23 = animation, 24..31 = hold on end-frame."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Always-on
    draw_title_bar(d)

    # Sub-skill strip lights frame 0..7 (one per frame), then stays lit
    if i < 8:
        lit = i + 1
    else:
        lit = 8
    draw_skill_strip(d, y=146, lit_count=lit)

    # Layer chips appear at frame 9
    if i >= 9:
        draw_layer_chips(d, y=190)

    # Digest panel fills in: row 1 at frame 12, row 2 at 15, row 3 at 18
    if i >= 12:
        if i < 15:
            rows = 1
        elif i < 18:
            rows = 2
        else:
            rows = 3
        draw_digest_panel(d, rows_visible=rows)

    # Footer appears at frame 19, pulses at 22+
    if i >= 19:
        pulse = (i % 4) < 2 if i >= 22 else False
        draw_footer(d, pulse=pulse)

    return img


def render_all() -> Path:
    total = 32  # 24 animation + 8 hold
    print(f"Rendering {total} frames to {FRAMES_DIR}/")
    for i in range(total):
        # Frames 24..31 = duplicate of frame 23 (the end-frame hold)
        frame_index = min(i, 23)
        img = make_frame(frame_index)
        path = FRAMES_DIR / f"f{i:03d}.png"
        img.save(path)
    print("Frames rendered. Assembling via ffmpeg...")

    out = OUT_DIR / "hero.gif"
    palette = FRAMES_DIR / "palette.png"
    subprocess.run([
        "ffmpeg", "-y", "-framerate", "6", "-i", str(FRAMES_DIR / "f%03d.png"),
        "-vf", "palettegen=max_colors=64:stats_mode=full", str(palette)
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-y", "-framerate", "6", "-i", str(FRAMES_DIR / "f%03d.png"),
        "-i", str(palette),
        "-lavfi", "[0:v][1:v]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
        "-loop", "0",
        str(out)
    ], check=True, capture_output=True)
    print(f"Output: {out}")
    print(f"Size: {out.stat().st_size / 1024:.1f} KB")
    return out


if __name__ == "__main__":
    render_all()
