#!/usr/bin/env bash
# Stop-hook: blocks session completion when code was edited without filing
# a corresponding task on the GitHub Project board.
#
# Triggers: Claude Code Stop event
# Reads: session transcript (CLAUDE_TRANSCRIPT_PATH env) + session log
# Behavior:
#   - If any Edit/Write/NotebookEdit tool was called this session
#     AND no `gh issue` / `gh project` API call was logged
#     → exit 2 with instructions to file the task first.
#
# Bypass: append `[bmad-bypass]` to the user message that triggered the work,
# OR set BMAD_BYPASS=1 in the shell. Bypasses are logged.

set -euo pipefail

REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
SESSION_LOG="${REPO_ROOT}/.claude/session-tasks.log"
TRANSCRIPT_PATH="${CLAUDE_TRANSCRIPT_PATH:-}"
BYPASS_LOG="${REPO_ROOT}/.claude/bypass.log"

# Bypass guard
if [ "${BMAD_BYPASS:-0}" = "1" ]; then
  echo "$(date -u +%FT%TZ) BYPASS via BMAD_BYPASS=1" >> "$BYPASS_LOG"
  exit 0
fi

# If no transcript, can't validate. Don't block.
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
  exit 0
fi

# Check if user message contained bypass token
if grep -q '\[bmad-bypass\]' "$TRANSCRIPT_PATH" 2>/dev/null; then
  echo "$(date -u +%FT%TZ) BYPASS via [bmad-bypass] token in user message" >> "$BYPASS_LOG"
  exit 0
fi

# Did this session use any code-editing tool?
code_edited=$(grep -cE '"name"\s*:\s*"(Edit|Write|NotebookEdit)"' "$TRANSCRIPT_PATH" 2>/dev/null || echo 0)

if [ "$code_edited" -eq 0 ]; then
  exit 0  # read-only / chat-only session, no gate
fi

# Did the session log a board API call (issue creation, project item edit)?
board_calls=0
if [ -f "$SESSION_LOG" ]; then
  board_calls=$(grep -cE '^gh (issue|project) (create|item-add|item-edit)' "$SESSION_LOG" 2>/dev/null || echo 0)
fi

if [ "$board_calls" -eq 0 ]; then
  cat >&2 <<'EOF'
═══════════════════════════════════════════════════════════════════════════
  STOP-HOOK BLOCK: code was edited this session but no GitHub Project
  task was filed or updated.

  STRICT FLOW (PLAN.md §9) requires:
    1. bmad-sm files a story + GitHub issue → Status=Backlog
    2. bmad-dev flips Status=In Progress → implements → Status=In Review
    3. bmad-qa verifies → Status=Done

  Fix: invoke the bmad-sm skill to create the story now, then re-stop.

  Bypass (logged): append [bmad-bypass] to your message, OR set BMAD_BYPASS=1.
═══════════════════════════════════════════════════════════════════════════
EOF
  exit 2
fi

exit 0
