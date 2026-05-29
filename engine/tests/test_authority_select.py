"""Tests for cli._select_authority (DT-3 wiring).

Synthetic-candidate tests of the second-pass authority selection: independent
cap, no double-surfacing of buyer posts, gate disposition folded into
dropped_counts, and the disable-flag revert. No Reddit network, no SQLite.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.cli import _select_authority  # noqa: E402


NOW = int(time.time())

KEYWORDS = [
    "invoicing", "invoice", "bookkeeping", "accounting", "reconciliation",
    "expense", "client", "workflow", "spreadsheet", "automation",
]


def _weights(enabled=True, cap=4, min_density=2) -> dict:
    return {
        "scoring": {
            "freshness_decay": {"zero_hours": 30, "max_points": 30},
            "upvote_velocity": {"multiplier": 4, "max_points": 20},
            "comment_velocity": {"multiplier": 6, "max_points": 15},
            "pain_keyword_match": {"points_per_keyword": 6, "max_points": 30},
            "blog_coverage_bonus": {"points_per_match": 25, "max_points": 50},
            "intent_bonus": {"question_bonus": 20, "pain_bonus": 15},
            "tier_weight": {"tier_1": 1.0, "tier_2": 1.25},
        },
        "authority_track": {
            "enabled": enabled,
            "cap": cap,
            "min_keyword_density": min_density,
            "scoring": {
                "reach_weight": 1.5, "answerability_weight": 1.5,
                "blog_weight": 1.5, "pain_weight": 0.25, "freshness_max_points": 30,
            },
        },
    }


def _candidate(post_id, *, reason="tier2_no_saas_brand", sub="Bookkeeping",
               tier=2, title=None, body="planning a workflow, no tool yet",
               score=10, num_comments=3, created_utc=None) -> dict:
    if title is None:
        title = "How do you handle invoicing and reconciliation for clients?"
    return {
        "post": {
            "id": post_id, "title": title, "subreddit": sub,
            "url": f"https://reddit.com/r/{sub}/comments/{post_id}/",
            "canonical_url": f"https://reddit.com/comments/{post_id}/",
            "author": "u", "created_utc": created_utc or (NOW - 3600),
            "score": score, "num_comments": num_comments, "body": body,
            "removed": False, "locked": False, "score_internal": 0.0,
        },
        "sub": {"name": sub, "tier": tier, "weight": 1.0, "saturation": "medium"},
        "blog_matches": [],
        "gate_reason": reason,
        "vet": {"verdict": "pass"},
        "bucket_kw": KEYWORDS,
    }


def test_select_authority_accepts_qualified_candidates():
    pool = [_candidate("a1"), _candidate("a2", sub="Accounting")]
    dropped: dict[str, int] = {}
    out = _select_authority(pool, set(), _weights(), dropped)
    ids = {c["post"]["id"] for c in out}
    assert ids == {"a1", "a2"}
    # Selected surfaces carry the authority score, not the buyer 0.0 placeholder.
    assert all(c["post"]["score_internal"] > 0 for c in out)


def test_select_authority_respects_independent_cap():
    pool = [_candidate(f"a{i}", sub=f"sub{i}") for i in range(10)]
    dropped: dict[str, int] = {}
    out = _select_authority(pool, set(), _weights(cap=4), dropped)
    assert len(out) == 4


def test_select_authority_no_double_surface_of_buyer_post():
    """A post already surfaced on the buyer track must NOT appear in authority."""
    pool = [_candidate("dup1"), _candidate("a2", sub="Accounting")]
    dropped: dict[str, int] = {}
    out = _select_authority(pool, {"dup1"}, _weights(), dropped)
    ids = {c["post"]["id"] for c in out}
    assert "dup1" not in ids
    assert "a2" in ids


def test_select_authority_disabled_returns_empty():
    """Disable flag = no authority surfaces at all (revert to buyer-only)."""
    pool = [_candidate("a1"), _candidate("a2", sub="Accounting")]
    dropped: dict[str, int] = {}
    out = _select_authority(pool, set(), _weights(enabled=False), dropped)
    assert out == []
    assert dropped == {}, "disabled track must not record any disposition"


def test_select_authority_rejections_fold_into_dropped_counts():
    """Career post + non-eligible-reason candidate are recorded, not surfaced."""
    pool = [
        _candidate("good1"),
        _candidate("career1",
                   title="Should I switch careers into accounting? good career?",
                   body="wondering about salary and the workflow"),
        _candidate("badreason1", reason="tier2_keyword_density"),
    ]
    dropped: dict[str, int] = {}
    out = _select_authority(pool, set(), _weights(), dropped)
    ids = {c["post"]["id"] for c in out}
    assert ids == {"good1"}
    assert dropped.get("authority_career_identity") == 1
    assert dropped.get("authority_not_eligible_reason") == 1


def test_select_authority_dedups_crosspost_keeps_higher():
    """Two identical (sub, title) candidates collapse to one (higher reach)."""
    low = _candidate("lo", score=2, num_comments=1)
    high = _candidate("hi", score=90, num_comments=40)
    dropped: dict[str, int] = {}
    out = _select_authority([low, high], set(), _weights(), dropped)
    assert len(out) == 1
    assert out[0]["post"]["id"] == "hi"


def test_select_authority_empty_pool():
    dropped: dict[str, int] = {}
    assert _select_authority([], set(), _weights(), dropped) == []


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
