---
name: subscope-stack-audit
description: Surface Reddit threads where an OP publicly lists 8+ tools in their stack and asks how to consolidate. Highest-intent format — OP is already in cutting mode, lurkers are watching. Triggers on "stack audit", "/subscope-stack-audit", "stack rationalization", "find stack consolidation threads", "tool sprawl posts", "consolidation play".
allowed-tools: Bash, Read, Write
---

# /subscope-stack-audit (🧱)

Run the daily surface in **stack-audit mode** — gate tuned for OPs publicly listing many SaaS tools and asking how to consolidate.

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli fetch-score --mode stack-audit
```

Surfaces land in the cooling queue (30 min hold) like the default run. Output JSON has `mode: "stack-audit"` and each surface gets `pattern_emoji: "🧱"`.

Optional Notion sync writes the `Pattern` column = `stack-audit`. See `skills/run/SKILL.md` for the full Notion-sync procedure.

Print the engine's `inline_markdown` verbatim. No drafting.
