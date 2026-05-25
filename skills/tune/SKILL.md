---
name: tune
description: Sharpen the subseek ranker with 3 rounds of Good/Bad/Meh feedback. Shows you 10 recent surfaces, you mark each in terse format (1g 2g 3b 4m 5g ...), the engine back-propagates into per-sub weights + keyword scores. Faster than re-running /profile when the daily list feels mediocre. Triggers on "tune subseek", "/subseek:tune", "fix the rankings", "list is mediocre", "feedback on surfaces", "tune the ranker".
allowed-tools: Bash, Read, Write, Edit
---

# /subseek:tune

3-round feedback loop. You mark 10 surfaces per round, the engine adjusts weights between rounds, and your config gets sharper without re-running the full `/profile` interview.

## When to use

The daily list (`/subseek:run`) feels mediocre. A few surfaces are great, a few are off, and you're not sure why. Instead of editing YAML by hand: tune.

## Procedure

### Step 1 — Pull the last 10 surfaces

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json
from subseek.lib import store
with store.connect() as conn:
    rows = store.hot_surfaces(conn)[:10]
    print(json.dumps([{
        'id': r['post_id'],
        'subreddit': r['subreddit'],
        'title': r['title'],
        'url': r['url'],
    } for r in rows], indent=2))
"
```

If fewer than 10 surfaces returned, tell the user: *"Only N surfaces in the recent pool. Run /subseek:run first, then come back."*

### Step 2 — Present in chat

Render the 10 surfaces in a numbered list with `[g/b/m]` markers, per ui-ux spec:

```
1. r/RevOps — "Anyone else drowning in HubSpot ops debt?"  [g/b/m]
2. r/SaaS — "Looking for a fractional RevOps person"        [g/b/m]
3. r/SalesOps — "Canceling Apollo, what do you use for sequence?"  [g/b/m]
...
10. r/B2BSaaS — "Salesforce minimums went up to 50 seats"  [g/b/m]

Mark all 10, then send. Blank = meh.
```

### Step 3 — Parse user's reply

User responds with terse marks like: `1g 2g 3b 4m 5g 6b 7g 8m 9g 10b`

Parse via `tune_engine.parse_marks(user_reply)`. Tolerates whitespace, commas, missing indices.

### Step 4 — Apply marks → back-propagate weights

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json, sys
from pathlib import Path
from subseek.lib import store, tune_engine

surfaces = json.loads(sys.stdin.read())['surfaces']
marks = json.loads(sys.stdin.read())['marks']  # {1: 'g', 2: 'b', ...}
subs_path = store.xdg_config_dir() / 'subreddits.yml'
result = tune_engine.apply_marks_to_subs(surfaces, marks, subs_path)
print(tune_engine.format_deltas_readout(result['changes'], round_num=1))
tune_engine.record_session(marks, result['changes'], surfaces, round_num=1)
"
```

Pass surfaces + marks as JSON to stdin (Claude composes this).

### Step 5 — Show the readout

Engine returns a top-5 deltas block like:

```
Round 1 → Round 2 changes:
  r/RevOps         weight 1.20 → 1.45  (+0.25)  [3 good]
  r/Entrepreneur   weight 1.00 → 0.60  (-0.40)  [2 bad, 1 meh]
  r/SaaS           weight 1.00 → 0.80  (-0.20)  [1 bad]

10 more surfaces incoming. Round 2 of 3.
```

Show verbatim to user.

### Step 6 — Repeat for rounds 2 + 3

After round 1's deltas, fetch the next 10 surfaces, present, parse, apply, show. Same loop. On round 3, the final readout replaces the "Round N+1" line with "Tuning complete."

### Step 7 — Tell user what to do next

```
Tuning complete. Updated weights saved to ~/.config/subseek/subreddits.yml.

Next /subseek:run should reflect these changes. If a sub's weight drops
below 0.2, consider quarantining it (edit subreddits.yml: tier: 3, weight: 0.0).

To audit the tuning history: ~/.local/share/subseek/tune-sessions.jsonl
```

## Anti-patterns

- **Don't auto-re-rank between marks.** Batch the round, apply once, show deltas. Per-mark re-ranking confuses the user about what's changing.
- **Don't silently delete subs.** Even if a sub gets 10 bad marks in a row, the worst it does is drop to weight 0.1 (floor). Quarantine is a user decision, not a tune action.
- **Don't ask "are you sure?" after each round.** The user signed up for 3 rounds; ship them through.
- **Don't generate any new keywords from the marks.** This skill tunes EXISTING config, doesn't create new entries. New keywords come from `/subseek:profile`.
- **Don't suggest re-running /profile after /tune.** It defeats the point. Mention only if 3 full rounds didn't materially change the ranker.

## Resumability

`/tune` runs are stateless within a session. If interrupted mid-round-2, restart from round 1 (the round-1 nudge already persisted to `subreddits.yml`).
