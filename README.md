<div align="center">

# subscope

![subscope hero: 8-bit arcade scanner UI with subreddit feeds, skill chips lighting up, and three sample surfaces in a digest panel](assets/hero.gif)

**subscope reads Reddit for you and finds threads where someone is actively shopping for what you sell.**

Every morning, ~10 of the strongest threads land directly in your Claude Code chat. Things like "Apollo renewal hike, what's the alternative?" or "switching from HubSpot, recommendations?". You read them, decide which deserve a reply, and write the comment yourself on Reddit. Free. No API keys. Runs inside Claude Code.

```bash
/plugin install dancolta/subscope
/subscope:onboard       # 3 questions, 60s
/subscope:run           # your first scan
```

</div>

---

## Who this is for

### B2B SaaS
_Project management, analytics, productivity, HR, anything per-seat._

subscope catches posts like *"We outgrew Notion at 30 people, what's everyone moving to?"* in r/SaaS, the moment a real buyer publicly admits their current tool is broken.

### Sales or marketing tool
_CRM, outreach, automation._

It catches posts like *"Apollo just hiked our renewal 40%, what's everyone moving to?"* in r/sales the morning they go up, before the OP picks their next vendor.

### Agency or freelance practice
_Marketing, RevOps, dev work._

It catches *"Need a freelance Webflow dev who actually knows e-commerce"* in r/Entrepreneur before five other agencies pile into the comments.

### Developer tool
_API, framework, infra._

It catches *"Anyone moved off Temporal at scale? Looking for something lighter."* in r/devops while they are still in the discovery phase.

---

## What you do day to day

| Command | What it does |
|---|---|
| `/subscope:run` | Daily scan — top ~10 threads land in chat with pattern badges |
| `/subscope:judge <n>` | Deeper read on a single thread, returns intent and a reply angle |
| `/subscope:tune` | Mark surfaces good/bad/meh, the ranker adjusts to your niche |
| `/subscope:postmortem` | Auto-tracks the replies you actually send on Reddit, scores them 7 days later (upvotes, follow-ups, removal status), feeds that back into next week's rankings |

**The tool gets sharper for your specific niche the longer you use it, because it learns from what actually worked.**

---

## The 8 signals it catches

Each pattern has its own scoring path. A `pricing-rage` thread and an `alternative-seeking` thread rank separately because they are different buying moments.

| Pattern | What it captures |
|---|---|
| `pricing-rage` | Public anger about a renewal hike |
| `churn` | "Looking to ditch X for..." threads |
| `build-vs-buy` | Debates with actual numbers attached |
| `rfp-bait` | A vs B vs C comparison threads |
| `stack-audit` | "Help me cut tools from my stack" posts |
| `alternative-seeking` | Explicit "alternative to X?" threads |
| `resurrect` | Quality threads aged 6 to 18 months still getting traffic |
| `rivals` | Any mention of a brand in your competitive set |

---

## How it works

![workflow demo: terminal types /subscope:run, counters increment, five ranked surfaces populate with pattern badges](assets/workflow.gif)

You answer 3 questions about your product during `/subscope:onboard` (60 seconds). subscope builds a profile that maps which subreddits to scan and what buying signals to watch for.

Subreddits are split into two tiers. Tier 1 are your bullseye subs, scanned every morning. Tier 2 are broader subs where only standouts surface. Throwaway accounts are filtered before scoring. What's left gets ranked by signal strength: how fresh the post is, how fast it's gaining upvotes and comments, keyword density, and which of 8 buying-intent patterns it matches.

---

## Integrations

subscope slots into the tools you already use.

| Integration | Why | Setup |
|---|---|---|
| Reddit OAuth | Recommended. 10x rate budget, enables postmortem reply tracking | Free script app at reddit.com/prefs/apps |
| Bulk LLM grading | Optional. Grade posts at scale via any of 5 providers | One API key in setup wizard |
| Notion daily triage DB | Optional. 14-column triage schema with OP score | ~5 min |
| Slack daily push | Optional. Formatted morning digest to your channel | Paste one webhook URL |
| Obsidian weekly digest | Optional. Weekly pulse via `/subscope:pulse` | Vault path in config |

**Supported LLM providers for bulk grading:** Anthropic, OpenAI, Groq, OpenRouter, Ollama. Provider is auto-detected from your key prefix. Without a key, the regex gate runs alone and `/subscope:judge` handles ad-hoc grading at no extra cost.

---

<details>
<summary>All 16 skills</summary>

The 4 core skills above plus 12 pattern-scan and utility skills:

`/subscope:onboard` `/subscope:profile` `/subscope:setup` `/subscope:pulse`
`/subscope:pricing-rage` `/subscope:churn` `/subscope:build-vs-buy` `/subscope:rfp-bait`
`/subscope:stack-audit` `/subscope:alternative-seeking` `/subscope:resurrect` `/subscope:rivals`

Each pattern skill runs `fetch-score --mode <pattern>` so you can scan a single intent class on demand. All 16 listed in [`skills/`](skills/).

</details>

---

## Setup

Run `/subscope:setup`. The wizard presents each optional layer. Skip any of them and the default runs without it. Runs on day 1 with zero API keys.

Need more than 10 results per run? `--max-surfaces N` raises the cap.

Config lives at `~/.config/subscope/`. Every file is written with `chmod 600`.

---

## Privacy

- All data is local. SQLite at `~/.local/share/subscope/subscope.sqlite`, config at `~/.config/subscope/`. Both `0o600`.
- Reddit OAuth credentials are written atomically so the file is never world-readable at any point during creation.
- When bulk LLM grading is enabled, post bodies (capped at 800 chars) go to your configured endpoint. A one-time notice appears the first time. Zero telemetry otherwise.

---

You find the thread. You write the reply. subscope handles the part that would take you an hour every morning.

MIT. See [LICENSE](LICENSE).
