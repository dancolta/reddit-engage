# reddit-engage

![hero](assets/hero.gif)

Daily Reddit pain-post surfacing for NodeSparks authority building. Scans 22 subreddits across two tiers, gates by tier-aware thresholds, scores survivors, and surfaces up to 15 NEW posts per day. Posts are never repeated thanks to SQLite-backed dedup. The daily list pushes to a Notion board and prints inline in the Claude Code chat.

**v1 is surface-only.** No drafting, no posting. You read the list, write your own replies on Reddit.

## What it does

Each morning you run `/reddit-engage` in Claude Code. The skill:

1. Hash-checks the NodeSparks blog index. If a new post landed, it deep-scrapes the post and updates the knowledge map.
2. Fetches `/r/<sub>/new` for 22 configured subs (5 Tier 1 daily + 17 Tier 2 opportunistic).
3. Gates each post by tier-specific thresholds: pain-keyword density, upvote velocity, post age, comment ceiling, sub size floor, saturation modifier (high-saturation Tier 2 subs check existing top replies).
4. Scores survivors by freshness, upvote velocity, comment velocity, pain-keyword match, blog-coverage bonus, sub weight, tier weight.
5. Selects up to 15 (max 2 per Tier 1 sub, max 1 per Tier 2 sub). Quality-first, no quotas. Empty days are fine.
6. Writes everything to SQLite, archives the prior Notion board, creates new rows.
7. Prints the list inline so you can scan it instantly.

## Architecture

```
~/.claude/skills/reddit-engage/SKILL.md     # Claude orchestrator (Playwright MCP + Notion MCP)
                                            #
~/Work/NodeSparks/Projects/reddit-engage/   # Python CLI (no MCP calls)
  scripts/reddit_engage.py                  #   subcommands: setup, fetch-score, status, history, blog, prune
  scripts/lib/
    reddit_public.py                        #   raw Reddit JSON fetcher, URL canonicalization, rate-limit handling
    score.py                                #   tier-aware gates + scoring formula
    store.py                                #   SQLite wrapper (single source of truth for dedup)
    blog_extractor.py                       #   rule-based keyword extractor for new blog posts
    output.py                               #   inline markdown renderer
  config/
    subreddits.yml                          #   22 subs locked: tier, saturation, weight, backing blogs
    keywords.yml                            #   pain-keyword seeds, per bucket + per blog post
    weights.yml                             #   scoring weights + gate thresholds, tunable
    blog-map.yml                            #   cached blog knowledge map (auto-refreshed)
  db/reddit-engage.sqlite                   #   runtime, gitignored
  tests/                                    #   24 tests covering canonicalization, gates, scoring, em-dash audit
```

Python handles fetch + gate + score + SQLite. Claude (via SKILL.md) handles Playwright (blog refresh) and Notion (board sync). They communicate via JSON on stdout/stdin.

## Why two tiers

**Tier 1** = 5 subs you scan every day, build account recognition, compound on AI Overview citations. Looser gates because consistent engagement is the goal.

**Tier 2** = 17 subs you scan opportunistically. 95% of posts there should NOT surface. Only gold-tier hits do. Strict gates: 3+ pain keywords, velocity > 8/hr, sub size floor, comment dropped, post age sort priority (not a hard cutoff per stress-test).

Saturation modifier on `high`-saturation Tier 2 subs (r/sysadmin, r/devops, r/selfhosted, r/Automate, r/marketing): also requires no existing technical reply with 3+ upvotes already in the thread.

## Setup

```bash
git clone <this-repo> ~/Work/NodeSparks/Projects/reddit-engage
cd ~/Work/NodeSparks/Projects/reddit-engage
python3 -m pip install -e .
python3 -m scripts.reddit_engage setup
```

Then from Claude Code, run `/reddit-engage setup` once. That verifies the Notion DB schema (creates missing properties via Notion MCP) and validates Reddit connectivity.

## Daily run

In Claude Code, just type `/reddit-engage`. The skill takes ~10 seconds: blog hash-check, Reddit fetch across 22 subs, gate + score + select, Notion sync, inline output.

## Other commands

| Command | Action |
|---|---|
| `/reddit-engage status` | Last-run summary, blog-map staleness, DB path |
| `/reddit-engage history [YYYY-MM-DD]` | Past surfaces |
| `/reddit-engage prune` | Drop posts older than 90 days (keeps surfaced rows forever) |

## Stack

- Python 3.10+, stdlib + `pyyaml` + `certifi`. No web framework, no ORM.
- SQLite via stdlib `sqlite3`.
- Reddit raw public JSON (no OAuth, no API key). Anti-bot fallback and exponential backoff on 429.
- Playwright MCP (headless) for blog refresh. Notion MCP for board sync.
- pytest for the test suite.

## Hard rules baked in

- **No em dashes** in any user-facing output. Audited by a dedicated test (`tests/test_no_em_dashes.py`). Dan's personal-brand rule. The audit covers rendered markdown and the JSON payload pushed to Notion.
- **No drafting** in v1. The skill never writes a Reddit reply. You read the list, decide your own angle.
- **No link-drops in replies** (out of scope here, but documented for the human in the loop).
- **Dedup is absolute**: `surfaced.post_id` is the SQLite PK. A post is shown at most once across all time.
- **No weekly caps**. Daily per-sub caps only (max 2 Tier 1, max 1 Tier 2 per sub per day).

## License

MIT.
