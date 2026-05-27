---
name: onboard
description: Mandatory first-run setup for subscope. Paste 2-3 URLs (homepage + case studies or blog posts), confirm a 6-field targeting card with full source provenance, choose Reddit access mode (skip OAuth or connect), pick destinations (Notion, Slack, Obsidian, or chat-only), and the first scan runs automatically. If the URLs are thin (no testimonials, no named customers), the skill falls back to a 3-question kickoff before showing the card. Optionally pulls deeper research via DataForSEO or Firecrawl when the user opts in. Triggers on "onboard", "/subscope:onboard", "set up subscope", "first time setup", "configure subscope", "get started with subscope", "install subscope".
allowed-tools: Bash, Read, Write, Edit, WebFetch
---

# /subscope:onboard

First-run setup. URL-driven by default, with a short kickoff fallback when URLs don't carry enough signal.

## Operating principles

1. **Infer from URLs when URLs can answer. Ask the user when they can't.** Customer names, verbatim pain quotes, buyer titles live on homepages when the user has rich social proof. When they don't, asking is faster and more accurate than guessing.
2. **Every auto-filled field carries provenance.** No `[conf: high/med/low]` abstractions. Use action-oriented labels: `[verbatim from <source>]` for direct pulls, `[inferred from <signal>, edit if wrong]` for synthesized, `[needs your input]` for fields the URLs couldn't answer.
3. **One card, six fields.** No 50-line wall. Candidate keywords + example pains are written silently to YAML and referenced by name only. The user reviews 6 things, not 12.
4. **Conditional kickoff.** If WebFetch finds zero testimonials and zero named customers across all URLs, ask 3 short questions before showing the card. Otherwise skip straight to the card.
5. **Never block on OAuth.** Public Reddit JSON is the default fallback. OAuth is an opt-in upgrade, asked once.
6. **Optional integrations are user-gated and credential-verified.** Ask the user once. If MCP is missing, ask one concise credential prompt. Verify the credentials work before continuing.
7. **Destinations always asked.** Notion, Slack, Obsidian are multi-select at onboard.
8. **No filler.** No "let's get started", "welcome", "great", "perfect". No exclamation marks. No em dashes anywhere.

## Procedure

### Step 1: Greet + collect URLs

**Render Step 1 exactly once per session.** Before printing, silently check for a draft:

```bash
[ -f ~/.config/subscope/.onboard-draft.json ] && echo "draft: present" || echo "draft: absent"
```

- If `draft: absent`, suppress all output from the check and proceed directly to the prompt below.
- If `draft: present`, surface the resume question (see Resumability section) instead of the Step 1 prompt.

If the user replies with something that isn't URL-shaped (e.g. "ready", "ok", "go"), do NOT re-emit Step 1. Acknowledge with one line: `"Paste the URLs when you have them. Homepage plus 2-3 case study or blog links."` Then wait.

Print verbatim:

```
Drop your homepage + 2-3 case study or blog URLs (newline or space separated).

I'll pull positioning, customer references, competitors, and pain language
directly from the URLs. You'll see a 6-field card with source citations,
edit anything wrong, then the first scan runs.
```

Wait for input. Accept 1 to N URLs (no hard cap, but warn if more than 8). These URLs serve double duty: inference sources AND seed entries for `blog-map.yml`. There is no separate "your own content URLs" question later.

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

**Always run:** WebFetch each URL provided in Step 1. For each URL, capture the extraction into the scratchpad with explicit source attribution (URL + section where the signal was found). Extract:
- H1 / sub-headline / positioning line → tag as `source: <url>#h1`
- Named customer testimonials (look for "Founder, <Company>", "Head of <X>, <Company>", quoted statements) → tag as `source: <url>#testimonial-N` with index N
- Verbatim customer quotes (anything in quote marks attributed to a named person) → tag as `source: <url>#quote-N`
- Linked case studies / pricing / customer logos → tag as `source: <url>#case-N`
- Visible competitor names ("alternative to X", "replace Y") → tag as `source: <url>#competitor-context`
- Pain language (problem statements, "before/after" phrasing) → tag as `source: <url>#pain-N`
- Buyer titles quoted in testimonials ("Head of Ops at...", "RevOps Lead at...") → tag as `source: <url>#title-N`

**Testimonial-richness signal.** After all WebFetches complete, compute one boolean:

- `urls_carry_social_proof = (named_customers_count >= 1) OR (verbatim_quotes_count >= 1)`

This signal gates Step 3.5 (conditional kickoff). Save it in the scratchpad.

**If DataForSEO is ready:** call these in parallel:
- `mcp__dataforseo__dataforseo_labs_google_competitors_domain` on the homepage domain
- `mcp__dataforseo__dataforseo_labs_google_ranked_keywords` on the same domain
- `mcp__dataforseo__dataforseo_labs_search_intent` on the top 5 ranked keywords (only if ranked_keywords returned results)

**If Firecrawl is ready:** crawl the homepage one layer deeper to catch case study or pricing links not in the user's paste.

**Warm-scan:** skip in Step 3. It runs (if OAuth is present) only after Step 6 OAuth selection. Reason: public Reddit JSON without OAuth rate-limits within seconds and contaminates the flow.

For each inferred field, attach a **provenance label** (action-oriented, not abstract confidence):

- `[verbatim from <source>]`: the value appears verbatim in a URL or DataForSEO row. Always include the specific source citation (which URL, which testimonial index, which keyword cluster).
- `[inferred from <signal>, edit if wrong]`: synthesized from adjacent signals (case-study language, ranked-keyword clusters, positioning phrases). Always name the signal.
- `[needs your input]`: URLs and enrichment sources didn't produce a value. The field is blank and the user must fill it.

Never use `[conf: high/med/low]`. Always use one of the three labels above.

Save everything to `~/.config/subscope/.onboard-draft.json` for resumability.

### Step 3.5: Conditional kickoff (only if URLs are thin)

If `urls_carry_social_proof` is **false**, ask 3 short questions before showing the card. These cover the fields URLs couldn't fill. If `urls_carry_social_proof` is **true**, skip this step entirely and go straight to Step 4.

When firing, print exactly this:

```
Your URLs are positioning-rich but light on customer references, so three quick
questions before the card:

1. Last 3 customers (name + title + company + what they replaced).
   Type "skip" on any individual line you can't fill.
2. One verbatim pain quote you've actually heard from a customer.
   Type "no quote yet" if you don't have one. The scorer treats it as
   absent rather than synthesizing one.
3. Top 3 buyer titles (how they describe themselves on LinkedIn).
   Comma-separated.
```

Capture the three answers. Merge into the scratchpad with provenance `[verbatim from kickoff Q<n>]`. Continue to Step 4.

### Step 4: Targeting card (6 fields)

Render ONE card with 6 fields. Each field shows its provenance label inline. The user confirms or edits in ONE reply. Use this exact template:

```
─── Your subscope targeting ───

Confirm or edit each field. Reply with inline edits (one per line, field number
+ new value, e.g. "4: drop Pipedrive, add Outreach.io") or type "looks good"
to lock in everything.

1 / 6  what you sell                              [verbatim from <homepage url>]
       <one-sentence positioning, lifted from H1 + sub-headline>

2 / 6  your last 3 customers                      [verbatim from <homepage>#testimonials]
       <Name>, <Title> at <Company>  (replaced <tool>)        ← testimonial #1
       <Name>, <Title> at <Company>                           ← testimonial #2
       <Name>, <Title> at <Company>                           ← testimonial #3

       Use [needs your input] with 3 placeholder lines if no testimonials were
       found on URLs and the kickoff was skipped. Use [verbatim from kickoff Q1]
       when the user supplied via Step 3.5 kickoff.

3 / 6  the pain quote (drives scorer)             [verbatim from <homepage>#testimonial-2]
       "<exact quoted text>"
       attributed to: <name>, <company>

       Variants:
         - [verbatim from kickoff Q2] when supplied via kickoff
         - [no quote yet, scorer treats as absent] when the user typed "no
           quote yet" in kickoff (this is explicit, not a hallucination fallback)

4 / 6  competitors / tools you displace           [verbatim from <urls> + DataForSEO]
       <up to 12 names, grouped by category if useful>
       Each name annotated with source: <homepage|case-study-url|dfs-keyword>.

5 / 6  buyer titles                               [verbatim from <homepage>#testimonials]
       <up to 4 titles, one per line>
       Use [verbatim from kickoff Q3] when supplied via kickoff.

6 / 6  subreddits (tier 1 daily + tier 2 opportunistic)   [inferred from ICP + competitor signals, edit if wrong]
       Tier 1: r/<sub>, r/<sub>, r/<sub>             (3-5 subs, daily scan)
       Tier 2: r/<sub>, r/<sub>, r/<sub>, r/<sub>    (3-8 subs, opportunistic)

       Each sub gets a one-line reason in subreddits.yml. Watch-list subs
       (r/Entrepreneur, r/startups, r/smallbusiness, r/marketing) are
       auto-quarantined to tier 3 and not shown here.

Wrote silently to ~/.config/subscope/:
  keywords.yml      <N shared + N operator + N builder phrases>
  example-pains.yml <5 synthesized pain-post titles for scorer few-shots>
  brand-anchor.yml  <merged competitor + adjacent-SaaS list>

  Review or override with /subscope:profile <section> any time.

─── Reply with edits or "looks good" ───
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

The scratchpad records inference output + whether the targeting card was answered. Resume lands at the unanswered step.

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
- **No `[conf: high/med/low]` labels.** Use the three provenance labels: `[verbatim from <source>]`, `[inferred from <signal>, edit if wrong]`, `[needs your input]`. Abstract confidence scores tell the user nothing about what to do.
- **No fabricated customer references.** If WebFetch found no testimonials and the kickoff didn't supply names, field 2 renders with `[needs your input]` and three placeholder lines. Never invent names, titles, or companies to fill the card.
- **No synthesized pain quote when none exists.** If neither URLs nor kickoff supplied a verbatim quote, render field 3 as `[no quote yet, scorer treats as absent]`. The scorer's pain-quote weight is downgraded to zero in that branch.
- **No intermediate output cards.** The user sees ONE card in Step 4. Steps 1-3 are inputs and silent inference. Step 3.5 (kickoff) is 3 short questions only when URLs are thin. Steps 5-6 are short questions, not cards.
- **Never render the full targeting card twice.** If the user edits a field, show ONLY the diff. Never re-print the full card.
- **Never write configs without passing through Step 4.** The card is the mandatory gate.
- **Never re-emit Step 1.** If the user sends a non-URL message after Step 1, acknowledge with one line and wait. Re-printing Step 1 creates the double-prompt bug.
- **Never block on a missing optional integration.** If DataForSEO/Firecrawl creds fail twice, treat as missing and continue. Warm-scan is auto-skipped when OAuth is absent. Never run it against public JSON during onboarding.

## What's NOT in this skill

- LLM provider configuration. That's a power-user concern, kept in `/subscope:setup --llm`.
- Per-section refinement. After onboarding, `/subscope:profile` handles single-section deep dives.
- Preset shortcut. There is no preset shortcut. Every install passes through the full flow.
