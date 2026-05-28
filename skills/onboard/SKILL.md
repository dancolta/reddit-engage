---
name: subscope-onboard
description: Mandatory first-run setup for subscope. One conversation, three plain questions, one confirmation, optional integrations, first scan. Paste URLs, answer what-you-sell / who-buys-it / what's-the-pain, confirm the targeting card, pick integrations to connect (DataForSEO, Firecrawl, Notion, Slack, Obsidian), scan. No fast path. Every install passes through this. Triggers on "onboard", "/subscope-onboard", "set up subscope", "first time setup", "configure subscope", "get started with subscope", "install subscope".
allowed-tools: Bash, Read, Write, Edit, WebFetch
---

# /subscope-onboard

First-run setup. Seven turns, plain questions, one confirmation, optional integrations, first scan.

## Operating principles

1. **Ask, do not infer-and-confirm.** The user tells you what they sell, who buys it, what the pain is. Do not show an 8-field form for them to audit.
2. **One thing per turn.** Each chat message asks for exactly one input or shows exactly one summary.
3. **WebFetch silently in the background.** While the user answers turn 2, 3, 4 you are scraping their URLs. Never narrate this.
4. **Integrations are optional, not deferred.** T6 offers DataForSEO, Firecrawl, Notion, Slack, Obsidian as a single menu. Skip is a first-class choice.
5. **Verify creds inline.** If a paste fails, re-ask once. Twice failed, log and move on. The scan still runs.
6. **No filler.** No "welcome", "let's get started", "great", "perfect". No exclamation marks. No em dashes anywhere.

## Turn 1: collect URLs

Print verbatim:

```
SUBSCOPE ONBOARDING  ·  1 / 7
─────────────────────────────

I'll use these URLs to seed your Reddit targeting profile.
Paste the following:

→  Homepage URL
→  Case studies   (optional)
→  Blog / pricing (optional)

One per line.
```

Wait for input. Accept 1 to N URLs. Warn if more than 8.

Kick off WebFetch on all provided URLs **in parallel and in the background**. Extract:
- H1 / sub-headline / positioning line
- Linked case studies and pricing pages
- Visible competitor names ("alternative to X", "replace Y")
- Pain phrasing from problem statements
- Buyer titles quoted in case studies

Save raw fetch output to `~/.config/subscope/.onboard-draft.json` as you go.

**Background warmup.** As soon as the user pastes URLs, kick off the enrichment warmup in parallel with WebFetch so the DataForSEO competitor list + Firecrawl homepage scrape are cached by the time we reach T5 discovery. Silent no-op if DFS/Firecrawl keys are absent. Substitute `$HOMEPAGE_URL` with the first pasted URL:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
from subscope.lib import enrich, store
with store.connect() as conn:
    enrich.warmup_for_onboarding('$HOMEPAGE_URL', conn)
" &
```

Do not block on this. Do not show any status, recap, or summary. Move straight to T2.

## Turn 2: what do you sell

Print verbatim:

```
SUBSCOPE ONBOARDING  ·  2 / 7
─────────────────────────────

What do you sell?

→  One line is enough.
→  Example: "Reddit lead-gen for B2B SaaS."
```

Wait for input. Save to scratchpad. No echo, no confirmation. Move to T3.

## Turn 3: who buys it

Print verbatim:

```
SUBSCOPE ONBOARDING  ·  3 / 7
─────────────────────────────

Who buys it?

→  A job title works.
→  Example: "Head of Ops at a SaaS startup."
→  Or just: "RevOps leads."
```

Wait for input. Save to scratchpad. Move to T4.

## Turn 4: what is the pain

Print verbatim:

```
SUBSCOPE ONBOARDING  ·  4 / 7
─────────────────────────────

What do they complain about right before they find you?

→  A real customer quote is gold.
→  Paraphrase is fine.
```

Wait for input. Save to scratchpad.

**Run live subreddit discovery before T5.** This calls the engine to find subs where the user's pain phrasing is actively discussed on Reddit. Replaces the old templatish archetype-map seed.

Pipe the answers JSON via stdin so apostrophes / quotes in user input don't break shell quoting. Build the JSON in a temp variable (Claude assembles it from the scratchpad), then pipe it in:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && python3 -c "
import json
print(json.dumps({
    'what_offering': '''<T2_VALUE>''',
    'who_to_reach':  '''<T3_VALUE>''',
    'pain_quote':    '''<T4_VALUE>''',
}))" | PYTHONPATH=engine python3 -m subscope.cli discover \
  --homepage "$HOMEPAGE_URL" \
  --answers-json -
```

Substitute `<T2_VALUE>`, `<T3_VALUE>`, `<T4_VALUE>` with the exact answers from the scratchpad. The triple-quoted strings handle embedded apostrophes safely; `--answers-json -` reads the piped JSON from stdin.

The engine returns JSON with: `subs` (ranked list with `name`, `score`, `why`, `thread_count`), `needs_clarification` (bool), `clarifier_prompt` (string when clarification needed), `discovery_unreachable` (bool), `source_mix`.

**If `needs_clarification` is true:** render T4.5 sub-turn with the engine's `clarifier_prompt` verbatim, wait for the user's reply, then re-run the same `discover` command with an added `--vertical "<user reply>"` flag. Use that second result for T5 regardless of clarification flag (we only ask once).

**If `discovery_unreachable` is true:** the T5 card will show a one-line warning under the Subreddits row (see T5 card shape below).

## Turn 5: confirm the scan card

Build the card from WebFetch output + the three answers + the discovery result. Render exactly this shape:

```
SUBSCOPE ONBOARDING  ·  5 / 7
─────────────────────────────

Here's what I'm scanning for. Confirm or correct.

→  You sell       <one-liner from T2>
→  Buyers         <titles from T3>
→  Pain pattern   <theme from T4>
→  Subreddits     r/<sub>   (<thread_count> threads · "<top_query>")
                  r/<sub>   (<thread_count> threads · "<top_query>")
                  ... up to 8 entries from discover.subs
→  Competitors    <up to 6, inferred from WebFetch + DFS cache>

Reply "go" to confirm, or tell me what to fix.
```

If `discovery_unreachable` is true, replace the Subreddits row with archetype-map output and append `(discovery thin, generic fallback)` to that row. If `discovery_unreachable` is false but the list is short (1-4 subs), still render what we have; do not pad with generic founder subs.

If the user replies with edits, apply silently and re-render the card. Do NOT re-render after a "go".

When the user says "go", proceed to T6.

## Turn 6: connect integrations

Print verbatim:

```
SUBSCOPE ONBOARDING  ·  6 / 7
─────────────────────────────

Connect anything before the scan?

→  dataforseo   Competitor keywords + search intent
→  firecrawl    Deeper URL crawling
→  notion       Daily digest in a Notion database
→  slack        Digest to a channel
→  obsidian     Weekly pulse in your vault

Reply with the ones you want, space-separated. Or "skip".
Example: "dataforseo notion" or "skip".
```

If user replies "skip", jump straight to T7. No marker file needed.

Otherwise parse the picks. For each picked integration, run its micro-prompt in order. Each one is its own short turn. Failed verification = re-ask once. Failed twice = log it, continue with the next pick.

**Per-sub-prompt skip path.** If at any sub-prompt the user replies "skip" (case-insensitive), drop that integration immediately, write a marker (`touch ~/.config/subscope/.<name>-skipped`), and move to the next picked integration without re-asking. If it was the last pick, jump straight to T7. Do not re-render the menu, do not ask for confirmation.

### dataforseo

Probe first: check session for any `mcp__dataforseo__*` tool. If present, skip the credential prompt and mark ready.

Otherwise print verbatim:

```
SUBSCOPE ONBOARDING  ·  6 / 7
─────────────────────────────
DataForSEO  (optional)

Get credentials at:
https://app.dataforseo.com/api-access

→  API password lives in the API Access tab.
→  Not your dashboard login.

Paste here:
login api_password

Full MCP toolset (optional):
claude mcp add dataforseo -e DATAFORSEO_USERNAME=<login> -e DATAFORSEO_PASSWORD=<pw> -- npx -y dataforseo-mcp-server

Or reply "skip".
```

On paste:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_dataforseo_config
login: $DFS_LOGIN
password: $DFS_PASSWORD
EOF
```

Verify with a single live call:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import base64, json, urllib.request, yaml
from pathlib import Path
cfg = yaml.safe_load(Path.home().joinpath('.config/subscope/dataforseo.yml').read_text())
auth = base64.b64encode(f\"{cfg['login']}:{cfg['password']}\".encode()).decode()
req = urllib.request.Request('https://api.dataforseo.com/v3/appendix/user_data', headers={'Authorization': f'Basic {auth}'})
try:
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    print('dataforseo: ok' if resp.get('status_code') == 20000 else f\"dataforseo: error {resp.get('status_message')}\")
except Exception as e:
    print(f'dataforseo: error {e}')
"
```

### firecrawl

Probe for `seo-firecrawl` skill or `FIRECRAWL_API_KEY` env var. If present, mark ready.

Otherwise print verbatim:

```
SUBSCOPE ONBOARDING  ·  6 / 7
─────────────────────────────
Firecrawl  (optional)

Paste your Firecrawl API key (starts with fc-).

→  Get one at: https://www.firecrawl.dev/app/api-keys

Full MCP (optional):
claude mcp add firecrawl -e FIRECRAWL_API_KEY=<key> -- npx -y firecrawl-mcp

Or reply "skip".
```

On paste:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_firecrawl_config
api_key: $FIRECRAWL_API_KEY
EOF
```

Verify with a small scrape:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json, urllib.request, yaml
from pathlib import Path
cfg = yaml.safe_load(Path.home().joinpath('.config/subscope/firecrawl.yml').read_text())
req = urllib.request.Request(
    'https://api.firecrawl.dev/v1/scrape',
    data=json.dumps({'url': 'https://example.com', 'formats': ['markdown']}).encode(),
    headers={'Authorization': f\"Bearer {cfg['api_key']}\", 'Content-Type': 'application/json'},
)
try:
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    print('firecrawl: ok' if resp.get('success') else f\"firecrawl: error {resp}\")
except Exception as e:
    print(f'firecrawl: error {e}')
"
```

### notion

Probe for any `mcp__*notion*` tool. If present, skip the install step and jump to the database-name question.

Otherwise print verbatim:

```
SUBSCOPE ONBOARDING  ·  6 / 7
─────────────────────────────
Notion  (optional)

Install the official MCP, then authorize in your browser:
claude mcp add --transport http notion https://mcp.notion.com/mcp

Once OAuth completes, reply with the database name to write to.

Or reply "skip".
```

On reply with a database name, write the config:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_notion_config
mode: mcp
database_name: $NOTION_DB_NAME
EOF
```

The engine resolves the database ID at runtime via the MCP `search` tool. No manual ID needed.

### slack

Print verbatim:

```
SUBSCOPE ONBOARDING  ·  6 / 7
─────────────────────────────
Slack  (optional)

Paste your Slack webhook URL.

→  Must start with https://hooks.slack.com/

Or reply "skip".
```

SSRF guard rejects anything that isn't `https://hooks.slack.com/...`. On valid paste:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_slack_config
webhook_url: $SLACK_WEBHOOK_URL
EOF
```

### obsidian

Print verbatim:

```
SUBSCOPE ONBOARDING  ·  6 / 7
─────────────────────────────
Obsidian  (optional)

Paste your absolute Obsidian vault path.

Or reply "skip".
```

Verify the path exists:

```bash
[ -d "$VAULT_PATH" ] && echo "ok" || echo "missing"
```

If ok, write `~/.config/subscope/obsidian.yml`:

```yaml
vault_path: /absolute/path/to/vault
pulse_folder: subscope
```

### After all picks

Write the surface.yml with the chosen modes (always include `table` so chat output is on):

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m scripts.write_surface_config <<EOF
modes: [table, $CHOSEN_DESTINATIONS]
default_render: table
EOF
```

## Turn 7: write configs + run the first scan

Merge the targeting payload (scratchpad WebFetch + T2/T3/T4/T5 confirmed values) and write the YAML files:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json
from subscope.lib import profile_synth
payload = $PAYLOAD_JSON
files = profile_synth.to_yaml_files(payload)
written = profile_synth.write_to_xdg(files, backup=True)
for name, path in written.items():
    print(f'  wrote: {path}')
profile_synth.clear_draft('.onboard-draft.json')
"
```

Validate via `profile_synth.validate_synthesis(payload, weights_cfg)`. If validation fails, surface the failures and ask for a one-line correction.

Warm the enrichment cache once more as insurance. The same warmup fired in background at T1, but if the user finished onboarding faster than the API calls, or if they configured DFS/Firecrawl for the first time at T6, this second call fills the gap. Cached payloads short-circuit, so cost stays zero when T1's warmup already populated everything. Substitute `$HOMEPAGE_URL` with the URL the user pasted at T1:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json
from subscope.lib import enrich, store
with store.connect() as conn:
    result = enrich.warmup_for_onboarding('$HOMEPAGE_URL', conn)
print(json.dumps(result))
"
```

The output is informational only (showing which providers fired and what was cached). Do not surface it to the user unless both calls were attempted and both reported a fail-open `skipped_reason`, in which case mention once: "DataForSEO and Firecrawl could not reach their APIs. Cache will fill on the next successful onboarding."

Run the first scan:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli fetch-score
```

Render the engine's `inline_table` in chat. If destinations include Notion/Slack/Obsidian, the engine handles those automatically.

After the scan output, print verbatim:

```
SUBSCOPE ONBOARDING  ·  7 / 7
─────────────────────────────
Done. Configs written to ~/.config/subscope/.

→  /subscope-run        Fresh scan
→  /subscope-tune       Sharpen the ranker after a few scans
→  /subscope-profile    Refine a single section
```

## Resumability

On invocation, check for `~/.config/subscope/.onboard-draft.json`:

- Present AND <24 hours old → ask: `Found a draft from earlier. Resume, or start fresh?`
- Present AND >24 hours old → delete, start fresh
- Absent → start fresh

The scratchpad records: URLs, WebFetch output, T2/T3/T4 answers, T5 confirmation, T6 picks. Resume lands at the unanswered turn.

The scratchpad is cleared on successful T7 config write.

## Anti-patterns

- **No exclamation marks.** Anywhere.
- **No em dashes.** Anywhere. Use commas, periods, or restructure.
- **No "welcome" / "let's get started" / "great" / "perfect".** Operational tone only.
- **No confidence bars, no progress bars.** Step counter in the header (`N / 7`) is the only allowed pacing signal. The user sees titled prompts, bulleted hints, and one summary card.
- **No 8-field confirmation form.** The three plain questions replace it.
- **No status recap lines.** WebFetch runs silent. The user sees questions, not engine narration.
- **Never re-render the T5 card after "go".** Once locked, move on.
- **Never block on a missing optional integration.** Failed twice = log, continue. The scan still runs.

## What's NOT in this skill

- LLM provider configuration. Power-user concern, kept in `/subscope-setup --llm`.
- Per-section refinement. After onboarding, `/subscope-profile` handles single-section deep dives.
- Preset shortcut. There is no preset shortcut. Every install passes through the full flow.
