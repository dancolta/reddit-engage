---
name: pricing-rage
description: Surface Reddit price-hike rage threads (Salesforce/HubSpot/Gong cyclical Q1/Q3 spikes). Time-sensitive — cooling queue auto-disabled. Triggers on "pricing rage", "/reddit-engage:pricing-rage", "find price hike threads", "renewal complaints", "predatory pricing posts", "tier change rants".
allowed-tools: Bash, Read, Write
---

# /reddit-engage:pricing-rage (🔥)

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m reddit_engage.cli fetch-score --mode pricing-rage
```

**Cooling queue auto-disabled for this mode** — price-hike threads spike fast and decay fast. Surfaces land state=hot immediately.

Notion `Pattern` = `pricing-rage`, emoji prefix `🔥`. Print `inline_markdown` verbatim.
