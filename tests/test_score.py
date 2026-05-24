"""Tests for gate + scoring logic."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import score  # noqa: E402


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
    "hard_gates": {"age_max_hours": 24, "dollar_regex_or_role": False},
    "tier1_gates": {
        "post_age_hours": 6, "comment_ceiling": 30,
        "velocity_floor": 3, "pain_keywords_min": 1,
    },
    "tier2_gates": {
        "post_age_hours": 24, "comment_ceiling": 0,
        "velocity_floor": 8, "pain_keywords_min": 3,
        "pain_keywords_min_wide_open": 2, "sub_size_floor": 25000,
        "blog_coverage_required": False,
        "viral_override": {"pain_keywords": 3, "velocity_per_hour": 20},
    },
    "scoring": {
        "freshness_decay": {"zero_hours": 30, "max_points": 30},
        "upvote_velocity": {"multiplier": 4, "max_points": 20},
        "comment_velocity": {"multiplier": 6, "max_points": 15},
        "pain_keyword_match": {"points_per_keyword": 6, "max_points": 30},
        "blog_coverage_bonus": {"points_per_match": 25, "max_points": 50},
        "tier_weight": {"tier_1": 1.0, "tier_2": 1.25},
    },
    "saturation_high": {"fetch_comments": True, "skip_if_existing_technical_reply_upvotes": 3},
}

KEYWORDS = ["alternative to", "too expensive", "HubSpot", "stack costs"]


def test_dollar_figure_detection():
    assert score.has_dollar_figure("paying $290/mo")
    assert score.has_dollar_figure("the bill hit $50")
    assert not score.has_dollar_figure("just need help")
    assert not score.has_dollar_figure("paying $5 total")  # only 1 digit


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


def test_tier1_drop_low_velocity():
    post = make_post(score=2, created_utc=NOW - 7200)  # 1 upv/hr
    sub = make_sub()
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert "velocity" in reason


def test_tier1_drop_too_old():
    post = make_post(created_utc=NOW - 8 * 3600)  # 8 hours old, ceiling is 4
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


def test_tier2_strict_keyword_density():
    """Tier 2 default requires 3 keywords. 2 is rejected unless wide_open."""
    post = make_post(
        title="HubSpot too expensive",  # 2 keywords
        body="just venting",
        score=20, created_utc=NOW - 3600,  # 20/hr velocity (passes 8/hr)
    )
    sub = make_sub(tier=2, saturation="medium")
    sub.pop("gate_overrides", None)
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert "keyword_density" in reason


def test_tier2_wide_open_relaxes_to_2_keywords():
    post = make_post(
        title="HubSpot too expensive",  # 2 keywords
        body="just venting",
        score=20, created_utc=NOW - 3600,
    )
    sub = make_sub(tier=2, saturation="wide_open")
    sub.pop("gate_overrides", None)
    passes, reason = score.evaluate_gate(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert passes, f"expected pass, got {reason}"


def test_tier2_high_sat_blocked_by_existing_reply():
    post = make_post(
        title="alternative to HubSpot too expensive stack costs killing",  # 4 keywords
        score=20, created_utc=NOW - 3600,
    )
    sub = make_sub(tier=2, saturation="high")
    sub.pop("gate_overrides", None)
    top_comments = [{"score": 5, "body": "just self-host", "author": "x"}]
    passes, reason = score.evaluate_gate(
        post, sub, [], WEIGHTS, KEYWORDS, top_comments=top_comments, now=NOW
    )
    assert not passes
    assert "existing_technical_reply" in reason


def test_tier2_high_sat_passes_with_only_weak_replies():
    post = make_post(
        title="alternative to HubSpot too expensive stack costs killing",
        score=20, created_utc=NOW - 3600,
    )
    sub = make_sub(tier=2, saturation="high")
    sub.pop("gate_overrides", None)
    top_comments = [{"score": 1, "body": "weak reply", "author": "x"}]
    passes, reason = score.evaluate_gate(
        post, sub, [], WEIGHTS, KEYWORDS, top_comments=top_comments, now=NOW
    )
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


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
