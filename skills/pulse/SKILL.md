---
name: pulse
description: Weekly Obsidian digest of subscope activity. Builds a sub × surface heat map plus tier counts for the trailing 7 days, writes it as a dated markdown note to the user's Obsidian vault. Optional — skipped if Obsidian vault not configured. Triggers on "weekly pulse", "/subscope:pulse", "obsidian pulse digest", "reddit engage weekly recap", "what did subscope surface this week".
allowed-tools: Bash, Read, Write
---

# /subscope:pulse

Weekly reflection layer. Notion is the daily-triage surface; Obsidian is the weekly-review surface where you spot patterns over time.

## Preflight

Check for Obsidian vault config:

```bash
cat ~/.config/subscope/obsidian.yml 2>/dev/null
```

Expected shape:
```yaml
vault_path: /Users/dan/Documents/MyVault
pulse_folder: subscope  # optional, defaults to 'subscope'
```

If `obsidian.yml` missing: print "Obsidian vault not configured. Run `/subscope:onboard` to wire it (or drop `~/.config/subscope/obsidian.yml` with a `vault_path:` line manually), then re-run."

## Generate digest

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
from subscope.lib import store, obsidian_sync
with store.connect() as conn:
    print(obsidian_sync.build_weekly_digest(conn))
"
```

That prints the markdown digest content to stdout.

## Write to Obsidian

Use the **obsidian MCP** to write the digest:

1. Compute the filename: `YYYY-WNN-pulse.md` (current ISO week)
2. Compute the path: `<vault_path>/<pulse_folder>/<filename>` (create the folder if missing)
3. Call `mcp__obsidian__create-note` with that path and the markdown body from the previous step

If obsidian MCP not available (rare — Dan has it installed by default), fall back to writing the file via the host filesystem (`Bash: mkdir -p ... && cat > ...`).

## After write

Print one line:
```
Pulse written: <vault_path>/<pulse_folder>/<filename>  (N surfaces this week)
```

Do not print the digest body — Dan reads it in Obsidian.

## Optional: include postmortem stats

If Phase 5 postmortem is wired and `reply_log` table has data, the digest will include reply outcomes (Phase 5.5 extends `build_weekly_digest`). No skill change needed — the engine handles it.
