---
name: profile
description: 8-question conversational interview that builds a personalized subseek config from your work, ICP, competitors, and content. Replaces generic preset selection — you don't have to know which subreddits matter, the wizard figures it out with you. Outputs 4 tuned YAML files. Re-runnable, additive. Triggers on "profile", "/subseek:profile", "build my profile", "personalize subseek", "tune to my ICP", "create my subseek profile".
allowed-tools: Bash, Read, Write, Edit, WebFetch
---

# /subseek:profile

Don't know which subreddits matter? Neither did we. This is an 8-question conversation where you describe what you're building and who it's for. You come back with a config tuned to you: a starting list of subs worth reading, pain phrases in your ICP's voice, your competitor anchor, and the example titles the classifier learns from.

~12 minutes. Re-run anytime.

## The pacing rule

**One question per turn. Wait for an answer.** Don't batch across themes. Reflect-and-advance after each answer: *"Got it — RevOps-as-a-service for Series A founders skipping the hire."* Don't say "got it" alone — that's filler.

Escalate to pushback only when the answer is a category not a position: *"'B2B SaaS' covers a lot — pick the buyer you'd rather get a DM from."*

## Phase labels

Render each question with a single bracketed header. Lowercase, em-rule, editorial:

```
─── 1 / 8 · what you sell ───
```

The 4 phases:
- 1-3: **Positioning**
- 4-5: **Where they hang out**
- 6-7: **Voice & anchor**
- 8: **Synthesis**

## The 8 questions

### `─── 1 / 8 · what you sell ───`

> In one sentence, what do you sell and who pays for it?

Free-text. Multi-paragraph allowed. Forces offer + buyer in a single noun-verb-payer triple. After the user replies, paraphrase back in one sentence and move on.

### `─── 2 / 8 · ground truth ───`

> Paste 1-3 URLs: homepage, pricing page, or a recent case study.

URL paste. Actually WebFetch each URL. Report back what was extracted:

```
Fetching... pulled headline, h2s, and first 400 words.
Use this as ground truth? [yes / try again]
```

If fetch fails, say so and ask for a copy-pasted summary instead. Don't pretend.

### `─── 3 / 8 · your last 3 customers ───`

> Describe your last 3 actual customers — not the persona deck, the real people who paid you. Job title, company size, what tool/process they replaced to buy you.

Free-text, multi-paragraph encouraged. The "what they replaced" clause is the gold — reveals adjacent tool categories + the trigger event. If the user can't name 3, accept 1-2 (note in scratchpad as `confidence: low`).

### `─── 4 / 8 · the pain quote (load-bearing) ───`

> What did that customer literally say was broken before they found you? Paste a quote if you have one — Slack, sales call, review, anything.

Free-text + optional paste. **This is the most important question.** Without verbatim language, synthesis falls back to generic. If the user answers with a paraphrase ("they said it was inefficient"), push back: *"Got a literal quote? 'inefficient' is yours, not theirs."*

### `─── 5 / 8 · where they vent ───`

> When that pain hits at 11pm, where does your buyer go to vent or ask for help? Reddit, Twitter, Slack groups, Discord, LinkedIn, nowhere?

Free-text. Diagnostic. If user says "I don't know" or leaves blank: **first blank = gentle rephrase**: *"Even a guess? 'Probably Slack', 'I don't think they post anywhere'?"* **Second blank = website fallback**: *"No problem. The URL you pasted in Q2 will fill in most of it. Moving on."* Mark `confidence: low` and continue.

### `─── 6 / 8 · who they're stealing customers from ───`

> List 3-7 tools you steal customers from (or that your buyer evaluates you against).

List input. Comma-separated OR newline — Claude parses both. The "steal from" framing surfaces real competitors, not aspirational ones. Echo back as a clean bulleted list for confirmation.

### `─── 7 / 8 · how they describe themselves ───`

> What job titles or self-descriptions does your buyer use? Examples: "indie hacker", "agency owner", "RevOps lead", "fractional CTO". Give 2-4.

List input. Drives the operator/builder bucket assignment.

### `─── 8 / 8 · your own content ───`

> Paste 3-5 URLs of your own content (blog, YouTube, threads) that converts best, or that you'd want to reference in a Reddit reply. Optional — type `skip` if you don't have it.

Optional. If provided, WebFetch each and extract titles/H1s for the `blog-map.yml`. If skipped, the engine works fine without.

## After all 8 answers — synthesis

Save a scratchpad first:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json
from pathlib import Path
from subseek.lib import store
draft = store.xdg_config_dir() / '.profile-draft.json'
draft.write_text(json.dumps($ANSWERS_DICT, indent=2))
print(f'scratchpad: {draft}')
"
```

Then call the synth library:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 << 'PY'
import json, sys, yaml
from pathlib import Path
from subseek.lib import profile_synth, store

# Compose the interview summary (markdown) for the LLM prompt
answers = json.load((store.xdg_config_dir() / '.profile-draft.json').open())
summary_lines = []
for k, v in answers.items():
    summary_lines.append(f"## {k}")
    summary_lines.append(v)
    summary_lines.append("")
interview = "\n".join(summary_lines)

# Try LLM synth (Anthropic API path), fall back to archetype
payload = profile_synth.llm_synthesize(interview)
if payload is None:
    print("[info] no API key — falling back to archetype-mapped synthesis", flush=True)
    payload = profile_synth.fallback_from_archetype(answers)

# Load weights for ceilings
weights_path = Path("config/weights.yml")
weights_cfg = yaml.safe_load(weights_path.read_text()) if weights_path.exists() else {}

ok, problems = profile_synth.validate_synthesis(payload, weights_cfg)
if not ok:
    print("VALIDATION FAILED:")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)

print(json.dumps(payload, indent=2))
PY
```

## Synthesis reveal — progressive write-with-confirm

For each of the 4 YAML files the synth produced, ask the user separately:

```
Writing subreddits.yml — 4 tier-1 subs, 7 tier-2, 3 quarantined.
  → Want to see it, or trust and continue? [show / continue]
```

Default to `continue`. If user types `show`, dump the YAML in a fenced block AND offer a 1-line edit prompt: *"Anything to swap before I write?"*

Repeat for `keywords.yml`, `brand-anchor.yml`, `example-pains.yml`.

After all 4 confirmed, batch-write to `~/.config/subseek/` via `profile_synth.write_to_xdg(payload)` — Python does the disk write with chmod 600.

## After synthesis — the locked next-action prompt

```
Config written. Run /subseek:run when you want your first scan —
10 surfaces, ranked, no posting. Takes about 90 seconds.

After you've seen output, /subseek:tune sharpens the ranker in 3 rounds.
```

No "ready to go?!" energy. State the command, the output shape, the time, seed awareness of `/tune` without pushing.

## Anti-patterns

- **No exclamation marks anywhere.** This audience flinches at exclamation marks.
- **No "Let's build your profile together!" / "Welcome to the wizard!"** Instant trust kill.
- **No emoji in question prompts.** Pixel-monospace voice; phase em-rules already carry the rhythm.
- **Never auto-fill from the URL without showing what was extracted.** Silent ingestion feels invasive.
- **Don't ask "are you sure?" between every question.** Trust the user to type their own answer; only confirm at synthesis reveal.
- **Don't write any YAML file without `show / continue` confirmation.** Even if the user says "just trust the synth", the confirm is the consent gate.
- **Don't suggest re-running /profile after /profile.** Use /tune for refinement.

## Resumability

Check for `~/.config/subseek/.profile-draft.json` on invocation. If present AND <7 days old: *"Found a draft from Tuesday — 5 of 8 answers done. Resume, or start fresh?"* If >7 days: stale, prompt to start fresh.

Scratchpad is overwritten on each turn, deleted on successful synthesis.

## Optional: research-validator

If `ANTHROPIC_API_KEY` is set AND the user opts in at synthesis-reveal time, spawn the research-validator agent (see `engine/subseek/prompts/profile_research.md`). It WebFetches each candidate sub's `about.json` and spot-checks recent threads. Returns a JSON with `verified_subs[]`, `rejected_subs[]`, `suggested_additions[]`. ~30s, ~$0.30. Show the report; let the user accept/reject the recommendations before final disk write.
