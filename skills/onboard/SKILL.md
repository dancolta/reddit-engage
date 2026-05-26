---
name: onboard
description: Mandatory first-run setup for subscope. One conversation, one input, one combined questionnaire, one scan. Paste 2-3 URLs (homepage + case studies or blog posts), confirm or refine the inferred targeting in a single combined card, choose Reddit access mode (skip OAuth or connect), pick destinations (Notion, Slack, Obsidian, or chat-only), and the first scan runs automatically. Optionally pulls deeper research via DataForSEO or Firecrawl when the user opts in. No fast path. Every install passes through this. Triggers on "onboard", "/subscope:onboard", "set up subscope", "first time setup", "configure subscope", "get started with subscope", "install subscope".
allowed-tools: Bash, Read, Write, Edit, WebFetch
---

# /subscope:onboard

Mandatory first-run setup. One conversation, one combined questionnaire, one scan.

You will not see a single output card until all the questions are answered. The plugin only works if your targeting is sharp, so the only path is the sharp one.

## Operating principles

1. **Infer aggressively from URLs.** Never ask what URLs can answer.
2. **Gather everything before showing anything.** No intermediate review cards, no big inferred-targeting dumps mid-flow. The user sees ONE combined questionnaire when all inference + integration setup is complete.
3. **Single-turn combined questionnaire.** All 8 lock fields pre-filled with confidence labels, rendered in one card. User edits inline or says "looks good" in one turn.
4. **No shortcut, no fast path.** Every user passes through all 8 steps.
5. **Never block on OAuth.** Public Reddit JSON is the default fallback. OAuth is an opt-in upgrade, asked once.
6. **Optional integrations are user-gated and credential-verified.** Ask the user once. If MCP is missing, ask one concise credential prompt. Verify the credentials work before continuing.
7. **Destinations always asked.** Notion, Slack, Obsidian are multi-select at onboard.
8. **No filler.** No "let's get started", "welcome", "great", "perfect". No exclamation marks. No em dashes anywhere.

## Procedure

### Step 1: Greet + collect URLs

Print verbatim:

```
Drop your homepage + 2-3 case study or blog URLs (newline or space separated).

I'll come back with one combined questionnaire covering ICP, displaced tools,
buyer titles, subreddits, keywords, and example pains. You confirm or refine
in one reply. Then the first scan runs.
```

Wait for input. Accept 1 to N URLs (no hard cap, but warn if more than 8).

### Step 2: Enrichment opt-in + credential setup

Ask once:

```
Want deeper research sources for sharper picks?
  - DataForSEO: competitor domains + ranked keywords from your URLs
  - Firecrawl: deeper crawl than basic WebFetch (catches linked case studies)
  - Reddit warm-scan: live preview against archetype-seeded subs (needs OAuth, auto-skipped otherwise)

[yes / lean]
```

If `lean`: skip credential probing entirely. Use WebFetch only in Step 3.

If `yes`: probe each in this order. For each missing source, ask ONE concise credential prompt, then verify before continuing.

#### DataForSEO

Probe: check if any tool matching `mcp__dataforseo__*` is available in this session.

- If available: mark ready.
- If missing: ask exactly:

```
DataForSEO MCP not detected. Paste DataForSEO credentials as login:password (one line) or type skip.
```

If user pastes credentials, persist + verify:

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

If verification fails, surface the error, re-ask credentials once. If it fails twice, treat DataForSEO as missing and continue.

#### Firecrawl

Probe: check for the `seo-firecrawl` skill OR a `FIRECRAWL_API_KEY` env var.

- If available: mark ready.
- If missing: ask exactly:

```
Firecrawl not detected. Paste FIRECRAWL_API_KEY (fc-...) or type skip.
```

If user pastes a key, persist + verify:

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

If verification fails, re-ask once. Then continue without Firecrawl.

#### Reddit warm-scan

Check for OAuth:

```bash
[ -f ~/.config/subscope/reddit_oauth.yml ] && echo "oauth: present" || echo "oauth: absent"
```

- If OAuth present: mark warm-scan ready.
- If OAuth absent: mark warm-scan as auto-skip (will run later after Step 6 OAuth choice if user picks B).

#### Report enrichment status (one line)

```
DataForSEO: <ready / skipped>
Firecrawl:  <ready / skipped>
Warm-scan:  <ready / auto-skip (no OAuth)>
```

Then proceed silently to Step 3. Missing sources are non-fatal.

### Step 3: Silent parallel enrich

Fire all available sources in parallel. Capture results into a scratchpad. Do NOT render any card to the user during this step. One-line status only if a source fails ("dataforseo: empty result, skipping").

**Always run:** WebFetch each URL provided in Step 1. Extract:
- H1 / sub-headline / positioning line
- Linked case studies / pricing / customer logos
- Visible competitor names ("alternative to X", "replace Y")
- Pain language (problem statements, "before/after" phrasing)
- Buyer titles quoted in case studies ("Head of Ops at...", "RevOps Lead at...")

**If DataForSEO is ready:** call these in parallel:
- `mcp__dataforseo__dataforseo_labs_google_competitors_domain` on the homepage domain
- `mcp__dataforseo__dataforseo_labs_google_ranked_keywords` on the same domain
- `mcp__dataforseo__dataforseo_labs_search_intent` on the top 5 ranked keywords (only if ranked_keywords returned results)

**If Firecrawl is ready:** crawl the homepage one layer deeper to catch case study or pricing links not in the user's paste.

**Warm-scan:** skip in Step 3. It runs (if OAuth is present) only after Step 6 OAuth selection. Reason: public Reddit JSON without OAuth rate-limits within seconds and contaminates the flow.

For each inferred field, attach a **confidence score** (high / medium / low):
- High: explicit, verbatim from URLs or DataForSEO output
- Medium: inferred from adjacent signals (case study quotes, ranked keyword clusters)
- Low: synthesized or guessed because URLs were sparse

Save everything to `~/.config/subscope/.onboard-draft.json` for resumability.

### Step 4: Single combined questionnaire (the only card)

Render ONE card with the full inferred targeting plus all 8 lock fields pre-filled. User confirms or edits inline in ONE reply. Use this exact template:

```
─── Your subscope targeting ───

Confirm or edit each field below. Reply with edits inline (one per line,
field name + new value) or type "looks good" to lock in everything.

1 / 8  what you sell                                     [conf: <h/m/l>]
       <one-sentence positioning, derived from H1 + sub-headline>

2 / 8  your last 3 customers                             [conf: <h/m/l>]
       <title at company, what they replaced>
       <title at company>
       <title at company>

3 / 8  the pain quote (load-bearing)                     [conf: low]
       <paraphrased pain statement from URL content>
       Paste a verbatim customer quote if you have one. Otherwise leave as-is.

4 / 8  where they vent                                   [conf: <h/m/l>]
       <top 3 subreddits / venues>

5 / 8  competitors / tools you displace                  [conf: <h/m/l>]
       <up to 12, grouped by category>

6 / 8  how they describe themselves                      [conf: <h/m/l>]
       <up to 4 buyer titles>

7 / 8  subreddit tiers                                   [conf: <h/m/l>]
       Tier 1 (daily):       <3-5 subs>
       Tier 2 (opportunistic): <3-8 subs>

8 / 8  your own content URLs (optional)
       <skip by default; paste 3-5 URLs if you want them in blog-map.yml>

Candidate keywords (auto-derived, you can override in /subscope:profile later):
  Shared:   <5-9 phrases>
  Operator: <5-10 phrases>
  Builder:  <5-8 phrases>

Example pains (synthesized from URL content):
  1. <pain post 1>
  2. <pain post 2>
  3. <pain post 3>

─── Reply with edits like "5: drop Pipedrive, add Outreach.io" or "looks good" ───
```

Accept inline edits in any format. Apply edits silently. Show ONE small diff confirmation (only the changed fields, max 5 lines) before proceeding to Step 5. Do NOT re-render the full card.

Merge final answers into the draft payload:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json
from subscope.lib import profile_synth, store
draft = store.xdg_config_dir() / '.onboard-draft.json'
existing = json.load(draft.open()) if draft.exists() else {}
existing['locks'] = $LOCKS_DICT
draft.write_text(json.dumps(existing, indent=2))
"
```

Validate via `profile_synth.validate_synthesis(payload, weights_cfg)`. If validation fails, surface the failures and ask for inline correction (still one reply).

### Step 5: Reddit access mode

Ask:

```
Reddit access:
  [A] Skip OAuth, scan via public JSON (works now, ~60 req/min, no rate-budget cushion)
  [B] Connect Reddit OAuth (10x rate limit, enables postmortem tracking + warm-scan)

Type A or B.
```

If `A`: write a marker so the engine knows the user explicitly opted out:

```bash
mkdir -p ~/.config/subscope
touch ~/.config/subscope/.oauth-skipped
```

If `B`: walk through the OAuth flow:
1. Tell user to open https://www.reddit.com/prefs/apps and click "create another app" at the bottom
2. Settings: name = `subscope`, type = **script** (critical), redirect URI = `http://localhost`
3. Capture client_id (14 chars under app name), secret, username
4. Write via the atomic helper:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_oauth
{
  "client_id":     "$CLIENT_ID",
  "client_secret": "$CLIENT_SECRET",
  "username":      "$USERNAME",
  "user_agent":    "subscope/0.1 by u/$USERNAME"
}
EOF
```

Verify:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
from subscope.lib import reddit
print('has_oauth:', reddit.has_oauth())
"
```

If verification fails, re-prompt once. If it fails twice, fall back to option A and tell the user they can retry later with `/subscope:onboard --reauth`.

### Step 6: Destinations (always ask, multi-select)

```
Where should results land? (multi-select, type letters separated by spaces)

  [t] Chat table (default, no setup)
  [n] Notion database (paste API token + DB ID)
  [s] Slack channel (paste webhook URL)
  [o] Obsidian vault (paste vault path)

Examples: "t" / "t n" / "t s o" / "n s"
```

Default if user just hits enter: `t` only.

For each selected destination, run the corresponding setup:

**Chat (`t`)**: write surface.yml so /run knows:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_surface_config
modes: [table]
default_render: table
EOF
```

If multiple destinations are picked, change `modes` to include all of them, e.g. `[table, notion, slack, obsidian]`.

**Notion (`n`)**: ask for:
1. Notion API key (sk-...). If they don't have one, point to https://www.notion.so/profile/integrations.
2. Database ID (32 chars) OR full DB URL (extract ID from URL).

Write via atomic helper:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_notion_config
api_key: $NOTION_API_KEY
database_id: $NOTION_DB_ID
EOF
```

Dry-run migration:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 engine/scripts/notion_admin.py migrate --dry-run
```

If dry-run succeeds, run live migration:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 engine/scripts/notion_admin.py migrate
```

**Slack (`s`)**: ask for the webhook URL. SSRF guard rejects anything that isn't `https://hooks.slack.com/...`.

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_slack_config
webhook_url: $SLACK_WEBHOOK_URL
EOF
```

**Obsidian (`o`)**: ask for absolute vault path + optional pulse subfolder (default `subscope`).

```bash
[ -d "$VAULT_PATH" ] && echo "OK" || echo "MISSING"
```

If OK, write `~/.config/subscope/obsidian.yml`:

```yaml
vault_path: /absolute/path/to/vault
pulse_folder: subscope
```

### Step 7: Write the targeting config + auto-run first scan

Take the merged payload (Step 3 inference + Step 4 locks) and write the four YAML files:

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

Then chain directly into the first scan. If warm-scan was deferred and OAuth is now present, the same fetch-score call covers it:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli fetch-score
```

Render the engine's `inline_table` in chat. If destinations include Notion/Slack/Obsidian, the engine handles those automatically per surface.yml.

### Step 8: Next-action footer (locked)

After the scan output, print verbatim:

```
Onboarding complete. The four config files live at ~/.config/subscope/.

Run /subscope:run anytime for a fresh scan.
Run /subscope:tune after a few scans to sharpen the ranker.
Run /subscope:profile to refine a single section (competitor anchor, pain
language, subreddit tiers) without redoing the whole flow.
```

## Resumability

Check for `~/.config/subscope/.onboard-draft.json` on invocation:

- Present AND <24 hours old → ask: *"Found a draft from earlier. Resume, or start fresh?"*
- Present AND >24 hours old → delete and start fresh
- Absent → start fresh

The scratchpad records inference output + whether the combined questionnaire was answered. Resume lands at the unanswered step.

The scratchpad is cleared on successful Step 7 write.

## Re-auth path

If user runs `/subscope:onboard --reauth`, skip to Step 5 directly. Used by people who initially picked option A (skip OAuth) and want to upgrade later.

```bash
if [ "$1" = "--reauth" ]; then
  rm -f ~/.config/subscope/.oauth-skipped
  # jump to Step 5
fi
```

## Anti-patterns

- **No exclamation marks.** Anywhere.
- **No em dashes.** Anywhere. Use commas, periods, or restructure.
- **No "welcome" / "let's get started" / "great" / "perfect".** Operational tone only.
- **No intermediate output cards.** The user sees ONE card in Step 4. Steps 1-3 are inputs and silent inference. Steps 5-6 are short questions, not cards. The combined questionnaire is the only big card before the final scan.
- **Never render the full inferred targeting twice.** If the user edits a field, show ONLY the diff. Never re-print the full questionnaire.
- **Never present a blank question.** Step 4 fields always pre-fill from inference. If inference is empty, say so explicitly and mark `confidence: low`.
- **Never write configs without passing through Step 4.** The combined questionnaire is the mandatory gate.
- **Never block on a missing optional integration.** If DataForSEO/Firecrawl creds fail twice, treat as missing and continue. Warm-scan is auto-skipped when OAuth is absent — never run it against public JSON during onboarding.

## What's NOT in this skill

- LLM provider configuration. That's a power-user concern, kept in `/subscope:setup --llm`.
- Per-section refinement. After onboarding, `/subscope:profile` handles single-section deep dives.
- Preset shortcut. There is no preset shortcut. Every install passes through the full flow.
