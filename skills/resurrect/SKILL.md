---
name: resurrect
description: Find 6-18 month old high-quality Reddit threads that still get Google traffic. Late comments compound forever via SEO. Triggers on "resurrect threads", "/subscope:resurrect", "find old threads worth commenting", "SEO comment opportunities", "thread resurrect".
allowed-tools: Bash, Read, Write
---

# /subscope:resurrect (🪦)

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli fetch-score --mode resurrect
```

**Behavior diverges from other modes:** instead of `/r/<sub>/new`, this mode queries Reddit search with `t=year` timeframe (last 12 months) plus an age floor of 6 months. Gate filters by score ≥ 50 and comment velocity > 0 in the trailing week.

Cooling queue applies (these aren't time-sensitive).

Notion `Pattern` = `resurrect`, emoji prefix `🪦`. Print `inline_markdown` verbatim.

> **Note (Phase 3 implementation):** the search-API path requires extending `reddit_oauth.fetch_delta` with a search-mode branch. If not yet wired, this skill falls back to default `/new` and logs a warning — surface volume will be lower.
