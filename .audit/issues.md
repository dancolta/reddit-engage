# reddit-engage audit — prioritized fix list

5 agents (competitive, market, strategy, ui-ux, content) all returned. Strong consensus on the hero-block restructure + anti-positioning placement + named comparison table. Severity calibrated per audit skill rubric.

## CRITICAL (apply now)

### C1. Anti-positioning placement is wrong
The `> What this is not` callout currently sits AFTER the hero. Every agent independently said it must go IMMEDIATELY after the tagline, before any hero asset. Trust gate fires before they look at the GIF.

**Fix:** Restructure hero block to: H1 → 12-word tagline → 3 badges → hero GIF → WARNING-style anti-positioning callout (3 sharp lines naming Devi AI + ReplyGuy + auto-comment category by name) → install command.

### C2. GitHub About is empty
Repo currently has no About sentence. Single biggest miss for GitHub search + AI engine summarization.

**Fix:** `gh repo edit dancolta/reddit-engage --description "..."` with the 316-char synthesis sentence.

### C3. GitHub topic tags are empty
Zero topic tags = invisible to GitHub's category browsers.

**Fix:** 20 ranked tags via `gh repo edit --add-topic` per tag.

### C4. STOP claiming GummySearch replacement
Product strategist: positioning as a GummySearch alternative invites comparisons on coverage / dashboards / team features — axes a CLI plugin will always look thin on. Real slot: "the tool a technical founder actually opens at 8am."

**Fix:** Remove any "GummySearch alternative" framing. Keep the comparison table (still useful evidence), but don't position the product on that axis.

## HIGH (apply now)

### H1. Named comparison table
Current README has a comparison table but the axes don't flatter the actual differentiator. Strategist provided 10 rows + 7 columns (reddit-engage | Devi | ReplyGuy | F5Bot | Syften | Brand24 | Manual) with deliberate "scales past one human's attention: ✗" row owning the constraint.

**Fix:** Replace existing comparison table with strategist's matrix.

### H2. 11 sub-skills should collapse behind `<details>` accordion
Currently the sub-skill table dominates the middle section. UI-UX + competitive both flagged this.

**Fix:** Wrap the 11-row sub-skill table in `<details><summary>11 pattern-aware sub-skills</summary>...</details>`.

### H3. AI-citation Q&A block missing
No passage-level Q&A formatted for Perplexity/ChatGPT/Claude citation.

**Fix:** Add 6 Q&A blocks at the FAQ section (content-marketer supplied them verbatim).

### H4. Badge discipline
Current README has no badges. Convention is 3, single row, under H1.

**Fix:** Add shields.io badges for v0.1.0 + MIT + Claude Code Plugin.

## MEDIUM (apply after Critical/High pass)

### M1. Tagline tightening
Current tagline ("A daily inbox of Reddit threads worth your reply. You write the reply.") is 14 words. UI-UX recommends 12 max for above-fold scannability. Strategy suggested: "Claude Code plugin that surfaces Reddit pain posts. You write the reply."

**Fix:** Replace tagline.

### M2. Hero GIF refresh
Existing assets/hero.gif is from pre-plugin version, content doesn't match current plugin shape. UI-UX spec: 1280×640, 18-30 frames, 3-4s loop, **static end-frame = readable mock digest with subreddit / 3 post titles / intent score / "Reply manually?" prompt**.

**Fix:** Generate new GIF via /claude-gif. Backup old to assets/hero.v0.gif.

## LOW (defer to Phase 8 polish)

- L1. Auto-TOC suggestion (GitHub native) — README is 300+ lines, marginal
- L2. Honest "regex is dumb, here's when it misses" limitations section
- L3. Drop "Roadmap" details, link to PLAN.md only

## What we are NOT changing

- Repo name `reddit-engage` is fine (no agent flagged it)
- Pixel-art hero aesthetic stays (it IS the brand)
- "The automation stops where the conversation starts" line stays (load-bearing)
- License MIT stays
