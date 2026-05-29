---
name: subscope-tune
description: Sharpen the subscope ranker with targeted feedback. Shows your recent surfaces; you mark ONLY the ones that are off (and any standouts) and skip the rest. The engine nudges per-sub weights from your marks. Faster than re-running /profile when the daily list feels a little off. Triggers on "tune subscope", "/subscope-tune", "fix the rankings", "list is mediocre", "feedback on surfaces", "tune the ranker".
allowed-tools: Bash, Read, Write, Edit
---

# /subscope-tune

Targeted feedback. You mark only the surfaces that stand out (wrong or great), the engine nudges per-sub weights, and your config gets sharper without re-running the full `/profile` interview. Anything you skip is left untouched.

## When to use

The daily list (`/subscope-run`) is mostly fine but a few surfaces are off. Instead of editing YAML by hand: tune. Flag the wrong ones, optionally the great ones, ignore the rest.

## Procedure

### Step 1: Pull recent surfaces

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json
from subscope.lib import store
with store.connect() as conn:
    rows = store.hot_surfaces(conn)[:15]
    print(json.dumps([{
        'id': r['post_id'],
        'subreddit': r['subreddit'],
        'title': r['title'],
        'url': r['url'],
    } for r in rows], indent=2))
"
```

If the pool is empty, tell the user: *"No surfaces in the recent pool yet. Run /subscope-run first, then come back."*

### Step 2: Present in chat (mark only what stands out)

Render the recent surfaces as a clean numbered list. Make clear that marking is OPTIONAL and partial: the user flags only what is off (and any standouts), and skipping changes nothing.

```
Your recent surfaces. Mark only the ones that are off, or great. Skip the rest, they stay as-is.

  b = surface less of this     g = surface more     (skip = leave alone)

  1. r/RevOps        "Anyone else drowning in HubSpot ops debt?"
  2. r/SaaS          "Looking for a fractional RevOps person"
  3. r/Entrepreneur  "How to find first 10 customers?"
  4. r/RevOps        "Mass-update HubSpot deals via API?"
  5. r/sales         "Apollo just hiked us 40 percent"

Reply with just the ones worth flagging, e.g.  3b  or  3b 5g  (spaces or commas).
Reply "done" to finish without changes.
```

Rules:
- Lead with the one-line instruction. State plainly that partial feedback is fine and skipping is the default.
- Do NOT render a `[ ? ]` placeholder on every row. That implies the user must rate all of them, which is exactly the friction we are removing. Plain numbered list only.
- Do not force a fixed count or rounds. Show what is in the pool (up to ~15).
- If a row was flagged in an earlier pass this session, you may show its mark in brackets (e.g. `[b]`), but never require the user to re-confirm it.

### Step 3: Parse the reply

Parse via `tune_engine.parse_marks(user_reply)`. It tolerates whitespace, commas, and missing indices. Unmarked rows carry NO signal and never change a weight, so the user only needs to type the few they care about. If the user replies "done" with no marks, skip to "no changes".

### Step 4: Apply marks, nudge weights

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json, sys
from subscope.lib import store, tune_engine

payload = json.loads(sys.stdin.read())
surfaces = payload['surfaces']
marks = payload['marks']  # {1: 'g', 3: 'b', ...} for ONLY the flagged rows
subs_path = store.xdg_config_dir() / 'subreddits.yml'
result = tune_engine.apply_marks_to_subs(surfaces, marks, subs_path)
print(tune_engine.format_deltas_readout(result['changes'], round_num=1, total_rounds=1))
tune_engine.record_session(marks, result['changes'], surfaces, round_num=1)
"
```

Pass surfaces + the flagged marks as one JSON object to stdin (Claude composes this). Only include the rows the user actually marked.

### Step 5: Show the readout

The engine returns a deltas block listing ONLY the subs that actually changed:

```
Updated weights:
  r/RevOps         1.20 -> 1.45  (+0.25)  [2 flagged good]
  r/Entrepreneur   1.00 -> 0.80  (-0.20)  [1 flagged bad]

Tuning complete. Saved to ~/.config/subscope/subreddits.yml.
```

Show it verbatim. If nothing was flagged (or the user said "done"), print one line: *"No changes, nothing flagged. Your config is unchanged."* and stop.

### Step 6: Offer another pass (optional)

If the user wants to keep refining, pull the next batch of surfaces and repeat. Never force multiple rounds; one targeted pass is a complete, valid session.

### Step 7: What to do next

```
Next /subscope-run reflects these weights. If a sub keeps surfacing posts you
flag as bad, consider quarantining it (edit subreddits.yml: tier: 3, weight: 0.0).

Tuning history: ~/.local/share/subscope/tune-sessions.jsonl
```

## Anti-patterns

- **Don't require feedback on every surface.** Targeted, partial feedback is the whole point. The user types only the few that stand out.
- **Don't penalize skipped surfaces.** Skipped means no signal means no change. The engine enforces this (meh nudge is zero); the presentation must match it.
- **Don't silently delete subs.** Even after repeated bad flags, the worst case is the 0.1 weight floor. Quarantine is a user decision, not a tune action.
- **Don't generate new keywords from the marks.** This skill sharpens EXISTING config. New entries come from `/subscope-profile`.
- **Don't suggest re-running /profile after /tune** unless several passes did not move the ranker.

## Resumability

`/tune` is stateless within a session. Each pass persists to `subreddits.yml` immediately, so an interruption just means fewer surfaces got marked. Nothing to resume.
