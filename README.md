<div align="center">

# subscope

[![License: MIT](https://img.shields.io/github/license/dancolta/subscope?color=blue)](LICENSE) [![Release](https://img.shields.io/github/v/release/dancolta/subscope)](https://github.com/dancolta/subscope/releases) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

![subscope hero: 8-bit arcade scanner UI with subreddit feeds, skill chips lighting up, and three sample surfaces in a digest panel](assets/hero.gif)

**subscope reads Reddit for you and finds threads where someone is actively shopping for what you sell.**

Run it whenever you want. Each scan returns ~10 of the strongest threads directly in your Claude Code chat. Things like "Apollo renewal hike, what's the alternative?" or "switching from HubSpot, recommendations?". You read them, decide which deserve a reply, and write the comment yourself on Reddit. Free. No API keys. Runs inside Claude Code.

```bash
/plugin install dancolta/subscope
/subscope:onboard       # mandatory targeting setup, ends with your first scan
/subscope:run           # any subsequent scan
```

</div>

---

## Who this is for

### 🧱 B2B SaaS founder
_Project management, analytics, productivity, HR, anything per-seat._

You run `/subscope:run` at 11am and it surfaces a thread posted two hours ago: *"30-person team, Notion is a mess, what's next?"* It has 6 replies. You write comment 7. By tomorrow it has 80 replies and a locked-in shortlist. The scan returned it while the OP was still active because you ran it early, not because anything was watching.

### 📈 Sales or marketing tool
_CRM, outreach, automation._

A sales ops manager posts in r/sales: *"Apollo just hiked us 40%, who's everyone moving to?"* You run a scan, the thread is four hours old with 12 replies. The OP has not started booking demos yet. That is the window. You get in before the vendor pile-on hardens into a shortlist, because you checked while the thread was still forming.

### 🛠️ Agency or freelance practice
_Marketing, RevOps, dev work._

This one is incoming demand, not competitor defection. You run the scan and it pulls a post from this morning: *"Need a freelance Webflow dev who actually knows e-commerce, 4 weeks part-time."* Eight people have replied with identical pitches. You are still early enough to write something different. The scan did not hand you the brief, it found it in the subs you configured. You ran it, you got the signal, you still have time to act on it.

### 🧑‍💻 Developer tool
_API, framework, infra._

You run `/subscope:run` and one of the surfaces is an engineer asking: *"Anyone moved off Temporal at scale? Looking for something lighter?"* The thread is a few hours old. They are comparing options, reading docs, not yet committed. You have an input into what they evaluate. A week from now they are justifying a tool they already picked. You ran the scan when the thread was still in discovery.

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

## What you do day to day

| Command | What it does |
|---|---|
| `/subscope:run` | Manual scan, top ~10 threads land in chat with pattern badges |
| `/subscope:judge <n>` | Deeper read on a single thread, returns intent and a reply angle |
| `/subscope:tune` | Mark surfaces good/bad/meh, the ranker adjusts to your niche |
| `/subscope:postmortem` | Auto-tracks the replies you actually send on Reddit, scores them 7 days later (upvotes, follow-ups, removal status), feeds that back into next week's rankings |

**The tool gets sharper for your specific niche the longer you use it, because it learns from what actually worked.**

---

## How it works

![workflow demo: terminal types /subscope:run, counters increment, five ranked surfaces populate with pattern badges](assets/workflow.gif)

**The setup is where the targeting actually happens.** Every install goes through one onboarding flow: `/subscope:onboard`. No shortcut, no fast path. You won't see a single scored post until the flow ends, that's the tradeoff.

Here's what the flow walks you through:

1. **Paste 2-3 URLs.** Your homepage plus a couple of case studies, blog posts, or pricing pages. subscope reads them and pulls positioning, buyer language, and the tools your case studies mention.
2. **Auto-enrich (when available).** DataForSEO for competitor domains and ranked keywords, Firecrawl for deeper crawl, a 30-second Reddit warm-scan against archetype-seeded subs. If DataForSEO and Firecrawl aren't configured, the flow falls back to URL parsing + your answers. Inference quality drops, the profile still ships.
3. **Review card.** A high-level sanity check on everything inferred so far: ICP, competitors, candidate subreddits in Tier 1 / Tier 2 buckets, keyword sets, and example pain posts seen this week. You correct anything obviously wrong inline before the deeper questions begin.
4. **8 deep questions.** Field-level confirm or refine. Each question shows the inferred answer pre-filled with a confidence score. High-confidence ones are 5-second taps. Low-confidence ones (competitor anchor, the literal pain quote your buyers used) get real attention because URLs can't infer them.
5. **Reddit access.** Public JSON (zero setup, works now) or OAuth (~2 min, 10x rate budget, enables postmortem reply tracking).
6. **Destinations.** Chat (default), Notion, Slack, Obsidian, multi-select.
7. **First scan runs.** Top ~10 threads land in chat with pattern badges.

The flow writes four config files at `~/.config/subscope/` (subreddits, keywords, brand-anchor, example-pains). Every future scan reads them. This is the actual product differentiator: the profile is built specifically for you, not pulled from a generic SaaS-founder template.

Need to refine later? `/subscope:profile` is a per-section deep dive: "redo just the competitor anchor", "rebuild pain language", "swap a subreddit tier". Not a full re-interview, just the section that's drifted.

Once your profile is in place, each scan fetches new posts from your configured subs, filters throwaway accounts before scoring, and ranks what's left by signal strength: freshness, upvote velocity, comment velocity, keyword density, and which of 8 buying-intent patterns the post matches. Tier 1 surfaces every run. Tier 2 surfaces only when a standout appears.

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

The 4 core skills above are what you'll use day to day. The other 12 are setup, pattern-specific scans, and one-off utilities.

**Setup and onboarding**

| Skill | What it does |
|---|---|
| `/subscope:setup` | Standalone configuration wizard for OAuth, LLM provider, surface choice (chat / Notion / Slack / Obsidian), and dry-run validation. Most users don't need this — `/subscope:onboard` covers it. |
| `/subscope:onboard` | Mandatory first-run flow. Paste your homepage + 2-3 case study URLs, auto-enrich via DataForSEO/Firecrawl/warm-scan when available, review the inferred ICP/competitors/subreddits/keywords in one card, lock the 8 deep questions field by field, pick Reddit access + destinations, and the first scan runs at the end. No fast path. |
| `/subscope:profile` | Per-section deep dive for refining an existing profile. "Redo competitor anchor", "rebuild pain language", "swap a subreddit tier". Not a full re-interview, just the section that's drifted. |

**Pattern-specific scans** (each runs `fetch-score --mode <pattern>` so you can target one intent class on demand)

| Skill | What it catches |
|---|---|
| `/subscope:pricing-rage` | Renewal-hike rage threads. Cooling queue skipped because these go cold fast. |
| `/subscope:churn` | "Looking to ditch X for..." posts. Active switching intent. |
| `/subscope:build-vs-buy` | In-house vs SaaS debates with actual numbers (engineering hours, TCO). |
| `/subscope:rfp-bait` | "A vs B vs C" comparison threads where multiple vendors are named. |
| `/subscope:stack-audit` | Posts where someone lists 8+ tools and asks what to cut. Highest-intent format. |
| `/subscope:resurrect` | 6 to 18-month-old quality threads that still pull Google traffic. Late comments compound forever. |
| `/subscope:rivals` | Today's mentions of any competitor in your `brand_anchor` list. |

**Utilities**

| Skill | What it does |
|---|---|
| `/subscope:pulse` | Weekly Obsidian digest. Builds a markdown summary of the week's surfaces and writes it to your vault. |
| `/subscope:op-vet <user>` | Vet a single Reddit user before replying. Returns karma, age, audience-fit breakdown, GO / HOLD / SKIP verdict. |

Skill source files in [`skills/`](skills/).

</details>

---

## Setup

Run `/subscope:setup`. The wizard presents each optional layer. Skip any of them and the default runs without it. Runs on day 1 with zero API keys.

Need more than 10 results per run? `--max-surfaces N` raises the cap.

Want recurring scans? Wrap `subscope fetch-score` in a cron job or launchd service. The SQLite cursor handles dedup across runs, so you never see the same thread twice.

Config lives at `~/.config/subscope/`. Every file is written with `chmod 600`.

---

## Privacy

- All data is local. SQLite at `~/.local/share/subscope/subscope.sqlite`, config at `~/.config/subscope/`. Both `0o600`.
- Reddit OAuth credentials are written atomically so the file is never world-readable at any point during creation.
- When bulk LLM grading is enabled, post bodies (capped at 800 chars) go to your configured endpoint. A one-time notice appears the first time. Zero telemetry otherwise.

---

You find the thread. You write the reply. subscope handles the part that would take you an hour every morning.

MIT. See [LICENSE](LICENSE).
