# reddit-engage

> Claude Code plugin that surfaces Reddit pain posts. You write the reply.

[![Version](https://img.shields.io/github/v/tag/dancolta/reddit-engage?label=version&color=blue)](https://github.com/dancolta/reddit-engage/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-plugin-orange)](https://docs.claude.com/en/docs/claude-code/plugins)

> [!WARNING]
> **Not an auto-poster.** Devi AI and ReplyGuy auto-draft your replies. `reddit-engage` refuses to. No auto-comments. No account rotation. No shadowban roulette. **The automation stops where the conversation starts.**

![reddit-engage arcade hero: 8-bit pixel-art animation of a small orange-and-teal sprite walking past floating subreddit name plaques (r/<your-niche>, r/founders, r/startups, r/SaaS, r/<your-icp>, r/sysadmin). HUD chips read SURF 12/15 and DEDUP ON. A scrolling ticker cycles generic pain-post headlines like TOOL X TOO EXPENSIVE, ALTERNATIVE TO Y?, STACK COST $$$. Title bar REDDIT-ENGAGE, subtitle DAILY PAIN-POST RADAR. Read-only surfacing tool, not an auto-poster.](assets/hero.gif)

```bash
# in Claude Code
/plugin install dancolta/reddit-engage
/reddit-engage:run
```

`reddit-engage` scans the subreddits you care about every morning, gates posts by tier-aware thresholds + author vetting + optional LLM classification, and hands you a curated list of up to 15 pain posts worth a human reply. SQLite enforces permanent deduplication — the same post never appears twice.

## Plug-and-play, with optional add-ons

The default install needs **zero API keys**. Pick a preset, run `/reddit-engage:run`, get a daily list inline in chat. That's it.

| Layer | What it gives you | What it needs |
|---|---|---|
| **Default** | Regex-gated daily scan, inline output | Nothing — works on day 1 |
| **Reddit OAuth** (recommended) | 10× rate budget + postmortem reply tracking | 5-min app registration ([docs](docs/setup-oauth.md)) |
| **Interactive judgment** | `/reddit-engage:judge <n>` — single-surface classification using your Claude Code subscription | Already in Claude Code |
| **Bulk LLM grading** | Every regex-passing post LLM-graded automatically | `ANTHROPIC_API_KEY` env (~$0.50/day) |
| **Notion triage board** | Persistent surface board with Hot list / Drafting / Pattern pulse / Replied views | Notion API key + 3-min setup ([docs](docs/setup-notion.md)) |
| **Obsidian pulse digest** | Weekly markdown digest in your vault | Vault path |

Skip any layer, the others still work. Add layers later without re-installing.

**Made for one user, designed for any.** Pick from 4 industry presets (B2B SaaS founder / agency owner / indie hacker / consultant) or bring your own subs + keywords. The engine is identical.

## How it works

1. **Configure once.** Drop your subs, your bucket keywords, and (optionally) your blog post knowledge map into `config/*.yml`. Five minutes.
2. **Run daily.** `/reddit-engage` from Claude Code fetches `/r/<sub>/new` for each sub, gates posts (pain-keyword density, upvote velocity, post age), scores survivors, and surfaces up to 15.
3. **You reply.** The list prints inline and syncs to a Notion board (cleared each run). You read, decide, write the reply yourself on Reddit. SQLite remembers every surfaced post forever, so the same thread never returns.

## Configure it for your niche

The skill ships with one worked example (NodeSparks, the maintainer's setup). Replacing it with yours is four files.

### 1. Pick your subs ([`config/subreddits.yml`](config/subreddits.yml))

Each entry needs `name`, `tier` (1 for daily, 2 for opportunistic), `bucket` (`operator` or `builder`), `weight`, and an optional list of backing blog references.

```yaml
subreddits:
  - {name: <sub_you_scan_daily>, tier: 1, bucket: operator, weight: 1.2,
     backing_blogs: [YourPost1, YourPost2],
     gate_overrides: {post_age_hours: 4, comment_ceiling: 25, velocity_floor: 5, pain_keywords_min: 1}}

  - {name: <niche_sub>, tier: 2, bucket: operator, saturation: wide_open, weight: 1.3,
     backing_blogs: [YourPost1]}

blog_aliases:
  YourPost1: https://yourdomain.com/post-slug
  YourPost2: https://yourdomain.com/another-post
```

**Tier 1 vs Tier 2.** Tier 1 subs you scan daily and engage consistently. Tier 2 are opportunistic, scanned with strict gates so only gold-tier threads surface. Recommended: 3 to 5 Tier 1 subs, 10 to 20 Tier 2 subs.

**Saturation tags** apply to Tier 2 only and modify gate strictness:
- `wide_open` (relaxed gate). You are likely the only technical voice in this sub.
- `medium`. Standard gate.
- `high` (extra strict). Saturated with other consultants and operators answering the same threads.

### 2. Pick your pain vocabulary ([`config/keywords.yml`](config/keywords.yml))

Three buckets: phrases shared across all subs, operator-specific phrases (SaaS-cost rants, tool complaints), and builder-specific phrases (self-host, stack choices).

```yaml
shared:
  - "alternative to"
  - "too expensive"
  - "build vs buy"

operator:
  - "<a SaaS tool you target>"
  - "renewal"
  - "per seat"

builder:
  - "self-host"
  - "Hetzner"
  - "<your favorite open-source stack>"
```

The keyword density gate fires when a post hits N+ keywords from `shared` + the sub's `bucket` list (1 for Tier 1, 3 for Tier 2, 2 if `wide_open`).

### 3. Wire your knowledge map ([`config/blog-map.yml`](config/blog-map.yml))

Optional but valuable. Each entry teaches the skill which posts of yours back replies in which threads. The scoring formula gives a 25-point bonus per matched blog post (capped at 50 for two matches), so a "perfect fit" thread rises to the top.

```yaml
blog_posts:
  - url: https://yourdomain.com/your-post-slug
    title: "Your post title"
    pain: "1-line description of the pain it addresses"
    saas_replaced: "the SaaS/category your post unseats"
    persona: "who the post is for"
    stack: "the alternative stack you propose"
    keywords:
      - "specific phrase from your post"
      - "another signature phrase"
```

If you don't have blog content yet, skip this file. The skill still surfaces posts, just without the blog-coverage bonus.

### 4. Tune scoring ([`config/weights.yml`](config/weights.yml))

Sensible defaults are pre-locked. Tweak only if you understand why:

- `tier1_gates.velocity_floor` (default 3 upvotes/hour). Raise if your subs are noisy.
- `tier2_gates.pain_keywords_min` (default 3). Lower to 2 if your bucket keyword list is thin.
- `scoring.blog_coverage_bonus.points_per_match` (default 25). Raise if blog-backed replies convert way better than generic ones.
- `daily_output.hard_ceiling` (default 15). Your daily inbox size.

## Install (Claude Code plugin)

`reddit-engage` ships as a Claude Code plugin — install it from the GitHub repo:

```bash
# from inside Claude Code
/plugin install dancolta/reddit-engage
```

Claude Code prompts you for the [user config](#user-config) on install. Secrets land in your OS keychain.

Then install the Python engine (one-time, for the fetch + score + dedup work):

```bash
git clone https://github.com/dancolta/reddit-engage ~/Work/reddit-engage
cd ~/Work/reddit-engage
python3 -m pip install -e .
# optional install groups:
python3 -m pip install -e '.[reddit,anthropic,notion]'     # OAuth, classifier, Notion sync
python3 -m pip install -e '.[vec]'                          # semantic dedup (Phase 2)
```

### User config

On install Claude Code asks for:

| Key | Required? | What |
|---|---|---|
| `reddit_client_id` | yes | From https://reddit.com/prefs/apps (script-type app) |
| `reddit_client_secret` | yes | Same registration |
| `reddit_username` | yes | Your username (no `u/`) |
| `notion_api_key` | no | Enables Notion daily-triage sync |
| `notion_database_id` | if Notion enabled | The 32-char database ID |
| `obsidian_vault_path` | no | Absolute path to vault for weekly pulse digest |

### First-time setup

```
# from Claude Code, once:
/reddit-engage:setup
```

(Setup wizard is a stub today — see [PLAN.md](PLAN.md) §4 Phase 7 for the full implementation roadmap. Until then, copy `config/*.yml` from this repo into `~/.config/reddit-engage/` to bootstrap.)

## Daily run

In Claude Code:

```
/reddit-engage:run
```

That's it. Print 5-15 surfaces inline; optionally synced to Notion.

## Classification: three-tier cost model

The default `:run` uses **regex + author-vet + tier gates only** — zero LLM cost, zero API key required. Works on day-1 install. Most posts surfaced by the regex gate are already high quality; you don't need LLM grading on every single one.

When you DO want LLM judgment, pick the right tool:

| Use case | Tool | Cost | Auth |
|---|---|---|---|
| Default daily run | `/reddit-engage:run` (regex-only) | $0 | None |
| "Should I reply to surface #3?" | `/reddit-engage:judge 3` | $0 (uses Claude subscription) | Claude Code login |
| Every regex-passing post LLM-graded automatically | Set `ANTHROPIC_API_KEY` env, `:run` auto-engages SDK | ~$0.50/day @ 5K posts (Haiku 4.5 + prompt caching) | Anthropic API key |

The bulk SDK path is opt-in for a reason: it's the only one that needs a separate API key. Most users won't need it. The `judge` skill covers 90% of cases at zero marginal cost.

<details>
<summary><strong>11 pattern-aware sub-skills</strong> (click to expand)</summary>

| Skill | What it finds |
|---|---|
| `/reddit-engage:run` | General pain + named SaaS (default daily scan) |
| `/reddit-engage:judge <n>` | Interactive single-surface classifier via Claude subscription — free |
| `/reddit-engage:setup` | Conversational onboarding wizard |
| `/reddit-engage:stack-audit` | OPs listing 8+ tools, asking how to consolidate |
| `/reddit-engage:churn` | "Canceling X" / "switching from X" + vendor name |
| `/reddit-engage:pricing-rage` | Price-hike threads (cyclical Q1/Q3 spikes) |
| `/reddit-engage:build-vs-buy` | Explicit debate threads with numeric arguments |
| `/reddit-engage:rfp-bait` | "X vs Y vs Z" comparison threads |
| `/reddit-engage:resurrect` | 6–18 month-old threads still getting Google traffic |
| `/reddit-engage:rivals <brand>` | Configurable competitor-mention digest |
| `/reddit-engage:op-vet <user>` | Score an OP profile pre-reply (GO / HOLD / SKIP) |
| `/reddit-engage:postmortem` | 7-day outcome on your replies (auto-detected via OAuth) |
| `/reddit-engage:pulse` | Weekly sub × surface heat-map → Obsidian |

</details>

## Compared

Named comparison vs the live category. The constraint row at the bottom is deliberate — owning it is the point.

|  | **reddit-engage** | Devi AI | ReplyGuy | F5Bot | Syften | Brand24 | Manual |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Zero cost to start | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ | ✓ |
| Works day-1, no API keys | ✓ | ✗ | ✗ | partial | ✗ | ✗ | ✓ |
| Runs inside your IDE / terminal | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Pattern-aware curation (not keyword spam) | ✓ | partial | partial | ✗ | ✗ | partial | ✗ |
| Never auto-comments or drafts replies | ✓ | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ |
| No account rotation / shadowban risk | ✓ | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ |
| Optional LLM judgment, user-controlled | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Notion + Obsidian sync for builder workflow | ✓ | ✗ | ✗ | ✗ | ✗ | partial | ✗ |
| Open source / MIT / self-hosted | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | n/a |
| Scales past one human's attention | ✗ | ✓ | ✓ | partial | ✓ | ✓ | ✗ |

That last row is a feature, not a bug. `reddit-engage` is the tool a technical founder actually opens at 8am. It's not a Reddit growth machine. If you wanted one of those, the table above tells you where to look.

## Why two tiers

**Tier 1** is the small set of subs you scan every morning to build account recognition and compound on AI Overview citations. Looser gates because consistent engagement is the goal.

**Tier 2** is a wider net you scan opportunistically. 95% of posts there should never surface. Only gold-tier hits do: 3+ pain keywords, velocity > 8 upvotes/hour, age < 24h.

Recommended starting layout for any niche:

- 3 to 5 Tier 1 subs where your ICP literally lives and complains.
- 10 to 20 Tier 2 subs that are adjacent or niche enough that hits are rare but high-quality.

The full subreddit list ships with the maintainer's NodeSparks setup (22 subs total). Use it as a template, then swap to your own.

## Architecture

```
Plugin (this repo, ships to Claude Code)
  .claude-plugin/plugin.json                userConfig + manifest
  skills/run/SKILL.md                       /reddit-engage:run daily orchestrator
  skills/setup/SKILL.md                     /reddit-engage:setup wizard (Phase 7)
  skills/<pattern>/SKILL.md                 sub-skills (Phase 3 — stack-audit, churn, …)

Engine (this repo, Python package)
  engine/reddit_engage/cli.py               setup, fetch-score, status, blog ingest
  engine/reddit_engage/lib/
    reddit_public.py                        Raw Reddit JSON (Phase 1 → PRAW OAuth)
    score.py                                Tier-aware gates + scoring formula
    store.py                                SQLite + XDG path resolution
    classify.py                             LLM intent classifier (Phase 2)
    dedup_vec.py                            sqlite-vec semantic dedup (Phase 2 opt-in)
    blog_extractor.py                       Rule-based keyword extractor
    output.py                               Inline markdown renderer
  engine/scripts/migrate_to_xdg.py          one-shot legacy DB migration

Per-user state (XDG conventions)
  ~/.config/reddit-engage/                  oauth.json, llm.json, *.yml configs
  ~/.local/share/reddit-engage/             reddit-engage.sqlite, logs
```

Python handles fetch + gate + score + persistence. Claude (via SKILL.md) handles Notion / Obsidian sync. They communicate via JSON on stdout. MCP tools are scoped to the Claude session; Python subprocess cannot reach them, so the orchestration sits in the right place.

<details>
<summary>Schema reference</summary>

The SQLite schema lives in [`engine/reddit_engage/lib/store.py`](engine/reddit_engage/lib/store.py). Key invariants:

- `posts.canonical_url UNIQUE` and `posts.id PRIMARY KEY` for cross-host dedup. URL canonical form is `https://reddit.com/comments/<t3_id>/`.
- `surfaced.post_id PRIMARY KEY` is the single column that guarantees a post surfaces at most once across all time. The Notion board can be cleared on every run; SQLite remembers everything.
- `runs.notes` captures fetch and persist errors per run so failures degrade gracefully without taking down the run.

</details>

<details>
<summary>The maintainer's worked example (NodeSparks)</summary>

The repo ships with the maintainer's actual configuration:

- **5 Tier 1 subs**: `r/smallbusiness`, `r/SaaS`, `r/Entrepreneur`, `r/sales`, `r/nocode`
- **17 Tier 2 subs**: finance ops (`r/Bookkeeping`, `r/Accounting`, `r/CFO`, `r/nonprofit`), sales/RevOps (`r/SalesOperations`, `r/RevOps`, `r/coldemail`), marketing (`r/marketing`, `r/marketingautomation`, `r/CustomerSuccess`, `r/PPC`), recruiting (`r/recruiting`), devtools (`r/ExperiencedDevs`, `r/sysadmin`, `r/devops`, `r/Automate`), builder (`r/selfhosted`).
- **3 backing blog posts** (SaaS replacement playbook, Apollo alternative, Bill.com Slack-native invoice agent) at nodesparks.com.

It is a working starting point if your niche overlaps (build-vs-buy, SaaS replacement, ops automation). If not, treat the repo's `config/*.yml` as a template and replace.

</details>

## FAQ

**What is reddit-engage?**
`reddit-engage` is an open-source Claude Code plugin (MIT, v0.1.0) that scans subreddits you configure every morning, scores posts by pain-keyword density and upvote velocity, and surfaces up to 15 high-intent threads worth a human reply. It never posts or comments on your behalf.

**Does reddit-engage require a Reddit API key or any paid subscription?**
No. The default daily run uses Reddit's public JSON endpoints with zero API keys. Optional layers — Reddit OAuth for a higher rate budget, an Anthropic API key for bulk LLM grading, Notion for a triage board, and Obsidian for a weekly digest — can be added independently without reinstalling.

**How is reddit-engage different from Devi AI or ReplyGuy?**
Devi AI and ReplyGuy auto-draft replies for you and post on your behalf, which carries real shadowban risk and dilutes your voice. `reddit-engage` is fully read-only: it surfaces threads but never generates or posts replies. SQLite-enforced permanent deduplication means the same post never appears twice. The reply is the one part that has to be you.

**What sub-skills does reddit-engage include?**
`reddit-engage` ships 11 pattern-specific sub-skills beyond the default daily run: `stack-audit` (consolidation threads), `churn` (switching/canceling + vendor), `pricing-rage` (price-hike threads), `build-vs-buy` (debates with numbers), `rfp-bait` (comparison threads), `resurrect` (old posts still getting Google traffic), `rivals` (competitor mentions), `op-vet` (OP profile scoring), `judge` (single-post LLM classification at zero marginal cost via your Claude subscription), `postmortem` (7-day reply outcome tracking), and `pulse` (weekly sub heat-map to Obsidian).

**How do I install reddit-engage?**
`reddit-engage` installs as a Claude Code plugin with a single command — `/plugin install dancolta/reddit-engage` — run from inside Claude Code. The Python engine is cloned separately from github.com/dancolta/reddit-engage and installed with pip. No onboarding call, no paid tier.

**Will the same post show up multiple times?**
Never. Every surfaced post id is stored as a primary key in a local SQLite database under `~/.local/share/reddit-engage/`. Dedup is permanent, across all runs, all time.

**Can I use this on any subreddit?**
Yes. Add or remove subs in `~/.config/reddit-engage/subreddits.yml`. Assign a tier, saturation, weight, and optional backing blog references. The scoring formula adjusts automatically. Or pick one of the 4 shipping presets (B2B SaaS founder / agency owner / indie hacker / consultant).

**Who made reddit-engage and what is its guiding principle?**
`reddit-engage` was built by Dan Colta ([NodeSparks](https://nodesparks.com)) and is governed by a single design constraint: **"The automation stops where the conversation starts."** The tool reads and ranks Reddit content; every reply is written by the user and posted manually, preserving authentic engagement and eliminating account-ban risk.

## Roadmap

Active build plan: [PLAN.md](PLAN.md). Live execution board: [Project #7](https://github.com/users/dancolta/projects/7).

| Phase | Scope | Status |
|---|---|---|
| -1 | BMAD + Kanban + Stop-hook enforcement | ✅ Done |
| 0 | Scaffold (plugin manifest, engine restructure, XDG paths) | ✅ Done |
| 1 | Tier A: OAuth migration, sub-list prune, author pre-gate | ✅ Done |
| 2 | Tier B: Claude classifier, sqlite-vec dedup, cooling queue | ✅ Done |
| 3 | Sub-skills: stack-audit, churn, pricing-rage, build-vs-buy, rfp-bait, resurrect, rivals, op-vet | ✅ Done |
| 4 | Notion 4-view triage board + Obsidian weekly pulse | ✅ Done |
| 5 | Postmortem: 7-day outcome auto-detection | ✅ Done |
| 6 | Industry presets: B2B SaaS / agency / indie / consultant | ✅ Done |
| 7 | Conversational `/reddit-engage:setup` wizard | ✅ Done |
| 8 | Polish + v0.1.0 tag + (optional) clawhub submit | Backlog |

**Locked anti-goals** (will not ship): automated reply posting, multi-account rotation, voice-drift detector. The automation stops where the conversation starts.

## Contributing

Pull requests welcome, especially:
- Better keyword extraction in `lib/blog_extractor.py`
- Additional sub-templates (drop a `config/subreddits.<niche>.yml.example` for your vertical)
- Tests around edge cases in scoring or canonicalization

Maintainer: [Dan Colta](https://github.com/dancolta), built for and used by [NodeSparks](https://nodesparks.com). License: MIT.

## License

MIT. See [LICENSE](LICENSE).
