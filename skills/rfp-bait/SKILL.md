---
name: rfp-bait
description: Surface "X vs Y vs Z" comparison threads where ≥2 vendors are named in a comparative structure. Adding a 4th non-cliche option is welcomed, not seen as spam. Triggers on "rfp bait", "/reddit-engage:rfp-bait", "find comparison threads", "vs threads", "shortlist threads", "evaluation threads".
allowed-tools: Bash, Read, Write
---

# /reddit-engage:rfp-bait (🤝)

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m reddit_engage.cli fetch-score --mode rfp-bait
```

Gate requires ≥2 SaaS brand names AND a "vs"/"or"/"between" construction. Cooling queue applies.

Notion `Pattern` = `rfp-bait`, emoji prefix `🤝`. Print `inline_markdown` verbatim.
