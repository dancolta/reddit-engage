---
name: onboard
description: Mandatory first-run setup for subscope. One conversation, one input, one consolidated review, eight field-level locks, one scan. Paste 2-3 URLs (homepage + case studies or blog posts), confirm or refine the inferred targeting in a single review card, lock each of the 8 deep targeting fields with pre-filled answers, choose Reddit access mode (skip OAuth or connect), pick destinations (Notion, Slack, Obsidian, or chat-only), and the first scan runs automatically. Optionally pulls deeper research via DataForSEO, Firecrawl, or a live Reddit warm-scan when the user opts in. No fast path. Every install passes through this. Triggers on "onboard", "/subscope:onboard", "set up subscope", "first time setup", "configure subscope", "get started with subscope", "install subscope".
allowed-tools: Bash, Read, Write, Edit, WebFetch
---

# /subscope:onboard

The default post-install entry point. Mandatory. One conversation, one input, one consolidated review, eight field-level locks, one scan.

You won't see a single scored post until the flow ends, that's the tradeoff. The plugin only works if your targeting is sharp, so the only path is the sharp one.

## Operating principles

1. **Infer aggressively from URLs.** Never ask what URLs can answer.
2. **One review card before the deep questions.** High-level sanity check on everything inferred so far.
3. **Field-level locks after the review card.** 8 questions, each pre-filled from inference with a confidence score. High-confidence ones are 5-second taps. Low-confidence ones get real attention.
4. **No shortcut, no fast path.** Every user passes through all 9 steps.
5. **Never block on OAuth.** Public Reddit JSON is the default fallback. OAuth is an opt-in upgrade, asked once.
6. **Optional integrations are user-gated.** Ask the user if they want deeper research first. Only then probe MCP availability.
7. **Destinations always asked.** Notion, Slack, Obsidian are multi-select at onboard. No "skip the question" path.
8. **No filler.** No "let's get started", "welcome", "great", "perfect". No exclamation marks. No em dashes anywhere.

## Procedure

### Step 1: Greet + collect URLs

Print verbatim:

```
Drop your homepage + 2-3 case study or blog URLs (newline or space separated).

I'll come back with your ICP, the tools you displace, the titles you sell to,
candidate subreddits, candidate keywords, and example pains. You confirm or
refine each field before the first scan runs.
```

Wait for input. Accept 1 to N URLs (no hard cap, but warn if more than 8).

### Step 2: Ask the enrichment question (gate the optional sources)

Before any deep fetching, ask once:

```
Want deeper research sources for sharper picks?
  - DataForSEO: competitor domains + ranked keywords from your URLs
  - Firecrawl: deeper crawl than basic WebFetch (catches linked case studies)
  - Reddit warm-scan: 30-second live preview against archetype-seeded subs

[yes / lean]
```

If `lean`: skip availability probing entirely. Use WebFetch only in Step 3.

If `yes`: probe each in this order, report back in one line:

```bash
# DataForSEO: check if MCP tool is available in this Claude Code session.
# Test by listing tools matching mcp__dataforseo__*. If the tool list contains
# any dataforseo tool, mark as available.

# Firecrawl: check for the seo-firecrawl skill OR a FIRECRAWL_API_KEY env var.

# Reddit warm-scan: always available (uses engine's public JSON path).
```

Report:

```
DataForSEO: <ready / missing, install dataforseo MCP to enable>
Firecrawl:  <ready / missing, install firecrawl or set FIRECRAWL_API_KEY>
Warm-scan:  ready

Running <N> of 3 enrichment sources.
```

Then proceed. Missing sources are non-fatal.

### Step 3: Parallel enrich

Fire all available sources in parallel. Capture results into a scratchpad.

**Always run:** WebFetch each URL provided in Step 1. Extract:
- H1 / sub-headline / positioning line
- Linked case studies / pricing / customer logos
- Visible competitor names ("alternative to X", "replace Y")
- Pain language (problem statements, "before/after" phrasing)
- Buyer titles quoted in case studies ("Head of Ops at...", "RevOps Lead at...")

**If DataForSEO is ready AND user opted in:** call these in parallel:
- `mcp__dataforseo__dataforseo_labs_google_competitors_domain` on the homepage domain
- `mcp__dataforseo__dataforseo_labs_google_ranked_keywords` on the same domain
- `mcp__dataforseo__dataforseo_labs_search_intent` on the top 5 ranked keywords

**If Firecrawl is ready AND user opted in:** crawl the homepage one layer deeper to catch any case study or pricing links not in the user's paste.

**If warm-scan is enabled:**

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli fetch-score \
  --limit-per-sub 5 --daily-cap 10 --no-slack --max-surfaces 5 2>/dev/null \
  || echo "warm-scan-skipped"
```

Use the warm-scan results to validate which archetype-seeded subreddits actually have ICP-relevant posts right now. Surface the 3 strongest matches by title into the review card as candidate example pains.

For each inferred field, attach a **confidence score** (high / medium / low) based on signal strength:
- High: explicit, verbatim from URLs or DataForSEO output
- Medium: inferred from adjacent signals (case study quotes, ranked keyword clusters)
- Low: synthesized or guessed because URLs were sparse

Save everything to `~/.config/subscope/.onboard-draft.json` for resumability.

### Step 4: The single consolidated review card

Render ONE card with everything inferred. Use this exact template:

```
─── Your subscope targeting ───

Positioning:  <one-line, derived from H1 + sub-headline>
Buyer:        <role(s) + company size, inferred from case studies>

Competitors (<N>):
  <list, max 15, DataForSEO + URL-extracted + de-duped>

Self-described titles (<N>):
  <Head of Ops, RevOps Lead, Founder, etc, from case study quotes>

Candidate subreddits (<N>):
  Tier 1 (daily): <3-5 subs, validated by warm-scan if available>
  Tier 2 (opportunistic): <3-8 subs>

Candidate keywords (<N>):
  Shared:   <5-9 phrases, from pain language + DataForSEO keywords>
  Operator: <5-10 phrases, work-pain specific>
  Builder:  <5-8 phrases, technical/replacement-oriented>

Example pains seen this week (<N>):
  <if warm-scan ran: 3-5 real post titles>
  <else: 3-5 synthesized from URL content>

─── Anything obviously wrong? Edit inline or type "looks good" ───
```

Accept inline edits (e.g. "swap r/sales for r/SaaSSales", "drop Copy.ai from competitors") or a `looks good` to proceed. This is a sanity check on the whole picture, not a field-by-field lock. Field-level locks happen in Step 5.

Apply edits. Show the updated card once. Do NOT loop on micro-edits more than twice.

### Step 5: Field-level locks (8 questions, pre-filled)

After the review card, walk the user through 8 deep targeting questions. Each one shows the inferred answer pre-filled with a confidence score. The user confirms with one keystroke or refines with a real answer.

**Pacing rule:** one question per turn. Wait for an answer. Don't batch.

**Pre-fill rule:** every question shows the system's best guess from the URL/enrichment data, labeled with confidence. Never present a blank prompt.

Render each question with a single bracketed header:

```
─── 1 / 8 · what you sell ───
```

#### `─── 1 / 8 · what you sell ───`

Pre-fill from H1 + sub-headline.

```
Inferred: "<one-sentence positioning, derived from URL>"
Confidence: <high / medium / low>

Confirm or refine in one sentence (offer + buyer in one noun-verb-payer triple).
[type "confirm" to accept, or paste a corrected sentence]
```

#### `─── 2 / 8 · your last 3 customers ───`

Pre-fill from case study quotes if present.

```
Inferred customers (from your URLs):
  1. <title at company, what they replaced if visible>
  2. <title at company>
  3. <title at company>
Confidence: <high / medium / low>

Confirm, or describe the last 3 actual customers, not the persona deck. Job
title, company size, what tool/process they replaced to buy you.
[type "confirm" / paste corrected list]
```

If only 0-2 case studies were visible, mark `confidence: low` and ask for at least one real customer.

#### `─── 3 / 8 · the pain quote (load-bearing) ───`

URL inference rarely surfaces verbatim quotes. Default to **low confidence** unless a case study contains a direct buyer quote.

```
Inferred pain language (from URL content):
  "<paraphrased pain statement>"
Confidence: low

This question is load-bearing. Paste a literal customer quote if you have one,
from Slack, a sales call, a review, anything. Verbatim language is the
difference between generic and sharp.
[paste the quote, or type "skip" if you genuinely don't have one]
```

If user pastes a paraphrase ("they said it was inefficient"), push back once: *"Got a literal quote? 'inefficient' is yours, not theirs."* If still no verbatim, accept and mark `confidence: low` in the scratchpad.

#### `─── 4 / 8 · where they vent ───`

Pre-fill from candidate subreddits in the review card.

```
Inferred venues: <top 3 subreddits from review card, or "Reddit + LinkedIn" if subreddit signal is weak>
Confidence: <high / medium / low>

When that pain hits at 11pm, where does your buyer go to vent or ask for help?
Reddit, Twitter, Slack groups, Discord, LinkedIn, nowhere?
[type "confirm" / add a venue]
```

If user says "I don't know", accept and mark `confidence: low`.

#### `─── 5 / 8 · who they're stealing customers from ───`

Pre-fill from competitors detected on the URL plus DataForSEO competitor domains.

```
Inferred competitors:
  <up to 7, ranked by signal strength>
Confidence: <high / medium / low>

Add, remove, or reorder. These drive your brand anchor list.
[type "confirm" / edit inline]
```

#### `─── 6 / 8 · how they describe themselves ───`

Pre-fill from case study titles ("Head of Ops at...").

```
Inferred self-descriptions:
  <up to 4 titles>
Confidence: <high / medium / low>

What job titles or self-descriptions does your buyer actually use? Examples:
"indie hacker", "agency owner", "RevOps lead", "fractional CTO".
[type "confirm" / edit inline]
```

#### `─── 7 / 8 · subreddit tiers ───`

Pre-fill from review card's Tier 1 / Tier 2 splits.

```
Tier 1 (daily scan, always included):
  <3-5 subs>
Tier 2 (opportunistic, standouts only):
  <3-8 subs>
Confidence: <high / medium / low>

Confirm, or move a sub between tiers / swap a sub.
[type "confirm" / paste edits like "move r/SaaS to tier 1, drop r/marketing"]
```

#### `─── 8 / 8 · your own content (optional) ───`

```
Paste 3-5 URLs of your own content (blog, YouTube, threads) that converts
best, or that you'd want to reference in a Reddit reply.

Optional. Type "skip" if you don't have it.
```

If provided, WebFetch each and extract titles/H1s for the `blog-map.yml`. If skipped, the engine works fine without.

### Step 6: Merge locks into the draft payload

After all 8 locks are captured, merge them with the Step 3 inference into the final payload. Save to scratchpad:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -c "
import json
from subscope.lib import profile_synth, store
draft = store.xdg_config_dir() / '.onboard-draft.json'
existing = json.load(draft.open()) if draft.exists() else {}
existing['locks'] = $LOCKS_DICT
draft.write_text(json.dumps(existing, indent=2))
print(f'scratchpad: {draft}')
"
```

Validate the merged payload via `profile_synth.validate_synthesis(payload, weights_cfg)` before continuing. If validation fails, surface the failures and let the user correct inline.

### Step 7: Reddit access mode

Ask:

```
Reddit access:
  [A] Skip OAuth, scan via public JSON (works now, ~60 req/min, no rate-budget cushion)
  [B] Connect Reddit OAuth (10x rate limit, enables postmortem tracking)

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

### Step 8: Destinations (always ask, multi-select)

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

**Chat (`t`)**: no setup needed, but write surface.yml so /run knows:

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

Write via atomic helper (never pass key inline on the command line):

```bash
cd "$CLAUDE_PLUGIN_ROOT" && cat <<EOF | PYTHONPATH=engine python3 -m scripts.write_notion_config
api_key: $NOTION_API_KEY
database_id: $NOTION_DB_ID
EOF
```

Dry-run migration to verify access:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 engine/scripts/notion_admin.py migrate --dry-run
```

If dry-run succeeds, run the live migration:

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

### Step 9: Write the targeting config + auto-run first scan

Take the merged payload (review card + Step 5 locks) and write the four YAML files:

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

Then chain directly into the first scan:

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli fetch-score
```

Render the engine's `inline_table` in chat. If destinations include Notion/Slack/Obsidian, the engine handles those automatically per surface.yml.

### Step 10: Next-action footer (locked)

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

The scratchpad records both inference output and which of the 8 locks have been answered, so resuming lands on the next unanswered question.

The scratchpad is cleared on successful Step 9 write.

## Re-auth path

If user runs `/subscope:onboard --reauth`, skip to Step 7 directly. Used by people who initially picked option A (skip OAuth) and want to upgrade later.

```bash
# Detect --reauth flag
if [ "$1" = "--reauth" ]; then
  rm -f ~/.config/subscope/.oauth-skipped
  # jump to Step 7
fi
```

## Anti-patterns

- **No exclamation marks.** Anywhere.
- **No em dashes.** Anywhere. Use commas, periods, or restructure.
- **No "welcome" / "let's get started" / "great" / "perfect".** Operational tone only.
- **No phase labels per step.** The em-rule appears ONLY on the review card in Step 4 and the 8 field-level locks in Step 5.
- **Never present a blank question.** Step 5 questions always pre-fill from inference. If inference is empty, say so explicitly and mark `confidence: low`.
- **Never write configs without passing through Steps 4 AND 5.** Both gates are mandatory.
- **Never block on a missing optional integration.** DataForSEO missing? One-line note, continue. Firecrawl missing? Same. Warm-scan fails? Same.
- **Never skip the 8 field-level locks.** Even when URL inference is high-confidence across the board, the user still confirms each field. "Confirm" is a 5-second tap, not a survey question.

## What's NOT in this skill

- LLM provider configuration. That's a power-user concern, kept in `/subscope:setup --llm` for users who want bulk grading. The default classify path uses the user's Claude Code subscription via `/subscope:judge` and is free.
- Per-section refinement. After onboarding, `/subscope:profile` handles single-section deep dives (redo competitor anchor, rebuild pain language, etc.) without forcing a full re-run.
- Preset shortcut. There is no preset shortcut. Every install passes through the full flow.
