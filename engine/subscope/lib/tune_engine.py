"""Back-propagate Good/Bad/Meh feedback into weights + sub configs.

Used by `/subscope-tune`. The user marks 10 surfaces from a recent run
with `g` / `b` / `m` (good / bad / meh). This module ingests those marks
and updates:

  - `subreddits.yml` — per-sub weight nudged up (good marks) or down (bad)
  - `keywords.yml`   — per-keyword score nudged based on which keywords
                       matched on good/bad surfaces

Per ui-ux Phase 9 spec: shows a top-5 deltas readout after each round,
batches per round (not per mark), and never SILENTLY deletes a user-edited
sub even if it scored badly.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import yaml

from . import store


# Nudge magnitudes. Conservative defaults — three rounds × max 0.3 ≈ ±0.9
# total swing on weights starting at 1.0, never crossing the 0.0 floor or
# 2.0 ceiling.
GOOD_NUDGE = 0.15
BAD_NUDGE = -0.20         # bad slightly stronger than good (precision over recall)
MEH_NUDGE = -0.05
WEIGHT_FLOOR = 0.1        # never drop a sub below this from /tune alone
WEIGHT_CEILING = 2.0


def parse_marks(raw: str, expected_count: int = 10) -> dict[int, str]:
    """Parse a terse mark string like '1g 2g 3b 4m 5g 6b 7g 8m 9g 10b'.

    Returns {surface_index_1based: 'g' | 'b' | 'm'}. Missing indices default
    to 'm' (meh). Tolerates noise, extra whitespace, comma separation.
    """
    marks: dict[int, str] = {}
    for token in re.findall(r"(\d+)\s*([gbm])", raw.lower()):
        idx = int(token[0])
        mark = token[1]
        if 1 <= idx <= expected_count:
            marks[idx] = mark
    # Fill in missing as 'm'
    for i in range(1, expected_count + 1):
        marks.setdefault(i, "m")
    return marks


def apply_marks_to_subs(
    surfaces: list[dict[str, Any]],
    marks: dict[int, str],
    subs_path: Path | str,
) -> dict[str, Any]:
    """Nudge per-sub weights based on which subs produced good vs bad surfaces.

    Returns a delta report:
        {
          "changes": [{"name": "RevOps", "old_weight": 1.0, "new_weight": 1.4,
                       "good_marks": 3, "bad_marks": 0, "meh_marks": 1}, ...],
          "skipped": [...]  # subs not in tracked file
        }
    Writes the updated YAML back to subs_path. Never silently deletes a sub.
    """
    subs_path = Path(subs_path)
    data = yaml.safe_load(subs_path.read_text()) or {}
    subs_list = data.get("subreddits") or []
    by_name = {s["name"].lower(): s for s in subs_list}

    # Tally per-sub good/bad/meh counts
    counts: dict[str, dict[str, int]] = {}
    for idx, mark in marks.items():
        if idx - 1 >= len(surfaces):
            continue
        surface = surfaces[idx - 1]
        sub_name = (surface.get("subreddit") or "").lower()
        if not sub_name:
            continue
        counts.setdefault(sub_name, {"g": 0, "b": 0, "m": 0})
        counts[sub_name][mark] += 1

    changes: list[dict[str, Any]] = []
    skipped: list[str] = []

    for sub_name, c in counts.items():
        if sub_name not in by_name:
            skipped.append(sub_name)
            continue
        entry = by_name[sub_name]
        old_weight = float(entry.get("weight", 1.0))
        nudge = (c["g"] * GOOD_NUDGE) + (c["b"] * BAD_NUDGE) + (c["m"] * MEH_NUDGE)
        new_weight = max(WEIGHT_FLOOR, min(WEIGHT_CEILING, old_weight + nudge))
        entry["weight"] = round(new_weight, 2)
        if abs(new_weight - old_weight) >= 0.01:
            changes.append({
                "name": entry["name"],
                "old_weight": old_weight,
                "new_weight": new_weight,
                "good_marks": c["g"],
                "bad_marks": c["b"],
                "meh_marks": c["m"],
            })

    # Sort by absolute delta, biggest first (caller shows top 5)
    changes.sort(key=lambda x: abs(x["new_weight"] - x["old_weight"]), reverse=True)

    # Write back. Preserve top-of-file comments.
    yaml_out = _yaml_with_comments(data, original_text=subs_path.read_text())
    subs_path.write_text(yaml_out)
    return {"changes": changes, "skipped": skipped}


def _yaml_with_comments(data: dict[str, Any], original_text: str) -> str:
    """Naive comment preservation: keep the original top-of-file `#` lines,
    then emit the (potentially modified) YAML body. Good enough for our
    simple subreddits.yml structure. PyYAML proper has no comment round-trip.
    """
    header_lines: list[str] = []
    for line in original_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or stripped == "":
            header_lines.append(line)
        else:
            break
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    return "\n".join(header_lines) + "\n" + body


def record_session(
    marks: dict[int, str],
    changes: list[dict[str, Any]],
    surfaces: list[dict[str, Any]],
    round_num: int,
) -> Path:
    """Append this round's marks + deltas to a JSONL log for audit / future learning."""
    log_path = store._xdg_data_dir() / "tune-sessions.jsonl"
    record = {
        "timestamp": int(time.time()),
        "round": round_num,
        "marks": marks,
        "changes": changes,
        "surface_ids": [s.get("id") for s in surfaces],
    }
    with log_path.open("a") as f:
        f.write(json.dumps(record) + "\n")
    return log_path


def format_deltas_readout(changes: list[dict[str, Any]], round_num: int, total_rounds: int = 3) -> str:
    """Human-readable top-5 changes block per ui-ux spec."""
    if not changes:
        return f"Round {round_num} → Round {round_num + 1}: no significant changes."
    lines = [f"Round {round_num} → Round {round_num + 1} changes:"]
    for c in changes[:5]:
        delta = c["new_weight"] - c["old_weight"]
        marks_str = []
        if c["good_marks"]:
            marks_str.append(f"{c['good_marks']} good")
        if c["bad_marks"]:
            marks_str.append(f"{c['bad_marks']} bad")
        if c["meh_marks"]:
            marks_str.append(f"{c['meh_marks']} meh")
        sign = "+" if delta > 0 else ""
        lines.append(
            f"  r/{c['name']:<20} weight {c['old_weight']:.2f} → {c['new_weight']:.2f}  "
            f"({sign}{delta:.2f})  [{', '.join(marks_str)}]"
        )
    if round_num < total_rounds:
        lines.append("")
        lines.append(f"{10} more surfaces incoming. Round {round_num + 1} of {total_rounds}.")
    else:
        lines.append("")
        lines.append("Tuning complete. Updated weights saved to subreddits.yml.")
    return "\n".join(lines)
