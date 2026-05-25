---
name: churn
description: Surface high-intent Reddit posts where someone explicitly says they are canceling, switching from, or fed up with a named SaaS vendor. Pure buying intent. Triggers on "churn signals", "/reddit-engage:churn", "find churn posts", "who's canceling", "switching from posts", "churn-signals scan".
allowed-tools: Bash, Read, Write
---

# /reddit-engage:churn (⚡)

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m reddit_engage.cli fetch-score --mode churn
```

Gate tuned for verb-anchor + vendor co-occurrence ("canceling Apollo", "switching from HubSpot"). Cooling queue still applies.

Notion `Pattern` = `churn`, emoji prefix `⚡`. Print `inline_markdown` verbatim.
