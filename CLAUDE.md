# subscope — Contributor Guide

This file is for **contributors working on the codebase**, not plugin users. Plugin users want [README.md](README.md). Plugin behavior is defined in [`skills/`](skills/), not here. (`claude plugin validate` flags this file as "not loaded as plugin context" — that's correct, by design.)

If you opened a clone and asked Claude to help you contribute, this is the orientation document.

---

## What this codebase is

A Python engine + Claude Code skills:

- **`engine/subscope/`** — Python. Fetches Reddit (PRAW or public JSON), runs regex + optional LLM gates, scores survivors, writes to SQLite, prints JSON to stdout. Stdlib + pyyaml + optional `praw`, `openai`, `notion-client`.
- **`skills/*/SKILL.md`** — 16 user-invocable Claude Code skills. Each one is a single Markdown file that tells Claude how to orchestrate a workflow (Notion sync via MCP, Obsidian write via MCP, Playwright blog refresh, etc.). The Python engine does no MCP work — the skill layer does.
- **`config/`** — YAML defaults: weights, default subreddits, default keywords, scoring caps. Public users override by writing to `~/.config/subscope/`.
- **`presets/`** — 4 starter bundles (b2b-saas-founder, agency-owner, indie-hacker, consultant) for users who don't want to run `/subscope:onboard`.
- **`assets/`** — README hero GIF + the Python+Pillow render script.

The engine is intentionally separable: you could pipe its JSON output to any orchestrator, not just Claude Code.

---

## File layout

```
.
├── .claude-plugin/plugin.json    # plugin manifest (required by Claude Code)
├── engine/
│   ├── subscope/
│   │   ├── cli.py                # all CLI subcommands (fetch-score, status, op-vet, ...)
│   │   ├── lib/                  # the engine modules
│   │   │   ├── store.py          # SQLite + XDG paths
│   │   │   ├── score.py          # gate + score + selection
│   │   │   ├── reddit_oauth.py   # PRAW with public-JSON fallback
│   │   │   ├── reddit_public.py  # the fallback
│   │   │   ├── classify.py       # OpenAI-compat bulk LLM grader
│   │   │   ├── author_vet.py     # OP karma/age/audience pre-gate
│   │   │   ├── archetype_map.py  # 6 archetypes for /onboard + /profile
│   │   │   ├── profile_synth.py  # 8-Q + 3-Q config synthesis
│   │   │   ├── obsidian_sync.py  # weekly pulse digest builder
│   │   │   ├── postmortem.py     # auto-detect + score sent replies
│   │   │   ├── slack.py          # optional webhook push
│   │   │   ├── tune_engine.py    # /tune ranker back-prop
│   │   │   └── output.py         # markdown + table renderers
│   │   └── prompts/              # system prompts (classify, profile_synth)
│   ├── scripts/                  # one-shot helpers (write_oauth, notion_admin, ...)
│   └── tests/                    # pytest, 100+ tests
├── skills/                       # 16 SKILL.md files, one per pattern
├── config/                       # default YAML (subreddits, keywords, weights, presets)
├── presets/                      # 4 starter bundles
├── assets/                       # hero.gif + render_hero.py
└── docs/                         # setup-oauth.md, setup-notion.md (public only)
```

---

## Conventions

These are non-negotiable for any PR:

- **No em dashes** in any user-facing text (chat output, Notion writes, error messages). Use commas or restructure. The engine output is em-dash-free; preserve that. `engine/tests/test_no_em_dashes.py` enforces it.
- **Parameterized SQL only.** Every `conn.execute()` must use `?` placeholders. f-string SQL is a defect.
- **`chmod 600` on every config + DB file.** Atomic creation via `os.open(path, O_WRONLY|O_CREAT|O_TRUNC, 0o600)` — never `open()` then `chmod()` (umask race).
- **XDG-compliant paths.** Config at `~/.config/subscope/` (or `$XDG_CONFIG_HOME/subscope/`), data at `~/.local/share/subscope/`. Override via `SUBSCOPE_CONFIG` / `SUBSCOPE_DATA` env for tests.
- **Reddit username validation.** Any value interpolated into a `reddit.com/user/<x>/` URL must pass `reddit_oauth._safe_username()` regex first (defuses path-segment injection).
- **No new shell=True subprocess calls.** Use `subprocess.run([..., args], shell=False)` with list args. The engine has zero `shell=True` calls today; keep it that way.
- **SSRF guard.** Any user-configurable URL (LLM endpoint, Slack webhook, future adapters) must validate scheme + host before the HTTP call. See `classify._validate_base_url()` for the pattern.
- **No telemetry, ever.** No analytics, no error reporting, no usage pings. If you need to send anything off the user's machine, it must be opt-in with a one-time stderr banner.

---

## Adding a new pattern skill

The 16 patterns share one engine (`fetch-score --mode <pattern>`). Adding a pattern is ~30 minutes:

1. Add pattern keywords: `config/keywords-<pattern>.yml`
2. Add cap in `config/weights.yml` under `pattern_caps`
3. Add the mode to `VALID_MODES` in `engine/subscope/cli.py`
4. Add an emoji in `PATTERN_EMOJI` in `cli.py`
5. Create `skills/<pattern>/SKILL.md`:

```markdown
---
name: <pattern>
description: One-paragraph description. Triggers on "<pattern>", "/subscope:<pattern>", "...".
allowed-tools: Bash, Read, Write
---

# /subscope:<pattern>

[1-line intent]

```bash
cd "$CLAUDE_PLUGIN_ROOT" && PYTHONPATH=engine python3 -m subscope.cli fetch-score --mode <pattern>
```

[Any pattern-specific instructions for Claude here]
```

6. Add a test stub to `engine/tests/test_<pattern>.py` (mock the fetch, assert dropped_counts shape).

That's it. The engine handles the rest.

---

## Running tests

```bash
pip install -e '.[dev]'
python3 -m pytest engine/tests/
```

114 tests, target <1s total runtime. New PRs must keep the suite green.

End-to-end smoke (live Reddit fetch, no posting):

```bash
PYTHONPATH=engine python3 -m subscope.cli fetch-score --limit-per-sub 3 --daily-cap 3 --no-slack
```

Validates the plugin manifest:

```bash
claude plugin validate .
```

---

## What NOT to add

- Auto-posting, auto-commenting, account rotation — these are deliberate omissions. The plugin's positioning is human-in-the-loop. PRs that add write-side Reddit operations will be closed.
- New SaaS dependencies — every integration must work with a free tier or stdlib-only. No Resend, Postmark, Clearbit, Apollo paid layers.
- Cross-platform adapters in v0.1.x — they're roadmapped for v0.2/v0.3. Open an issue first.
- Em dashes anywhere.

---

## Architecture decisions worth knowing

These are choices that look weird in code review but exist for a reason:

- **Two LLM-call paths** are NOT in the code despite the older Anthropic SDK being installable — we standardized on the OpenAI-compatible client because Anthropic exposes `/openai/v1`. Reverting to a separate Anthropic SDK path is dead code today; if you need prompt caching, that's the v0.2 work.
- **The cooling queue** holds new surfaces in `state=drafting` for `cool_minutes` (default 15) before promoting to `hot`. This prevents bot-detection patterns (replying within 2 minutes of post creation looks like automation). Pricing-rage mode sets this to 0 because the pattern is genuinely time-sensitive.
- **The cap is a UX filter, not a safety limit.** `hard_ceiling=12` exists because attention drops 80% past position 10 (Nielsen Norman). Reddit's API allows ~100 QPM; we use ~30 req/day. Power users override via `--max-surfaces`.
- **author_vet** runs BEFORE scoring, not after. Catches throwaway/karma-farmer OPs early so they never enter the scoring pool. Cached 7 days in SQLite (`vetted_authors` table).
- **The 3-question `/onboard` + 8-question `/profile` BOTH route through `profile_synth.py`.** The shorter flow seeds an archetype and lets Claude refine in chat; the deeper flow runs the LLM synthesis prompt directly. Same validator, same YAML writer.

---

## License + Contributing

MIT. PRs welcome. Open an issue first for non-trivial changes — the plugin's anti-positioning surface (what it deliberately doesn't do) matters as much as the features.
