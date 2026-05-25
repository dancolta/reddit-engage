---
name: setup
description: Interactive onboarding wizard for subseek. Walks new users through Reddit OAuth (optional), LLM provider config (optional), industry preset selection, optional Notion DB hookup, optional Obsidian vault wiring, and a final dry-run validation. Conversational — pauses for each user decision. Triggers on "setup subseek", "/subseek:setup", "initialize subseek", "configure subseek", "onboard me", "first-time setup", or when daily run fails due to missing config.
allowed-tools: Bash, Read, Write, Edit
---

# /subseek:setup

Conversational setup wizard. Resumable — each step checks current state and skips if already configured.

## Goal

Get a new user from `/plugin install` → first working `/subseek:run` in under 10 minutes, with green checks at every step.

## Procedure

Greet the user briefly:

> Setting up subseek. I'll walk you through the OAuth, preset, and optional integrations. Each step is skippable if you don't need it — say "skip" anytime.

Then run the steps in order. Pause for input at each.

### Step 1 — Reddit OAuth (optional but recommended)

```bash
[ -f ~/.config/subseek/oauth.json ] && echo "EXISTS" || echo "MISSING"
```

If `EXISTS`: tell the user "Reddit OAuth already configured — moving on." Continue to Step 2.

If `MISSING`: ask:

> Reddit OAuth gives you 10x more API rate budget + enables postmortem reply tracking. Want to set it up now? (yes / skip)

If yes:
1. Tell them to open https://www.reddit.com/prefs/apps and click "create another app..." at the bottom.
2. Settings: name = `subseek`, type = **script** (critical), redirect URI = `http://localhost`.
3. Once they click "create app", ask for the **14-character string** under the app name (that's `client_id`).
4. Ask for the **secret** field.
5. Ask for their Reddit username.

Then write the credentials via the atomic-perms helper (creates the file with 0o600 from the moment it appears on disk — no umask race):

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_oauth
{
  "client_id":     "$CLIENT_ID",
  "client_secret": "$CLIENT_SECRET",
  "username":      "$USERNAME",
  "user_agent":    "subseek/0.1 by u/$USERNAME"
}
EOF
```

Verify:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
from subseek.lib import reddit_oauth
print('has_oauth:', reddit_oauth.has_oauth())
"
```

If `True`: ✓ proceed. If `False`: re-prompt for credentials, don't continue with broken state.

If user said "skip": tell them "Skipping OAuth — the daily run will work via public Reddit JSON, but you won't be able to use postmortem until you re-run setup."

### Step 2 — LLM provider (optional)

Tell the user:

> subseek has three classification tiers:
> 1. **Default:** regex-only gate, zero cost, no API key needed.
> 2. **Interactive:** `/subseek:judge <surface-id>` uses your Claude Code subscription, free.
> 3. **Bulk LLM:** any OpenAI-compatible provider (Anthropic, OpenAI, Groq, OpenRouter, Together, local Ollama). ~$0.50/day at 5K posts.
>
> Want to enable the bulk-LLM tier? (yes / skip)

If yes, the user sets one env var (`LLM_API_KEY`, or legacy `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`). The base URL is auto-detected from the key prefix (`sk-ant-` → Anthropic /openai/v1, `sk-or-` → OpenRouter, `gsk_` → Groq, else OpenAI). For local Ollama or a custom endpoint, also set `LLM_BASE_URL`.

To lock the preference, write a minimal `~/.config/subseek/llm.json`:
```json
{"provider": "openai_compatible"}
```

Test the resolved config (this will also fail loudly if `LLM_BASE_URL` targets a private IP — the SSRF guard is intentional):
```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
from subseek.lib import classify
import json
print(json.dumps(classify.status(), indent=2))
"
```

If skip: write `{"provider": "disabled"}` to make the choice explicit.

### Step 3 — Targeting (route to /onboard)

Don't pick a preset directly here. Tell the user:

> Targeting works best with 3 quick questions — /subseek:onboard takes about 60 seconds and produces a config tuned to your specific work, not a generic lane. Recommended for almost everyone.
>
> If you really want the 30-second generic lane: type `preset` and I'll show the 4 options.

If user opts for `/subseek:onboard`: invoke it. The onboard skill handles preset escape internally (`/subseek:onboard preset`) for users who type `preset` mid-flow.

If user explicitly wants preset here in setup (rare), show the 4 options + copy chosen preset to `~/.config/subseek/`. But default is route to onboard.

Research backing (Phase 9.5 validation): generic preset alone produces 3/10 ICP-match per surface. The 3-question routing pushes it to 5-7/10. Don't deprive the user of that lift unless they explicitly opt out.

### Step 4 — Notion (optional)

Ask:

> Want to sync surfaces to a Notion database for daily triage? (yes / skip)

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

The helper writes to `~/.config/subseek/notion.yml` with `chmod 600` from the moment the file appears (atomic, no umask race).

4. Test with a dry-run migration that READS the file (no env-var leak):

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 engine/scripts/notion_admin.py migrate --dry-run
```

5. If dry-run succeeds, run the live migration to add Pattern/State/Fit properties + backfill existing rows:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 engine/scripts/notion_admin.py migrate
```

### Step 5 — Obsidian (optional)

Ask:

> Want weekly pulse digests written to your Obsidian vault? (yes / skip)

If yes:
1. Ask for the absolute vault path.
2. Ask for the pulse subfolder name (default: `subseek`).
3. Verify the path exists:

```bash
[ -d "$VAULT_PATH" ] && echo "OK" || echo "MISSING"
```

If OK, write `~/.config/subseek/obsidian.yml`:

```yaml
vault_path: /Users/you/Documents/MyVault
pulse_folder: subseek
```

### Step 6 — Dry-run validation

Now run the full pipeline once in dry mode to make sure everything works:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subseek.cli status
```

Then a real, very-limited daily run:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subseek.cli fetch-score --limit-per-sub 3 --daily-cap 3
```

Translate the output to a green-check checklist:

```
Setup complete:
  ✓ OAuth: <yes/skip>
  ✓ LLM provider: <provider>
  ✓ Preset: <name>
  ✓ Notion: <yes/skip>
  ✓ Obsidian: <yes/skip>
  ✓ Dry-run surfaced N posts (limit=3 per sub)

You're ready. Run /subseek:run for a real daily scan.
```

If any check fails, surface the failure clearly and suggest the fix.

## Resumability

Setup is idempotent. Re-running detects existing config and skips configured steps. To re-configure a single step, delete the relevant file:

| Step | File |
|---|---|
| OAuth | `~/.config/subseek/oauth.json` |
| LLM | `~/.config/subseek/llm.json` |
| Preset | `~/.config/subseek/subreddits.yml` + `keywords.yml` |
| Notion | `~/.config/subseek/notion.yml` |
| Obsidian | `~/.config/subseek/obsidian.yml` |

## Anti-patterns

- Don't continue with broken state. If OAuth fails verification, ask the user to re-paste credentials — don't just write the file and pretend.
- Don't write API keys to anywhere except `~/.config/subseek/*.json` with `chmod 600`. Never echo them in chat.
- Don't make decisions for the user. Every optional step gets a "yes/skip" prompt.
- If a preset YAML is malformed (user-edited), fall back to the b2b-saas-founder default and tell them.
