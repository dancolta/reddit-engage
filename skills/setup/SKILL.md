---
name: subscope-setup
description: Reconfigure individual pieces of subscope after first-run onboarding. Use this when you want to add or change LLM provider, swap a destination (Notion / Slack / Obsidian), or rotate credentials. NOT the first-run flow. First-time users should run /subscope-onboard instead. Triggers on "/subscope-setup", "reconfigure subscope", "change subscope settings", "update subscope LLM", "rotate subscope credentials", "swap subscope destination".
allowed-tools: Bash, Read, Write, Edit
---

# /subscope-setup

Reconfiguration tool for an already-onboarded subscope install. For first-run, route the user to `/subscope-onboard` instead. The 6 steps below are now individually addressable: ask the user which one they want to change before walking the whole flow.

## Goal

Let an existing user change one piece of their config without re-doing the whole onboarding.

## Procedure

First, check whether the user has already onboarded:

```bash
[ -f ~/.config/subscope/subreddits.yml ] && echo "ONBOARDED" || echo "NOT_ONBOARDED"
```

If `NOT_ONBOARDED`: redirect to `/subscope-onboard` and stop. Do not run the steps below for a new install.

If `ONBOARDED`: ask which piece they want to change:

> What do you want to reconfigure?
>   1. LLM provider (add or swap)
>   2. Targeting (re-pick preset, or re-run /subscope-onboard for full re-do)
>   3. Notion database
>   4. Slack webhook
>   5. Obsidian vault
>
> Pick a number, or type "all" to walk every step.

Then jump to that step only. Each step is independent.

### Step 1 — LLM provider (optional)

Tell the user:

> subscope has three classification tiers:
> 1. **Default:** regex-only gate, zero cost, no API key needed.
> 2. **Interactive:** `/subscope-judge <surface-id>` uses your Claude Code subscription, free.
> 3. **Bulk LLM:** any OpenAI-compatible provider (Anthropic, OpenAI, Groq, OpenRouter, Together, local Ollama). ~$0.50/day at 5K posts.
>
> Want to enable the bulk-LLM tier? (yes / skip)

If yes, the user sets one env var (`LLM_API_KEY`, or legacy `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`). The base URL is auto-detected from the key prefix (`sk-ant-` → Anthropic /openai/v1, `sk-or-` → OpenRouter, `gsk_` → Groq, else OpenAI). For local Ollama or a custom endpoint, also set `LLM_BASE_URL`.

To lock the preference, write a minimal `~/.config/subscope/llm.json`:
```json
{"provider": "openai_compatible"}
```

Test the resolved config (this will also fail loudly if `LLM_BASE_URL` targets a private IP — the SSRF guard is intentional):
```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
from subscope.lib import classify
import json
print(json.dumps(classify.status(), indent=2))
"
```

If skip: write `{"provider": "disabled"}` to make the choice explicit.

### Step 2 — Targeting (route to /onboard)

Don't pick a preset directly here. Tell the user:

> Targeting works best with 3 quick questions — /subscope-onboard takes about 60 seconds and produces a config tuned to your specific work, not a generic lane. Recommended for almost everyone.
>
> If you really want the 30-second generic lane: type `preset` and I'll show the 4 options.

If user opts for `/subscope-onboard`: invoke it. The onboard skill handles preset escape internally (`/subscope-onboard preset`) for users who type `preset` mid-flow.

If user explicitly wants preset here in setup (rare), show the 4 options + copy chosen preset to `~/.config/subscope/`. But default is route to onboard.

Research backing (Phase 9.5 validation): generic preset alone produces 3/10 ICP-match per surface. The 3-question routing pushes it to 5-7/10. Don't deprive the user of that lift unless they explicitly opt out.

### Step 3 — Where do you want to see your daily surfaces?

Ask the user (this question is non-skippable, but every choice is valid):

> How do you want to see your daily surfaces?
>   a) **Inline table in Claude Code chat** (default, no setup, click links from chat)
>   b) **Notion database** (5-min setup, persistent triage across devices, queryable views)
>   c) **Both** (table rendered in chat AND synced to Notion)
>   d) **Skip** (engine prints JSON only — for piping to your own tools)

Translate the choice to the surface.yml config:

```bash
# Pick ONE based on user's answer
MODES="[table]"            # (a) default
MODES="[notion]"           # (b)
MODES="[table, notion]"    # (c)
MODES="[]"                 # (d)

cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_surface_config
modes: $MODES
default_render: table
EOF
```

If the user picked (b) or (c), continue to Step 3b (Notion setup) below. Otherwise skip Step 3b and continue to Step 4 (Obsidian).

### Step 3b — Notion DB hookup (only if Step 3 picked Notion)

If yes:
1. Ask if they have a Notion API key + DB ID, OR want to use an existing DB URL.
2. If they paste a Notion DB URL, extract the 32-char ID from it.
3. **Write the config file FIRST** (never pass `NOTION_API_KEY=$KEY` inline on the command line — the secret would land in /proc/<pid>/environ, ps output, and shell history). Use the atomic helper:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_notion_config
api_key: $NOTION_API_KEY
database_id: $NOTION_DB_ID
EOF
```

The helper writes to `~/.config/subscope/notion.yml` with `chmod 600` from the moment the file appears (atomic, no umask race).

4. Test with a dry-run migration that READS the file (no env-var leak):

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 engine/scripts/notion_admin.py migrate --dry-run
```

5. If dry-run succeeds, run the live migration to add Pattern/State/Fit properties + backfill existing rows:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 engine/scripts/notion_admin.py migrate
```

### Step 4 — Obsidian (optional)

Ask:

> Want weekly pulse digests written to your Obsidian vault? (yes / skip)

If yes:
1. Ask for the absolute vault path.
2. Ask for the pulse subfolder name (default: `subscope`).
3. Verify the path exists:

```bash
[ -d "$VAULT_PATH" ] && echo "OK" || echo "MISSING"
```

If OK, write `~/.config/subscope/obsidian.yml`:

```yaml
vault_path: /Users/you/Documents/MyVault
pulse_folder: subscope
```

### Step 5 — Dry-run validation

Now run the full pipeline once in dry mode to make sure everything works:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli status
```

Then a real, very-limited daily run:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli fetch-score --limit-per-sub 3 --daily-cap 3
```

Translate the output to a green-check checklist:

```
Setup complete:
  ✓ LLM provider: <provider>
  ✓ Preset: <name>
  ✓ Notion: <yes/skip>
  ✓ Obsidian: <yes/skip>
  ✓ Dry-run surfaced N posts (limit=3 per sub)

You're ready. Run /subscope-run for a real daily scan.
```

If any check fails, surface the failure clearly and suggest the fix.

## Resumability

Setup is idempotent. Re-running detects existing config and skips configured steps. To re-configure a single step, delete the relevant file:

| Step | File |
|---|---|
| LLM | `~/.config/subscope/llm.json` |
| Preset | `~/.config/subscope/subreddits.yml` + `keywords.yml` |
| Notion | `~/.config/subscope/notion.yml` |
| Obsidian | `~/.config/subscope/obsidian.yml` |
| DataForSEO | `~/.config/subscope/dataforseo.yml` |
| Firecrawl | `~/.config/subscope/firecrawl.yml` |

## Anti-patterns

- Don't continue with broken state. If a credential verification fails, ask the user to re-paste, don't just write the file and pretend.
- Don't write API keys to anywhere except `~/.config/subscope/*.json` with `chmod 600`. Never echo them in chat.
- Don't make decisions for the user. Every optional step gets a "yes/skip" prompt.
- If a preset YAML is malformed (user-edited), fall back to the b2b-saas-founder default and tell them.
