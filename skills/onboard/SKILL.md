---
name: onboard
description: 3-question routing flow that replaces the generic preset menu. Asks who you're trying to reach, what you're offering, and your homepage URL. Claude reasons in chat (using your Claude Code subscription, free) and writes a personalized config. ~60 seconds. The default first-launch path. Triggers on "onboard", "/subseek:onboard", "first time setup", "configure subseek", "set up subseek".
allowed-tools: Bash, Read, Write, Edit, WebFetch
---

# /subseek:onboard

The default first-launch flow. Three questions, ~60 seconds, produces a config that's specific to YOUR work — not a generic industry preset.

Validated by all 4 research agents in Phase 9. Generic preset alone produces 3/10 ICP-match per surface; the 3-question routing pushes it to 5-7/10. That's the difference between "tool I use daily" and "tool I uninstall after week 2."

## The framing rule

This is **configuration**, not **profiling**. The questions exist so `/subseek:run` targets the right subreddits. Frame it that way. Never use words like "profile", "ICP", "tell us about yourself" — those signal lead-gen tooling and the audience flinches.

## Procedure

### Step 1 — Welcome

Print verbatim (no exclamation marks, no concierge selling):

```
Three quick questions so /subseek:run targets the right subreddits.
About 60 seconds.

Type "preset" any time to skip these and use a generic lane instead.
```

### Step 2 — Question 1 (no phase label, keep it light)

```
Who are you trying to reach?
(e.g. "RevOps leaders at Series B SaaS", "indie devs shipping AI tools",
 "agency owners running 5-20 person teams")
```

User answers in free text. Don't reflect-and-advance after Q1 — feels padded for a 3-question flow. Just go to Q2.

### Step 3 — Question 2

```
What are you offering or building?
(one line — product, service, or "building in public")
```

User answers. After Q2, reflect both answers in one tight sentence:

```
Got it — targeting [reach] with [offering].
```

### Step 4 — Question 3 (URL, mandatory with override)

```
Paste your homepage URL — sharpens targeting a lot.
Type "none" if you don't have one yet.
```

If user pastes a URL: **actually WebFetch it.** Extract:
- H1 + sub-headline
- First 400 chars of body
- Any competitor names mentioned ("alternative to X", "we replace Y")
- Rough price-point signal (if pricing page visible)

Show what was extracted:

```
Fetching... pulled headline, h2s, and first 400 words.
H1: "[extracted]"
Competitors mentioned: [list, or "none detected"]
Use this as ground truth? [yes / try again]
```

If `none`: skip URL fetch, mark `confidence: medium` (not low — 2 answers is still useful).

### Step 5 — Synthesize (Claude reasons in chat, free)

Save the answers to scratchpad first:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json
from subseek.lib import profile_synth
profile_synth.save_draft({
    'who_to_reach': '$Q1',
    'what_offering': '$Q2',
    'homepage_url': '$Q3' if '$Q3' != 'none' else '',
    'url_extracts': $URL_JSON_OR_EMPTY,
})
"
```

**Claude now reasons through the answers IN CHAT** (this is the key — uses subscription, free). Steps:

1. Read the synthesis prompt: `cat "$CLAUDE_PLUGIN_ROOT/engine/subseek/prompts/profile_synth.md"`
2. Apply the prompt's rules to the 3 answers (plus URL extracts if available)
3. Emit a JSON payload matching the synthesis schema (3-5 tier 1 subs, 5-8 tier 2, etc.)
4. Validate via `profile_synth.validate(payload)` — fail loud if schema breaks
5. If URL extracts present, merge them via `profile_synth.merge_url_extracts(payload, url_extracts)`

If user has API key (`LLM_API_KEY` env), optionally offer to run the research-validator agent (Phase 9.3) to verify sub picks via live Reddit data. ~30s, ~$0.30. Default: skip — keep onboard friction at ~60s.

### Step 6 — Show + confirm

Per the UI-UX spec, do NOT dump 4 YAML files. Show a tight summary:

```
Targeting: [reach] / offering [offering].

Subs picked:
  Tier 1 (daily scan): r/RevOps, r/SalesOps, r/CRM (3)
  Tier 2 (opportunistic): r/SaaS, r/B2BSaaS, r/sales, r/ProductManagement (4)

Keywords seeded: 12 shared, 18 operator, 6 builder
Brand anchor: Apollo, HubSpot, Clari, Default, Pocus (+ 7 more)

Look right? [yes / show full config / change subs / change keywords]
```

If `show full config`: dump the 4 YAML files in fenced blocks.

If user wants changes, take the edit, re-validate, re-show. No magic — just edit the JSON and re-emit.

### Step 7 — Write to disk

On `yes`:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json
from subseek.lib import profile_synth
payload = $PAYLOAD_JSON
written = profile_synth.write_to_xdg(payload)
for name, path in written.items():
    print(f'  wrote: {path}')
profile_synth.clear_draft()
"
```

This writes 4 files to `~/.config/subseek/` with chmod 600, backs up any existing.

### Step 8 — The next-action prompt (locked)

```
Config written. Run /subseek:run when you want your first scan —
about 10 surfaces, ranked, no posting. Takes about 90 seconds.

If the daily list feels mediocre after a few runs, /subseek:tune
sharpens the ranker in 3 rounds of Good/Bad/Meh feedback.

If you want a deeper, 8-question version of this interview later,
/subseek:profile is the upgrade path.
```

## The "preset" escape hatch

At any question, if user types `preset` (or `skip`, `1`, etc.):

1. Confirm: *"Switching to preset mode. Which lane? (RevOps / DevTools / Indie SaaS / Agency / Other)"*
2. Copy the chosen preset to `~/.config/subseek/`
3. Skip to Step 8 next-action prompt

No shame, no friction. Some users genuinely want the 30-second path.

## Anti-patterns

- **Don't reflect-and-advance after every question.** For 3 questions, reflection only after Q2 is enough. After every question = padded.
- **Don't add phase labels like `─── 1/3 ───`.** Em-rules feel ceremonious at this scale. Save them for the 8-question /profile.
- **Don't ask "are you sure?" between any question.** Trust the user.
- **Don't silently ingest the URL.** Show the extraction.
- **Don't write any YAML file without the confirm at Step 6.** Even if the user trusts the synth, the confirm is the consent gate.
- **Never use words like "ICP", "profile", "audience targeting", "lead profile".** Operational language only: "targeting", "subreddits", "config".

## Resumability

Check for `~/.config/subseek/.onboard-draft.json` on invocation. If present AND <24 hours old: *"Found a draft from earlier — 2 of 3 questions done. Resume, or start fresh?"* If >24 hours: stale, prompt to start fresh.

Scratchpad cleared on successful synthesis (`profile_synth.clear_draft()`).
