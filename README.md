<div align="center">

# subscope

[![License: MIT](https://img.shields.io/github/license/dancolta/subscope?color=blue)](LICENSE) [![Release](https://img.shields.io/github/v/release/dancolta/subscope)](https://github.com/dancolta/subscope/releases) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

![subscope hero: 8-bit arcade scanner, purple grid background, SUBSCOPE title pulsing as the magenta scan-line sweeps across, pattern words like PRICING-RAGE / CHURN / ALTERNATIVES flashing in colored brackets](assets/hero.gif)

**subscope reads Reddit for you and finds threads where someone is actively shopping for what you sell.**

Run it whenever you want. Each scan returns 5 to 12 of the strongest threads directly in your Claude Code chat. Things like "Apollo renewal hike, what's the alternative?" or "switching from HubSpot, recommendations?". You read them, decide which deserve a reply, and write the comment yourself on Reddit. Free. No API keys. Runs inside Claude Code.

```bash
/plugin install dancolta/subscope
/subscope-onboard       # mandatory targeting setup, ends with your first scan
/subscope-run           # any subsequent scan
```

</div>

---

## Who this is for

### 🧱 B2B SaaS founder
_Project management, analytics, productivity, HR, anything per-seat._

You run `/subscope-run` at 11am and it surfaces a thread posted two hours ago: *"30-person team, Notion is a mess, what's next?"* It has 6 replies. You write comment 7. By tomorrow it has 80 replies and a locked-in shortlist. The scan returned it while the OP was still active because you ran it early, not because anything was watching.

### 📈 Sales or marketing tool
_CRM, outreach, automation._

A sales ops manager posts in r/sales: *"Apollo just hiked us 40%, who's everyone moving to?"* You run a scan, the thread is four hours old with 12 replies. The OP has not started booking demos yet. That is the window. You get in before the vendor pile-on hardens into a shortlist, because you checked while the thread was still forming.

### 🛠️ Agency or freelance practice
_Marketing, RevOps, dev work._

This one is incoming demand, not competitor defection. You run the scan and it pulls a post from this morning: *"Need a freelance Webflow dev who actually knows e-commerce, 4 weeks part-time."* Eight people have replied with identical pitches. You are still early enough to write something different. The scan did not hand you the brief, it found it in the subs you configured. You ran it, you got the signal, you still have time to act on it.

### 🧑‍💻 Developer tool
_API, framework, infra._

You run `/subscope-run` and one of the surfaces is an engineer asking: *"Anyone moved off Temporal at scale? Looking for something lighter?"* The thread is a few hours old. They are comparing options, reading docs, not yet committed. You have an input into what they evaluate. A week from now they are justifying a tool they already picked. You ran the scan when the thread was still in discovery.

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
| `/subscope-run` | Manual scan, 5 to 12 threads land in chat with pattern badges. Posts under 24 hours old get a freshness boost so first-mover threads surface even when the keyword gate barely catches them. |
| `/subscope-judge <n>` | Deeper read on a single thread, returns intent and a reply angle |
| `/subscope-tune` | Mark surfaces good/bad/meh, the ranker adjusts to your niche |

**The tool gets sharper for your specific niche the longer you use it, because `/subscope-tune` back-propagates your good/bad/meh judgments into per-sub weights and keyword scores.**

---

## How it works

![workflow demo: terminal types /subscope-run, counters increment, five ranked surfaces populate with pattern badges](assets/workflow.gif)

**The setup is where the targeting actually happens.** Every install goes through one onboarding flow: `/subscope-onboard`. No shortcut, no fast path. You won't see a single scored post until the flow ends, that's the tradeoff.

Seven turns, plain questions, one confirmation, optional integrations, first scan:

1. **Paste URLs.** Homepage plus optional case studies, blog posts, or pricing pages. One per line. subscope scrapes them silently in the background while you answer the next three questions, pulling positioning, competitor names, buyer titles, and pain phrasing.
2. **What do you sell?** One line.
3. **Who buys it?** A job title is enough.
4. **What is the pain?** A real customer quote is gold. Paraphrase is fine.
5. **Confirm the scan card.** What you sell, buyers, pain pattern, your competitor list, and the recommended subreddits. Each subreddit carries a confidence score, a one-line reason it was picked, and a clickable link to a real buyer thread posted in the last 7 days (see ["How subscope finds your subreddits"](#how-subscope-finds-your-subreddits) below). Reply `go` to lock the card, or tell the flow what to fix and it re-renders.
6. **Connect integrations (optional).** One menu, multi-pick. DataForSEO, Firecrawl, Notion, Slack, Obsidian. Reply `skip` to skip the whole menu, or `skip` inside any sub-prompt to drop just that one. A failed paste re-asks once, then moves on. The scan still runs.
7. **First scan runs.** If DataForSEO or Firecrawl keys were set up, the engine warms the enrichment cache against your homepage once. Then 5 to 12 threads land in chat with pattern badges, grouped by tier, with a plain-English summary of what was filtered before scoring (subreddit rules, author quality, content rules).

The flow writes config files to `~/.config/subscope/` (subreddits, keywords, brand-anchor, example-pains, plus one file per connected integration). Every future scan reads them. The product differentiator: the profile is built specifically for you from your URLs, your competitor brands, and live Reddit threads matching your actual pain phrasing, not pulled from a generic SaaS-founder template.

Need to refine later? `/subscope-profile` is a per-section deep dive: `redo just the competitor anchor`, `rebuild pain language`, `swap a subreddit`. Not a full re-interview, just the section that's drifted.

Once your profile is in place, each scan fetches new posts from your configured subs, filters throwaway accounts before scoring, and ranks what's left by signal strength: freshness, upvote velocity, comment velocity, keyword density, and which of 8 buying-intent patterns the post matches. Tier 1 surfaces every run. Tier 2 surfaces only when a standout appears.

---

## How subscope finds your subreddits

When you onboard, subscope does not hand you a generic list of r/SaaS and r/Entrepreneur. It does not hand you a list of subreddits at all. It hands you a list of people asking for what you sell, with the receipts.

Here is what happens during discovery:

1. **Live search, not a template.** subscope searches Reddit in real time using your own pain phrasing and your competitors' brand names. The subreddits it recommends come from real conversations happening this week, not a founder-archetype lookup. Two people selling different things get different subreddits.

2. **A real buyer thread, dated, on every result.** A subreddit only makes the list if it has a genuine buyer thread from the **last 7 days**. Each recommendation includes a direct link to that exact thread plus an absolute timestamp. A subreddit name is a guess. A live buyer thread is evidence.

3. **Claude reviews every candidate.** A keyword pass finds candidates, then Claude (the AI running the plugin) reads each one and drops the false positives that keyword matching cannot catch: career questions ("Software Engineering vs Dentistry"), self-promoters announcing their own newsletter, and brand-name collisions (the law software "Clio" vs the Renault "Clio", the scheduling app "Homebase" vs the Eufy camera "Homebase"). You only see subreddits with a confirmed buyer.

4. **A plain-English reason + a confidence score.** Each result tells you why it was picked, naming only signals that are actually in the thread, plus a 0-100 confidence so you know which to trust most. A result looks like this:

   ```
   [64] r/LawFirm   buyer post 2026-05-28 07:29 UTC
        "Best tool for document parsing?"
        Buyer post 14h ago. Someone asking about a "tool" with buying intent ("best").
   ```

**Verify it yourself.** Click the thread link on any recommendation. If it is not a real person shopping for what you sell, the tool failed. That is the bar we hold it to, and you can check it in one click.

**Precision over volume, on purpose.** In a narrow B2B niche you might see one to three subreddits, or occasionally "no active buyer this week." That honest result beats padding the list with noise. subscope never auto-posts and never invents a match. You find the thread, you decide, you write the reply.

---

## Integrations

subscope slots into the tools you already use.

| Integration | Why | Setup |
|---|---|---|
| Bulk LLM grading | Optional. Grade posts at scale via any of 5 providers | One API key in setup wizard |
| DataForSEO | Optional. SERP-verified competitor list for brand-anchor seeding + ranked-keyword extension | Paste login + API password during onboarding |
| Firecrawl | Optional. Cleaner positioning extraction from your homepage + link context on surfaced Reddit posts that cite comparison pages | Paste `fc-…` API key during onboarding |
| Notion daily triage DB | Optional. 14-column triage schema with OP score | ~5 min |
| Slack daily push | Optional. Formatted morning digest to your channel | Paste one webhook URL |
| Obsidian weekly digest | Optional. Weekly pulse via `/subscope-pulse` | Vault path in config |

**Supported LLM providers for bulk grading:** Anthropic, OpenAI, Groq, OpenRouter, Ollama. Provider is auto-detected from your key prefix. Without a key, the regex gate runs alone and `/subscope-judge` handles ad-hoc grading at no extra cost.

**DataForSEO + Firecrawl behavior.** Both are silent no-ops when no key is present. When configured, DataForSEO seeds your `brand_anchor.yml` competitor list during onboarding (`competitors_domain` lookup) and Firecrawl scrapes your homepage for richer positioning copy. Every result is cached in SQLite (30 days for DFS, 90 days for Firecrawl). Daily scans are cache-read only and never touch the network for enrichment. Disable per-run with `--no-enrich`, globally with `SUBSCOPE_NO_ENRICH=1`.

---

<details>
<summary>All 15 skills</summary>

The 3 core skills above are what you'll use day to day. The other 12 are setup, pattern-specific scans, and one-off utilities.

**Setup and onboarding**

| Skill | What it does |
|---|---|
| `/subscope-setup` | Standalone configuration wizard for LLM provider, surface choice (chat / Notion / Slack / Obsidian), and dry-run validation. Most users don't need this; `/subscope-onboard` covers it. |
| `/subscope-onboard` | Mandatory first-run flow. Seven turns: paste URLs, answer what-you-sell / who-buys-it / what-is-the-pain, confirm the targeting card, pick optional integrations (DataForSEO, Firecrawl, Notion, Slack, Obsidian), and the first scan runs at the end. No fast path. |
| `/subscope-profile` | Per-section deep dive for refining an existing profile. "Redo competitor anchor", "rebuild pain language", "swap a subreddit". Not a full re-interview, just the section that's drifted. |

**Pattern-specific scans** (each runs `fetch-score --mode <pattern>` so you can target one intent class on demand)

| Skill | What it catches |
|---|---|
| `/subscope-pricing-rage` | Renewal-hike rage threads. Cooling queue skipped because these go cold fast. |
| `/subscope-churn` | "Looking to ditch X for..." posts. Active switching intent. |
| `/subscope-build-vs-buy` | In-house vs SaaS debates with actual numbers (engineering hours, TCO). |
| `/subscope-rfp-bait` | "A vs B vs C" comparison threads where multiple vendors are named. |
| `/subscope-stack-audit` | Posts where someone lists 8+ tools and asks what to cut. Highest-intent format. |
| `/subscope-resurrect` | 6 to 18-month-old quality threads that still pull Google traffic. Late comments compound forever. |
| `/subscope-rivals` | Today's mentions of any competitor in your `brand_anchor` list. |

**Utilities**

| Skill | What it does |
|---|---|
| `/subscope-pulse` | Weekly Obsidian digest. Builds a markdown summary of the week's surfaces and writes it to your vault. |
| `/subscope-op-vet <user>` | Vet a single Reddit user before replying. Returns karma, age, audience-fit breakdown, GO / HOLD / SKIP verdict. |

Skill source files in [`skills/`](skills/).

</details>

---

## Setup

Run `/subscope-setup`. The wizard presents each optional layer. Skip any of them and the default runs without it. Runs on day 1 with zero API keys.

Need more than 10 results per run? `--max-surfaces N` raises the cap.

Want to tune the scan without touching code? Three knobs in `~/.config/subscope/weights.yml`:
- `daily_output.minimum` (default 5) and `tier2_per_sub_cap` (default 2) control how aggressively backfill kicks in when the gate pool is thin.
- `freshness_floor.max_age_hours` / `max_promoted` (defaults 24h / 3 per run) control how many sub-24-hour posts get auto-promoted past the keyword gate.
- `author_vet.min_comment_karma` / `min_account_age_days` (defaults 50 / 30) control OP-quality strictness. Lower these when the daily list runs dry.

Want recurring scans? Wrap `subscope fetch-score` in a cron job or launchd service. The SQLite cursor handles dedup across runs, so you never see the same thread twice.

Config lives at `~/.config/subscope/`. Every file is written with `chmod 600`.

---

## Privacy

- All data is local. SQLite at `~/.local/share/subscope/subscope.sqlite`, config at `~/.config/subscope/`. Both `0o600`.
- All credentials (LLM, DataForSEO, Firecrawl, Notion, Slack) are written atomically with `0o600` from the moment they appear on disk, no umask race.
- When bulk LLM grading or DataForSEO or Firecrawl is enabled, the relevant data (post bodies capped at 800 chars for LLM, your homepage for Firecrawl, domain queries for DataForSEO) goes to your configured endpoint. A one-time stderr notice appears the first time per provider. Zero telemetry otherwise.

---

You find the thread. You write the reply. subscope handles the part that would take you an hour every morning.

MIT. See [LICENSE](LICENSE).
