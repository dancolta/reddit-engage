# Hero GIF shotlist

Replacement for `assets/hero.gif`. Old version archived at `assets/hero.v0.gif`.

## Brief

Pixel-art (8-bit aesthetic, same palette as v0: orange `#f15b25` + teal `#46ccde` on dark navy `#2d2d2d`). Loops once then holds on a readable end-frame. The end-frame is what most GitHub viewers see — it must function as a static screenshot of the daily digest output.

## Specs

| Field | Value |
|---|---|
| Dimensions | 1280 × 640 (2:1, renders crisp at GitHub's ~900px content width, survives mobile) |
| Frame count | 24 frames |
| Duration | 4 seconds, 6 fps |
| Loop behavior | Once, then hold on frame 24 |
| File size | < 2 MB (GitHub inlines, no lazy-load penalty) |
| Palette | 8-bit pixel-art: `#f15b25` orange, `#46ccde` teal, `#2d2d2d` navy bg, `#ebe8e7` text |
| Output path | `assets/hero.gif` (replace) |

## Frame storyboard

### Frames 1–4 (~0.7s) — Boot
- Top-left: terminal-style cursor blinks
- Bottom row of HUD chips appear one at a time: `REGEX ✓` `OAUTH ?` `LLM ?` `NOTION ?` `OBSIDIAN ?`
- Title bar fills in: **REDDIT-ENGAGE v0.1.0**
- Sub-title: **DAILY PAIN-POST RADAR** in monospace bleed-text

### Frames 5–12 (~1.3s) — Sub-skill bar lights up
- Below the title, a horizontal row of sub-skill chips lights up one at a time, left-to-right:
  - `🔥 :run` → `🧱 :stack-audit` → `⚡ :churn` → `🔥 :pricing-rage` → `⚖️ :build-vs-buy` → `🤝 :rfp-bait` → `🪦 :resurrect` → `🥷 :rivals`
- Each chip pulses orange when activated
- After all are lit, the strip stays glowing

### Frames 13–18 (~1s) — Surfaces materializing
- Center area: 3 post rows materialize one at a time with a typewriter scroll
- Each row format (use real-feeling fake content):
  ```
  [T1] r/RevOps     · 14h     · score 92  · 🧱
       HubSpot renewal +28%, anyone moved off?
       PAIN: pricing-rage  ·  FIT: 9/10
  ```
- Use 3 different patterns: `🧱 stack-audit`, `⚡ churn`, `🔥 pricing-rage` so the sub-skill diversity is visible

### Frames 19–22 (~0.7s) — Prompt for human action
- A bottom-card slides up:
  ```
  ────────────────────────────────────
  YOU read.  YOU judge.  YOU reply.
  /reddit-engage:judge <n>  →  full classification
  ────────────────────────────────────
  ```
- "YOU" pulses orange

### Frames 23–24 (~0.3s) — Hold (THE STATIC END-FRAME)

This is the frame 70% of viewers see. It must function as a screenshot:

```
┌──────────────────────────────────────────────────────────────────┐
│ REDDIT-ENGAGE v0.1.0     DAILY PAIN-POST RADAR        DEDUP ✓    │
│                                                                  │
│ 🔥 🧱 ⚡ 🔥 ⚖️ 🤝 🪦 🥷                  PLUG & PLAY · v0.1.0      │
│                                                                  │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │ [T1] r/RevOps      ·  14h  ·  score 92  ·  🧱  stack-audit   │ │
│ │      HubSpot renewal +28%, anyone moved off?                 │ │
│ │      PAIN: pricing-rage   FIT: 9/10                          │ │
│ │                                                              │ │
│ │ [T1] r/SalesOps    ·  6h   ·  score 78  ·  ⚡  churn         │ │
│ │      Canceling Apollo, what do you use for sequence?         │ │
│ │      PAIN: churn-signal   FIT: 8/10                          │ │
│ │                                                              │ │
│ │ [T2] r/B2BSaaS     ·  3h   ·  score 71  ·  🔥  pricing-rage  │ │
│ │      Salesforce minimums went up to 50 seats — alternatives? │ │
│ │      PAIN: pricing-rage   FIT: 8/10                          │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ YOU read.  YOU judge.  YOU reply.                                │
│ The automation stops where the conversation starts.              │
└──────────────────────────────────────────────────────────────────┘
```

Alt text for accessibility: "reddit-engage daily digest showing 3 high-intent surfaces: HubSpot renewal complaint in r/RevOps tagged stack-audit, Apollo cancellation in r/SalesOps tagged churn, Salesforce price hike in r/B2BSaaS tagged pricing-rage. Footer: YOU read. YOU judge. YOU reply."

## Generation command

Suggested implementation route — `/claude-gif create` (Remotion programmatic, since this is text/UI animation, not photorealistic motion):

```
/claude-gif create

8-bit pixel-art hero GIF for reddit-engage README.

Read the shotlist at /Users/dancolta/Work/NodeSparks/Projects/reddit-engage/assets/hero-shotlist.md
verbatim. Match the existing /Users/dancolta/Work/NodeSparks/Projects/reddit-engage/assets/hero.v0.gif
aesthetic exactly (palette, pixel size, font choice). Replace the content with the
new storyboard.

Output: /Users/dancolta/Work/NodeSparks/Projects/reddit-engage/assets/hero.gif
Loop: once-then-hold (FFmpeg -loop 1)
Optimize for <2MB after final render.
```

## Anti-patterns (do NOT do)

- ✗ Don't show auto-reply / typing animation — defeats the entire anti-positioning
- ✗ Don't include Devi/ReplyGuy product logos
- ✗ Don't add cursive / decorative fonts — pixel-monospace only
- ✗ Don't loop infinitely — the static end-frame is the load-bearing visual
- ✗ Don't use the Reddit alien mascot — trademark risk
- ✗ Don't make the cursor look like a sprite walking — too playful; readout-style is the brand
