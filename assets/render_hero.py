"""Render the subscope hero GIF in pure Python + Pillow.

Aesthetic: 8-bit arcade scanner. Deep-purple background, hot-magenta and
cyan accent flashes, chunky monospace. Pattern words punch in one at a
time (PRICING-RAGE / CHURN / BUILD-VS-BUY / ALTERNATIVES / STACK-AUDIT)
under a scan-line that sweeps left-to-right between each.

Output: assets/hero.gif (1280x480, ~3s loop, <80KB target)

Design notes:
- 1280x480 (less empty canvas than the previous 1280x640)
- 24 animation frames at 8fps = 3.0s, no end-frame hold (loop IS the loop)
- No emoji, no postmortem mentions, no OAuth chips, no version badge
- Monospace via Menlo at chunky sizes for the 8-bit-arcade feel
- Scan-line accent moves with each pattern switch so the user reads it
  as a real scanner, not a static title card
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# === 8-bit arcade purple palette ===
BG       = (14, 10, 30)         # #0e0a1e  deep space purple
BG_GRID  = (28, 20, 56)         # #1c1438  subtle grid lines

PURPLE   = (181, 102, 255)      # #b566ff  primary arcade purple
PURPLE_D = (110, 60, 180)       # #6e3cb4
MAGENTA  = (255, 92, 244)       # #ff5cf4  hot pink accent
CYAN     = (0, 240, 255)        # #00f0ff  cyan accent (rare)
ORANGE   = (255, 160, 60)       # #ffa03c  warm accent (rare)

CREAM    = (245, 237, 255)      # #f5edff  text highlight
LAVENDER = (170, 150, 210)      # #aa96d2  muted text
SCANLINE = (80, 55, 130, 0)     # used as alpha overlay

W, H = 1280, 480
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


F_TITLE = load_font(96)         # SUBSCOPE huge
F_PATTERN = load_font(64)       # pattern word, big
F_TAG = load_font(20)           # tagline + footer
F_CHIP = load_font(16)          # small accent labels


# ─── Drawing helpers ─────────────────────────────────────────────────

def draw_grid(d: ImageDraw.ImageDraw) -> None:
    """Faint 8-bit-arcade grid background. Static (cheap on palette)."""
    step = 40
    for x in range(0, W, step):
        d.line([(x, 0), (x, H)], fill=BG_GRID, width=1)
    for y in range(0, H, step):
        d.line([(0, y), (W, y)], fill=BG_GRID, width=1)


def draw_scanline(d: ImageDraw.ImageDraw, x_pos: int) -> None:
    """Vertical scan-line. Drawn as a 4-pixel band with two trailing dots
    so it reads as motion even at low frame rates."""
    if 0 <= x_pos < W:
        d.rectangle([(x_pos, 0), (x_pos + 3, H)], fill=MAGENTA)
        # trailing fade
        if x_pos - 12 >= 0:
            d.rectangle([(x_pos - 12, 0), (x_pos - 10, H)], fill=PURPLE_D)
        if x_pos - 24 >= 0:
            d.rectangle([(x_pos - 24, 0), (x_pos - 23, H)], fill=PURPLE_D)


def draw_title(d: ImageDraw.ImageDraw, glow: bool = False) -> None:
    """SUBSCOPE in the upper area. Glow on first frames + every loop pulse."""
    text = "SUBSCOPE"
    bbox = d.textbbox((0, 0), text, font=F_TITLE)
    tw = bbox[2] - bbox[0]
    cx = (W - tw) // 2
    y = 56
    if glow:
        # Magenta glow: redraw text at small offsets in dim magenta first
        for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            d.text((cx + dx, y + dy), text, font=F_TITLE, fill=PURPLE_D)
    d.text((cx, y), text, font=F_TITLE, fill=CREAM)


def draw_sub(d: ImageDraw.ImageDraw) -> None:
    """Subtitle under the title."""
    text = "ARCADE-MODE BUYER-INTENT SCANNER FOR REDDIT"
    bbox = d.textbbox((0, 0), text, font=F_TAG)
    tw = bbox[2] - bbox[0]
    cx = (W - tw) // 2
    d.text((cx, 168), text, font=F_TAG, fill=LAVENDER)


def draw_pattern(d: ImageDraw.ImageDraw, text: str, accent: tuple[int, int, int],
                 punch: int = 0) -> None:
    """Big pattern word in the middle band. `punch` 0..3 = brightness pulse
    on first frame the word appears (white -> cream -> stable)."""
    bbox = d.textbbox((0, 0), text, font=F_PATTERN)
    tw = bbox[2] - bbox[0]
    cx = (W - tw) // 2
    y = 250

    # Brackets in accent color, big
    bracket_l = "["
    bracket_r = "]"
    bb_l = d.textbbox((0, 0), bracket_l, font=F_PATTERN)
    bb_r = d.textbbox((0, 0), bracket_r, font=F_PATTERN)
    bl_w = bb_l[2] - bb_l[0]
    br_w = bb_r[2] - bb_r[0]
    d.text((cx - bl_w - 20, y), bracket_l, font=F_PATTERN, fill=accent)
    d.text((cx + tw + 20, y), bracket_r, font=F_PATTERN, fill=accent)

    # Word: punch frames are pure white, then settle to cream
    color = (255, 255, 255) if punch == 1 else CREAM if punch >= 2 else CREAM
    d.text((cx, y), text, font=F_PATTERN, fill=color)


def draw_footer(d: ImageDraw.ImageDraw, blink: bool = False) -> None:
    """Footer stat line. Subtle blink on the surface count."""
    cap_color = MAGENTA if blink else PURPLE
    parts = [
        ("8 PATTERNS", CREAM),
        ("·", LAVENDER),
        ("UP TO 12 / DAY", cap_color),
        ("·", LAVENDER),
        ("LOCAL SQLITE", CREAM),
    ]
    # Measure total width
    spacing = 16
    total = 0
    sizes = []
    for txt, _ in parts:
        bbox = d.textbbox((0, 0), txt, font=F_TAG)
        w = bbox[2] - bbox[0]
        sizes.append(w)
        total += w
    total += spacing * (len(parts) - 1)
    x = (W - total) // 2
    y = 410
    for (txt, color), w in zip(parts, sizes):
        d.text((x, y), txt, font=F_TAG, fill=color)
        x += w + spacing


# ─── Frame composer ──────────────────────────────────────────────────

# Pattern sequence: 4 words, each shown 4 frames, scan-line moves between.
# Total: 24 frames = ~3s at 8fps.
PATTERNS = [
    ("PRICING-RAGE",   MAGENTA),
    ("CHURN",          CYAN),
    ("BUILD-VS-BUY",   ORANGE),
    ("ALTERNATIVES",   PURPLE),
    ("STACK-AUDIT",    MAGENTA),
    ("RFP-BAIT",       CYAN),
]

FRAMES_PER_PATTERN = 4
TOTAL_FRAMES = FRAMES_PER_PATTERN * len(PATTERNS)  # 24


def make_frame(i: int) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    draw_grid(d)

    pattern_index = (i // FRAMES_PER_PATTERN) % len(PATTERNS)
    sub_frame = i % FRAMES_PER_PATTERN  # 0..3 within this pattern

    # Scan-line sweeps across the canvas during each pattern's 4 frames.
    # x goes from 0 -> W over the 4 sub-frames.
    scan_x = int((sub_frame / (FRAMES_PER_PATTERN - 1)) * W) if FRAMES_PER_PATTERN > 1 else W
    draw_scanline(d, scan_x)

    # Title: glow on the first sub-frame of EVERY pattern (rhythmic pulse).
    glow = sub_frame == 0
    draw_title(d, glow=glow)
    draw_sub(d)

    # Pattern word: shows on sub-frames 1..3 (skip 0 so the scan-line "reveals" it).
    if sub_frame >= 1:
        word, accent = PATTERNS[pattern_index]
        punch = 1 if sub_frame == 1 else 2
        draw_pattern(d, word, accent, punch=punch)

    # Footer blinks the cap value on sub-frame 0 of every other pattern.
    blink = (sub_frame == 0) and (pattern_index % 2 == 0)
    draw_footer(d, blink=blink)

    return img


def render_all() -> Path:
    print(f"Rendering {TOTAL_FRAMES} frames to {FRAMES_DIR}/ at 1280x480")
    for i in range(TOTAL_FRAMES):
        img = make_frame(i)
        path = FRAMES_DIR / f"f{i:03d}.png"
        img.save(path)
    print("Frames rendered. Assembling via ffmpeg...")

    out = OUT_DIR / "hero.gif"
    palette = FRAMES_DIR / "palette.png"
    subprocess.run([
        "ffmpeg", "-y", "-framerate", "8", "-i", str(FRAMES_DIR / "f%03d.png"),
        "-vf", "palettegen=max_colors=48:stats_mode=full", str(palette)
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-y", "-framerate", "8", "-i", str(FRAMES_DIR / "f%03d.png"),
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
