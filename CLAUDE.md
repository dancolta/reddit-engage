# reddit-engage — Repo Development Conventions

> **Scope of this file:** repo-internal dev guidance ONLY. This is what Claude reads when working *on* this codebase (Phase -1 → Phase 8 build). It is **not plugin user-facing context** and is intentionally excluded from the plugin distribution surface — `claude plugin validate` warns about this placement, which is expected (see PLAN.md §9 for justification).
>
> User-facing plugin context lives in [`skills/`](skills/) (auto-discovered) and [`README.md`](README.md).

Follow these conventions exactly while building this plugin.

## Source of truth

| Artifact | Purpose | Editable? |
|---|---|---|
| [`PLAN.md`](PLAN.md) | Full stress-tested build plan, scope, phases, decisions | **No** — only Dan changes scope |
| [`docs/stories/`](docs/stories/) | Sharded BMAD story files, one per work item | Updated by SM/Dev/QA agents |
| [GitHub Project #7](https://github.com/users/dancolta/projects/7) | Live Kanban board with Status/Phase/Agent/Effort | Updated by every BMAD agent turn |
| [`.bmad-board/refs.yml`](.bmad-board/refs.yml) | Field IDs + option IDs for `gh api graphql` calls | Regenerate if board schema changes |

## STRICT FLOW — non-negotiable

**No code change ships without a corresponding card on Project #7 moving `Backlog → In Progress → In Review → Done`.**

For ANY request that touches code or config:

```
1. Invoke bmad-sm (alias for bmad-create-story)
   → reads docs/stories/<story-id>.md
   → if missing: creates draft card on Project #7 (Status=Backlog, Agent=SM, Effort=<size>)
   → writes/updates the story file

2. Invoke bmad-dev (alias for bmad-agent-dev, persona "Amelia")
   → reads the story file
   → flips Status=In Progress via gh api graphql
   → implements with test-first discipline
   → updates story file (file list, completion notes)
   → flips Status=In Review

3. Invoke bmad-qa (alias for bmad-code-review)
   → reads story + implementation
   → runs tests, verifies AC
   → if pass: flips Status=Done
   → if fail: flips Status=In Progress, comments gaps
```

Reporting "done" to Dan **without completing this loop is forbidden**. The Stop-hook at `.claude/hooks/stop-task-gate.sh` blocks any session that edits code without logging a `gh project` API call. If you hit that block, file the card properly — do not bypass the hook.

## Field IDs reference

All field + option IDs are in [`.bmad-board/refs.yml`](.bmad-board/refs.yml). Always read from that file rather than hardcoding.

Example: flip Status to "In Progress":

```bash
PROJECT_ID="PVT_kwHOBegOq84BYvhw"
ITEM_ID="<from item-add>"
STATUS_FIELD="PVTSSF_lAHOBegOq84BYvhwzhTzGqM"
IN_PROGRESS="c179d3d0"

gh api graphql -f query='
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "'$PROJECT_ID'", itemId: "'$ITEM_ID'",
    fieldId: "'$STATUS_FIELD'",
    value: { singleSelectOptionId: "'$IN_PROGRESS'" }
  }) { projectV2Item { id } }
}'
```

Every `gh api graphql` / `gh project` call must be appended to `.claude/session-tasks.log` so the Stop-hook can verify the board was touched.

## When the Stop-hook fires

| Session activity | Hook behavior |
|---|---|
| Read-only / chat-only (no Edit/Write/NotebookEdit) | No block — exits 0 |
| Edited code AND logged a board API call | No block — exits 0 |
| Edited code AND no board API call logged | **Block (exit 2)** with instructions |
| User added `[bmad-bypass]` to their message | No block — logged to `.claude/bypass.log` |
| `BMAD_BYPASS=1` env var set | No block — logged to `.claude/bypass.log` |

If you genuinely need to skip the gate (rare — e.g. emergency hotfix, fixing the hook itself), use one of the documented escape hatches. Don't try to evade the hook through other means.

## BMAD agent aliases

| Alias | Real skill | Persona | When to invoke |
|---|---|---|---|
| `bmad-sm` | `bmad-create-story` | Scrum Master | Start any new work item |
| `bmad-dev` | `bmad-agent-dev` | Amelia (Senior Software Engineer) | Implement an approved story |
| `bmad-qa` | `bmad-code-review` | QA reviewer | Verify a story's AC are met |

Other BMAD skills (`bmad-prd`, `bmad-agent-architect`, etc.) are installed but **not part of the dev cycle**. Don't invoke them unless Dan explicitly asks — PLAN.md replaces planning-phase output.

## What lives where

```
.
├── PLAN.md                         # frozen build plan
├── CLAUDE.md                       # this file
├── README.md                       # public-facing
├── .claude/
│   ├── settings.json               # registers Stop-hook
│   ├── hooks/stop-task-gate.sh     # the gate
│   ├── session-tasks.log           # evidence the gate reads
│   ├── bypass.log                  # logged hook bypasses
│   └── skills/                     # BMAD-installed Claude skills (auto-symlinked)
├── _bmad/                          # BMAD configs + scripts (don't edit)
├── _bmad-output/                   # BMAD's planning/impl artifacts
├── .bmad-board/refs.yml            # Project field IDs reference
├── docs/stories/                   # sharded BMAD stories (live work surface)
├── scripts/plan_to_stories.py      # regenerate stories + board cards
├── engine/                         # (Phase 0) Python project
├── skills/                         # (Phase 0) plugin's user-invoked skills
└── presets/                        # (Phase 6) industry preset configs
```

## NodeSparks-specific notes

- Dan's personal preset lives at `~/.config/reddit-engage/nodesparks-ops.yml`, **not** in this repo
- Public presets in `presets/` must stay generic — no NodeSparks branding, blog URLs, or proprietary keywords
- Voice-drift detector dropped (see PLAN.md §6); do not add voice-grading features
- "Setup wizard" terminology refers to `/reddit-engage setup`, the Claude-orchestrated onboarding flow

## Pure-research / planning conversations

If Dan asks a question, requests research, or wants planning input — **no story or card needed**. The Stop-hook only fires when Edit/Write/NotebookEdit was called. Read-only work is unrestricted.

## Quality bar — Anthropic compliance (non-negotiable)

This plugin ships under Dan's name. Every artifact must pass an outside-audit quality bar against Anthropic's current published guidance — **not memorized knowledge, fetched at compliance time**.

**Before any QA Done flip**, the QA agent MUST:

1. Identify which Anthropic-controlled surfaces the story touched:
   - `.claude-plugin/plugin.json` → plugin manifest schema
   - `skills/**/SKILL.md` → skill frontmatter + body conventions
   - `.claude/hooks/*.sh` + `.claude/settings.json` → hook event contracts (exit codes, env vars)
   - Any code that calls the Claude API or `claude` CLI → SDK patterns + prompt caching
2. Fetch the current spec for that surface from `docs.claude.com` (don't infer from training data — schemas evolve)
3. Diff our implementation against the spec
4. Block Done if any deviation isn't already documented with a "why" in code comments + PLAN.md

**Reference URLs (always fetch fresh):**
- https://docs.claude.com/en/docs/agents-and-tools/agent-skills
- https://docs.claude.com/en/docs/claude-code/plugins
- https://docs.claude.com/en/docs/claude-code/hooks
- https://docs.claude.com/en/api/prompt-engineering
- https://docs.claude.com/en/docs/claude-code/sdk

**Justified deviations** (e.g. our BMAD-flow Stop-hook gating) must be documented inline + cross-referenced in PLAN.md so a future reviewer doesn't think it's an oversight.

## When to escalate to Dan

- Scope changes (anything that would edit PLAN.md outside §8 status checkboxes)
- New phases or stories not in the original 63
- BMAD agent persona drift (Amelia going off-character, etc.)
- Stop-hook blocking legitimate work — don't paper over with bypasses, report the gap
