---
name: setup
description: Interactive onboarding wizard for reddit-engage. Walks new users through Reddit OAuth (optional), LLM provider config (optional), industry preset selection, optional Notion DB hookup, optional Obsidian vault wiring, and a final dry-run validation. Conversational — pauses for each user decision. Triggers on "setup reddit-engage", "/reddit-engage:setup", "initialize reddit-engage", "configure reddit-engage", "onboard me", "first-time setup", or when daily run fails due to missing config.
allowed-tools: Bash, Read, Write, Edit
---

# /reddit-engage:setup

Conversational setup wizard. Resumable — each step checks current state and skips if already configured.

## Goal

Get a new user from `/plugin install` → first working `/reddit-engage:run` in under 10 minutes, with green checks at every step.

## Procedure

Greet the user briefly:

> Setting up reddit-engage. I'll walk you through the OAuth, preset, and optional integrations. Each step is skippable if you don't need it — say "skip" anytime.

Then run the steps in order. Pause for input at each.

### Step 1 — Reddit OAuth (optional but recommended)

```bash
[ -f ~/.config/reddit-engage/oauth.json ] && echo "EXISTS" || echo "MISSING"
```

If `EXISTS`: tell the user "Reddit OAuth already configured — moving on." Continue to Step 2.

If `MISSING`: ask:

> Reddit OAuth gives you 10x more API rate budget + enables postmortem reply tracking. Want to set it up now? (yes / skip)

If yes:
1. Tell them to open https://www.reddit.com/prefs/apps and click "create another app..." at the bottom.
2. Settings: name = `reddit-engage`, type = **script** (critical), redirect URI = `http://localhost`.
3. Once they click "create app", ask for the **14-character string** under the app name (that's `client_id`).
4. Ask for the **secret** field.
5. Ask for their Reddit username.

Then write:

```bash
mkdir -p ~/.config/reddit-engage
cat > ~/.config/reddit-engage/oauth.json <<EOF
{
  "client_id":     "$CLIENT_ID",
  "client_secret": "$CLIENT_SECRET",
  "username":      "$USERNAME",
  "user_agent":    "reddit-engage/0.1 by /u/$USERNAME"
}
EOF
chmod 600 ~/.config/reddit-engage/oauth.json
```

Verify:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
from reddit_engage.lib import reddit_oauth
print('has_oauth:', reddit_oauth.has_oauth())
"
```

If `True`: ✓ proceed. If `False`: re-prompt for credentials, don't continue with broken state.

If user said "skip": tell them "Skipping OAuth — the daily run will work via public Reddit JSON, but you won't be able to use postmortem until you re-run setup."

### Step 2 — LLM provider (optional)

Tell the user:

> reddit-engage has three classification tiers:
> 1. **Default:** regex-only gate, zero cost, no API key needed.
> 2. **Interactive:** `/reddit-engage:judge <surface-id>` uses your Claude Code subscription, free.
> 3. **Bulk LLM:** requires ANTHROPIC_API_KEY; ~$0.50/day at 5K posts.
>
> Want to enable the bulk-LLM tier? (yes / skip)

If yes, ask if they want to set it now or just confirm `$ANTHROPIC_API_KEY` is already in their shell env. Write `~/.config/reddit-engage/llm.json` with `{"provider": "anthropic_api"}` to lock in the preference. Test:

```bash
PYTHONPATH=engine python3 -c "
from reddit_engage.lib import classify
import json
print(json.dumps(classify.status(), indent=2))
"
```

If skip: write `{"provider": "disabled"}` to make the choice explicit.

### Step 3 — Targeting (route to /onboard)

Don't pick a preset directly here. Tell the user:

> Targeting works best with 3 quick questions — /reddit-engage:onboard takes about 60 seconds and produces a config tuned to your specific work, not a generic lane. Recommended for almost everyone.
>
> If you really want the 30-second generic lane: type `preset` and I'll show the 4 options.

If user opts for `/reddit-engage:onboard`: invoke it. The onboard skill handles preset escape internally (`/reddit-engage:onboard preset`) for users who type `preset` mid-flow.

If user explicitly wants preset here in setup (rare), show the 4 options + copy chosen preset to `~/.config/reddit-engage/`. But default is route to onboard.

Research backing (Phase 9.5 validation): generic preset alone produces 3/10 ICP-match per surface. The 3-question routing pushes it to 5-7/10. Don't deprive the user of that lift unless they explicitly opt out.

### Step 4 — Notion (optional)

Ask:

> Want to sync surfaces to a Notion database for daily triage? (yes / skip)

If yes:
1. Ask if they have a Notion API key + DB ID, OR want to use an existing DB URL.
2. If they paste a Notion DB URL, extract the 32-char ID from it.
3. Test write with a fixture row:

```bash
NOTION_API_KEY=$KEY PYTHONPATH=engine python3 engine/scripts/notion_migrate.py --database-id $DB_ID --dry-run
```

If dry-run succeeds, write `~/.config/reddit-engage/notion.yml`:

```yaml
api_key: <secret_xxx>
database_id: <32-char>
```

`chmod 600` it.

Then run the live migration to add Pattern/State/Fit properties + backfill existing rows.

### Step 5 — Obsidian (optional)

Ask:

> Want weekly pulse digests written to your Obsidian vault? (yes / skip)

If yes:
1. Ask for the absolute vault path.
2. Ask for the pulse subfolder name (default: `reddit-engage`).
3. Verify the path exists:

```bash
[ -d "$VAULT_PATH" ] && echo "OK" || echo "MISSING"
```

If OK, write `~/.config/reddit-engage/obsidian.yml`:

```yaml
vault_path: /Users/you/Documents/MyVault
pulse_folder: reddit-engage
```

### Step 6 — Dry-run validation

Now run the full pipeline once in dry mode to make sure everything works:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m reddit_engage.cli status
```

Then a real, very-limited daily run:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m reddit_engage.cli fetch-score --limit-per-sub 3 --daily-cap 3
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

You're ready. Run /reddit-engage:run for a real daily scan.
```

If any check fails, surface the failure clearly and suggest the fix.

## Resumability

Setup is idempotent. Re-running detects existing config and skips configured steps. To re-configure a single step, delete the relevant file:

| Step | File |
|---|---|
| OAuth | `~/.config/reddit-engage/oauth.json` |
| LLM | `~/.config/reddit-engage/llm.json` |
| Preset | `~/.config/reddit-engage/subreddits.yml` + `keywords.yml` |
| Notion | `~/.config/reddit-engage/notion.yml` |
| Obsidian | `~/.config/reddit-engage/obsidian.yml` |

## Anti-patterns

- Don't continue with broken state. If OAuth fails verification, ask the user to re-paste credentials — don't just write the file and pretend.
- Don't write API keys to anywhere except `~/.config/reddit-engage/*.json` with `chmod 600`. Never echo them in chat.
- Don't make decisions for the user. Every optional step gets a "yes/skip" prompt.
- If a preset YAML is malformed (user-edited), fall back to the b2b-saas-founder default and tell them.
