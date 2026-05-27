---
name: subscope-rivals
description: Track today's Reddit mentions of competitors from your brand_anchor config. Pure competitive intel — surfaces every substantive mention of a named vendor in the last 24h across configured subs. Triggers on "rivals scan", "/subscope-rivals", "track competitor mentions", "competitor radar".
allowed-tools: Bash, Read, Write
---

# /subscope-rivals (🥷)

Scans today's Reddit mentions of any competitor in your `brand_anchor` config (set during /subscope-onboard or /subscope-profile). Surfaces substantive mentions in the last 24h — reviews, switching threads, pricing complaints, alternative-seeking posts.

```bash
# user invocation
/subscope-rivals
```

Engine call:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli fetch-score --mode rivals
```

The rivals mode loads `config/keywords-rivals.yml` (alternative-seeking, switching, churn keywords) and matches against your brand_anchor list. If you want a one-off scan of a brand NOT in your config, add it to brand_anchor temporarily in `~/.config/subscope/profile.yml`.

Cooling queue applies (24h window already keeps it fresh).

Notion `Pattern` = `rivals`, emoji prefix `🥷`. Print `inline_markdown` verbatim.
