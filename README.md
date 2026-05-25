# subscope

A Claude Code plugin that scans subreddits daily and classifies posts by pain type, not keywords. Pricing rage, churn, build-vs-buy, alternative-seeking, RFP comparisons, stack-audits, alternative-seeking, resurrect, rivals. You see 5 to 15 posts per day where someone in your exact buyer profile is hurting right now. You write the reply yourself. The plugin tracks every reply you send, scores 7-day outcomes, and adjusts next week's ranking. No SaaS. No auto-posting. Runs local in your Claude Code session.

```bash
/plugin install dancolta/subscope
/subscope:onboard       # 3 questions, 60 seconds
/subscope:run           # your first daily scan
```

> **The automation stops where the conversation starts.** subscope never drafts your reply, never queues a comment, never touches your Reddit account. If you want a Reddit engagement machine that runs while you sleep, look at Devi AI or ReplyGuy. This is not that.

---

## What it does

Three steps per session:

1. **Onboard once.** Three questions: who you are reaching, what you are selling, your homepage URL. Claude writes a config tuned to your product in chat using your existing subscription. Not a generic template.
2. **Daily scan.** `/subscope:run` pulls your configured subs, runs posts through regex gate + optional LLM grading, and surfaces 5 to 15 threads classified by pain type. SQLite deduplication: a post that surfaced yesterday never reappears.
3. **You reply.** The list lands in Claude Code chat (and optionally Notion, Slack, Obsidian). Open the thread, write the reply on Reddit yourself. The plugin tracks what you sent and scores it 7 days later on upvotes, follow-up replies, and lock status.

**The 8 intent classes it classifies:**

| Class | What triggers it |
|---|---|
| pricing-rage | public upset about a renewal hike |
| churn | "looking to ditch X for..." threads |
| build-vs-buy | debates with actual numbers attached |
| rfp-bait | A vs B vs C comparison threads |
| stack-audit | "help me cut tools from my stack" |
| alternative-seeking | explicit "alternative to X?" posts |
| resurrect | quality threads aged 6 to 18 months |
| rivals | any mention of a brand in your competitive set |

---

## What it does NOT do

- Does not post, comment, or queue replies on your behalf
- Does not learn what your competitors are doing
- Does not replace building a real reputation in a community
- Does not cap at 12 surfaces because it thinks "lead gen at scale" is the goal (see `--max-surfaces`)
- Does not store any data outside your machine

---

## Why over the alternatives

|  | subscope | Pulse for Reddit | F5Bot | GummySearch |
|---|---|---|---|---|
| Price | Free, OSS | Paywalled SaaS | Free (email) | $59/mo, DEAD Nov 2025 |
| Lives in | Your Claude Code session | Their dashboard | Your inbox | n/a |
| Matching | 8 intent classes | Keyword + AI-drafted reply | Keyword only | Keyword + sentiment |
| Auto-drafts replies | No, by design | Yes | No | No |
| Learns from sent replies | Yes (postmortem) | No | No | No |
| BYO LLM | Yes, any OpenAI-compat | No | No | No |
| Data residency | 100% local SQLite | Their cloud | Their cloud | n/a |

Every paid Reddit listening tool that survived GummySearch's shutdown does keyword matching: match a phrase, get an alert, you sift. subscope classifies by intent before anything hits your list. Pricing rage is not the same buying signal as someone asking a general category question. The tool knows the difference.

---

## Install

```bash
/plugin install dancolta/subscope
/subscope:setup
```

Works on day 1 with zero API keys. The setup wizard walks through optional layers and skips anything you skip. Choose where you want to see your daily surfaces:

- **Inline table in Claude Code** (default, zero setup, click links from chat)
- **Notion database** (5-min setup, persistent triage across devices)
- **Both** (rendered in chat AND synced to Notion)
- **Skip** (JSON only, for piping to your own tools)

---

## Cost model

| Layer | Cost | Required? |
|---|---|---|
| Default daily run | $0 | Yes |
| Reddit OAuth | $0 (free Reddit app registration) | Recommended |
| Interactive grading via Claude Code | $0 (your subscription) | Optional |
| Bulk LLM grading | ~$0.50/day at 5K posts | Optional |
| Notion, Slack, Obsidian outputs | $0 | Optional |

Bulk LLM grading is provider-agnostic. Set any OpenAI-compatible key: Anthropic, OpenAI, Groq, OpenRouter, local Ollama.

---

## Power-user mode (`--max-surfaces`)

Default caps at 12 surfaces because attention drops 50% past position 7 and 80% past position 10 (Nielsen Norman). If you have 20 to 30 subs configured and ~30 minutes of review budget, override the cap per-run:

```bash
PYTHONPATH=engine python3 -m subscope.cli fetch-score --max-surfaces 25
```

Reddit's API is fine with the volume (~30 read requests/day, well under the 100 QPM ceiling, and read-only `/new.json` polling is not the ban surface). Your review fatigue is the real risk. To raise the per-profile sub ceiling above 13 total, edit `tier1_subs_max` and `tier2_subs_max` in `~/.config/subscope/weights.yml`.

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

## Privacy

- Reddit credentials at `~/.config/subscope/oauth.json` (0o600). Written atomically, never world-readable.
- LLM API key is opt-in. When set, post bodies (capped at 800 chars) go to your configured endpoint. One-time stderr banner the first time this fires.
- SSRF guard on `llm_base_url`: requests to private IPs (RFC-1918, AWS metadata 169.254.169.254) and to `http://` for non-localhost hosts are refused.
- SQLite at `~/.local/share/subscope/subscope.sqlite` (0o600). No data leaves your machine unless you opted in to LLM, Notion, or Slack.
- No telemetry. No analytics. No pings.

---

## Roadmap

- **v0.1.1**: Merged Reddit OAuth/public modules, unit tests for cli.py, expanded preset library
- **v0.2.0**: HackerNews adapter (`/subscope:hn`), Anthropic prompt caching
- **v0.3.0**: LinkedIn pulse adapter (public posts only)

---

## License

MIT.

---

*Built by [Dan Colta](https://github.com/dancolta) at [NodeSparks](https://nodesparks.com). Operator automation, not lead-gen tooling.*
