---
name: run
description: Run the daily Reddit pain-post surface. Fetch new posts from configured subs, score by intent/keyword/freshness, optionally classify via Claude Haiku, dedup against history, hold in cooling queue, and emit inline markdown (plus optional Notion sync). Triggers on "run subseek", "/subseek run", "daily reddit", "scan reddit", "show today's reddit posts", or the default `/subseek:run` invocation.
allowed-tools: Bash, Read, Write
---

# /subseek:run

Daily Reddit surfacing orchestrator. Python (under `engine/`) does fetch + gate + score + SQLite + JSON output. This skill is the Claude-side wrapper: it invokes the engine, optionally syncs to Notion (if configured), and prints the inline list to chat.

## Preflight

1. Verify the plugin is set up:
   - `~/.config/subseek/oauth.json` exists OR the user has run `/subseek:setup`
   - At least one preset is active in `~/.config/subseek/subreddits.yml`
2. If preflight fails, redirect the user to `/subseek:setup`.

## Daily run procedure

### Step 1 — Fetch + gate + score (Python engine)

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subseek.cli fetch-score
```

Engine output: a single JSON document on stdout with `run_id`, `fetched`, `surfaced`, `dropped_counts`, `surfaces[]`, and `inline_markdown`.

### Step 2 — Optional Notion sync

If `~/.config/subseek/notion.yml` exists AND `${user_config.notion_api_key}` is set:

1. For each surface in the engine output, create a row in the configured Notion database with these fields:
   - `Title`, `Tier`, `Subreddit`, `Score`, `Upvotes`, `Comments`, `Posted` (ISO date), `Pain`, `Fit`, `URL` (verbatim from engine output — **never hand-compose Reddit URLs**), `Surfaced on` (today, ISO)
   - `Pattern` = the mode that produced the surface (default: `run`)
   - `State` = `Drafting` if cooling queue active, else `Hot`
   - `OP score` ← read from `surface.op_score` (string like `"2y old · 4.2k karma · 12% wrong-audience"`). Saves opening the OP's profile to evaluate quality.
2. Notion sync failure is **non-fatal**. Capture the reason and proceed.

If Notion is not configured, skip silently.

### Step 3 — Optional Slack push (handled by Python automatically)

If `~/.config/subseek/slack.json` exists OR `SLACK_WEBHOOK_URL` env is set, the engine pushes a formatted message to that webhook at the end of `fetch-score`. This skill does NOT need to do anything — the integration is in `engine/subseek/lib/slack.py` and silently no-ops if no webhook is configured. To suppress for one run, pass `--no-slack` to `fetch-score`.

### Step 4 — Output

Print the `inline_markdown` field from the engine JSON **verbatim**. That's the user-facing list. If Notion sync failed, append exactly one line: `(Notion sync failed: <reason>)`.

## Critical guardrails

- **No em dashes** in any output written to Notion or chat. The Python output is em-dash-free; preserve that.
- **NEVER hand-compose Reddit URLs.** Read `url` directly from the JSON. Post IDs are globally unique; a single typo can resolve to a completely unrelated (potentially NSFW) post.
- **Idempotent:** running twice surfaces zero new posts (`surfaced.post_id` PK in SQLite enforces this).
- **No drafting in v1.** If the user asks "draft a reply for post N", politely defer — that's a deliberate omission, see PLAN.md §6.

## Configuration

All configs live under `${SUBSEEK_CONFIG:-~/.config/subseek/}`:

| File | Purpose |
|---|---|
| `oauth.json` | Reddit OAuth credentials (Phase 1) |
| `llm.json` | LLM provider preference (Phase 2) |
| `subreddits.yml` | Active sub list — copied from a preset at setup |
| `keywords.yml` | Active keyword bucket |
| `weights.yml` | Score weights + gate thresholds |
| `notion.yml` (optional) | Notion DB ID + integration |
| `obsidian.yml` (optional) | Vault path for pulse digests |

State (SQLite, logs) lives under `${SUBSEEK_DATA:-~/.local/share/subseek/}`.

## After completion

Print the `inline_markdown` from the engine output verbatim. Do NOT add a preamble. If Notion sync was attempted and failed, append exactly one line noting the reason.
