# reddit-engage

> A daily inbox of Reddit threads worth your reply. You write the reply.

![reddit-engage arcade hero: 8-bit pixel-art animation of a small orange-and-teal sprite walking past floating subreddit name plaques (r/<your-niche>, r/founders, r/startups, r/SaaS, r/<your-icp>, r/sysadmin). HUD chips read SURF 12/15 and DEDUP ON. A scrolling ticker cycles generic pain-post headlines like TOOL X TOO EXPENSIVE, ALTERNATIVE TO Y?, STACK COST $$$. Title bar REDDIT-ENGAGE, subtitle DAILY PAIN-POST RADAR. Read-only surfacing tool, not an auto-poster.](assets/hero.gif)

> **What this is not.** It does not post for you. It does not comment for you. It does not farm karma, rotate accounts, or warm up personas. There is no AI ghostwriter pasting replies into Reddit at 3am. It surfaces threads. You read them. You decide if they deserve your voice. The automation stops where the conversation starts.

`reddit-engage` is a Claude Code skill that scans the subreddits you care about every morning, gates posts by tier-aware thresholds, and hands you a curated list of up to 15 pain posts worth a human reply. SQLite guarantees you never see the same post twice, across all time.

**Made for one user, designed for any.** Bring your own subs, your own pain keywords, your own backing blog. The engine is identical for an indie SaaS founder, a recruiter, an agency owner, a devtools builder, or anyone using Reddit to compound authority in a specific niche.

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

## Install (Claude Code skill)

```bash
git clone https://github.com/dancolta/reddit-engage ~/Work/<your-project-folder>
cd ~/Work/<your-project-folder>
python3 -m pip install -e .
```

Then symlink (or copy) the skill so Claude Code picks it up:

```bash
mkdir -p ~/.claude/skills/reddit-engage
cp SKILL.md ~/.claude/skills/reddit-engage/
```

Edit `~/.claude/skills/reddit-engage/SKILL.md`: update the `Notion target` block with your own Notion database ID + data source ID (create the database via the Notion MCP or the included setup helper).

Finally bootstrap:

```bash
python3 -m scripts.reddit_engage setup
```

Then from Claude Code run `/reddit-engage setup` once. That verifies Reddit connectivity and the Notion DB.

## Daily run

In Claude Code, type `/reddit-engage`. Done.

## Compared

Honest comparison. The skill loses on setup friction. It wins everywhere the user actually cares: curation, dedup, and not getting their account nuked.

| | reddit-engage | F5Bot | Reddit auto-poster | Manual scrolling | Paid Reddit growth SaaS |
|---|---|---|---|---|---|
| Who writes the reply | You | You | The bot | You | The bot or a VA |
| Mod-culture risk | None, read-only | None | High (bans, shadowbans) | None | High |
| Never shows the same post twice | Yes, SQLite-enforced | No, re-alerts on every match | n/a | No, you re-scroll | Varies |
| Signal quality | Pain-shaped, scored, ranked | Raw keyword hits | Raw keyword hits | Depends on you | Mixed |
| Setup friction | Claude Code skill install + config | Email signup (easier) | Account + risk | Zero (easier) | Onboarding call |
| Price | Free, self-hosted | Free | Paid + account risk | Free | Paid monthly |
| Tuneable to your niche | Yes, 4 YAML files | No (keyword filters only) | No | n/a | Mostly no |

## Why two tiers

**Tier 1** is the small set of subs you scan every morning to build account recognition and compound on AI Overview citations. Looser gates because consistent engagement is the goal.

**Tier 2** is a wider net you scan opportunistically. 95% of posts there should never surface. Only gold-tier hits do: 3+ pain keywords, velocity > 8 upvotes/hour, age < 24h.

Recommended starting layout for any niche:

- 3 to 5 Tier 1 subs where your ICP literally lives and complains.
- 10 to 20 Tier 2 subs that are adjacent or niche enough that hits are rare but high-quality.

The full subreddit list ships with the maintainer's NodeSparks setup (22 subs total). Use it as a template, then swap to your own.

## Architecture

```
~/.claude/skills/reddit-engage/SKILL.md     Claude orchestrator (Playwright + Notion MCP)
                                            │
~/Work/<your-folder>/                       Python CLI (no MCP calls)
  scripts/reddit_engage.py                  setup, fetch-score, status, blog ingest
  scripts/lib/
    reddit_public.py                        Raw Reddit JSON, canonicalization, rate-limit handling
    score.py                                Tier-aware gates + scoring formula
    store.py                                SQLite wrapper, single source of truth for dedup
    blog_extractor.py                       Rule-based keyword extractor for new blog posts
    output.py                               Inline markdown renderer
  config/                                   subreddits.yml, keywords.yml, weights.yml, blog-map.yml, notion.yml
  db/reddit-engage.sqlite                   runtime, gitignored
  tests/                                    21 tests, all passing
```

Python handles fetch + gate + score + persistence. Claude (via SKILL.md) handles Playwright (optional blog refresh) and Notion (board sync). They communicate via JSON on stdout. MCP tools are scoped to the Claude session; Python subprocess cannot reach them, so the orchestration sits in the right place.

<details>
<summary>Schema reference</summary>

The SQLite schema lives in [`scripts/lib/store.py`](scripts/lib/store.py). Key invariants:

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

**Is this a Reddit bot?**
No. `reddit-engage` never posts, comments, votes, or logs into Reddit. It reads public JSON endpoints. You read the output list and write your own replies manually.

**Will the same post show up multiple times?**
Never. Every surfaced post id is stored as a primary key in a local SQLite database. Dedup is permanent, across all runs, all time.

**How is this different from F5Bot or keyword alerts?**
F5Bot sends raw keyword matches with no intent scoring. `reddit-engage` gates posts by pain-keyword density, upvote velocity, post age, and subreddit weight before anything surfaces. Most posts never make the cut.

**Does it need a Reddit API key?**
No. Uses Reddit's public JSON (no OAuth, no API key). Standard rate-limit handling and exponential backoff on 429s are built in.

**Can I use this on any subreddit?**
Yes. Add or remove subs in `config/subreddits.yml`. Assign a tier, saturation, weight, and optional backing blog references. The scoring formula adjusts automatically.

**Do I need a blog?**
No. The blog-coverage bonus is opt-in. If you skip `config/blog-map.yml`, the skill still surfaces posts by pure engagement and pain-keyword signal. Add blog content later for the multi-point bonus.

**Why a Claude Code skill instead of a standalone CLI?**
The optional blog refresh runs through Playwright MCP (headless browser) and the Notion board sync runs through Notion MCP. Both are scoped to the Claude session. Python handles the parts that should be a CLI (fetch, gate, score, persist); Claude handles the rails. Right tool, right job.

## Roadmap

- v1, this release: surface-only. No drafting, no posting.
- v2, maybe: optional reply-angle suggestions (never auto-send). Per-sub conversion attribution from profile-click data. AI Overview citation tracking instrumented via a future `surfaced.ai_citation_count` column.

The roadmap stays read-only on Reddit's side. The automation stops where the conversation starts.

## Contributing

Pull requests welcome, especially:
- Better keyword extraction in `lib/blog_extractor.py`
- Additional sub-templates (drop a `config/subreddits.<niche>.yml.example` for your vertical)
- Tests around edge cases in scoring or canonicalization

Maintainer: [Dan Colta](https://github.com/dancolta), built for and used by [NodeSparks](https://nodesparks.com). License: MIT.

## License

MIT. See [LICENSE](LICENSE).
