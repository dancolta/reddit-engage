# reddit-engage

> A daily inbox of Reddit threads worth your reply. You write the reply.

![reddit-engage arcade hero: 8-bit pixel-art animation of a small NodeSparks orange-and-teal sprite walking past floating subreddit name plaques (r/smallbusiness, r/SaaS, r/Entrepreneur, r/sales, r/nocode, r/Bookkeeping). HUD chips read SURF 12/15 and DEDUP ON. A scrolling ticker cycles pain-post headlines like BILL.COM $79/USER and APOLLO HURTS $316. The title bar reads REDDIT-ENGAGE, subtitle DAILY PAIN-POST RADAR. Read-only surfacing tool, not an auto-poster.](assets/hero.gif)

> **What this is not.** It does not post for you. It does not comment for you. It does not farm karma, rotate accounts, or warm up personas. There is no AI ghostwriter pasting replies into r/SaaS at 3am. It surfaces threads. You read them. You decide if they deserve your voice. The automation stops where the conversation starts.

`reddit-engage` is a Claude Code skill that scans 22 subreddits every morning, gates posts by tier-aware thresholds, and hands you a curated list of up to 15 pain posts worth a human reply. SQLite guarantees you never see the same post twice, across all time. Built for indie operators, SME builders, and founders building Reddit authority without engagement-farming.

## How it works

1. **Blog hash-check.** Headless Playwright fetches your blog index. If a new post landed, it deep-scrapes it and updates the knowledge map.
2. **Fetch + gate + score.** Python pulls `/r/<sub>/new` for 5 Tier 1 daily-scan subs and 17 Tier 2 opportunistic subs. Each post is gated by tier-specific thresholds (pain-keyword density, upvote velocity, post age, sub size floor). Survivors are scored by freshness, velocity, comment velocity, keyword match, blog-coverage bonus, and tier weight.
3. **Surface + sync.** Up to 15 surfaces (max 2 per Tier 1 sub, max 1 per Tier 2 sub). Output prints inline in chat. Notion board syncs (prior day archived, new rows created). Done in about 15 seconds end to end.

## Install (Claude Code skill)

```bash
git clone https://github.com/dancolta/reddit-engage ~/Work/NodeSparks/Projects/reddit-engage
cd ~/Work/NodeSparks/Projects/reddit-engage
python3 -m pip install -e .
python3 -m scripts.reddit_engage setup
```

Then from Claude Code, run `/reddit-engage setup` once. That verifies the Notion DB schema (creates missing properties via Notion MCP) and validates Reddit connectivity.

## Daily run

In Claude Code, type `/reddit-engage`. That is it.

## Compared

Honest comparison. The skill loses on setup friction. It wins everywhere the user actually cares: curation, dedup, and not getting their account nuked.

| | reddit-engage | F5Bot | Reddit auto-poster | Manual scrolling | Paid Reddit growth SaaS |
|---|---|---|---|---|---|
| Who writes the reply | You | You | The bot | You | The bot or a VA |
| Mod-culture risk | None, read-only | None | High (bans, shadowbans) | None | High |
| Never shows the same post twice | Yes, SQLite-enforced | No, re-alerts on every match | n/a | No, you re-scroll | Varies |
| Signal quality | Pain-shaped, scored, ranked | Raw keyword hits | Raw keyword hits | Depends on you | Mixed |
| Setup friction | Claude Code skill install | Email signup (easier) | Account + risk | Zero (easier) | Onboarding call |
| Price | Free, self-hosted | Free | Paid + account risk | Free | Paid monthly |

## Why two tiers

**Tier 1** is 5 subs you scan every day to build account recognition and compound on AI Overview citations: `r/smallbusiness`, `r/SaaS`, `r/Entrepreneur`, `r/sales`, `r/nocode`. Looser gates because consistent engagement is the goal.

**Tier 2** is 17 subs you scan opportunistically. 95% of posts there should never surface. Only gold-tier hits do. Strict gates: 3+ pain keywords, velocity > 8 upvotes/hour, sub size floor, post age sort priority, dollar-figure regex opt-in.

The list of all 22 subs and their tier, saturation, weight, and backing blog references is locked in [`config/subreddits.yml`](config/subreddits.yml).

## Architecture

```
~/.claude/skills/reddit-engage/SKILL.md     Claude orchestrator (Playwright + Notion MCP)
                                            │
~/Work/NodeSparks/Projects/reddit-engage/   Python CLI (no MCP calls)
  scripts/reddit_engage.py                  setup, fetch-score, status, history, blog, prune
  scripts/lib/
    reddit_public.py                        Raw Reddit JSON, canonicalization, rate-limit handling
    score.py                                Tier-aware gates and scoring formula
    store.py                                SQLite wrapper, single source of truth for dedup
    blog_extractor.py                       Rule-based keyword extractor for new blog posts
    output.py                               Inline markdown renderer
  config/                                   subreddits.yml, keywords.yml, weights.yml, blog-map.yml
  db/reddit-engage.sqlite                   runtime, gitignored
  tests/                                    24 tests, all passing
```

Python handles fetch + gate + score + persistence. Claude (via SKILL.md) handles Playwright (blog refresh) and Notion (board sync). They communicate via JSON on stdout. MCP tools are scoped to the Claude session; Python subprocess cannot reach them, so the orchestration sits in the right place.

<details>
<summary>Schema reference</summary>

The SQLite schema lives in [`scripts/lib/store.py`](scripts/lib/store.py). Key invariants:

- `posts.canonical_url UNIQUE` and `posts.id PRIMARY KEY` for cross-host dedup. URL canonical form is `https://reddit.com/comments/<t3_id>/`.
- `surfaced.post_id PRIMARY KEY` is the single column that guarantees a post surfaces at most once across all time. The Notion board can be cleared on every run; SQLite remembers everything.
- `runs.notes` captures fetch and persist errors per run so failures degrade gracefully without taking down the run.
- `meta` table caches the blog index hash so the daily run skips the deep blog scrape when the index is unchanged.

</details>

<details>
<summary>Other commands</summary>

| Command | Action |
|---|---|
| `/reddit-engage status` | Last-run summary, blog-map staleness, DB path |
| `/reddit-engage history [YYYY-MM-DD]` | Past surfaces |
| `/reddit-engage prune` | Drop posts older than 90 days (keeps surfaced rows forever) |
| `/reddit-engage setup` | Bootstrap SQLite, validate Reddit, verify Notion schema |

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

**Can I use this on any subreddit, not just the 22 pre-configured ones?**
Yes. Add or remove subs in `config/subreddits.yml`. Assign a tier, saturation, weight, and optional backing blog references. The scoring formula adjusts automatically.

**Why a Claude Code skill instead of a standalone CLI?**
The blog refresh runs through Playwright MCP (headless browser) and the Notion board sync runs through Notion MCP. Both are scoped to the Claude session. Python handles the parts that should be a CLI (fetch, gate, score, persist); Claude handles the rails. Right tool, right job.

## Roadmap

- v1, this release: surface-only. No drafting, no posting.
- v2, maybe: optional reply-angle suggestions (never auto-send). Per-sub conversion attribution from profile-click data. AI Overview citation tracking instrumented via the existing `surfaced.ai_citation_count` column.

The roadmap stays read-only on Reddit's side. The automation stops where the conversation starts.

## License

MIT. See [LICENSE](LICENSE).
