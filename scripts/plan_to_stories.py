"""Generate BMAD-compatible story files + GitHub issues from PLAN.md.

Reads STORIES (the manifest below), writes one md file per story to
docs/stories/, then files a GitHub issue + Project item for each, setting
Phase/Agent/Effort/Story-ref/Status fields per the .bmad-board/refs.yml
reference.

Idempotent: skips story files that already exist on disk; skips issues that
already exist (matched by exact title).

Run:
    python3 scripts/plan_to_stories.py --emit          # write story files
    python3 scripts/plan_to_stories.py --file-issues   # create gh issues + project items
    python3 scripts/plan_to_stories.py --all           # both
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
STORIES_DIR = REPO_ROOT / "docs" / "stories"
REFS_PATH = REPO_ROOT / ".bmad-board" / "refs.yml"
SESSION_LOG = REPO_ROOT / ".claude" / "session-tasks.log"


# (phase, story_num, slug, title, role, action, benefit, effort, ac_lines, dev_notes)
STORIES: list[tuple] = [
    # ─── Phase -1: Bootstrap ───
    ("-1 Bootstrap", "1.1", "install-bmad-method",
     "Install BMAD-METHOD dev cycle into repo",
     "build orchestrator", "BMAD installed with bmm module + claude-code IDE wiring",
     "story/dev/qa workflows are available as Claude skills",
     "S (1-3h)",
     ["BMAD v6.7.x installed via `npx bmad-method install`",
      "claude-code tool selected → skills appear in `.claude/skills/`",
      "bmm module config sets user_skill_level=expert, user_name=Dan",
      "Aliases bmad-sm → bmad-create-story, bmad-dev → bmad-agent-dev, bmad-qa → bmad-code-review created"],
     "Reference: PLAN.md §9.6. Note: BMAD installer template-substitutes `{output_folder}` literally in some paths — manually fix _bmad/bmm/config.yaml after install."),

    ("-1 Bootstrap", "1.2", "github-project-fields",
     "Create GitHub Project + custom fields",
     "build orchestrator", "a GitHub Project board with Status/Phase/Agent/Effort/Story-ref fields",
     "every story has a live status surface",
     "S (1-3h)",
     ["Project created at github.com/users/dancolta/projects/N",
      "Status options: Backlog, In Progress, In Review, Done",
      "Phase options: -1 through 8 matching PLAN.md",
      "Agent options: SM, Dev, QA, Dan",
      "Effort options: XS (≤1h), S (1-3h), M (3-8h), L (1-2d), XL (2d+)",
      "All field/option IDs captured in .bmad-board/refs.yml"],
     "Use gh project + gh api graphql for field creation. Reference: PLAN.md §9.2."),

    ("-1 Bootstrap", "1.3", "generate-story-files",
     "Generate story files from PLAN.md",
     "build orchestrator", "one BMAD-format story file per work item in docs/stories/",
     "the dev cycle has its inputs ready",
     "S (1-3h)",
     ["scripts/plan_to_stories.py generates all stories",
      "Story files use BMAD template (Status / AC / Tasks / Dev Notes / Dev Agent Record)",
      "Frontmatter includes phase, story-num, effort, status",
      "Output: docs/stories/<phase>-<n>-<slug>.md"],
     "This story IS the generator. Self-bootstrapping."),

    ("-1 Bootstrap", "1.4", "bulk-file-issues",
     "Bulk-create GitHub issues from stories",
     "build orchestrator", "every story file mirrored as a GitHub issue on the Project board",
     "the board reflects the full backlog",
     "S (1-3h)",
     ["Script reads docs/stories/*.md",
      "For each: gh issue create, gh project item-add, sets Phase + Agent=SM + Status=Backlog + Effort + Story-ref",
      "Each call logged to .claude/session-tasks.log (Stop-hook evidence)",
      "Re-runs are idempotent — skip if issue title already exists"],
     "Use gh project item-edit with field IDs from .bmad-board/refs.yml."),

    ("-1 Bootstrap", "1.5", "write-claude-md",
     "Write CLAUDE.md with strict-flow rules",
     "Claude session in this repo", "CLAUDE.md instructions documenting the BMAD + board flow",
     "every future session follows the locked execution loop",
     "XS (≤1h)",
     ["CLAUDE.md exists at repo root",
      "Documents: PLAN.md as source of truth, docs/stories/ as live surface, Project URL",
      "Documents: SM → Dev → QA flow with exact gh commands",
      "Documents: Stop-hook behavior, BMAD_BYPASS escape hatch, [bmad-bypass] token",
      "Documents: when the hook does/doesn't fire (read-only OK)"],
     "Reference: PLAN.md §9.7."),

    ("-1 Bootstrap", "1.6", "stop-hook-wiring",
     "Write Stop-hook + settings.json",
     "Claude harness", "a Stop-event hook that blocks code-edit sessions without a board task",
     "the strict flow is enforced by the harness, not documentation",
     "S (1-3h)",
     [".claude/hooks/stop-task-gate.sh exists, executable",
      "Hook reads CLAUDE_TRANSCRIPT_PATH, counts Edit/Write/NotebookEdit tool calls",
      "Hook reads .claude/session-tasks.log, counts gh issue/project calls",
      "If edits > 0 AND board-calls == 0 → exit 2 with instructions",
      "Escape hatches: BMAD_BYPASS=1 env, [bmad-bypass] in user message",
      ".claude/settings.json registers hook on Stop event"],
     "Reference: PLAN.md §9.4."),

    ("-1 Bootstrap", "1.7", "smoke-test-flow",
     "Smoke-test end-to-end BMAD flow",
     "build orchestrator", "a trivial story exercised through SM → Dev → QA with board updates",
     "we know the flow + hook work before real stories ship",
     "S (1-3h)",
     ["Trivial story exists (e.g. add a badge line to README)",
      "bmad-sm invocation creates GitHub issue, sets Status=Backlog",
      "bmad-dev invocation edits a file, flips Status=In Progress → In Review",
      "bmad-qa invocation verifies, flips Status=Done",
      "Stop-hook validates board calls were logged",
      "Test: same flow without filing task → hook blocks at Stop"],
     "First real exercise of the strict-flow loop."),

    # ─── Phase 0: Scaffold ───
    ("0 Scaffold", "0.1", "claude-plugin-manifest",
     "Create .claude-plugin/plugin.json",
     "Claude plugin system", "a plugin manifest with version + optional env",
     "this repo loads as a proper Claude plugin",
     "XS (≤1h)",
     [".claude-plugin/plugin.json exists",
      "Version: 0.1.0",
      "Required env: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME",
      "Optional env: ANTHROPIC_API_KEY, NOTION_API_KEY, OBSIDIAN_VAULT_PATH",
      "Author, license MIT, repo URL"],
     "Reference: PLAN.md §2 layout."),

    ("0 Scaffold", "0.2", "restructure-engine",
     "Restructure scripts/ → engine/reddit_engage/",
     "developer", "Python project under engine/, importable as `reddit_engage`",
     "the engine is decoupled from skills and follows package conventions",
     "M (3-8h)",
     ["engine/ directory contains pyproject.toml + reddit_engage/ package",
      "Existing scripts/lib/* moved to engine/reddit_engage/lib/",
      "Existing scripts/reddit_engage.py becomes engine/reddit_engage/cli.py",
      "pyproject [project.scripts] exposes `reddit-engage` console script",
      "All existing tests still pass after restructure",
      "Old scripts/ removed cleanly (git mv preserves history)"],
     "Use git mv to preserve history. Reference: PLAN.md §2."),

    ("0 Scaffold", "0.3", "xdg-paths",
     "XDG path resolution in store.py",
     "user", "SQLite + configs in ~/.config/reddit-engage and ~/.local/share/reddit-engage",
     "per-user state works across machines + reinstalls",
     "S (1-3h)",
     ["store.py resolves DB path from XDG_DATA_HOME or ~/.local/share/reddit-engage/",
      "Config loader resolves from XDG_CONFIG_HOME or ~/.config/reddit-engage/",
      "Both honored: REDDIT_ENGAGE_DATA, REDDIT_ENGAGE_CONFIG env vars override XDG",
      "Auto-creates dirs on first run with 700 perms",
      "Migration: detect old in-project DB at db/, prompt to copy to XDG location"],
     "Reference: PLAN.md §2 per-user filesystem layout."),

    ("0 Scaffold", "0.4", "skills-restructure",
     "Move skills under skills/reddit-engage/",
     "Claude plugin system", "skills/ at repo root with the orchestrator skill",
     "structure matches multi-skill plugin convention",
     "S (1-3h)",
     ["skills/reddit-engage/SKILL.md exists, contents from current ~/.claude/skills/reddit-engage/SKILL.md",
      "Updated paths inside SKILL.md to reference engine/reddit_engage instead of scripts/",
      "Symlink or removal of ~/.claude/skills/reddit-engage (dev-only stub)"],
     "Reference: PLAN.md §2."),

    ("0 Scaffold", "0.5", "sqlite-migration-script",
     "Migration script: existing SQLite → XDG path",
     "existing NodeSparks user (Dan)", "a one-time migration that preserves all surfaces history",
     "no learning data is lost in the restructure",
     "XS (≤1h)",
     ["Script: engine/scripts/migrate_to_xdg.py",
      "Detects db/reddit-engage.sqlite in project root, copies to ~/.local/share/reddit-engage/",
      "Verifies row counts match",
      "Renames source to db/reddit-engage.sqlite.pre-xdg-bak",
      "Idempotent: skips if XDG DB already exists"],
     ""),

    ("0 Scaffold", "0.6", "readme-skeleton",
     "README skeleton with install + setup pointers",
     "GitHub visitor", "a clear README explaining install + setup-wizard path",
     "OSS adopters understand the on-ramp before clicking Star",
     "XS (≤1h)",
     ["README has: badge row, one-line tagline, hero GIF placeholder, Install, Quick Start, Sub-skills, Roadmap",
      "Install section: `npx bmad-method install ...` or `claude plugin install dancolta/reddit-engage`",
      "Setup section: points to `/reddit-engage setup` for the wizard",
      "Sub-skills: stub table (filled in Phase 3)",
      "Roadmap: links to PLAN.md"],
     ""),

    ("0 Scaffold", "0.7", "phase0-smoke",
     "Smoke test: default /reddit-engage still works",
     "user", "the existing daily-run UX preserved through the restructure",
     "scaffolding didn't break the only thing that already worked",
     "XS (≤1h)",
     ["/reddit-engage produces inline-markdown identical to pre-restructure",
      "SQLite migration completed, surfaces history intact",
      "All existing tests pass"],
     ""),

    # ─── Phase 1: Tier A ───
    ("1 Tier A", "1.1", "praw-oauth-wrapper",
     "PRAW OAuth wrapper replaces reddit_public.py",
     "engine", "Reddit fetches via authenticated PRAW with 100 QPM headroom",
     "we have 10x rate budget and identity scope for postmortem",
     "M (3-8h)",
     ["engine/reddit_engage/lib/reddit_oauth.py uses PRAW",
      "fetch_delta(sub, last_seen_id) preserves existing return shape",
      "OAuth credentials read from ~/.config/reddit-engage/oauth.json",
      "Identity scope requested (read + identity)",
      "Refresh token persisted",
      "Fallback: if no oauth.json, fall through to existing reddit_public.py with warning",
      "All existing reddit_public.py tests adapted + still pass"],
     "Reference: PLAN.md §4 Phase 1, market-researcher findings on Reddit API 2026."),

    ("1 Tier A", "1.2", "oauth-config-walkthrough",
     "oauth.json config + Reddit app registration walkthrough",
     "user", "step-by-step walkthrough to register a Reddit OAuth app",
     "I can self-onboard without external docs",
     "S (1-3h)",
     ["docs/setup-oauth.md walks through reddit.com/prefs/apps registration",
      "Screenshots in assets/setup/ (app-type=script, callback=http://localhost)",
      "oauth.json schema documented: client_id, client_secret, username, refresh_token",
      "Setup wizard (Phase 7) consumes this doc"],
     ""),

    ("1 Tier A", "1.3", "sub-quarantine-logic",
     "Quarantine logic for tier-3 weight-0 subs",
     "engine", "quarantined subs fetched-but-never-surfaced cleanly",
     "I can reverse a sub deletion without losing config history",
     "S (1-3h)",
     ["Score multiplier skips weight=0 (no div-zero)",
      "Quarantined subs marked `tier: 3, weight: 0.0` in subreddits.yml",
      "fetch-score still pulls posts from tier-3 for telemetry",
      "Surface selection always excludes tier-3 (hard rule)",
      "Test: weight=0 sub never appears in `surfaces[]`"],
     ""),

    ("1 Tier A", "1.4", "sub-list-prune",
     "Drop 6 low-converting subs, add 5 new",
     "user", "a sub list that produces actual buying-intent posts",
     "daily surfaces convert better",
     "XS (≤1h)",
     ["Quarantine: r/Entrepreneur, r/SaaS, r/smallbusiness, r/nocode, r/coldemail, r/recruiting",
      "Add tier 2: r/B2BSaaS, r/msp, r/ExperiencedDevs, r/datascience, r/ProductManagement",
      "config/subreddits.yml updated with backing_blogs per sub",
      "Comment explains the prune (per reddit-community-builder research)"],
     "Reference: reddit-community-builder agent findings."),

    ("1 Tier A", "1.5", "author-vetting",
     "author_vet.py: karma/age/sub-history pre-gate",
     "engine gate", "to drop posts from low-quality / wrong-audience authors before scoring",
     "30% of wasted surfaces are killed before they reach Notion",
     "M (3-8h)",
     ["engine/reddit_engage/lib/author_vet.py module",
      "Function: vet_author(username, praw_client) -> {karma, account_age_days, sub_breakdown, verdict}",
      "Drop if: account_age < 30 OR comment_karma < 50 OR >80% activity in r/Entrepreneur-class subs",
      "Karma fetched via PRAW Redditor.comment_karma",
      "Sub breakdown cached in SQLite for 7d (avoid refetching same OP)",
      "Wired into evaluate_gate() as a soft signal before tier1/tier2 gates"],
     ""),

    ("1 Tier A", "1.6", "score-multiplier-safety",
     "Score multiplier handles weight=0 without div-zero",
     "engine", "no crashes on quarantined subs",
     "the test suite covers the edge case explicitly",
     "XS (≤1h)",
     ["compute_score short-circuits to 0.0 when sub.weight == 0",
      "Unit test covers weight=0 case",
      "Tier-3 short-circuit added to evaluate_gate as well"],
     ""),

    ("1 Tier A", "1.7", "ab-smoke-test",
     "A/B smoke test on frozen 100-post sample",
     "build orchestrator", "evidence the new gate improves surface quality",
     "we can validate the changes before shipping",
     "S (1-3h)",
     ["tests/fixtures/100_post_ab_sample.json captured",
      "scripts/ab_compare.py runs old + new gate, prints surface delta",
      "Delta documented in docs/phase1-ab.md with subjective quality scoring"],
     ""),

    # ─── Phase 2: Tier B ───
    ("2 Tier B", "2.1", "classify-abstraction",
     "classify.py abstraction (claude CLI + Anthropic API fallback)",
     "engine", "a single classify(post) interface backed by claude CLI or API",
     "I'm not locked into one LLM provider",
     "M (3-8h)",
     ["engine/reddit_engage/lib/classify.py",
      "Default: subprocess.run(['claude', '-p', prompt]), parse JSON from stdout",
      "Fallback: anthropic SDK with ANTHROPIC_API_KEY",
      "Provider auto-detect at startup: shutil.which('claude') → CLI; else API",
      "User override in llm.json: {provider: claude_cli | anthropic_api}",
      "Returns: {intent, buyer_stage, sentiment, competitor_mentioned, fit_score, suggested_angle}",
      "JSON parse retry x2 on failure"],
     "Reference: PLAN.md §4 Phase 2."),

    ("2 Tier B", "2.2", "classify-prompt",
     "Classification prompt + 3-shot examples + JSON schema",
     "engine", "a stable prompt that returns reliable JSON",
     "downstream code can trust the structure",
     "S (1-3h)",
     ["prompt template stored in engine/reddit_engage/prompts/classify.md",
      "3 few-shot examples covering: pain post, vendor content, neutral discussion",
      "JSON schema enforced via prompt + post-parse validation",
      "Cost target: <$30/mo for ~5K posts/day classified (only post-prefilter survivors)"],
     ""),

    ("2 Tier B", "2.3", "classifier-gate-wiring",
     "Wire classifier into gate (post-regex prefilter only)",
     "engine", "the LLM call only runs on candidates that already passed cheap regex",
     "classification cost stays bounded",
     "S (1-3h)",
     ["evaluate_gate adds classifier check as final stage",
      "Classifier only runs if regex gate passes (saves 80%+ calls)",
      "fit_score >= configured threshold required to surface",
      "Skip cleanly + warn if no LLM provider configured (graceful degradation)"],
     ""),

    ("2 Tier B", "2.4", "sqlite-vec-install",
     "sqlite-vec extension installer + optional install group",
     "user", "vector search available as `pip install reddit-engage[vec]`",
     "I can opt out of the heavy embedding dep if not wanted",
     "S (1-3h)",
     ["pyproject.toml [project.optional-dependencies] vec = [sqlite-vec, sentence-transformers]",
      "engine/scripts/install_sqlite_vec.py runs sqlite extension install",
      "Setup wizard asks: enable semantic dedup? → installs [vec] group if yes"],
     ""),

    ("2 Tier B", "2.5", "dedup-embeddings",
     "BGE-small embedding pipeline + 90d cosine dedup",
     "engine", "near-duplicate posts dropped via cosine similarity",
     "I stop seeing reposts of last week's already-surfaced threads",
     "M (3-8h)",
     ["engine/reddit_engage/lib/dedup_vec.py",
      "Lazy-load BAAI/bge-small-en-v1.5 via sentence-transformers",
      "On each new candidate: embed → cosine vs 90d sliding window",
      "Drop if max_similarity > 0.92 (configurable)",
      "Embeddings stored in sqlite-vec virtual table",
      "Bench: <1s per post on M-series CPU"],
     ""),

    ("2 Tier B", "2.6", "cooling-queue",
     "30-min cooling queue + --no-cool flag",
     "user", "drafts hold before flushing to Notion",
     "I avoid 5-min reply patterns Reddit flags",
     "S (1-3h)",
     ["New SQLite column: surfaced.state ('drafting' | 'hot' | 'dead')",
      "Default: surfaces land in 'drafting' state",
      "Notion sync only flushes rows in 'drafting' state older than 30 min → flips to 'hot'",
      "--no-cool flag bypasses for urgent posts (e.g. pricing-rage)",
      "Cooling duration configurable in weights.yml"],
     "Reference: reddit-community-builder agent on Reddit's 2026 behavioral classifier."),

    ("2 Tier B", "2.7", "tier-b-smoke",
     "Tier B integration smoke test",
     "build orchestrator", "evidence classifier + dedup + cooling don't break daily run",
     "I trust the new pipeline end-to-end",
     "S (1-3h)",
     ["Fixture run with all three layers enabled produces expected output",
      "Classifier round-trips on 20 fixture posts",
      "Dedup catches known repost pair",
      "Cooling queue holds + releases on schedule",
      "Latency: full daily run <60s with 50 candidates"],
     ""),

    # ─── Phase 3: Sub-skills ───
    ("3 Sub-skills", "3.1", "mode-flag",
     "Add --mode flag to engine CLI + per-mode config buckets",
     "engine", "fetch-score accepts --mode and loads mode-specific keywords/weights",
     "sub-skills can share fetching infra but specialize gating",
     "M (3-8h)",
     ["fetch-score --mode <default|stack-audit|churn|pricing-rage|build-vs-buy|rfp-bait|resurrect|rivals>",
      "Per-mode keyword bucket: config/keywords-{mode}.yml (falls back to keywords.yml)",
      "Per-mode weight overrides: config/weights-{mode}.yml",
      "Mode written to surface row + Notion `Pattern` column"],
     ""),

    ("3 Sub-skills", "3.2", "stack-audit-pattern",
     "stack-audit pattern: 8+ tools listed + consolidation ask",
     "user", "/reddit-engage stack-audit surfaces stack-cut threads",
     "I see highest-intent stack-rationalization posts",
     "M (3-8h)",
     ["config/keywords-stack-audit.yml: stack-listing patterns (counts of saas brand mentions in post)",
      "Gate adds: must mention ≥4 SaaS brands AND ≥1 consolidation phrase",
      "skills/reddit-engage-stack-audit/SKILL.md (thin router → --mode stack-audit)",
      "Emoji prefix: 🧱"],
     ""),

    ("3 Sub-skills", "3.3", "churn-signals-pattern",
     "churn-signals pattern: switching/canceling + named vendor",
     "user", "/reddit-engage churn-signals surfaces high-intent buying posts",
     "I see operators in active churn from a tool",
     "S (1-3h)",
     ["config/keywords-churn.yml: canceling/switching/fed-up verbs + vendor anchor",
      "Gate: must co-occur verb + brand within 100 chars",
      "skills/reddit-engage-churn-signals/SKILL.md",
      "Emoji prefix: ⚡"],
     ""),

    ("3 Sub-skills", "3.4", "pricing-rage-pattern",
     "pricing-rage pattern: price-hike threads",
     "user", "/reddit-engage pricing-rage surfaces price-hike rants",
     "I catch quarterly Salesforce/HubSpot/Gong rage spikes",
     "S (1-3h)",
     ["config/keywords-pricing-rage.yml: price-hike phrases × brand",
      "Gate: brand mention AND pricing-verb co-occurrence",
      "skills/reddit-engage-pricing-rage/SKILL.md",
      "Emoji prefix: 🔥",
      "Default --no-cool ON (time-sensitive)"],
     ""),

    ("3 Sub-skills", "3.5", "build-vs-buy-pattern",
     "build-vs-buy pattern: explicit debates with numbers",
     "user", "/reddit-engage build-vs-buy surfaces decision threads",
     "I find threads where my worldview is the answer",
     "S (1-3h)",
     ["config/keywords-build-vs-buy.yml: debate phrases + numeric patterns",
      "Gate: numeric ($X or X hours) AND build/buy verb pair",
      "skills/reddit-engage-build-vs-buy/SKILL.md",
      "Emoji prefix: ⚖️"],
     ""),

    ("3 Sub-skills", "3.6", "rfp-bait-pattern",
     "rfp-bait pattern: A vs B vs C comparison threads",
     "user", "/reddit-engage rfp-bait surfaces multi-vendor comparison asks",
     "I find threads welcoming a 4th option",
     "S (1-3h)",
     ["config/keywords-rfp-bait.yml: 'vs' patterns",
      "Gate: ≥2 SaaS brands in 'X vs Y' or 'X or Y' construction",
      "skills/reddit-engage-rfp-bait/SKILL.md",
      "Emoji prefix: 🤝"],
     ""),

    ("3 Sub-skills", "3.7", "resurrect-pattern",
     "resurrect pattern: 6-18mo old high-quality threads",
     "user", "/reddit-engage resurrect surfaces aged threads with SEO traffic",
     "I can leave late comments that compound forever",
     "M (3-8h)",
     ["Uses Reddit search API (not /new) for time-range query",
      "Gate: post age 6-18mo, score >= 50, comment-velocity-this-week > 0",
      "skills/reddit-engage-resurrect/SKILL.md",
      "Emoji prefix: 🪦"],
     ""),

    ("3 Sub-skills", "3.8", "rivals-pattern",
     "rivals pattern: configurable brand mention digest",
     "user", "/reddit-engage rivals <brand> surfaces today's mentions of a specific brand",
     "I have a simple competitive intel daily feed",
     "S (1-3h)",
     ["CLI: --rivals-brand <name> (or positional arg)",
      "Pure brand-mention surfacing, lighter gate than default",
      "skills/reddit-engage-rivals/SKILL.md takes brand as $1 argument",
      "Emoji prefix: 🥷"],
     ""),

    ("3 Sub-skills", "3.9", "op-vet-utility",
     "op-vet utility: score an OP profile pre-reply",
     "user", "/reddit-engage op-vet <username> returns a scored profile",
     "I can pre-filter before drafting a reply",
     "S (1-3h)",
     ["CLI: op-vet <username>",
      "Returns: {karma, age_days, sub_breakdown, throwaway_likelihood, verdict: GO|HOLD|SKIP}",
      "Reuses author_vet.py logic from Phase 1.5",
      "skills/reddit-engage-op-vet/SKILL.md"],
     ""),

    ("3 Sub-skills", "3.10", "pattern-column-notion",
     "Notion sync writes Pattern column with emoji prefix",
     "user", "Notion cards show pattern emoji at-a-glance",
     "I triage by pattern instantly without clicking",
     "XS (≤1h)",
     ["notion_sync.py prefixes card title with mode-specific emoji",
      "Pattern field set to mode string",
      "Test: surface from each pattern lands with correct emoji + pattern"],
     ""),

    # ─── Phase 4: Notion + Obsidian ───
    ("4 Notion+Obsidian", "4.1", "notion-schema-migration",
     "Notion schema: add Pattern, State, Fit (LLM) properties",
     "user", "the existing Notion DB extended with 3 new properties",
     "patterns + states + LLM scores live alongside daily surfaces",
     "S (1-3h)",
     ["scripts/notion_migrate.py adds 3 properties to existing DB",
      "Pattern: select with all mode names + emoji",
      "State: select Drafting/Hot/Replied/Won/Ignored/Dead",
      "Fit (LLM): number 0-10",
      "Backfill: existing rows get Pattern='default', State='Hot'",
      "Idempotent: re-running detects existing properties"],
     ""),

    ("4 Notion+Obsidian", "4.2", "notion-views",
     "Four Notion views: Hot list, Drafting queue, Pattern pulse, Replied",
     "user", "task-appropriate Notion views matching daily workflow",
     "I can triage / review / postmortem each in their own surface",
     "M (3-8h)",
     ["🔥 Hot list: board grouped by Subreddit, filter State=Hot, sort Fit desc",
      "🧪 Drafting queue: table, filter State=Drafting",
      "📊 Pattern pulse: board grouped by Pattern, last 7 days",
      "♻️ Replied: table, filter State=Replied, with Upvotes/Replies/Outcome columns",
      "Views created via Notion API where possible; manual fallback documented"],
     ""),

    ("4 Notion+Obsidian", "4.3", "notion-decay",
     "Daily decay: 14d-old surfaces flip to State=Dead",
     "engine", "old surfaces auto-archive themselves",
     "Hot list stays clean without manual cleanup",
     "XS (≤1h)",
     ["fetch-score appends a decay pass each run",
      "Query: State NOT IN (Dead) AND Surfaced > 14d ago → set State=Dead",
      "Logged in run notes"],
     ""),

    ("4 Notion+Obsidian", "4.4", "obsidian-pulse-sync",
     "Obsidian sync for weekly pulse digest",
     "user", "weekly pulse digests land as markdown notes in my Obsidian vault",
     "weekly review lives in my actual knowledge graph, not Notion",
     "M (3-8h)",
     ["engine emits markdown digest to stdout when --emit-obsidian set",
      "Claude orchestrator writes via obsidian MCP to <vault>/<pulse_folder>/YYYY-WW-pulse.md",
      "Frontmatter: tags [reddit-engage, pulse, week-NN], date, total-surfaces",
      "Body: table of (sub × keyword × delta) week-over-week",
      "Config: obsidian.yml has vault_path + pulse_folder"],
     ""),

    ("4 Notion+Obsidian", "4.5", "optional-integrations",
     "Notion + Obsidian both optional (graceful degradation)",
     "user", "the tool works without Notion or Obsidian configured",
     "I can run it standalone with just inline-chat output",
     "S (1-3h)",
     ["Missing notion.yml → skip Notion sync silently, log info",
      "Missing obsidian.yml → skip Obsidian write silently, log info",
      "Inline markdown is always emitted regardless",
      "Setup wizard makes both opt-in"],
     ""),

    # ─── Phase 5: Postmortem ───
    ("5 Postmortem", "5.1", "reply-log-table",
     "reply_log SQLite table",
     "engine", "a place to record which surfaces I replied to + comment URLs",
     "outcome tracking has a data home",
     "XS (≤1h)",
     ["Migration adds reply_log (post_id PK, comment_id, comment_url, replied_at, outcome JSON)",
      "store.py exposes insert_reply, update_outcome, fetch_due_for_postmortem"],
     ""),

    ("5 Postmortem", "5.2", "auto-detect-replies",
     "Auto-detect replies via OAuth identity scope",
     "engine", "to discover my replies to surfaced posts without manual logging",
     "zero-effort outcome tracking",
     "M (3-8h)",
     ["Daily pass: PRAW /user/<me>/comments?limit=100",
      "Match parent_id → surfaced.post_id; if hit, insert into reply_log",
      "Idempotent: skip if reply_log row already exists",
      "Skips comments older than 30d (catch-up window)"],
     ""),

    ("5 Postmortem", "5.3", "outcome-7d-job",
     "7-day outcome job: fetch upvotes/replies/banned state",
     "engine", "after a reply matures 7 days, record its outcome",
     "I can learn which patterns convert vs flop",
     "S (1-3h)",
     ["Daily pass: for reply_log rows aged ≥7d without outcome → fetch via PRAW",
      "Record: upvotes, num_replies, was_removed, was_locked",
      "Outcome stored as JSON in reply_log.outcome",
      "Writes to Notion ♻️ Replied view (Upvotes 7d / Replies 7d / Outcome columns)"],
     ""),

    ("5 Postmortem", "5.4", "postmortem-skill",
     "/reddit-engage postmortem skill",
     "user", "a command that triggers the auto-detect + outcome jobs",
     "I can pull the latest outcome data on demand",
     "S (1-3h)",
     ["skills/reddit-engage-postmortem/SKILL.md",
      "Runs auto-detect + outcome jobs sequentially",
      "Emits inline summary: 'N new replies detected, M outcomes recorded'"],
     ""),

    ("5 Postmortem", "5.5", "weekly-digest",
     "Weekly digest in pulse: pattern-that-worked / pattern-that-flopped",
     "user", "a weekly summary of pattern ROI",
     "I learn which sub-skill is worth the daily time",
     "S (1-3h)",
     ["pulse.py aggregates reply_log over rolling 7d",
      "Per-pattern: avg upvotes, reply rate, ban rate",
      "Top pattern + bottom pattern called out in digest",
      "Written to Obsidian weekly note (Phase 4.4)"],
     ""),

    # ─── Phase 6: Presets ───
    ("6 Presets", "6.1", "preset-b2b-saas-founder",
     "B2B SaaS founder preset",
     "B2B SaaS founder user", "a preset bundle that surfaces ICP pain posts on day 1",
     "I get value before customizing anything",
     "M (3-8h)",
     ["presets/b2b-saas-founder.yml exists",
      "Researched via market-researcher agent: 10-15 subs (T1/T2), 30-50 keywords, 30-50 brands",
      "5 example 'pain post' titles for prompt few-shots",
      "Persona description + ICP statement"],
     "Spawn market-researcher agent for the actual research."),

    ("6 Presets", "6.2", "preset-agency-owner",
     "Agency owner preset",
     "agency owner user", "a preset tuned to agency operational pain",
     "I get a tailored daily list",
     "M (3-8h)",
     ["presets/agency-owner.yml",
      "Subs around r/agency, r/AdAgency, r/digitalagency, r/marketing operators",
      "Keywords around client churn, retainer pain, scoping creep",
      "Same structure as 6.1"],
     ""),

    ("6 Presets", "6.3", "preset-indie-hacker",
     "Indie hacker preset",
     "indie hacker user", "a preset for solo-builder pain surfacing",
     "I find threads where my niche tool fits",
     "M (3-8h)",
     ["presets/indie-hacker.yml",
      "Subs: r/indiehackers, r/SideProject, r/Entrepreneur (kept here, fits ICP)",
      "Keywords: launch pain, marketing-from-zero, distribution problems",
      "Same structure as 6.1"],
     ""),

    ("6 Presets", "6.4", "preset-consultant",
     "Consultant preset",
     "consultant user", "a preset tuned for advisory engagement signals",
     "I find prospects describing problems I solve",
     "M (3-8h)",
     ["presets/consultant.yml",
      "Subs around r/consulting, r/sysadmin, r/devops, vertical-specific subs",
      "Keywords: 'looking for help with', 'anyone done X', engagement-shape signals",
      "Same structure as 6.1"],
     ""),

    # ─── Phase 7: Setup wizard ───
    ("7 Setup wizard", "7.1", "setup-skill",
     "/reddit-engage setup skill orchestrator",
     "new user", "a conversational wizard that gets me to first run in <10 min",
     "OSS adoption doesn't bounce on config friction",
     "M (3-8h)",
     ["skills/reddit-engage/SKILL.md routes `setup` keyword to wizard mode",
      "Wizard checks current state at each step (resumable)",
      "Steps: OAuth → LLM → Preset → Notion (opt) → Obsidian (opt) → Dry-run",
      "Final step prints next-action checklist"],
     "Reference: PLAN.md §4 Phase 7."),

    ("7 Setup wizard", "7.2", "oauth-step",
     "Setup step: OAuth registration walkthrough",
     "new user", "guided link + screenshots to register Reddit app",
     "I don't need to read external docs",
     "S (1-3h)",
     ["Step prompts: open reddit.com/prefs/apps + screenshot",
      "Collects client_id + client_secret + username",
      "Tests OAuth with 1 PRAW call against r/test",
      "Writes oauth.json"],
     ""),

    ("7 Setup wizard", "7.3", "llm-step",
     "Setup step: LLM provider detect/prompt",
     "new user", "automatic provider selection or guided override",
     "I don't think about which LLM to use",
     "S (1-3h)",
     ["Detects `claude` CLI in PATH → defaults claude_cli",
      "Else: prompts for ANTHROPIC_API_KEY",
      "Writes llm.json",
      "Skip path: 'no classifier' → engine falls back to regex-only"],
     ""),

    ("7 Setup wizard", "7.4", "preset-step",
     "Setup step: preset picker",
     "new user", "a menu of 4 industry presets to pick from",
     "I get on-ramp configs without writing YAML",
     "S (1-3h)",
     ["Lists 4 presets with one-line descriptions",
      "Copies chosen preset → ~/.config/reddit-engage/{subreddits.yml, keywords.yml, weights.yml}",
      "Notes which preset was applied in config.yml"],
     ""),

    ("7 Setup wizard", "7.5", "notion-step",
     "Setup step: Notion integration (optional)",
     "new user", "guided Notion DB creation or existing-DB hookup",
     "Notion sync is a 2-click decision",
     "M (3-8h)",
     ["Prompt: enable Notion? (skip-allowed)",
      "If yes: collect NOTION_API_KEY, either create new DB via API or accept existing DB URL",
      "Test write: insert a fixture row, verify visible",
      "Writes notion.yml"],
     ""),

    ("7 Setup wizard", "7.6", "obsidian-step",
     "Setup step: Obsidian integration (optional)",
     "new user", "vault path collection for weekly pulse",
     "Obsidian sync is opt-in and trivial",
     "S (1-3h)",
     ["Prompt: enable Obsidian? (skip-allowed)",
      "If yes: collect vault path + optional pulse subfolder",
      "Test write: create a placeholder note, verify",
      "Writes obsidian.yml"],
     ""),

    ("7 Setup wizard", "7.7", "dry-run",
     "Setup step: dry-run validation",
     "new user", "evidence the full pipeline works end-to-end before saving",
     "I see green checks before considering setup done",
     "S (1-3h)",
     ["Runs: OAuth ping, LLM ping, fetch 5 posts from one preset sub, classifier on 1 post, Notion write (if enabled), Obsidian write (if enabled)",
      "Prints checklist with ✓/✗",
      "On all-pass: announces 'setup complete, run /reddit-engage to start'"],
     ""),

    ("7 Setup wizard", "7.8", "readme-rewrite",
     "Full README rewrite for OSS launch",
     "GitHub visitor", "a README that converts stars + users",
     "the repo looks credible from first glance",
     "M (3-8h)",
     ["Badges (license, version, plugin install)",
      "Hero GIF (from Phase 8.1)",
      "Tagline (Dan-voice, anti-corporate)",
      "Install + Setup + Usage + Sub-skills table",
      "Architecture diagram (PLAN.md §2 layout)",
      "FAQ + Troubleshooting",
      "Roadmap linking to PLAN.md"],
     ""),

    # ─── Phase 8: Polish ───
    ("8 Polish", "8.1", "hero-gif",
     "Hero GIF for README",
     "GitHub visitor", "an animated hero that shows the daily run in action",
     "the README is visually compelling",
     "S (1-3h)",
     ["Use /claude-gif skill to generate or convert recording",
      "Shows: /reddit-engage invocation → inline output → Notion view",
      "<3MB, loops cleanly, looks pro"],
     ""),

    ("8 Polish", "8.2", "tag-v010",
     "Tag v0.1.0 release",
     "GitHub visitor", "an annotated git tag marking the first OSS release",
     "users can pin to a stable version",
     "XS (≤1h)",
     ["git tag -a v0.1.0 with detailed release notes",
      "Notes summarize: 10 sub-skills, OAuth, classifier, dedup, presets, setup wizard",
      "git push --tags",
      "GitHub release created with same notes"],
     ""),

    ("8 Polish", "8.3", "clawhub-submit",
     "Submit to clawhub (optional)",
     "OSS user", "the plugin discoverable in the Claude marketplace",
     "non-GitHub adopters find it",
     "XS (≤1h)",
     ["Follow last30days plugin submission pattern",
      "Verify plugin.json metadata complete",
      "Submit PR to clawhub registry"],
     "Optional — decide at launch."),
]


def slugify_phase(phase: str) -> str:
    # "-1 Bootstrap" -> "p-1", "0 Scaffold" -> "p0", "1 Tier A" -> "p1"
    head = phase.split(" ", 1)[0]
    return f"p{head}"


def emit_story_file(story: tuple) -> Path:
    phase, num, slug, title, role, action, benefit, effort, ac_lines, dev_notes = story
    phase_slug = slugify_phase(phase)
    filename = f"{phase_slug}.{num}-{slug}.md"
    path = STORIES_DIR / filename
    if path.exists():
        return path

    ac_block = "\n".join(f"{i+1}. {ac}" for i, ac in enumerate(ac_lines))
    tasks_block = "\n".join(f"- [ ] {ac[:80]}{'...' if len(ac) > 80 else ''} (AC: {i+1})" for i, ac in enumerate(ac_lines))

    content = f"""---
phase: "{phase}"
story-num: "{num}"
slug: "{slug}"
effort: "{effort}"
status: ready-for-dev
agent: SM
---

# Story {num}: {title}

Status: ready-for-dev

## Story

As a {role},
I want {action},
so that {benefit}.

## Acceptance Criteria

{ac_block}

## Tasks / Subtasks

{tasks_block}

## Dev Notes

{dev_notes or "(none — read PLAN.md for context)"}

### References

- [Source: PLAN.md] — phase "{phase}"

## Dev Agent Record

### Agent Model Used

<!-- filled by Dev agent -->

### Debug Log References

### Completion Notes List

### File List
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def log_session_call(cmd_str: str) -> None:
    SESSION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SESSION_LOG.open("a") as f:
        f.write(cmd_str + "\n")


def gh(*args: str) -> dict:
    cmd = ["gh", *args]
    cmd_str = " ".join(cmd)
    log_session_call(cmd_str)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh failed: {cmd_str}\n{result.stderr}")
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw": result.stdout.strip()}


def existing_draft_titles(project_id: str) -> set[str]:
    """List existing draft item titles on the Project board (for idempotency)."""
    query = (
        'query{node(id:"%s"){... on ProjectV2{items(first:100){nodes{'
        'content{... on DraftIssue{title}}}}}}}' % project_id
    )
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    nodes = data.get("data", {}).get("node", {}).get("items", {}).get("nodes", [])
    titles = set()
    for n in nodes:
        c = n.get("content") or {}
        t = c.get("title")
        if t:
            titles.add(t)
    return titles


def add_draft_item(project_id: str, title: str, body: str) -> str:
    """Create a draft (issueless) item on the Project board. Returns item ID."""
    mutation = (
        'mutation{addProjectV2DraftIssue(input:{projectId:"%s",title:%s,body:%s}){'
        'projectItem{id}}}'
    ) % (project_id, json.dumps(title), json.dumps(body))
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={mutation}"],
        capture_output=True, text=True, check=True,
    )
    log_session_call(f"gh project draft-add {title!r}")
    return json.loads(result.stdout)["data"]["addProjectV2DraftIssue"]["projectItem"]["id"]


def file_issues_for_stories() -> None:
    """Create Project board draft items (NOT GitHub issues) per story.

    The board itself IS the source of truth — no need to back every card with
    a repo issue. Kanban-pure.
    """
    refs = yaml.safe_load(REFS_PATH.read_text())
    project_id = refs["project"]["id"]
    fields = refs["fields"]
    f_status = fields["status"]
    f_phase = fields["phase"]
    f_agent = fields["agent"]
    f_effort = fields["effort"]
    f_storyref = fields["story_ref"]

    existing = existing_draft_titles(project_id)

    def set_select(item_id: str, field_id: str, option_id: str) -> None:
        mutation = (
            'mutation{updateProjectV2ItemFieldValue(input:{'
            'projectId:"%s",itemId:"%s",fieldId:"%s",'
            'value:{singleSelectOptionId:"%s"}}){projectV2Item{id}}}'
        ) % (project_id, item_id, field_id, option_id)
        subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={mutation}"],
            capture_output=True, text=True, check=True,
        )
        log_session_call(f"gh project item-edit --id {item_id} --field-id {field_id}")

    def set_text(item_id: str, field_id: str, value: str) -> None:
        mutation = (
            'mutation{updateProjectV2ItemFieldValue(input:{'
            'projectId:"%s",itemId:"%s",fieldId:"%s",'
            'value:{text:%s}}){projectV2Item{id}}}'
        ) % (project_id, item_id, field_id, json.dumps(value))
        subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={mutation}"],
            capture_output=True, text=True, check=True,
        )
        log_session_call(f"gh project item-edit --id {item_id} --field-id {field_id}")

    for story in STORIES:
        phase, num, slug, title, *_, effort, ac_lines, _ = story
        card_title = f"[{num}] {title}"
        if card_title in existing:
            print(f"  skip (exists): {card_title}")
            continue

        story_path = f"docs/stories/{slugify_phase(phase)}.{num}-{slug}.md"
        body = (
            f"**Story file:** `{story_path}`\n\n"
            f"**Phase:** {phase}  ·  **Effort:** {effort}\n\n"
            "Acceptance criteria + dev notes live in the story file."
        )

        item_id = add_draft_item(project_id, card_title, body)
        print(f"  created card: {card_title}")

        set_select(item_id, f_phase["id"], f_phase["options"][phase])
        set_select(item_id, f_agent["id"], f_agent["options"]["SM"])
        set_select(item_id, f_effort["id"], f_effort["options"][effort])
        set_select(item_id, f_status["id"], f_status["options"]["Backlog"])
        set_text(item_id, f_storyref["id"], story_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit", action="store_true", help="Write story files")
    parser.add_argument("--file-issues", action="store_true", help="Create gh issues + project items")
    parser.add_argument("--all", action="store_true", help="Both")
    args = parser.parse_args()

    if args.all or args.emit:
        print(f"Emitting {len(STORIES)} story files to {STORIES_DIR}/")
        for story in STORIES:
            path = emit_story_file(story)
            print(f"  {path.name}")

    if args.all or args.file_issues:
        print("Filing GitHub issues + project items")
        file_issues_for_stories()

    if not any([args.emit, args.file_issues, args.all]):
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
