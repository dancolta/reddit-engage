"""Lazy authority-vetting tests (merge: dual-track on the 403 rate-limit fix).

Two interactions are guarded here, both specific to running the dual-track
authority pass on top of the 403 rate-limit-hardened fetch loop:

1. LAZY VET FIRES (rate-limit safety). The main fetch loop does NOT vet
   authority-only candidates (it defers with candidate["vet"] = None) to avoid
   re-pressuring Reddit's RSS rate limit on the largest bucket of posts. The vet
   instead fires inside `_select_authority`, but only for posts that already
   passed the deterministic authority gate. These tests exercise the LIVE
   `author_vet.vet_author` path (no synthetic vet dict on the candidate) and
   prove (a) the vet actually runs and (b) a failing author is dropped.

2. DESIGN FIX 1 (the line ~312 interaction). The 403 fix added a lexical-gate
   early drop: `if not passes and not backfill_eligible: continue`. A brandless
   on-topic question is NOT backfill-eligible (no brand), so without sparing
   authority-eligible posts that `continue` would cull it before it ever reaches
   the authority pool, leaving the track nearly empty. This drives the REAL
   cmd_fetch_score and asserts a clean brandless question actually surfaces on
   the authority track.

No live Reddit fetch: the network boundaries (reddit.fetch_delta + author_vet)
are mocked, so these run offline and cost zero RSS requests.
"""
import io
import json
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope import cli  # noqa: E402
from subscope.cli import _select_authority  # noqa: E402
from subscope.lib import author_vet, classify, enrich, reddit, score, slack  # noqa: E402


NOW = int(time.time())

KEYWORDS = [
    "invoicing", "invoice", "bookkeeping", "accounting", "reconciliation",
    "expense", "client", "workflow", "spreadsheet", "automation",
]


def _weights(authority_enabled: bool = True, cap: int = 4, min_density: int = 2) -> dict:
    return {
        "tier1_gates": {"post_age_hours": 48, "comment_ceiling": 100, "pain_keywords_min": 1},
        "tier2_gates": {"post_age_hours": 72, "pain_keywords_min": 1, "pain_keywords_min_wide_open": 1},
        "scoring": {
            "freshness_decay": {"zero_hours": 30, "max_points": 30},
            "upvote_velocity": {"multiplier": 4, "max_points": 20},
            "comment_velocity": {"multiplier": 6, "max_points": 15},
            "pain_keyword_match": {"points_per_keyword": 6, "max_points": 30},
            "blog_coverage_bonus": {"points_per_match": 25, "max_points": 50},
            "intent_bonus": {"question_bonus": 20, "pain_bonus": 15},
            "tier_weight": {"tier_1": 1.0, "tier_2": 1.25},
        },
        "daily_output": {
            "hard_ceiling": 12, "default_target": 10, "minimum": 0,
            "tier1_per_sub_cap": 2, "tier2_per_sub_cap": 2,
            "backfill_sub_cap_bonus": 1,
            "pattern_caps": {"default": 10},
        },
        "freshness_floor": {"enabled": False},
        "authority_track": {
            "enabled": authority_enabled,
            "cap": cap,
            "min_keyword_density": min_density,
            "scoring": {"reach_weight": 1.5, "answerability_weight": 1.5,
                        "blog_weight": 1.5, "pain_weight": 0.25,
                        "freshness_max_points": 30},
        },
        "cooling": {"default_minutes": 0},
    }


# ─── Test 1: lazy vet fires on the gate survivor and drops a failing author ──

def _deferred_candidate(post_id="auth1") -> dict:
    """An authority-only candidate AS THE MAIN LOOP BUILDS IT: vet deferred to
    None (no synthetic verdict). A clean brandless on-topic question that clears
    the deterministic authority gate, so the lazy vet in _select_authority runs.
    """
    return {
        "post": {
            "id": post_id,
            "subreddit": "Bookkeeping",
            "title": "How do you handle invoicing and reconciliation for retainer clients?",
            "url": f"https://reddit.com/r/Bookkeeping/comments/{post_id}/x/",
            "canonical_url": f"https://reddit.com/comments/{post_id}/",
            "author": "auth_op",
            "created_utc": NOW - 3600,
            "score": 25, "num_comments": 12,
            "body": "planning a clean workflow, no tool picked yet",
            "removed": False, "locked": False, "score_internal": 0.0,
        },
        "sub": {"name": "Bookkeeping", "tier": 2, "weight": 1.0, "saturation": "medium"},
        "blog_matches": [],
        "gate_reason": "tier2_no_saas_brand",
        "vet": None,  # deferred by the main loop (lazy)
        "bucket_kw": KEYWORDS,
    }


def test_lazy_vet_fires_and_rejects_failing_author(monkeypatch):
    """The author vet runs LIVE inside _select_authority (candidate vet is None)
    and a failing verdict drops the candidate, folded into dropped_counts under
    its author_vet_<reason> key. Proves the deferred vet actually fires."""
    calls: list[str] = []

    def fake_vet(author, conn=None, weights=None):
        calls.append(author)
        return {"verdict": "fail", "reason": "wrong_audience"}

    monkeypatch.setattr(author_vet, "vet_author", fake_vet)

    pool = [_deferred_candidate("auth1")]
    dropped: dict[str, int] = {}
    out = _select_authority(pool, set(), _weights(), dropped, conn=None)

    assert out == [], "a failing-author candidate must not surface"
    assert calls == ["auth_op"], "lazy vet must fire exactly once on the gate survivor"
    assert dropped.get("author_vet_wrong_audience") == 1


def test_lazy_vet_passes_clean_author(monkeypatch):
    """The mirror case: a clean author lets the gate survivor through, and the
    surface carries the authority score (not the 0.0 placeholder)."""
    calls: list[str] = []

    def fake_vet(author, conn=None, weights=None):
        calls.append(author)
        return {"verdict": "pass", "reason": "ok"}

    monkeypatch.setattr(author_vet, "vet_author", fake_vet)

    pool = [_deferred_candidate("auth1")]
    dropped: dict[str, int] = {}
    out = _select_authority(pool, set(), _weights(), dropped, conn=None)

    assert [c["post"]["id"] for c in out] == ["auth1"]
    assert calls == ["auth_op"], "lazy vet must fire on the deferred candidate"
    assert out[0]["post"]["score_internal"] > 0


def test_lazy_vet_not_fired_when_gate_rejects(monkeypatch):
    """A candidate that fails the deterministic authority gate must NOT trigger a
    network vet (the whole point of running the gate first). Career/identity post
    is dropped on the gate, before any vet."""
    calls: list[str] = []

    def fake_vet(author, conn=None, weights=None):
        calls.append(author)
        return {"verdict": "pass", "reason": "ok"}

    monkeypatch.setattr(author_vet, "vet_author", fake_vet)

    c = _deferred_candidate("career1")
    c["post"]["title"] = "Should I switch careers into accounting? Is it a good career?"
    c["post"]["body"] = "wondering about salary and the bookkeeping workflow"
    dropped: dict[str, int] = {}
    out = _select_authority([c], set(), _weights(), dropped, conn=None)

    assert out == []
    assert calls == [], "vet must NOT fire on a deterministic-gate reject"
    assert dropped.get("authority_career_identity") == 1


def test_lazy_vet_reuses_existing_vet(monkeypatch):
    """A candidate that already carries a vet dict (e.g. a branded no_intent post
    vetted in the main loop, or a synthetic test vet) is reused, never re-vetted.
    """
    calls: list[str] = []

    def fake_vet(author, conn=None, weights=None):
        calls.append(author)
        return {"verdict": "pass", "reason": "ok"}

    monkeypatch.setattr(author_vet, "vet_author", fake_vet)

    c = _deferred_candidate("auth1")
    c["vet"] = {"verdict": "pass", "reason": "from_loop"}  # already vetted
    dropped: dict[str, int] = {}
    out = _select_authority([c], set(), _weights(), dropped, conn=None)

    assert [x["post"]["id"] for x in out] == ["auth1"]
    assert calls == [], "an already-vetted candidate must not be re-vetted"


# ─── Test 2: design-fix-1 regression through the REAL cmd_fetch_score ────────

def _sub() -> dict:
    return {"name": "Bookkeeping", "tier": 2, "bucket": "operator",
            "weight": 1.0, "saturation": "medium", "backing_blogs": []}


def _brandless_question_post() -> dict:
    """Brandless, on-topic, answerable question. reason -> tier2_no_saas_brand
    (passes keyword density + question intent, just names no brand). NOT
    backfill-eligible (no brand), so the 403 early drop would cull it unless
    design fix 1 spares authority-eligible posts."""
    return {
        "id": "fix1auth", "subreddit": "Bookkeeping",
        "title": "How do you handle invoicing and reconciliation for retainer clients?",
        "url": "https://reddit.com/r/Bookkeeping/comments/fix1auth/x/",
        "canonical_url": "https://reddit.com/comments/fix1auth/",
        "author": "clean_op", "created_utc": NOW - 3600,
        "score": 22, "num_comments": 9,
        "body": "planning a clean workflow for expense tracking, no tool picked yet",
        "removed": False, "locked": False, "over_18": False,
    }


def _run_fetch_score(monkeypatch, tmp_path, *, posts, vet_verdict, authority_enabled=True):
    monkeypatch.setenv("SUBSCOPE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "_load_configs", lambda mode="default": {
        "subs": [_sub()],
        "keywords": {"shared": KEYWORDS, "operator": []},
        "weights": _weights(authority_enabled=authority_enabled), "mode": mode,
    })
    monkeypatch.setattr(reddit, "fetch_delta", lambda name, cursor, max_limit=25: list(posts))
    monkeypatch.setattr(author_vet, "vet_author",
                        lambda author, conn=None, weights=None: dict(vet_verdict))
    monkeypatch.setattr(classify, "classify", lambda post: None)
    monkeypatch.setattr(enrich, "augment_scores", lambda cands, conn: None)
    monkeypatch.setattr(slack, "notify_if_configured", lambda payload: None)
    # Avoid any real network in the fetcher's rate-limit bookkeeping.
    monkeypatch.setattr(reddit, "is_rate_limited", lambda: False)

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.cmd_fetch_score(no_slack=True)
    return json.loads(buf.getvalue())


def test_design_fix1_brandless_question_reaches_authority_track(monkeypatch, tmp_path):
    """REGRESSION for design fix 1: a brandless on-topic question (clean author)
    actually REACHES and surfaces on the authority track through the real
    cmd_fetch_score. Guards the line ~312 early-drop interaction: without the
    authority_eligible spare clause, this post is dropped before authority_pool.
    """
    payload = _run_fetch_score(
        monkeypatch, tmp_path,
        posts=[_brandless_question_post()],
        vet_verdict={"verdict": "pass", "reason": "ok"},
        authority_enabled=True,
    )
    assert payload["buyer_count"] == 0, "brandless question is not a buyer signal"
    assert payload["authority_count"] == 1, "must surface on the authority track"
    tracks = {s["post_id"]: s["track"] for s in payload["surfaces"]}
    assert tracks.get("fix1auth") == "authority"


def test_design_fix1_post_dropped_when_authority_disabled(monkeypatch, tmp_path):
    """The same brandless question, with the authority track OFF, surfaces on no
    track at all (buyer-only revert). Confirms the spare clause is gated on the
    flag and the buyer track is unaffected."""
    payload = _run_fetch_score(
        monkeypatch, tmp_path,
        posts=[_brandless_question_post()],
        vet_verdict={"verdict": "pass", "reason": "ok"},
        authority_enabled=False,
    )
    assert payload["buyer_count"] == 0
    assert payload["authority_count"] == 0
    assert payload["surfaces"] == []


def test_design_fix1_authority_post_not_vetted_in_main_loop(monkeypatch, tmp_path):
    """Rate-limit safety end-to-end: an authority-ONLY post is vetted exactly
    once, and that vet is DEFERRED past the main loop (lazy). We assert two
    things that together pin the lazy contract:

    1. The candidate arrives at _select_authority still carrying vet=None, which
       can only happen if the main loop did NOT vet it. (A non-lazy loop would
       have attached a vet dict here, or dropped the post outright.)
    2. The author vet is called exactly once across the whole run.

    Under any implementation that vets authority-only posts in the main loop,
    assertion 1 fails (the candidate would arrive pre-vetted).
    """
    calls: list[str] = []
    pool_vet_states: list[Any] = []

    def counting_vet(author, conn=None, weights=None):
        calls.append(author)
        return {"verdict": "pass", "reason": "ok"}

    real_select_authority = cli._select_authority

    def spy_select_authority(authority_pool, buyer_ids, weights, dropped_counts, conn=None):
        # Snapshot the vet state of each candidate AS IT ENTERS selection,
        # before the lazy vet has a chance to fill it in.
        pool_vet_states.extend(c.get("vet") for c in authority_pool)
        return real_select_authority(
            authority_pool, buyer_ids, weights, dropped_counts, conn=conn)

    monkeypatch.setenv("SUBSCOPE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "_load_configs", lambda mode="default": {
        "subs": [_sub()],
        "keywords": {"shared": KEYWORDS, "operator": []},
        "weights": _weights(authority_enabled=True), "mode": mode,
    })
    monkeypatch.setattr(reddit, "fetch_delta",
                        lambda name, cursor, max_limit=25: [_brandless_question_post()])
    monkeypatch.setattr(author_vet, "vet_author", counting_vet)
    monkeypatch.setattr(cli, "_select_authority", spy_select_authority)
    monkeypatch.setattr(classify, "classify", lambda post: None)
    monkeypatch.setattr(enrich, "augment_scores", lambda cands, conn: None)
    monkeypatch.setattr(slack, "notify_if_configured", lambda payload: None)
    monkeypatch.setattr(reddit, "is_rate_limited", lambda: False)

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.cmd_fetch_score(no_slack=True)
    payload = json.loads(buf.getvalue())

    assert payload["authority_count"] == 1
    assert pool_vet_states == [None], (
        "authority-only candidate must reach _select_authority UNVETTED "
        f"(vet deferred by the main loop); saw vet states {pool_vet_states}")
    assert calls == ["clean_op"], (
        "an authority-only post must be vetted once, lazily; got "
        f"{len(calls)} vet call(s): {calls}")


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
