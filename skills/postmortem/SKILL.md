---
name: postmortem
description: Detect your replies to surfaces and score their 7-day outcome (upvotes, replies, banned). Closes the loop on which patterns convert vs flop. Requires Reddit OAuth identity scope (set up via docs/setup-oauth.md). Triggers on "postmortem", "/subscope:postmortem", "score my replies", "did my reddit replies work", "reddit reply outcomes", "reply post-mortem".
allowed-tools: Bash, Read
---

# /subscope:postmortem

Runs the postmortem pipeline:

1. **Detect new replies** — walk your own /user/<you>/comments, match against surfaced posts in SQLite, log new matches to `reply_log`
2. **Score 7-day outcomes** — for reply_log rows aged ≥7d without an outcome, fetch the comment + record upvotes/replies/removed state
3. **Print summary** — counts + averages

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json
from subscope.lib import postmortem, store
with store.connect() as conn:
    detect = postmortem.detect_replies(conn)
    update = postmortem.update_outcomes(conn)
    summ = postmortem.summary(conn)
print(json.dumps({'detect': detect, 'update': update, 'summary': summ}, indent=2))
"
```

## Output format

The JSON gives you three blocks:

| Block | Tells you |
|---|---|
| `detect` | scanned (your last N comments), new_matches (new replies discovered), already_logged, errors |
| `update` | scored (7d outcomes recorded this run), skipped_too_young, fetch_failures |
| `summary` | total_replies tracked, scored (with outcomes), avg_upvotes, avg_replies, removed_count, locked_count |

Translate to chat as a tight readout:

```
**Postmortem run** — N new replies detected · M outcomes scored

Lifetime: N replies tracked, avg X upvotes / Y replies. Removed: Z.
```

If `scored > 0`, also pull the worst removed/locked replies (`SELECT post_id, outcome FROM reply_log WHERE outcome IS NOT NULL AND (json_extract(outcome,'$.removed')=1 OR json_extract(outcome,'$.locked')=1)`) and surface them — those are the patterns to stop replying to.

## Preflight

If `~/.config/subscope/oauth.json` doesn't exist, the engine prints a warning but continues via the public-JSON fallback (lower fidelity). Tell the user: "Postmortem fidelity improves with OAuth — see docs/setup-oauth.md."

## When to run

Manually, weekly. Auto-runs are not wired (no scheduler in the plugin). The natural moment is when running `/subscope:pulse` for the weekly review — the pulse digest reads `postmortem.summary(conn)` and includes outcomes in the markdown if any are present.
