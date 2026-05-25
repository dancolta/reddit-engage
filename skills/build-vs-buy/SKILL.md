---
name: build-vs-buy
description: Surface explicit build-vs-buy debate threads with numeric arguments (engineering hours, TCO, payback). OP is rationalizing the decision publicly — your worldview is the answer. Triggers on "build vs buy", "/subseek:build-vs-buy", "find build-vs-buy debates", "in-house vs SaaS", "make-or-buy decisions".
allowed-tools: Bash, Read, Write
---

# /subseek:build-vs-buy (⚖️)

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subseek.cli fetch-score --mode build-vs-buy
```

Gate requires both a build-or-buy verb and numeric pattern in title or body. Cooling queue applies.

Notion `Pattern` = `build-vs-buy`, emoji prefix `⚖️`. Print `inline_markdown` verbatim.
