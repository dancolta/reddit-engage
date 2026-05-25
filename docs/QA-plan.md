# QA test plan — reddit-engage live testing on Dan's setup

**Status:** Ready to execute. Each test is a Kanban card on Project #7 in the `Backlog` lane, Phase = `QA`.

**Why this plan exists:** the 76 unit tests cover the engine logic with mocks. They don't prove the plug-and-play story actually works end-to-end with live Reddit, live Notion, your actual OAuth credentials, and your actual Notion DB at `https://www.notion.so/b4d9a0e7c9304087af5ba248976edf60`. This plan does.

**Execution model:** every test runs through the same BMAD flow as the build did — `bmad-sm` files the test on the board, `bmad-dev` (or you, manually) executes the test steps, `bmad-qa` validates pass/fail criteria. The Stop-hook still enforces — no code changes during a QA pass without a corresponding board card.

---

## Pre-flight (one-time, run before any test)

| Step | Command | Pass condition |
|---|---|---|
| Engine installed | `cd ~/Work/.../reddit-engage && pip install -e '.[reddit,anthropic,notion]'` | No errors |
| Plugin loaded | In Claude Code: `/plugin install dancolta/reddit-engage` | `/reddit-engage:run` resolves to a skill |
| Migration run | `PYTHONPATH=engine python3 engine/scripts/migrate_to_xdg.py` | Legacy DB copied to `~/.local/share/reddit-engage/`, row counts match |
| Local config present | `ls ~/.config/reddit-engage/` | `notion.yml` exists with your DB ID |
| Tests still green | `PYTHONPATH=engine python3 -m pytest engine/tests/ -q` | **76 passed** |
| Plugin validates | `claude plugin validate .` | passes with 1 known warning |

If any pre-flight fails, fix before running QA tests below.

---

## Test plan (10 cards, ~2 hours total)

### QA-1 — Default daily run (zero-key path)
**BMAD agent:** `bmad-qa`
**Setup:**
- Temporarily move `~/.config/reddit-engage/oauth.json` aside (`mv → .bak`)
- Unset `ANTHROPIC_API_KEY`
- Move `~/.config/reddit-engage/notion.yml` aside
**Steps:**
1. `/reddit-engage:run` from Claude Code
**Pass criteria:**
- Surfaces appear inline as markdown (5–15 rows)
- No errors about missing OAuth/API key/Notion
- Console log indicates "regex-only gate", "OAuth fallback to public JSON", "classifier disabled"
- SQLite has new rows in `surfaced` table with `state='drafting'`
**Restore:** put the three config files back.

### QA-2 — OAuth path activates correctly
**BMAD agent:** `bmad-qa`
**Setup:** ensure `~/.config/reddit-engage/oauth.json` has client_id + client_secret + username (per docs/setup-oauth.md)
**Steps:**
1. `cd ~/Work/.../reddit-engage && PYTHONPATH=engine python3 -c "from reddit_engage.lib import reddit_oauth; print(reddit_oauth.has_oauth()); posts, _ = reddit_oauth.fetch_delta('sales', None, max_limit=5); [print(p['id'], p['title'][:60]) for p in posts]"`
**Pass criteria:**
- `has_oauth: True`
- 5 real posts from r/sales printed
- No fallback warning in stderr
- 10× rate budget verified by repeated calls without 429

### QA-3 — Author pre-gate kills throwaways
**BMAD agent:** `bmad-qa`
**Steps:**
1. `/reddit-engage:op-vet [deleted]` → must return `verdict: fail, reason: deleted_or_private`
2. `/reddit-engage:op-vet AutoModerator` → high karma + long history, must `pass`
3. Pick a known-young account from today's surfaces; verify the cache write in SQLite: `sqlite3 ~/.local/share/reddit-engage/reddit-engage.sqlite "SELECT username, verdict, reason FROM vetted_authors LIMIT 10"`
**Pass criteria:**
- All three behave as documented
- 7-day cache rows present

### QA-4 — Classifier path (interactive subscription)
**BMAD agent:** `bmad-qa`
**Setup:** ANTHROPIC_API_KEY NOT set
**Steps:**
1. `/reddit-engage:run` → produces today's list inline
2. `/reddit-engage:judge 3` (or any surface number you find interesting)
**Pass criteria:**
- Claude reads the post, runs classify.md prompt, returns verdict in human-readable table format
- Final verdict line: `Go.` / `Borderline — your call.` / `Skip.`
- Zero API cost (subscription only)

### QA-5 — Classifier path (bulk SDK)
**BMAD agent:** `bmad-qa`
**Setup:** Export `ANTHROPIC_API_KEY=sk-ant-...` in shell
**Steps:**
1. `/reddit-engage:run` again
**Pass criteria:**
- Engine output JSON shows each surface has a `classifier` field with `intent`/`buyer_stage`/`fit_score`/etc
- Stderr log shows `provider=anthropic_api`
- Daily cost (printed at end of run if available) < $0.20

### QA-6 — Notion sync to your DB
**BMAD agent:** `bmad-qa`
**Setup:**
- `~/.config/reddit-engage/notion.yml` has DB ID `b4d9a0e7c9304087af5ba248976edf60` + your `NOTION_API_KEY`
- DB must have Pattern + State + Fit (LLM) properties (run `engine/scripts/notion_migrate.py --database-id b4d9a0e7c9304087af5ba248976edf60` first if missing)
**Steps:**
1. `/reddit-engage:run`
2. Open https://www.notion.so/b4d9a0e7c9304087af5ba248976edf60
**Pass criteria:**
- New rows appear with: Title / Tier / Subreddit / Score / Pain / Fit / URL / Surfaced on / Pattern / State='Drafting'
- URL field shows clickable Reddit link (NOT hand-composed — read verbatim from engine JSON)
- 30 min later, run again → drafting rows flip to State='Hot'

### QA-7 — Sub-skill regression sweep
**BMAD agent:** `bmad-qa`
**Steps (run each, verify each produces a usable list):**
1. `/reddit-engage:stack-audit`
2. `/reddit-engage:churn`
3. `/reddit-engage:pricing-rage` — should bypass cooling queue (state='hot' immediately)
4. `/reddit-engage:build-vs-buy`
5. `/reddit-engage:rfp-bait`
6. `/reddit-engage:rivals HubSpot`
**Pass criteria:**
- Each emits at least 1 surface OR a coherent "no matches today" empty-state
- Each output JSON has correct `mode` field
- Each surface has the right emoji prefix in inline_markdown

### QA-8 — Postmortem auto-detect
**BMAD agent:** `bmad-qa` (requires you to actually reply to a Reddit thread first)
**Setup:** Have at least 1 reply to a surfaced post in your Reddit history (any one).
**Steps:**
1. `/reddit-engage:postmortem`
**Pass criteria:**
- `detect` block: `new_matches >= 1` (the reply you made)
- Row in `reply_log` SQLite table with correct `comment_id`, `comment_url`, `replied_at`
- If reply is >7 days old: `update` block shows `scored >= 1` with `outcome` JSON populated

### QA-9 — Obsidian pulse digest
**BMAD agent:** `bmad-qa`
**Setup:** `~/.config/reddit-engage/obsidian.yml` with your vault path
**Steps:**
1. `/reddit-engage:pulse`
**Pass criteria:**
- New file at `<vault>/reddit-engage/YYYY-WNN-pulse.md`
- Frontmatter: tags include `reddit-engage, pulse, week-NN`
- Body has "Sub × surface count" table populated from last 7 days
- If reply_log has data: "Postmortem" section present with averages

### QA-10 — End-to-end first-time-user simulation
**BMAD agent:** `bmad-qa` (manual, paranoia mode)
**Setup:** Spin up a fresh Linux VM OR temporarily rename `~/.config/reddit-engage/` to `~/.config/reddit-engage.bak/` and `~/.local/share/reddit-engage/` to `~/.local/share/reddit-engage.bak/`
**Steps:**
1. `/plugin install dancolta/reddit-engage` (or symlink from local repo)
2. `/reddit-engage:setup` — walk through the conversational wizard
3. Pick `b2b-saas-founder` preset
4. Skip Notion + Obsidian for this test (test default-only path)
5. `/reddit-engage:run`
**Pass criteria:**
- Wizard completes without errors
- Skip paths work cleanly (don't ask for OAuth/LLM/Notion if user says skip)
- Final `/reddit-engage:run` produces surfaces using b2b-saas-founder preset's sub list
- All files written to XDG paths (verify: `ls ~/.config/reddit-engage/` after setup)
- **RESTORE:** move the `.bak` directories back when done

---

## How to run each test (the BMAD flow)

For every test card above:

1. **`bmad-sm`** invocation: "File QA-N as a board card, Phase=QA, Effort=XS-S, Status=Backlog"
   - Creates a story file `docs/stories/qa.N-<slug>.md`
   - Adds card to GitHub Project #7
2. **Manual execution OR `bmad-dev`**: run the test steps yourself, then update the story file with actual output
   - Flip card to In Progress while running
   - Flip to In Review when done
3. **`bmad-qa`** invocation: read the story file's "actual output" section, validate against Pass criteria, flip to Done OR back to In Progress with gaps noted

The Stop-hook still enforces — if you edit any code during a QA pass, you must have filed a card first.

---

## Bulk-file all 10 QA cards (one command)

```bash
cd ~/Work/NodeSparks/Projects/reddit-engage
PYTHONPATH=engine python3 scripts/qa_to_board.py  # will be created on first run
```

Or manually via the SM agent: "file QA-1 through QA-10 as cards on Project #7, Phase=QA, Agent=QA, Status=Backlog."

---

## Pass-fail summary template

After running all 10, fill this in:

| Test | Status | Issues found | Card |
|---|---|---|---|
| QA-1 default | ⬜ pass / ⬜ fail | | |
| QA-2 OAuth | ⬜ pass / ⬜ fail | | |
| QA-3 author vet | ⬜ pass / ⬜ fail | | |
| QA-4 judge skill | ⬜ pass / ⬜ fail | | |
| QA-5 bulk SDK | ⬜ pass / ⬜ fail | | |
| QA-6 Notion | ⬜ pass / ⬜ fail | | |
| QA-7 sub-skills | ⬜ pass / ⬜ fail | | |
| QA-8 postmortem | ⬜ pass / ⬜ fail | | |
| QA-9 Obsidian | ⬜ pass / ⬜ fail | | |
| QA-10 fresh install | ⬜ pass / ⬜ fail | | |

If 10/10 pass, the plugin is ready for v0.1.0 public release. Push the tag:

```bash
git push --tags
gh release create v0.1.0 --notes-from-tag
```

If any test fails:
1. SM files a fix card on the board (Phase=QA-fix, Effort=appropriate)
2. Dev implements the fix
3. QA re-runs the failed test
4. Repeat until 10/10
