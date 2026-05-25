# reddit-engage Plugin — Stress-Tested Build Plan

**Status:** Awaiting Dan's final approval before execution.
**Audience:** Public GitHub release (technical users), NodeSparks runs on a private preset.
**Film:** End-to-end demo of daily run + sub-skill outputs. No setup phase in the film. Film date flexible.
**Repo:** Existing `github.com/dancolta/reddit-engage` (rename/restructure, do NOT create new).
**Execution framework:** BMAD-METHOD (dev cycle) with hook-enforced GitHub Project board flow. See §9.

---

## 1. Locked decisions

| # | Decision | Why |
|---|---|---|
| 1 | Convert to **multi-skill Claude plugin** (`.claude-plugin/plugin.json` shape, last30days precedent) | 9+ sub-skills exceed single-skill budget |
| 2 | **Public GitHub plugin**, technical-user audience | Distribution intent |
| 3 | **4 industry presets**: B2B SaaS founder, Agency owner, Indie hacker, Consultant | Onboarding without leaking NodeSparks ICP |
| 4 | **Interactive setup wizard** via Claude (`/reddit-engage setup`) | Best UX for OSS users |
| 5 | **XDG storage**: configs in `~/.config/reddit-engage/`, state in `~/.local/share/reddit-engage/` | Standards, backup-friendly, plugin reinstall-safe |
| 6 | **LLM access**: try `claude` CLI subprocess first, fallback to `ANTHROPIC_API_KEY` env, single `classify()` abstraction | Zero-config for Claude Code users, portable for everyone else |
| 7 | **OAuth required** (each user registers their own Reddit app, walked through in setup wizard) | 10x rate headroom, identity scope for postmortem, no shared credentials |
| 8 | **Cooling queue default-on** (30-min hold before surfacing in Notion) | Stealth recommendation from research |
| 9 | **Sub-list "prune" = quarantine** (tier 3, weight 0.0, still fetched-but-hidden) | Reversible, no config history loss |
| 10 | **Notion + Obsidian both OPTIONAL** | Tool must work standalone with inline-chat output |
| 11 | **Voice-drift detector DROPPED** | Spam-tool optics; behavioral, not stylistic, is what Reddit detects |
| 12 | **Sub-pulse weekly digest → Obsidian** (markdown notes), Notion stays daily-triage only | Right tool per cadence |
| 13 | **Postmortem auto-detect** via OAuth identity scope on user's own account | Zero manual work after replying |
| 14 | **NodeSparks personal config = private preset**, not hardcoded | Repo stays clean for OSS |

---

## 2. Plugin layout

```
github.com/dancolta/reddit-engage-plugin/
├── .claude-plugin/
│   └── plugin.json                      # version, optionalEnv: ANTHROPIC_API_KEY,
│                                        # required: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET
├── README.md                            # install, Reddit app registration walkthrough
├── LICENSE                              # MIT
├── skills/
│   ├── reddit-engage/                   # orchestrator (default daily run + setup wizard)
│   ├── reddit-engage-stack-audit/
│   ├── reddit-engage-churn-signals/
│   ├── reddit-engage-pricing-rage/
│   ├── reddit-engage-build-vs-buy/
│   ├── reddit-engage-rfp-bait/
│   ├── reddit-engage-thread-resurrect/
│   ├── reddit-engage-op-vet/            # utility (not a daily surfacer)
│   ├── reddit-engage-postmortem/        # 7d-later outcome tracker
│   ├── reddit-engage-pulse/             # weekly Obsidian digest
│   └── reddit-engage-rivals/            # competitor mention digest
├── engine/                              # Python project (was scripts/)
│   ├── pyproject.toml
│   ├── reddit_engage/
│   │   ├── cli.py                       # subcommands per sub-skill
│   │   ├── lib/
│   │   │   ├── reddit_oauth.py          # PRAW wrapper, replaces reddit_public.py
│   │   │   ├── score.py                 # current scoring + new pattern-specific
│   │   │   ├── classify.py              # LLM abstraction (claude CLI / API key)
│   │   │   ├── author_vet.py            # karma/age/sub-history pre-gate
│   │   │   ├── cooling_queue.py
│   │   │   ├── dedup_vec.py             # sqlite-vec + BGE-small (optional)
│   │   │   ├── notion_sync.py
│   │   │   ├── obsidian_sync.py
│   │   │   ├── postmortem.py
│   │   │   └── store.py                 # SQLite, XDG paths
│   └── presets/
│       ├── b2b-saas-founder.yml
│       ├── agency-owner.yml
│       ├── indie-hacker.yml
│       └── consultant.yml
└── examples/
    └── nodesparks-ops.yml               # not in repo, gitignored; lives in Dan's private fork
```

**Per-user filesystem layout:**
```
~/.config/reddit-engage/
├── oauth.json              # Reddit client_id, client_secret, username, refresh_token
├── llm.json                # provider preference (claude_cli | anthropic_api), API key if set
├── config.yml              # active preset + user overrides
├── subreddits.yml          # active sub list (copied from preset, user-editable)
├── keywords.yml
├── weights.yml
├── notion.yml              # OPTIONAL: db_id, data_source_id
└── obsidian.yml            # OPTIONAL: vault_path, pulse_folder

~/.local/share/reddit-engage/
├── reddit-engage.sqlite    # runs, posts, surfaced, blog_posts, blog_refs, reply_log, embeddings
└── logs/
```

---

## 3. Sub-skills (final scope)

| Skill | Mode | Pattern surfaced | Notes |
|---|---|---|---|
| `/reddit-engage` (default) | `default` | General pain + named SaaS (current behavior) | Routes to daily run |
| `/reddit-engage setup` | wizard | n/a | Conversational Claude-driven onboarding |
| `/reddit-engage stack-audit` | `stack-audit` | OPs publicly listing 8+ tools, asking how to consolidate | Numeric tool-count regex + LLM stack-extraction |
| `/reddit-engage churn-signals` | `churn` | "Canceling," "switching from," "fed up with" + named vendor | High-intent verb-anchor regex |
| `/reddit-engage pricing-rage` | `pricing-rage` | Price-hike threads (Salesforce/HubSpot/Gong cyclical) | Brand × pricing-verb co-occurrence |
| `/reddit-engage build-vs-buy` | `build-vs-buy` | Explicit build-vs-buy debates with numbers | Pattern detector |
| `/reddit-engage rfp-bait` | `rfp-bait` | "[A] vs [B] vs [C]" comparison threads | ≥2-vendor count gate |
| `/reddit-engage resurrect` | `resurrect` | 6-18mo old high-quality threads still getting Google traffic | Search API + age filter |
| `/reddit-engage rivals <brand>` | `rivals` | Pure competitor mention digest, configurable brand | Simpler gate |
| `/reddit-engage op-vet <username>` | utility | Score an OP profile pre-reply | One-shot |
| `/reddit-engage postmortem` | `postmortem` | 7d outcomes on replied surfaces | Auto-detect via identity scope |
| `/reddit-engage pulse` | `pulse` | Weekly sub × keyword heat-map | Writes to Obsidian if configured |

---

## 4. Build phases (no daily deadline)

### Phase 0: Repo scaffold (3-4h)
- Create new repo `~/Work/NodeSparks/Projects/reddit-engage-plugin/` (separate from current `reddit-engage/`)
- `.claude-plugin/plugin.json`, README skeleton, LICENSE, .gitignore
- Move Python project into `engine/`, restructure for XDG paths
- Move current SKILL.md into `skills/reddit-engage/`, slim to thin router
- **Migration script**: pull existing SQLite from current location to `~/.local/share/reddit-engage/`
- Smoke test: `/reddit-engage` still works identically end-to-end

### Phase 1: Tier A — Foundation (1 day)
- **Reddit OAuth migration**: replace `reddit_public.py` with PRAW; `oauth.json` config; setup wizard generates the registration walkthrough
- **Sub-list quarantine**: kill 6 subs from active list (r/Entrepreneur, r/SaaS, r/smallbusiness, r/nocode, r/coldemail, r/recruiting), add 5 new (r/B2BSaaS, r/msp, r/ExperiencedDevs, r/datascience, r/ProductManagement), keep removed ones as `tier: 3, weight: 0.0`
- **Author pre-gate**: drop posts where OP <30d account age OR <50 karma OR >80% activity in r/Entrepreneur-class subs. New `author_vet.py` module.
- **Quarantine scoring fix**: weight=0 subs skip score multiplication entirely (no div-zero), but still fetched into pool for telemetry
- **Smoke test**: A/B old vs new gate on a frozen 100-post sample, log surface delta

### Phase 2: Tier B — Intelligence (2 days)
- **`classify.py` abstraction**:
  - Default path: `subprocess.run(['claude', '-p', prompt])`, parse JSON
  - Fallback: `anthropic.Anthropic(api_key=...).messages.create(...)`
  - Auto-detect at startup: `which claude` → `claude --version` → prefer CLI; else require `ANTHROPIC_API_KEY`
  - Single `classify(post) -> {intent, buyer_stage, sentiment, competitor_mentioned, fit_score, suggested_angle}` interface
  - Prompt with 3 few-shot examples, JSON schema enforced, retry on parse failure (max 2)
- **Classifier gate placement**: runs ONLY on posts that pass cheap regex prefilter (keeps cost <$5/mo for personal use, ~$30/mo for heavy use)
- **sqlite-vec dedup**:
  - Install `sqlite-vec` extension at setup
  - Lazy-load BGE-small-en-v1.5 (33M params, CPU, ~1s per post) via `sentence-transformers` — optional install group `[vec]`
  - On each candidate, cosine-similarity vs last 90d of surfaced posts; drop if max similarity >0.92
- **Cooling queue**: surfaces land with `state='drafting'`; Notion sync only flushes rows older than 30 min OR when `--no-cool` flag set
- **Smoke test**: classifier round-trips on 20 fixture posts, dedup catches a known repost pair, cooling queue holds and releases on schedule

### Phase 3: Sub-skills (2 days)
- Add `--mode` flag to engine CLI
- Per-mode config bucket: separate `keywords-{mode}.yml`, scoring weight overrides in `weights-{mode}.yml`
- Implement 7 pattern surfacers: stack-audit, churn, pricing-rage, build-vs-buy, rfp-bait, resurrect, rivals
- Each gets a skinny SKILL.md (30 lines), all delegate to same engine with `--mode`
- `op-vet` standalone utility (synchronous, returns scored profile)
- All write to the SAME Notion DB with `Pattern` column tagging
- **Smoke test**: each pattern produces ≥1 valid surface from a fixture run

### Phase 4: Notion + Obsidian (1 day)
- **Notion schema migration**: add `Pattern`, `State`, `Fit (LLM)` properties; backfill existing rows with `Pattern='default'`, `State='Hot'`
- **Four views**: 🔥 Hot list, 🧪 Drafting queue, 📊 Pattern pulse, ♻️ Replied. Property setup is a one-shot script.
- **Emoji-prefix card titles** at insert time (one-glance pattern recognition)
- **Daily decay job**: surfaces older than 14 days flip `State='Dead'`
- **Obsidian sync** for `pulse`: writes `<vault>/<pulse_folder>/YYYY-WW-pulse.md` weekly. Frontmatter with tags. Markdown table of (sub × keyword × delta). Uses obsidian MCP from inside Claude orchestrator (Python emits markdown, Claude writes via MCP).
- **Both optional**: missing `notion.yml` or `obsidian.yml` → skip silently, fall through to inline markdown output only

### Phase 5: Postmortem (1 day)
- New `reply_log` table: `(post_id, comment_id, comment_url, replied_at)`
- **Auto-detect**: daily background pass via OAuth identity scope queries `/user/<me>/comments?limit=100`, matches `parent_id` against `surfaced.post_id`, populates `reply_log`
- **7d outcome job**: for each `reply_log` row aged ≥7 days without an `outcome` field, fetch comment via OAuth, record `(upvotes, replies_to, banned, removed)`, write to `outcome` field
- **Notion sync** updates ♻️ Replied view with these columns
- **Weekly digest** (part of `pulse`): "this week: 3 replied, 2 upvoted, 1 dead. Pattern that worked: churn-signals (avg upvotes 8). Pattern that flopped: rfp-bait (banned 1×)"

### Phase 6: Industry presets (1-2 days, can parallelize with agents)
- Spawn 4 research agents in parallel (one per preset)
- Each researches: 10-15 relevant subs (tier 1/2 split), 30-50 keywords (shared/operator/builder buckets), 30-50 SaaS brand names, 3-5 example "pain post" titles for prompt few-shots
- Deliverable per preset: `presets/<name>.yml` with subreddits / keywords / brands / persona description
- Setup wizard picks one, copies into `~/.config/reddit-engage/`, user can edit after

### Phase 7: Setup wizard + README (4-6h)
- `/reddit-engage setup` is a thin SKILL.md instructing Claude to:
  1. Walk user through reddit.com/prefs/apps registration (display screenshots from `assets/`)
  2. Collect client_id, client_secret, username → write `oauth.json`
  3. Test OAuth with a single `/r/test/new.json` call via PRAW
  4. Detect `claude` CLI vs prompt for `ANTHROPIC_API_KEY`, write `llm.json`
  5. Show preset list, user picks, copy preset → `~/.config/reddit-engage/`
  6. Optionally: ask if Notion DB integration wanted, walk through Notion DB creation OR ask for existing DB ID
  7. Optionally: ask if Obsidian integration wanted, ask vault path
  8. Run a dry `/reddit-engage` with `--dry-run` to validate end-to-end
- README documents: install, the 8 setup steps, configuration files, sub-skill catalog, troubleshooting

### Phase 8: Polish + film (1 day)
- Hero GIF (use `/claude-gif` skill)
- Demo run on Dan's NodeSparks preset for the film
- Tag v0.1.0, push to GitHub, submit to clawhub if desired

**Total estimated build: 9-12 working days across 8 phases. Phases 0-2 are the critical path; 3-8 can interleave once foundation is solid.**

---

## 5. Stress-test findings (gaps now closed)

| # | Gap exposed | Resolution |
|---|---|---|
| 1 | Tomorrow deadline impossible at full scope | Film pushed; build properly across ~2 weeks |
| 2 | OAuth registration per user is friction | Setup wizard walks through it (standard for Reddit tools) |
| 3 | Claude CLI from cron = orchestration coupling | No cron exists; runs are Claude-orchestrated. CLI subprocess fine. Abstraction allows API fallback. |
| 4 | Postmortem needed reply IDs | Auto-detect via OAuth identity scope on user's own account; matches by `parent_id` |
| 5 | Obsidian MCP only works in Claude sessions | By design — pulse runs are Claude-orchestrated. Python emits markdown, Claude writes via MCP. |
| 6 | Notion schema migration with existing rows | Backfill script: existing rows get `Pattern='default'`, `State='Hot'`. One-shot. |
| 7 | sqlite-vec CPU-bound step might slow daily | Made optional install group; only fires post-prefilter. Per-post embed <1s, runs on max ~50 candidates/day = <60s total. |
| 8 | Sub quarantine + weight=0 = div-zero | Quarantined subs skip score multiplication entirely; still fetched for telemetry but never surfaced |
| 9 | NodeSparks configs leak into public repo | NodeSparks becomes a private preset (`examples/nodesparks-ops.yml`, gitignored); 4 generic presets ship in repo |
| 10 | Per-user filesystem state | XDG paths everywhere; project dir contains code only |
| 11 | Voice-drift adds spam-tool optics | Dropped |
| 12 | LLM provider lock-in | Single `classify()` abstraction; default CLI, fallback API key, future-extensible to OpenAI/Groq/Ollama |
| 13 | Notion/Obsidian as hard dependencies | Both optional; tool works standalone with inline-markdown output |
| 14 | What does film actually show? | End-to-end daily run + sub-skill outputs, no setup phase. Dan's NodeSparks preset for realism. |

---

## 6. Out of scope (explicitly deferred or dropped)

- ❌ Voice-drift detector (dropped)
- ❌ `launch-radar` sub-skill (vendor-content magnet)
- ❌ `moderator-watch` sub-skill (low ROI)
- ❌ `account-prep` sub-skill (one-time op, not recurring)
- ❌ Multi-account rotation (Reddit detects in 2 weeks)
- ❌ Automated reply posting (where every paid competitor dies)
- ❌ Pushshift / BigQuery / Common Crawl backfill (overkill for live signal)
- ❌ Pinecone / Qdrant / Chroma (sqlite-vec sufficient)
- ❌ Provider-agnostic LLM from day 1 (claude CLI + Anthropic API fallback only; rest comes later if requested)

---

## 7. Risk register (accepted)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Reddit OAuth ToS changes block commercial use | Medium | High | Personal/non-commercial use is allowed; users register own apps; not reselling |
| Claude CLI subprocess flakiness | Low | Medium | JSON parse retry x2, fallback to API key path |
| BGE embedding model bloats install | Low | Low | Optional install group `pip install reddit-engage[vec]` |
| Notion API rate-shaping at scale | Low | Low | Volume is ~10 inserts/day, well under 3 req/sec ceiling |
| Industry presets get stale | Medium | Low | Date-stamped in YAML; quarterly refresh via 4-agent parallel run |
| Postmortem comment fetch hits 429 | Low | Low | Bounded to user's own /comments endpoint, ~100 req/day max |
| Setup wizard fails partway, leaves orphan state | Medium | Medium | Idempotent: each step checks existing config, can resume |

---

## 8. Approval gate

Before I write a single line of code:

- [ ] Plan signed off as scoped (or further cuts requested)
- [x] Repo: existing `dancolta/reddit-engage` (rename/restructure only)
- [x] Execution framework: BMAD-METHOD dev cycle + GitHub Projects + Stop-hook (§9 below)
- [ ] Build order confirmed: Phase -1 → 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8?

Once approved, execution begins at **Phase -1 (BMAD + board bootstrap)**.

---

## 9. STRICT FLOW — BMAD + GitHub Projects + Stop-hook (NON-NEGOTIABLE, DAY 0)

**The rule:** No code change ships without a corresponding task on the GitHub Project board moving `Backlog → In Progress → Done`. A Claude Code Stop-hook enforces it at the wall level — no agent can finish a turn that produced code edits without a board API call logged in the same session.

### 9.1 Tools

- **BMAD-METHOD**: `bmad-code-org/bmad-method`, dev cycle only (Scrum Master, Dev, QA agents). Skip the planning agents — PLAN.md is our PRD.
- **GitHub Projects v2**: native project on `dancolta/reddit-engage`, board view, scriptable via `gh project` CLI + GraphQL.
- **Stop-hook**: `.claude/hooks/stop-task-gate.sh` validates the session log before allowing the agent to report completion.

### 9.2 Board structure

Project: **"reddit-engage build"** on `dancolta/reddit-engage`.

| Field | Type | Values |
|---|---|---|
| `Status` | Single-select | `Backlog` → `In Progress` → `In Review` → `Done` |
| `Phase` | Single-select | `-1 Bootstrap`, `0 Scaffold`, `1 Tier A`, `2 Tier B`, `3 Sub-skills`, `4 Notion+Obsidian`, `5 Postmortem`, `6 Presets`, `7 Setup wizard`, `8 Polish` |
| `Agent` | Single-select | `SM`, `Dev`, `QA`, `Dan` |
| `Story ref` | Text | BMAD story file path (e.g. `docs/stories/1.2-oauth-migration.md`) |
| `Effort` | Single-select | `XS (≤1h)`, `S (1-3h)`, `M (3-8h)`, `L (1-2d)`, `XL (2d+)` |

Each phase in §4 becomes a parent issue with N child task issues (one per acceptance criterion). PLAN.md is the source of truth; the board is the live execution surface.

### 9.3 The locked flow (every change, no exceptions)

```
User request
    ↓
[BMAD Scrum Master agent]
    1. gh issue create --title "<story>" --body "<acceptance criteria>"
    2. gh project item-add <project-id> --url <issue-url>
    3. gh project item-edit ... --field Status=Backlog --field Agent=Dev
    4. Write docs/stories/<id>.md (BMAD story format)
    5. Log task ID in .claude/session-tasks.log
    ↓
[BMAD Dev agent]
    1. Read story file
    2. gh project item-edit ... --field Status="In Progress"
    3. Implement
    4. Update story file with implementation notes + file list
    5. gh project item-edit ... --field Status="In Review"
    ↓
[BMAD QA agent]
    1. Read story + implementation
    2. Run tests, verify acceptance criteria
    3. If pass: gh project item-edit ... --field Status=Done
    4. If fail: gh project item-edit ... --field Status="In Progress" + comment with gaps
    ↓
[Stop-hook validates]
    - Did this session log a board API call?
    - Did Status reach "Done" (or back to "In Progress" on QA fail)?
    - If NO: block completion, error message instructing agent to file the task
    ↓
Report to Dan: "Done. Task #N closed. Story at docs/stories/<id>.md."
```

### 9.4 Stop-hook implementation

`.claude/hooks/stop-task-gate.sh` (executed on the Stop event):

```bash
#!/usr/bin/env bash
# Block session completion if code was edited but no board API call was logged.
set -euo pipefail

SESSION_LOG=".claude/session-tasks.log"
TRANSCRIPT_PATH="${CLAUDE_TRANSCRIPT_PATH:-}"

# Did this session produce code edits? (rough heuristic: Edit/Write tool calls)
code_edited=$(grep -cE '"name":"(Edit|Write|NotebookEdit)"' "$TRANSCRIPT_PATH" 2>/dev/null || echo 0)

if [ "$code_edited" -gt 0 ]; then
  # Did the session log a board API call?
  board_calls=$(grep -cE 'gh (issue|project) (create|item-edit)' "$SESSION_LOG" 2>/dev/null || echo 0)
  if [ "$board_calls" -eq 0 ]; then
    echo "STOP-HOOK BLOCK: code edits were made this session but no GitHub Project task was filed/updated." >&2
    echo "  Required: invoke BMAD Scrum Master agent first to create the story + board task, then re-run." >&2
    exit 2  # non-zero blocks the Stop
  fi
fi
exit 0
```

Wired in `.claude/settings.json`:
```json
{
  "hooks": {
    "Stop": [
      { "matcher": "*", "hooks": [{ "type": "command", "command": ".claude/hooks/stop-task-gate.sh" }] }
    ]
  }
}
```

### 9.5 BMAD adaptation for our scope

BMAD's default flow assumes planning agents produce `docs/prd.md` + `docs/architecture.md` first. We're skipping planning. The dev cycle expects sharded story files in `docs/stories/`. So:

**Phase -1 step**: convert PLAN.md sections §3 + §4 into pre-sharded story files:
- One story file per acceptance criterion (granular enough to be a single PR)
- BMAD-compatible frontmatter: `epic`, `story`, `status`, `acceptance_criteria`
- Stored in `docs/stories/<phase>.<n>-<slug>.md`
- Total stories: estimated 35-50 across 8 phases

The SM agent then picks the next `Backlog` story, hands to Dev, etc. Same loop as standard BMAD, just with pre-supplied story files.

### 9.6 New Phase -1 (Bootstrap, ~half-day)

Before any of the other 8 phases starts:

1. Install BMAD into the repo:
   ```bash
   cd ~/Work/NodeSparks/Projects/reddit-engage
   npx bmad-method@latest install --ide claude-code --flow dev-only
   ```
2. Configure BMAD to use Claude Code agents (SM, Dev, QA) — these become `.claude/agents/bmad-sm.md`, `.claude/agents/bmad-dev.md`, `.claude/agents/bmad-qa.md`
3. Create GitHub Project: `gh project create --owner dancolta --title "reddit-engage build"`; add the 5 custom fields
4. Generate the 35-50 story files from PLAN.md §3 + §4 (script: `scripts/plan_to_stories.py`)
5. Bulk-create GitHub issues from story files: `gh issue create` per story, add to project, set `Status=Backlog`, `Phase=<n>`, `Agent=SM`
6. Write `CLAUDE.md` (see §9.7)
7. Write `.claude/hooks/stop-task-gate.sh` + wire `.claude/settings.json`
8. Smoke-test: ask BMAD SM to claim story `-1.1` (a trivial test story like "add badge to README"), watch the full flow run, verify Stop-hook blocks if the board step is skipped

### 9.7 CLAUDE.md contents (mandatory)

Top-of-file instructions for any Claude session in this repo:

```markdown
# reddit-engage — Project Conventions

## SOURCE OF TRUTH
- `PLAN.md` — the full stress-tested build plan (do not edit without explicit Dan approval)
- `docs/stories/` — sharded BMAD story files derived from PLAN.md; the live work surface
- GitHub Project: https://github.com/users/dancolta/projects/N — board state of every story

## STRICT FLOW (non-negotiable)

**No code change ships without a corresponding task on the GitHub Project board.**

For ANY request that touches code or config:
1. Invoke `bmad-sm` agent → creates GitHub issue, adds to Project, sets Status=Backlog, writes/updates story file
2. Invoke `bmad-dev` agent → reads story, flips Status=In Progress, implements, flips Status=In Review
3. Invoke `bmad-qa` agent → verifies, flips Status=Done OR back to In Progress with gaps

Reporting "done" to Dan WITHOUT completing the above flow is forbidden.
The Stop-hook at `.claude/hooks/stop-task-gate.sh` will block any session that edits code without logging a board API call. If you hit that block, file the task properly — do not bypass the hook.

## Tools

- `gh project item-edit <project> --id <item> --field-id <fid> --single-select-option-id <vid>` — flip status
- `gh issue create --title "<X>" --body-file docs/stories/<id>.md` — file story
- `gh project item-add <project> --url <issue-url>` — link issue to project

The full field-id and option-id reference lives at `.bmad/board-refs.json` (generated at bootstrap).

## When NOT to use BMAD flow

Pure exploration / questions / planning conversations don't require board tasks. The hook only triggers when Edit/Write/NotebookEdit was called in the session. If you're answering a question or reading code, no board task needed.

## NodeSparks-specific notes

- Dan's personal preset lives at `~/.config/reddit-engage/nodesparks-ops.yml`, NOT in this repo
- Public presets in `presets/` must stay generic — no NodeSparks branding, blog URLs, or proprietary keywords
- Voice profile is dropped (see PLAN.md §6); do not add voice-drift features without revisiting
```

### 9.8 Risk register addendum

| Risk | Mitigation |
|---|---|
| Stop-hook becomes annoying for trivial fixes | Hook only fires on Edit/Write tool use; pure-read sessions unaffected. If still too aggressive: add `bypass-task` keyword that allowlists single commits (escape hatch, but logged) |
| BMAD agent definitions diverge from default | Pin BMAD version in `package.json`; document any customizations in `.bmad/CUSTOMIZATIONS.md` |
| GitHub Projects API rate limits | 5K req/hr authenticated; we'll do ~30-50 board calls/day max. Non-issue. |
| `npx bmad-method install` brings unwanted scaffolding | Run with `--flow dev-only` (skips planning agents/templates) |
| Hook script bash-fragile across OSes | macOS-bash only (your machine); cross-platform deferred to OSS release |
| Pre-existing untracked work in repo blocks bootstrap | Commit or stash first; bootstrap script asserts clean tree before BMAD install |

### 9.9 Approval items added

- [ ] §9 STRICT FLOW signed off as written?
- [ ] OK to install BMAD into existing repo (will add `.bmad/`, `docs/stories/`, `.claude/agents/bmad-*.md`)?
- [ ] OK to create GitHub Project under your account (single project, repo-scoped)?
- [ ] Stop-hook severity: hard block (exit 2) or soft warning (exit 0 + stderr message)?
