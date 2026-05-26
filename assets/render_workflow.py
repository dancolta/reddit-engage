"""Render the subscope workflow GIF (8-bit aesthetic, ~6s loop with hold).

Shows: terminal prompt -> /subscope:run command -> output table populating
row by row with pattern badges.

Lives next to hero.gif and reuses the same palette + font + frame loop.
Output: assets/workflow.gif (1280x640, 36 frames at 6 fps).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# === Palette (same as hero) ===
BG = (24, 24, 32)              # slightly deeper than hero BG for terminal feel
PROMPT_BG = (45, 45, 45)
ORANGE = (241, 91, 37)
ORANGE_DARK = (191, 62, 15)
TEAL = (70, 204, 222)
TEAL_DARK = (20, 123, 135)
LIGHT = (235, 232, 231)
MUTED = (132, 132, 132)
GREEN = (22, 163, 74)
YELLOW = (234, 179, 8)
PURPLE = (147, 51, 234)
RED = (220, 38, 38)
BLUE = (37, 99, 235)

W, H = 1280, 640
OUT_DIR = Path(__file__).resolve().parent
FRAMES_DIR = OUT_DIR / "_workflow_frames"
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


F_PROMPT = load_font(22)
F_BIG = load_font(28)
F_BODY = load_font(20)
F_CHIP = load_font(15)
F_HEADER = load_font(18)
F_TITLE = load_font(36)


# Pattern color map (lifted from CLI render conventions)
PATTERN_COLORS = {
    "pricing-rage": RED,
    "churn": YELLOW,
    "build-vs-buy": PURPLE,
    "rfp-bait": BLUE,
    "stack-audit": ORANGE_DARK,
    "alt-seek": TEAL,
    "resurrect": MUTED,
    "rivals": ORANGE,
}


# Sample rows (mirrors what the engine actually outputs)
ROWS = [
    ("T1", "RevOps", "92", "pricing-rage",
     "HubSpot renewal +28%, anyone moved off?", "2y/4.2k/12%wa"),
    ("T1", "SalesOps", "88", "churn",
     "Canceling Apollo, what do you use instead?", "4y/8.1k/0%wa"),
    ("T2", "B2BSaaS", "81", "alt-seek",
     "Alternative to Salesforce under 25 seats?", "3y/2.4k/6%wa"),
    ("T2", "SaaS", "78", "stack-audit",
     "Cut 4 of 9 tools - help me decide", "5y/12k/3%wa"),
    ("T2", "devops", "74", "build-vs-buy",
     "Built our own monitoring vs Datadog $40k/yr", "6y/22k/0%wa"),
]


def draw_chrome(d):
    """Top title bar + closing footer that's always on."""
    # Title bar
    d.rectangle([(0, 0), (W, 64)], fill=PROMPT_BG)
    d.text((40, 18), "subscope :: daily scan", font=F_BIG, fill=ORANGE)
    # Right-aligned status
    status = "DEDUP ON   COOLING 15m   v0.1.0"
    bbox = d.textbbox((0, 0), status, font=F_HEADER)
    sw = bbox[2] - bbox[0]
    d.text((W - sw - 40, 22), status, font=F_HEADER, fill=MUTED)


def draw_terminal_block(d, command_chars_visible):
    """Show the command being typed at the top of the body."""
    PX, PY = 40, 88
    PW, PH = W - 80, 64
    d.rounded_rectangle([(PX, PY), (PX + PW, PY + PH)], radius=6, fill=PROMPT_BG)
    cmd = "/subscope:run"
    visible = cmd[:command_chars_visible]
    cursor = "_" if command_chars_visible < len(cmd) else ""
    d.text((PX + 24, PY + 18), "$ ", font=F_BIG, fill=GREEN)
    d.text((PX + 60, PY + 18), visible + cursor, font=F_BIG, fill=LIGHT)


def draw_status_strip(d, y, fetched, gated, scored, surfaced):
    """Live counters under the terminal block."""
    items = [
        ("FETCHED", str(fetched), MUTED),
        ("GATED", str(gated), TEAL),
        ("SCORED", str(scored), TEAL),
        ("SURFACED", str(surfaced), ORANGE),
    ]
    x = 40
    for label, val, color in items:
        d.text((x, y), label, font=F_CHIP, fill=MUTED)
        d.text((x, y + 18), val, font=F_BIG, fill=color)
        x += 200


def draw_result_row(d, x, y, idx, row, dim=False):
    """One surface row in the output panel."""
    tier, sub, score, pattern, title, op = row
    color = MUTED if dim else LIGHT
    score_color = MUTED if dim else ORANGE

    # Index + tier badge
    d.text((x, y), f"{idx:>2}.", font=F_BODY, fill=color)
    tier_color = ORANGE if (tier == "T1" and not dim) else (TEAL if not dim else MUTED)
    d.text((x + 44, y), tier, font=F_BODY, fill=tier_color)

    # Subreddit
    d.text((x + 96, y), f"r/{sub}", font=F_BODY, fill=color)
    bbox = d.textbbox((0, 0), f"r/{sub}", font=F_BODY)
    sub_w = bbox[2] - bbox[0]

    # Pattern chip
    chip_x = x + 96 + sub_w + 12
    chip_color = MUTED if dim else PATTERN_COLORS.get(pattern, ORANGE)
    chip_text = pattern
    bbox = d.textbbox((0, 0), chip_text, font=F_CHIP)
    chip_w = bbox[2] - bbox[0] + 14
    d.rounded_rectangle(
        [(chip_x, y + 2), (chip_x + chip_w, y + 22)], radius=4, fill=chip_color,
    )
    d.text((chip_x + 7, y + 4), chip_text, font=F_CHIP, fill=LIGHT)

    # Score right-aligned
    score_text = f"score {score}"
    bbox = d.textbbox((0, 0), score_text, font=F_BODY)
    sw = bbox[2] - bbox[0]
    d.text((W - 80 - sw, y), score_text, font=F_BODY, fill=score_color)

    # Title underneath
    title_color = MUTED if dim else LIGHT
    d.text((x + 44, y + 26), f'"{title}"', font=F_HEADER, fill=title_color)

    # OP score footer
    d.text((x + 44, y + 48), f"OP: {op}", font=F_CHIP, fill=MUTED)


def make_frame(i: int) -> Image.Image:
    """36 frames total: 6 typing, 4 status warmup, 24 row reveals + holds, 2 endpause.
    Indexed 0..35. Last 8 frames are hold on the full output.
    """
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    draw_chrome(d)

    # Typing animation: frames 0..6 type the command, then it stays
    cmd_len = len("/subscope:run")
    if i < 7:
        typed = min(cmd_len, max(0, i * 2))
    else:
        typed = cmd_len
    draw_terminal_block(d, typed)

    # Status counters: appear at frame 7, ramp up over frames 7..14
    if i >= 7:
        # Frame-driven values, ending at the realistic real-run numbers
        progress = min(1.0, (i - 6) / 8.0)
        fetched = int(287 * progress)
        gated = int(43 * progress)
        scored = int(17 * progress)
        surfaced = int(5 * progress)
        draw_status_strip(d, y=170, fetched=fetched, gated=gated, scored=scored, surfaced=surfaced)

    # Rows appear one by one: row 1 at frame 13, row 2 at 17, etc.
    if i >= 13:
        # Header line above results
        d.text((40, 248), "OUTPUT", font=F_CHIP, fill=MUTED)

        first_visible_frame = 13
        gap = 3
        for r_idx, row in enumerate(ROWS):
            row_appears = first_visible_frame + (r_idx * gap)
            if i >= row_appears:
                # Newly-appearing rows briefly highlight (frame == row_appears)
                # then settle. For simplicity here we just paint them solid.
                y = 280 + r_idx * 72
                draw_result_row(d, x=40, y=y, idx=r_idx + 1, row=row)

    return img


def render_all() -> Path:
    total = 36  # 24 animation + 12 hold
    print(f"Rendering {total} frames to {FRAMES_DIR}/")
    for i in range(total):
        # Frames 24..35 = hold on frame 23 (the last animation frame)
        frame_index = min(i, 27)  # cap typing/row reveal animation
        img = make_frame(frame_index)
        path = FRAMES_DIR / f"f{i:03d}.png"
        img.save(path)
    print("Frames rendered. Assembling via ffmpeg...")

    out = OUT_DIR / "workflow.gif"
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
