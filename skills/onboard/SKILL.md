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

Pipe the answers JSON via stdin so apostrophes / quotes in user input don't break shell quoting. Pass any competitor brands you found in the WebFetch (T1) via `--competitors` as a comma-separated list. These are critical: they generate "replacing X" and "X alternative" queries which dramatically improve sub relevance for Reddit discovery.

```bash
cd "$CLAUDE_PLUGIN_ROOT" && python3 -c "
import json
print(json.dumps({
    'what_offering': '''<T2_VALUE>''',
    'who_to_reach':  '''<T3_VALUE>''',
    'pain_quote':    '''<T4_VALUE>''',
}))" | PYTHONPATH=engine python3 -m subscope.cli discover \
  --homepage "$HOMEPAGE_URL" \
  --competitors "<COMMA_SEPARATED_COMPETITOR_BRANDS>" \
  --answers-json -
```

Substitute:
- `<T2_VALUE>`, `<T3_VALUE>`, `<T4_VALUE>` with the exact answers from the scratchpad
- `<COMMA_SEPARATED_COMPETITOR_BRANDS>` with whatever brands Claude extracted from the user's homepage/case-studies during T1 WebFetch (e.g. `"Zapier,n8n,Make,Bill.com,Apollo.io"`). If no brands were found, pass an empty string.

The triple-quoted strings handle embedded apostrophes safely; `--answers-json -` reads the piped JSON from stdin.

The engine returns JSON with these fields:
- `subs`: ranked candidate subs (recall stage). Each entry has `name`, `confidence` (0-100), `relevance_path` ("competitor"/"noun"), `recent_thread_url`, `recent_thread_title`, `recent_thread_iso` (absolute UTC timestamp), `recent_thread_reason` (plain-English why-chosen line), `recent_thread_age_h`, `freshness_unverified`, `why`, `thread_count`, `sources`, `noise_downranked`
- `dropped_subs`: subs that failed Phase B (reasons: `no_fresh_buyer_activity`, `below_floor`, `validation_unreachable`)
- `needs_clarification`, `clarifier_reason` (`stale_only`/`thin_results`/`no_candidates`), `clarifier_prompt`, `discovery_unreachable`, `phase_a_count`, `phase_b_timed_out`

**Freshness guarantee:** every sub in `subs` has a buyer-intent thread in the last 7 days, with an absolute timestamp + clickable link the user can verify.

**MANDATORY relevance review (this is the precision step, do not skip).** The engine is the recall stage: it surfaces every sub with a fresh thread that passed the deterministic buyer-intent gate. The gate is lexical, so it cannot tell a real software buyer from a same-shaped non-buyer. Before rendering the T5 card, review each candidate sub's `recent_thread_reason` + `recent_thread_title` (open `recent_thread_url` if unsure) and DROP any where the evidence thread is not a genuine prospect for THIS user's product. Apply these rules:

- KEEP: someone comparing or shopping tools ("Buzzsprout vs Acast", "best tool for X", "alternative to Clio"), someone venting about a named competitor's price/UX, someone explicitly asking which software to buy.
- DROP: career / "should I switch professions" questions (e.g. "Software Engineering vs Dentistry" for a dental-software seller, "Medical billing vs Coding for analytics"), self-promotion ("just published my new Substack"), generic life/work venting that merely contains a product word, news/changelog reposts about a competitor with no buyer signal, threads where the matched word means something unrelated to the product (e.g. "Clio" the car, "Anchor" the boat).
- When in doubt, open the `recent_thread_url` and read it. A surfaced sub must have evidence a real buyer would recognize. Drop silently; do not show dropped candidates to the user.

After the review, you have the final sub list. If the review leaves fewer than 3 subs, treat it like a thin result (offer the clarifier / broaden). Never pad with generic founder subs.

**If `needs_clarification` is true:** render T4.5 sub-turn with the engine's `clarifier_prompt` verbatim. The clarifier varies by reason:
- `stale_only`: Phase A found candidates but none had fresh activity. Offers to broaden the freshness window or refine vertical.
- `thin_results` / `no_candidates`: Phase A didn't find enough relevant subs. Asks for the vertical.

Wait for user reply. If they say "broaden", re-run discover with extra arg `--fresh-window-hours 720` (30 days; discovery already defaults to 7 days, so broadening means going wider). Otherwise re-run with `--vertical "<user reply>"`. Use the second result regardless of clarification status (we only ask once).

**If `discovery_unreachable` is true:** the T5 card will show a one-line warning under the Subreddits row.

## Turn 5: confirm the scan card

Build the card from WebFetch output + the three answers + the discovery result. Render exactly this shape (v3, with confidence chips + freshness evidence + batched dropped line):

```
SUBSCOPE ONBOARDING  ·  5 / 7
─────────────────────────────

Here's what I'm scanning for. Confirm or correct.

You sell       <one-liner from T2>
Buyers         <titles from T3>
Pain pattern   <theme from T4>

Confidence:  ** 90+ trust   ++ 70-89 likely   ~~ 50-69 watch closely

Subreddits (each verified by a real buyer thread in the last 7 days)
** [<conf>] r/<sub>   buyer post <recent_thread_iso>  ·  "<recent_thread_title truncated to 50 chars>"
** [<conf>] r/<sub>   buyer post <recent_thread_iso>  ·  "..."
++ [<conf>] r/<sub>   buyer post <recent_thread_iso>  ·  "..."
~~ [<conf>] r/<sub>   buyer post <recent_thread_iso>  ·  "..."

Dropped <N> subs (no buyer activity in 7 days): r/<a>, r/<b>, r/<c>

Competitors    <up to 6, inferred from WebFetch + DFS cache>

Reply "go" to confirm, or tell me what to fix.
```

Rendering rules:
- Band prefix is determined by `confidence`: `**` for 90-100, `++` for 70-89, `~~` for 50-69. Subs below 50 are NOT in `subs` (already dropped by engine).
- `[<conf>]` is the integer confidence padded to 2 digits (e.g. `[94]`, `[76]`, `[ 8]`, never shown since <50 dropped, but format-pad).
- `<recent_thread_iso>` is each sub's `recent_thread_iso` field, the absolute UTC timestamp of the evidence thread (e.g. `2026-05-28 07:29 UTC`). Show it verbatim so the user can cross-check against what Reddit displays. The `recent_thread_url` is the clickable evidence link.
- `<recent_thread_title>` comes from each sub's `recent_thread_title` field, truncated to 50 chars with `...` suffix if longer.
- Discovery validates buyer activity over a 7-day window (onboarding picks subs to watch long-term). The daily `/subscope-run` scan uses a tighter 48h window for hot threads. Every timestamp is absolute, so "fresh" is never ambiguous.
- "Dropped N subs" line: read `dropped_subs` from the engine, filter to `reason: "no_fresh_buyer_activity"`, list sub names comma-separated. Skip the entire line if no dropped subs.
- If `discovery_unreachable` is true, replace the Subreddits block with the archetype-map output and append `(discovery thin, generic fallback)` to the first sub row.
- If any sub has `freshness_unverified: true`, append `· freshness unverified` to that sub's row (Phase B couldn't reach Reddit for that sub).

If the list is short (1-4 subs), still render what we have. Do not pad with generic founder subs.

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

Branch on the engine's `status` field before rendering:

- `status: "ok"` with surfaces: render the engine's `inline_table` in chat. If destinations include Notion/Slack/Obsidian, the engine handles those automatically.
- `status: "ok"` with zero surfaces: a quiet first scan is normal, the targeting is still saved. Print verbatim:

  ```
  No qualifying posts on this first scan. Your targeting is saved. Reddit was reachable, there just was not a buyer-intent thread in your subs right now. Run /subscope-run again later, fresh posts land through the day.
  ```

- `status: "rate_limited"`: the configs were written fine, Reddit just rate-limited this first scan (HTTP 429). Render any surfaces you got, then print verbatim:

  ```
  Configs saved. Reddit rate-limited this first scan, so some subreddits were skipped. This is temporary, not a block, and there is no login or API key to set up. Run /subscope-run again in a minute to pull your first full list.
  ```

  Do NOT call this "blocked" and do NOT suggest a Reddit login, API key, or OAuth setup.

- `status: "blocked"`: the configs were written fine, the scan just could not read Reddit this run. Print verbatim:

  ```
  Configs saved. Could not read Reddit on this first scan though, every feed request was blocked or unreachable.

  This is not a setup problem. subscope reads Reddit's public RSS feeds, so there is no login, API key, or account to configure. It is usually a temporary network or edge-throttle issue. Run /subscope-run in a few minutes to pull your first list.
  ```

  Do NOT tell the user to set up Reddit OAuth or a Reddit API key. There is no such step, the fetch path is keyless RSS by design.

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
