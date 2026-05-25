# subseek

> A Claude Code plugin that reads Reddit like your smartest teammate would. Pattern-aware, human-in-the-loop, learns from the replies you actually send.

[![Version](https://img.shields.io/github/v/tag/dancolta/subseek?label=version&color=blue)](https://github.com/dancolta/subseek/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-plugin-orange)](https://docs.claude.com/en/docs/claude-code/plugins)

![subseek arcade hero: pixel-art animation of a small orange-and-teal sprite walking past subreddit name plaques like r/founders, r/SaaS, r/sysadmin. HUD reads SURF 12/15 DEDUP ON. Scrolling ticker cycles pain-post headlines. Title bar reads SUBSEEK, subtitle DAILY PAIN-POST RADAR.](assets/hero.gif)

```bash
# in Claude Code
/plugin install dancolta/subseek
/subseek:onboard       # 3 questions, 60 seconds
/subseek:run           # your first daily scan
```

> [!NOTE]
> **The automation stops where the conversation starts.** subseek surfaces 5 to 15 posts a day where someone in your exact buyer profile is hurting right now. It never drafts your reply, never queues a comment, never touches your Reddit account. If you want a Reddit engagement machine that runs while you sleep, look at Devi AI or ReplyGuy. This is not that.

## How it works

1. **60-second onboarding.** Three questions (who you're trying to reach, what you're offering, your homepage URL). Claude reasons through your answers in chat (free, via your subscription) and writes a config tuned to YOUR product. Not a generic lane.
2. **Daily run.** `/subseek:run` scans your configured subs, gates posts by pain-pattern keywords plus author vetting plus optional LLM grading, and surfaces 5 to 15 high-fit threads. Pattern-aware: knows the difference between pricing rage, churn, build-vs-buy, and alternative-seeking intent.
3. **You reply.** The list lands in chat (and optionally Notion, Slack, and your Obsidian vault). Read, decide, write the reply yourself on Reddit. SQLite remembers every surfaced post forever, so the same thread never returns.

## What makes it different

Every paid Reddit listening tool (GummySearch shut down Nov 2025 over Reddit licensing, Pulse for Reddit, F5Bot, the seven post-Gummy clones) does keyword matching. Match a phrase, get an alert. You are still sifting.

subseek classifies posts by INTENT before they hit your inbox:

- **pricing-rage**: someone publicly upset about a renewal hike
- **churn**: switching or canceling threads ("looking to ditch X for...")
- **build-vs-buy**: debates with actual numbers attached
- **rfp-bait**: "A vs B vs C" comparison threads
- **stack-audit**: OPs listing tools and asking what to cut
- **alternative-seeking**: explicit "alternative to X?" posts
- **resurrect**: 6 to 18-month-old high-quality threads worth a late comment
- **rivals**: every mention of a brand in your competitive set

Plus a postmortem learner: every reply you actually send gets tracked, scored on 7-day outcome (upvotes, follow-up replies, lock status), and fed back into next week's ranking. That is the moat. No competitor learns from your sent replies.

## Sub-skills

<details>
<summary>16 invocable skills (click to expand)</summary>

| Skill | What it does |
|---|---|
| `/subseek:setup` | Conversational onboarding wizard. ~10min. |
| `/subseek:onboard` | 3-question routing flow. ~60s. Default first-launch path. |
| `/subseek:profile` | 8-question deep interview. ~12min. Sharper targeting. |
| `/subseek:run` | Daily scan. Lists ~10 surfaces in chat plus Notion plus Slack if configured. |
| `/subseek:judge <n>` | Interactive single-surface classification via your Claude subscription. |
| `/subseek:tune` | Mark surfaces good/bad/meh, ranker learns. ~3 rounds. |
| `/subseek:pulse` | Weekly digest written to your Obsidian vault. |
| `/subseek:postmortem` | Auto-detect your sent replies, score 7-day outcomes. |
| `/subseek:rivals` | Today's mentions of any competitor in your brand_anchor. |
| `/subseek:pricing-rage` | Price-hike threads, zero cooling (time-sensitive). |
| `/subseek:churn` | Switching/canceling threads in your space. |
| `/subseek:build-vs-buy` | Build-vs-buy debates with concrete numbers. |
| `/subseek:stack-audit` | "Help me cut tools from my stack" threads. |
| `/subseek:rfp-bait` | A vs B vs C comparison threads. |
| `/subseek:resurrect` | Quality threads aged 6 to 18 months. |
| `/subseek:op-vet <user>` | One-shot Reddit profile vetting (karma, age, audience fit). |

</details>

## Install

```bash
# In Claude Code
/plugin install dancolta/subseek
/subseek:setup
```

Works without any API keys on day 1. The setup wizard walks you through the optional layers and skips anything you do not want.

## Cost model

| Layer | Cost | Required? |
|---|---|---|
| Default daily run | $0 | Yes |
| Reddit OAuth | $0 (free Reddit app registration) | Recommended |
| `/subseek:judge` interactive | $0 (uses your Claude Code subscription) | Optional |
| Bulk LLM grading | ~$0.50/day at 5K posts | Optional, any provider |
| Notion triage | $0 (Notion free tier covers this) | Optional |
| Slack push | $0 (free Slack webhook) | Optional |
| Obsidian digest | $0 | Optional |

**Bulk LLM grading** is provider-agnostic. The plugin auto-detects the right OpenAI-compatible endpoint from your API key prefix:

| Provider | Key format | Auto-detected base URL |
|---|---|---|
| Anthropic (via `/openai/v1`) | `sk-ant-...` | `https://api.anthropic.com/v1/` |
| OpenAI | `sk-...` | `https://api.openai.com/v1` |
| Groq | `gsk_...` | `https://api.groq.com/openai/v1` |
| OpenRouter | `sk-or-...` | `https://openrouter.ai/api/v1` |
| Together / Fireworks | Custom | Set `LLM_BASE_URL` |
| Local Ollama | No key | Set `LLM_BASE_URL=http://localhost:11434/v1` |

## Compared

|  | subseek | Pulse for Reddit | F5Bot | GummySearch |
|---|---|---|---|---|
| Price | Free, OSS | Paywalled SaaS | Free email | $59/mo (DEAD Nov 2025) |
| Lives in | Your Claude Code session | Their dashboard | Your inbox | n/a |
| Matching | Pattern-aware (8 intent classes) | Keyword plus AI-drafted reply | Keyword only | Keyword plus sentiment |
| Auto-drafts replies | No, by design | Yes | No | No |
| Learns from your sent replies | Yes (postmortem) | No | No | No |
| BYO LLM provider | Yes (any OpenAI-compat) | No | No | No |
| Data residency | 100% local SQLite | Their cloud | Their cloud | n/a |
| Multi-platform expansion | LinkedIn / HN / X on roadmap | Reddit only | Reddit + HN | n/a |

Pulse is fine if you want a SaaS dashboard that auto-drafts spam-safe replies. subseek is for builders who want a daily, pattern-aware pain digest inside their own Claude session, where every reply they actually send teaches the next day's ranker.

## Privacy and data flow

- **Reddit credentials** live at `~/.config/subseek/oauth.json` (0o600). The plugin writes them via Python with `os.open(O_EXCL, 0o600)`, so the file is never world-readable.
- **LLM API key** is opt-in. If you set one, post bodies (capped at 800 chars) get sent to whichever OpenAI-compatible endpoint you configured. The plugin prints a one-time stderr banner the first time this happens.
- **SSRF guard** on `llm_base_url`: requests to private/link-local IPs (RFC-1918, AWS metadata 169.254.169.254, etc.) and to `http://` for non-localhost hosts are refused.
- **SQLite DB** at `~/.local/share/subseek/subseek.sqlite` (0o600). Contains post bodies and Reddit usernames you have surfaced. No data leaves your machine unless you opted in to LLM / Notion / Slack.
- **No telemetry.** No analytics, no error reporting, no usage pings.

## Architecture

<details>
<summary>Internals (click to expand)</summary>

- **Python engine** (`engine/subseek/`): fetch + gate + score + SQLite + JSON output. Stdlib + pyyaml + optional `praw`, `openai`, `notion-client`.
- **Skill orchestration** (`skills/<name>/SKILL.md`): Claude reads these to drive Notion and Obsidian MCP, blog refresh via Playwright, etc.
- **Three-tier classification**: regex (free, default) -> interactive judge (subscription, free) -> bulk LLM API (~$0.50/day, opt-in, provider-agnostic).
- **Storage**: XDG-compliant. Config at `~/.config/subseek/`, data at `~/.local/share/subseek/subseek.sqlite`. All sensitive files written with 0o600 atomically.
- **Security guards**: SSRF allowlist on `llm_base_url`, atomic 0o600 file creation via Python (no shell-heredoc race), Reddit username regex validation, parameterized SQL throughout, no shell=True subprocess calls.

</details>

## Roadmap

- **v0.1.0 (current)**: Reddit-only, 11 patterns, Notion + Obsidian + Slack outputs.
- **v0.1.1**: Merged Reddit OAuth/public modules, cli.py unit tests, expanded preset library.
- **v0.2.0**: HackerNews adapter (`/subseek:hn`), prompt caching for Anthropic bulk-grading.
- **v0.3.0**: LinkedIn pulse adapter (public posts only, never private data).
- **v0.4.0**: Custom-pattern definition via YAML, no code changes needed.

## FAQ

**Will Reddit ban me for using this?**
No. subseek never posts anything. It reads `/r/<sub>/new` the same way any human or browser does. With OAuth enabled, you get 100 QPM (which is well below Reddit's rate limit and well above what a daily scan needs).

**Can I use this to find leads at scale?**
No, by design. The default daily cap is 12 surfaces. If you want a list of 500 prospects, this is the wrong tool.

**What if I do not have any of the optional integrations?**
The default install works on day 1 with zero API keys. You get inline chat output. Add layers later as you need them.

**Does it work for non-English subreddits?**
The regex gates are English-keyword-tuned by default. Add language-specific keyword files in `~/.config/subseek/keywords-<lang>.yml` and the engine will use them. LLM grading works in any language the model supports.

**Why not just use F5Bot for free?**
F5Bot is keyword email alerts. subseek classifies by intent (pricing rage vs churn vs build-vs-buy), dedups permanently in SQLite, tracks your sent replies, learns from outcomes, and lives inside your existing dev workflow. Different category.

## Contributing

PRs welcome. The full design context is in [PLAN.md](PLAN.md). The 16 sub-skills follow a consistent pattern (`fetch-score --mode <name>`), so adding a new pattern is mostly a new keyword file plus a 30-line SKILL.md.

Discussion: [GitHub Discussions](https://github.com/dancolta/subseek/discussions).

## License

MIT. See [LICENSE](LICENSE).

---

*Built by [Dan Colta](https://github.com/dancolta) at [NodeSparks](https://nodesparks.com). Filed under operator-automation, not lead-gen tooling.*
