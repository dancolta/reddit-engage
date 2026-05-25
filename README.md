# subscope

A Claude Code plugin that scans subreddits daily and classifies posts by intent pattern. It surfaces 5 to 15 threads per day where someone in your buyer profile is actively in pain: pricing rage, churn, build-vs-buy debates, alternative-seeking, and four more. The pattern engine distinguishes intent, not just keyword presence. Runs entirely inside your Claude Code session.

```bash
/plugin install dancolta/subscope
/subscope:onboard       # 3 questions, 60 seconds
/subscope:run           # your first daily scan
```

---

## Features

### Pattern engine

Eight intent classes, each with distinct scoring behavior:

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

The 8 classes are not aliases for keyword buckets. `pricing-rage` and `alternative-seeking` are different buying signals. The ranker treats them differently.

---

### Daily workflow

**Onboard once.** Three questions: who you are trying to reach, what you are selling, your homepage URL. Claude reasons through the answers in chat (using your existing Claude Code subscription, free) and writes a config tuned to your product. No generic template.

Want more depth? `/subscope:profile` runs an 8-question interview (about 12 minutes) and produces sharper subreddit targeting. Four built-in presets (b2b-saas-founder, agency-owner, indie-hacker, consultant) are available as a fallback if you skip both flows.

**Daily scan.** `/subscope:run` fetches your configured subreddits, runs posts through the intent gate, scores survivors, and surfaces 5 to 15 threads in chat. Default cap is 12. Override with `--max-surfaces`:

```bash
PYTHONPATH=engine python3 -m subscope.cli fetch-score --max-surfaces 25
```

---

### Outputs

| Output | Setup required |
|---|---|
| Inline markdown table in Claude Code chat | None (default) |
| Notion database with 14-column triage schema | ~5 min setup |
| Slack webhook push | Paste one URL |
| Weekly Obsidian digest via `/subscope:pulse` | Vault path in config |
| JSON-only via stdout | `modes: []` in `surface.yml` |

---

### Intelligence layer

**Author vet pre-gate.** Karma, account age, and audience-fit are checked before a post enters the scoring pool. Throwaway accounts and karma-farmer OPs are filtered at this stage and never reach your list.

**SQLite deduplication.** Every surfaced post is recorded permanently. A post that appeared yesterday never reappears.

**Cooling queue.** New surfaces hold in a 15-minute queue before promotion. Pricing-rage posts bypass this because the pattern is time-sensitive.

**Postmortem learner.** `/subscope:postmortem` auto-detects your sent replies, pulls 7-day outcomes (upvotes, follow-up replies, lock status), and feeds the results back into next week's ranker. The tool gets more accurate the longer you use it.

**Tune.** `/subscope:tune` runs 3 rounds of Good/Bad/Meh marks on recent surfaces. Each round back-propagates into per-subreddit weights and keyword scores.

---

### Bring your own LLM

Bulk LLM grading on every run is opt-in. Any OpenAI-compatible endpoint works:

| Provider | Key prefix |
|---|---|
| Anthropic | `sk-ant-...` |
| OpenAI | `sk-...` |
| Groq | `gsk_...` |
| OpenRouter | `sk-or-...` |
| Together / Fireworks | provider key |
| Local Ollama | `http://localhost:11434/v1` |

Provider is auto-detected from the key prefix. If no LLM key is set, `/subscope:judge` still classifies individual surfaces free via your Claude Code subscription.

---

### Power user

- `--max-surfaces N` CLI flag overrides the daily cap per run
- Per-mode keyword files at `~/.config/subscope/keywords-<mode>.yml`
- `weights.yml` fully editable: scoring weights, gate thresholds, per-subreddit caps
- 6 pre-built archetypes: revops-leader, bootstrapped-saas, indie-hacker, and more

---

## The 16 skills

<details>
<summary>All invocable skills (click to expand)</summary>

| Skill | What it does |
|---|---|
| `/subscope:setup` | Conversational onboarding. ~10 min. |
| `/subscope:onboard` | 3-question routing flow. ~60 sec. Default first-launch path. |
| `/subscope:profile` | 8-question deep interview. ~12 min. Sharper targeting. |
| `/subscope:run` | Daily scan. 5 to 15 surfaces in chat, Notion, Slack if configured. |
| `/subscope:judge <n>` | Interactive single-surface classification via your Claude subscription. |
| `/subscope:tune` | Mark surfaces good/bad/meh, ranker learns. ~3 rounds. |
| `/subscope:pulse` | Weekly digest written to your Obsidian vault. |
| `/subscope:postmortem` | Auto-detect your sent replies, score 7-day outcomes. |
| `/subscope:rivals` | Today's mentions of any competitor in your brand_anchor. |
| `/subscope:pricing-rage` | Price-hike threads, zero cooling (time-sensitive). |
| `/subscope:churn` | Switching and canceling threads in your space. |
| `/subscope:build-vs-buy` | Build-vs-buy debates with concrete numbers. |
| `/subscope:stack-audit` | "Help me cut tools from my stack" threads. |
| `/subscope:rfp-bait` | A vs B vs C comparison threads. |
| `/subscope:resurrect` | Quality threads aged 6 to 18 months worth a late comment. |
| `/subscope:op-vet <user>` | One-shot Reddit profile vetting: karma, age, audience fit. |

</details>

---

## Install and configure

```bash
/plugin install dancolta/subscope
/subscope:setup
```

Works on day 1 with zero API keys. The setup wizard walks through optional layers and skips anything you skip.

**Reddit OAuth** (recommended): register a free script-type app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps). Gives 10x rate budget and enables postmortem reply tracking.

**LLM key** (optional): enables bulk grading on every run. Without it, the regex gate runs alone and `/subscope:judge` handles single-surface classification free via your Claude Code subscription.

**Notion/Slack/Obsidian** (optional): each is a single field in the setup wizard.

Config lives at `~/.config/subscope/`. All files written with `chmod 600`.

---

## Cost model

| Layer | Cost |
|---|---|
| Default daily run | $0 |
| Reddit OAuth | $0 (free app registration) |
| Interactive grading via Claude Code | $0 (your subscription) |
| Bulk LLM grading | ~$0.50/day at 5K posts |
| Notion, Slack, Obsidian outputs | $0 |

---

## Privacy and security

- All data stored in local SQLite at `~/.local/share/subscope/subscope.sqlite` (0o600)
- Reddit OAuth credentials at `~/.config/subscope/oauth.json` (0o600), written atomically
- SSRF guard on any user-configurable URL: private IPs (RFC-1918), AWS metadata endpoint, and non-HTTPS hosts are refused
- When an LLM key is set, post bodies (capped at 800 chars) go to your configured endpoint. One-time stderr banner the first time this fires
- No telemetry. No analytics. No usage pings. Ever.

---

## Roadmap

- **v0.1.1**: Reddit OAuth/public module merge, unit tests for `cli.py`, expanded preset library
- **v0.2.0**: HackerNews adapter (`/subscope:hn`), Anthropic prompt caching
- **v0.3.0**: LinkedIn pulse adapter (public posts only)

---

subscope surfaces and ranks; you decide which threads to engage with.

---

MIT. See [LICENSE](LICENSE).
