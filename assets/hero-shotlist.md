# Hero asset spec

`assets/hero.gif` is rendered by `assets/render_hero.py` (pure Python + Pillow,
assembled with ffmpeg). Regenerate with:

```bash
python3 assets/render_hero.py
```

## What it shows

A Claude Code chat after `/subscope-run`, in the 8-bit purple terminal style,
resolving to the product's two-track output:

- **BUYER SIGNALS**: ranked threads where a reply moves a deal (tag, subreddit,
  age, score, pattern, quoted title).
- **AUTHORITY PLAYS**: answerable threads with no buyer yet, worth a reply to
  build credibility.

Rows reveal under a descending magenta scan-line, then the GIF holds on the full
list. The resting end-frame is what most viewers see, so it must read as a clean
static screenshot of the dual-track output.

## Specs

| Field | Value |
|---|---|
| Dimensions | 1280 x 800 |
| Frames | ~15 at 6 fps |
| Loop | once, then hold on the last frame (`-loop -1`) |
| File size | under 2 MB (currently ~77 KB) |
| Palette / fonts | defined at the top of `render_hero.py` |

## Anti-patterns (do NOT do)

- No auto-reply or typing-a-comment animation. It contradicts the human-in-the-loop positioning.
- No fake stat footer, no version badge, no emoji.
- No infinite loop. The static end-frame is the load-bearing visual.
- Both section headers are mandatory. The dual track is the feature the hero exists to teach.
- Keep both section copy lines em-dash-free, like the rest of the project.
