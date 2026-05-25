"""Tests for gate + scoring logic."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subseek.lib import score  # noqa: E402


NOW = 1748100000  # fixed reference for deterministic age math


def make_post(**overrides):
    base = {
        "id": "fake01",
        "subreddit": "smallbusiness",
        "title": "HubSpot is too expensive, what alternative to it should I try?",
        "url": "https://www.reddit.com/r/smallbusiness/comments/fake01/x/",
        "canonical_url": "https://reddit.com/comments/fake01/",
        "author": "user",
        "created_utc": NOW - 3600,  # 1 hour old
        "score": 12,
        "num_comments": 4,
        "body": "We are paying $290/mo and looking for cheaper alternative to HubSpot. Stack costs killing us.",
        "removed": False,
        "locked": False,
    }
    base.update(overrides)
    return base


def make_sub(**overrides):
    base = {
        "name": "smallbusiness",
        "tier": 1,
        "bucket": "operator",
        "weight": 1.2,
        "gate_overrides": {
            "post_age_hours": 4,
            "comment_ceiling": 25,
            "velocity_floor": 5,
            "pain_keywords_min": 1,
        },
    }
    base.update(overrides)
    return base


WEIGHTS = {
    "tier1_gates": {
        "post_age_hours": 48, "comment_ceiling": 100, "pain_keywords_min": 1,
    },
    "tier2_gates": {
        "post_age_hours": 72,
        "pain_keywords_min": 1, "pain_keywords_min_wide_open": 1,
    },
    "scoring": {
        "freshness_decay": {"zero_hours": 30, "max_points": 30},
        "upvote_velocity": {"multiplier": 4, "max_points": 20},
        "comment_velocity": {"multiplier": 6, "max_points": 15},
        "pain_keyword_match": {"points_per_keyword": 6, "max_points": 30},
        "blog_coverage_bonus": {"points_per_match": 25, "max_points": 50},
        "tier_weight": {"tier_1": 1.0, "tier_2": 1.25},
    },
}

KEYWORDS = ["alternative to", "too expensive", "HubSpot", "stack costs"]


def test_count_keyword_hits():
    post = make_post()
    n, matched = score.count_keyword_hits(post, KEYWORDS)
    assert n >= 3
    assert "HubSpot" in matched


def test_tier1_pass():
    post = make_post()
    sub = make_sub()
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert passes, f"expected pass, got {reason}"


def test_low_velocity_now_passes_gate_scores_lower():
    """Velocity moved from hard gate to score signal. Slow posts still pass,
    they just rank lower."""
    fast = make_post(score=20, created_utc=NOW - 3600)   # 20 upv/hr
    slow = make_post(score=2, created_utc=NOW - 7200, id="slow01")   # 1 upv/hr
    sub = make_sub()
    fast_pass, _ = score.evaluate_gate(fast, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    slow_pass, _ = score.evaluate_gate(slow, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert fast_pass and slow_pass
    fast_score = score.compute_score(fast, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    slow_score = score.compute_score(slow, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert fast_score > slow_score


def test_tier1_drop_too_old():
    post = make_post(created_utc=NOW - 60 * 3600)  # 60h old; tier1 ceiling is 48h
    sub = make_sub()
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert "post_age" in reason


def test_tier1_drop_no_keywords():
    post = make_post(title="hello world", body="just a basic post with nothing relevant")
    sub = make_sub()
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert "keyword" in reason


def test_tier1_drop_removed():
    post = make_post(removed=True)
    sub = make_sub()
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "removed_or_locked"


def test_drop_nsfw_post():
    post = make_post(over_18=True)
    sub = make_sub()
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "nsfw_post"


def test_drop_nsfw_sub_blocklist():
    post = make_post(subreddit="ButtsAndBareFeet")
    sub = make_sub(name="ButtsAndBareFeet")
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "nsfw_sub"


def test_drop_crosspost_subreddit_mismatch():
    """A post fetched from r/sales but whose JSON says subreddit=programming
    (a crosspost surfaced in /new) gets rejected. NSFW-sub blocklist fires
    first if applicable; this test covers the non-NSFW case."""
    post = make_post(subreddit="programming")
    sub = make_sub(name="sales")
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "crosspost_subreddit_mismatch"


def test_tier2_keyword_min_blocks_zero_match():
    """Tier 2 requires at least 1 keyword. Zero matches drops the post."""
    post = make_post(title="random unrelated post", body="nothing relevant",
                     score=20, created_utc=NOW - 3600)
    sub = make_sub(tier=2, saturation="medium")
    sub.pop("gate_overrides", None)
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert "keyword_density" in reason


def test_tier2_wide_open_passes_with_single_keyword():
    post = make_post(title="HubSpot too expensive",  # 2 keywords, well above 1
                     body="just venting", score=20, created_utc=NOW - 3600)
    sub = make_sub(tier=2, saturation="wide_open")
    sub.pop("gate_overrides", None)
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert passes, f"expected pass, got {reason}"


def test_score_formula_monotonic():
    """A post with a blog match should outscore an identical post without."""
    post = make_post()
    sub = make_sub()
    no_match = score.compute_score(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    with_match = score.compute_score(
        post, sub,
        [{"url": "x", "title": "y", "match_score": 1.0, "matched_keywords": []}],
        WEIGHTS, KEYWORDS, now=NOW,
    )
    assert with_match > no_match


def test_score_tier2_weight_boost():
    """Identical post in Tier 2 should score 25% higher than Tier 1 (after tier_weight)."""
    post = make_post()
    s1 = make_sub(tier=1, gate_overrides=None)
    s1.pop("gate_overrides", None)
    s2 = make_sub(tier=2, saturation="medium")
    s2.pop("gate_overrides", None)
    score_1 = score.compute_score(post, s1, [], WEIGHTS, KEYWORDS, now=NOW)
    score_2 = score.compute_score(post, s2, [], WEIGHTS, KEYWORDS, now=NOW)
    assert abs(score_2 - score_1 * 1.25) < 0.5


def test_blog_match_finder():
    post = make_post()
    blogs = [
        {"url": "blog1", "title": "Playbook",
         "keywords": "HubSpot|stack costs|build vs buy"},
        {"url": "blog2", "title": "Apollo",
         "keywords": "Apollo|deliverability"},
    ]
    matches = score.find_blog_matches(post, blogs)
    assert len(matches) == 1
    assert matches[0]["url"] == "blog1"


def test_quarantine_tier3_gate_rejects():
    """Tier 3 sub: gate must reject with 'tier3_quarantined', regardless of post quality."""
    post = make_post()
    sub = make_sub(tier=3, weight=0.0)
    sub.pop("gate_overrides", None)
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "tier3_quarantined"
    assert reason in score.ABSOLUTE_REJECT_REASONS, (
        "tier3 reject must be ABSOLUTE so it bypasses the near-miss backfill path"
    )


def test_quarantine_weight_zero_rejects_even_at_tier2():
    """weight=0 at any tier acts as a kill switch — defends against accidental zeros."""
    post = make_post()
    sub = make_sub(tier=2, weight=0.0, saturation="medium")
    sub.pop("gate_overrides", None)
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "tier3_quarantined"


def test_compute_score_quarantine_short_circuits_to_zero():
    """Score must return 0.0 for tier 3 / weight 0, never div-by-zero or NaN."""
    post = make_post()
    s_t3 = make_sub(tier=3, weight=0.0)
    s_t3.pop("gate_overrides", None)
    assert score.compute_score(post, s_t3, [], WEIGHTS, KEYWORDS, now=NOW) == 0.0

    s_w0 = make_sub(tier=2, weight=0.0, saturation="medium")
    s_w0.pop("gate_overrides", None)
    assert score.compute_score(post, s_w0, [], WEIGHTS, KEYWORDS, now=NOW) == 0.0


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
