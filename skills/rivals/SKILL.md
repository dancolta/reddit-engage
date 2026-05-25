---
name: rivals
description: Track today's Reddit mentions of a specific competitor brand. Pure competitive intel — surfaces every substantive mention of a named vendor in the last 24h across configured subs. Triggers on "rivals scan", "/reddit-engage:rivals <brand>", "track competitor mentions", "who's talking about <brand>", "competitor radar".
allowed-tools: Bash, Read, Write
---

# /reddit-engage:rivals (🥷)

Takes a brand name as argument. Surfaces every Reddit post in the last 24h that names the brand in a substantive way (review, switching, pricing, alternative, etc.).

```bash
# user invocation example
/reddit-engage:rivals Apollo
```

Engine call:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m reddit_engage.cli fetch-score --mode rivals --rivals-brand "$BRAND"
```

If the user didn't pass a brand, ask them which competitor they want to track and re-run. Don't guess.

Cooling queue applies (24h window already keeps it fresh).

Notion `Pattern` = `rivals`, emoji prefix `🥷`. Print `inline_markdown` verbatim.
