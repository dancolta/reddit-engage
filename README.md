<div align="center">

# subscope

![subscope hero: 8-bit arcade scanner UI with subreddit feeds, skill chips lighting up, and three sample surfaces in a digest panel](assets/hero.gif)

**A Claude Code plugin that classifies Reddit posts into 8 buyer-intent patterns and surfaces up to 12 per day, ranked. Runs locally. No SaaS.**

```bash
/plugin install dancolta/subscope
/subscope:onboard       # 3 questions, 60 seconds
/subscope:run           # your first daily scan
```

</div>

---

## Pattern engine

Eight intent classes, each with its own scoring path. A `pricing-rage` thread and an `alternative-seeking` thread are different buying signals and rank separately.

| Class | What it captures |
|---|---|
| `pricing-rage` | Public upset about a renewal hike |
| `churn` | "Looking to ditch X for..." threads |
| `build-vs-buy` | Debates with actual numbers attached |
| `rfp-bait` | A vs B vs C comparison threads |
| `stack-audit` | "Help me cut tools from my stack" |
| `alternative-seeking` | Explicit "alternative to X?" posts |
| `resurrect` | Quality threads aged 6 to 18 months |
| `rivals` | Any mention of a brand in your competitive set |

---

## Daily workflow

![workflow demo: terminal types /subscope:run, counters increment, five ranked surfaces populate with pattern badges](assets/workflow.gif)

**Onboard once.** Three questions: who you reach, what you sell, your homepage URL. Claude reads the answers and writes a config tuned to your product. Uses your existing Claude Code subscription, no extra cost.

For deeper targeting, `/subscope:profile` runs an 8-question interview (~12 minutes). If you skip both flows, one of 6 built-in archetypes (revops-leader, bootstrapped-saas, agency-owner, indie-hacker, consultant, plg-devtool) seeds the config from your answers. Four pre-bundled presets ship under `presets/` for users who want a flat starting point instead.

**Daily scan.** `/subscope:run` fetches your subreddits, runs intent gates, scores survivors, and lists results in chat. Default cap is 12.

```bash
PYTHONPATH=engine python3 -m subscope.cli fetch-score --max-surfaces 25
```

---

## Outputs

| Output | Setup |
|---|---|
| Inline markdown table in Claude Code chat | none (default) |
| Notion database with 14-column triage schema (includes OP score) | ~5 min |
| Slack webhook push (formatted message) | paste one URL |
| Weekly Obsidian digest via `/subscope:pulse` | vault path in config |
| JSON-only via stdout | `modes: []` in `surface.yml` |

---

## Intelligence layer

**Author vet pre-gate.** Karma, account age, and audience-fit are checked before a post enters the scoring pool. Throwaway accounts and karma-farmer OPs are filtered out at this stage.

**Permanent SQLite deduplication.** Every surfaced post is recorded. A post that appeared yesterday never reappears.

**Cooling queue (15 min).** New surfaces hold in a queue before promotion so you don't engage with posts that look algorithmic. Pricing-rage threads bypass the queue, those posts lose value within hours.

**Postmortem learner.** `/subscope:postmortem` auto-detects your sent replies, pulls 7-day outcomes (upvotes, follow-up replies, lock status), and adjusts per-subreddit weights and per-keyword scores for the next run. No other tool in this category learns from what you actually sent.

**Tune.** `/subscope:tune` runs 3 rounds of Good/Bad/Meh marks on recent surfaces and back-propagates into the same weights. Use it when the daily list drifts.

**Judge.** `/subscope:judge <n>` sends a single surface body to Claude in your active Code session and returns intent + reply angle. No API key, no cost beyond your subscription.

---

## Bring your own LLM

Bulk LLM grading on every run is opt-in. Any OpenAI-compatible endpoint works:

| Provider | Key prefix or base URL |
|---|---|
| Anthropic | `sk-ant-...` |
| OpenAI | `sk-...` |
| Groq | `gsk_...` |
| OpenRouter | `sk-or-...` |
| Together / Fireworks | provider key + `LLM_BASE_URL` |
| Local Ollama | `http://localhost:11434/v1` |

Provider auto-detected from the key prefix. Cost: ~$0.50/day at 5,000 graded posts (typical SaaS founder scan). Without a key, the regex gate runs alone and `/subscope:judge` handles ad-hoc grading free.

---

## Power user

- `--max-surfaces N` raises the daily cap per run
- `~/.config/subscope/keywords-<mode>.yml` overrides per-mode keywords
- `~/.config/subscope/weights.yml` exposes scoring weights, gate thresholds, per-subreddit caps
- All 16 invocable commands are listed in [skills/](skills/)

---

## Install

```bash
/plugin install dancolta/subscope
/subscope:setup
```

Runs on day 1 with zero API keys. The wizard presents each optional layer; skip any and the default runs without it.

**Reddit OAuth** (recommended). Register a free script-type app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps). 10x rate budget plus identity scope for postmortem reply tracking.

**LLM key, Notion, Slack, Obsidian** are all optional, one field each in the wizard. Config lives at `~/.config/subscope/`, every file written with `chmod 600`.

---

## Privacy and security

- Local SQLite at `~/.local/share/subscope/subscope.sqlite` (0o600)
- Reddit OAuth creds at `~/.config/subscope/oauth.json` (0o600), written atomically with `os.open(O_EXCL, 0o600)` so the file is never world-readable
- SSRF guard on every user-configurable URL. Private IPs (RFC-1918), AWS metadata (`169.254.169.254`), and `http://` to non-localhost hosts are refused before the request fires
- When you opt into bulk LLM grading, post bodies (capped at 800 chars) go to your configured endpoint. One-time stderr banner the first time
- Zero telemetry

---

subscope surfaces and ranks. You write the reply on Reddit yourself, in your voice, from your account.

MIT. See [LICENSE](LICENSE).
