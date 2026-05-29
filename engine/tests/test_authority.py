"""Tests for the dual-track authority gate + scorer (DT-1 / DT-2).

Pure-function tests on synthetic post dicts (same style as test_score.py).
No Reddit network, no SQLite.

The authority track is a SECOND pass over the buyer-gate soft-reject pool.
It recovers on-topic, answerable questions that named no SaaS brand or showed
no explicit buying intent. The hard requirement is PRECISION: it must reject
career / identity / meta questions and must never resurrect the brandless
keyword-density leak.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import score  # noqa: E402


NOW = 1748100000  # fixed reference for deterministic age math

# Keyword bucket for a bookkeeping / ops ICP. The authority threshold is 2,
# so test posts must hit >= 2 of these to clear topical fit.
KEYWORDS = [
    "invoicing", "invoice", "bookkeeping", "accounting", "reconciliation",
    "expense", "client", "workflow", "spreadsheet", "automation",
]

WEIGHTS = {
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
    "authority_track": {
        "enabled": True,
        "cap": 4,
        "min_keyword_density": 2,
        "scoring": {
            "reach_weight": 1.5,
            "answerability_weight": 1.5,
            "blog_weight": 1.5,
            "pain_weight": 0.25,
            "freshness_max_points": 30,
        },
    },
}


def make_post(**overrides):
    base = {
        "id": "auth01",
        "subreddit": "Bookkeeping",
        # On-topic, answerable, brandless domain question. Two keyword hits
        # (invoicing + reconciliation) and a question mark.
        "title": "How do you handle invoicing and reconciliation for retainer clients?",
        "url": "https://www.reddit.com/r/Bookkeeping/comments/auth01/x/",
        "canonical_url": "https://reddit.com/comments/auth01/",
        "author": "user",
        "created_utc": NOW - 3600,
        "score": 12,
        "num_comments": 4,
        "body": "Trying to figure out a clean workflow. No tool in mind yet.",
        "removed": False,
        "locked": False,
    }
    base.update(overrides)
    return base


def make_sub(**overrides):
    base = {"name": "Bookkeeping", "tier": 2, "bucket": "operator",
            "weight": 1.0, "saturation": "medium"}
    base.update(overrides)
    return base


# ─── DT-1 gate: positive case ──────────────────────────────────────────

def test_authority_accepts_brandless_on_topic_question():
    """A brandless, on-topic, answerable domain question qualifies for authority
    when it failed the buyer gate for no_saas_brand."""
    post = make_post()
    sub = make_sub()
    passes, reason = score.evaluate_authority_gate(
        post, sub, "tier2_no_saas_brand", WEIGHTS, KEYWORDS, now=NOW)
    assert passes, f"expected authority pass, got {reason}"
    assert reason == "authority_pass"


def test_authority_accepts_no_intent_reject():
    """no_intent is also an authority-eligible buyer-gate failure."""
    post = make_post()
    sub = make_sub()
    passes, reason = score.evaluate_authority_gate(
        post, sub, "tier2_no_intent", WEIGHTS, KEYWORDS, now=NOW)
    assert passes, f"expected authority pass, got {reason}"


# ─── DT-1 gate: precision rejections ───────────────────────────────────

def test_authority_rejects_career_identity_post():
    """A career / identity question must be rejected even with question intent
    and keyword density. This is the precision crux of the keyless MVP."""
    post = make_post(
        title="Should I switch careers into accounting? Is it a good career?",
        body="I currently do bookkeeping but wondering about salary and the workflow.",
    )
    sub = make_sub()
    passes, reason = score.evaluate_authority_gate(
        post, sub, "tier2_no_saas_brand", WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "authority_career_identity"


def test_authority_rejects_when_buyer_reason_not_eligible():
    """A post that failed the buyer gate for keyword density (NOT no_saas_brand)
    is NOT authority-eligible. This is the leak guard: a brandless thin post
    carries *_keyword_density, so it can never reach the authority track."""
    post = make_post()
    sub = make_sub()
    passes, reason = score.evaluate_authority_gate(
        post, sub, "tier2_keyword_density", WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "authority_not_eligible_reason"


def test_authority_rejects_no_question_intent():
    """Authority = answering questions. A statement with no question intent fails."""
    post = make_post(
        title="My invoicing reconciliation workflow for clients",
        body="Here is what my expense process looks like.",
    )
    sub = make_sub()
    passes, reason = score.evaluate_authority_gate(
        post, sub, "tier2_no_saas_brand", WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "authority_no_question"


def test_authority_rejects_low_keyword_density():
    """Below min_keyword_density (2), the post is too thin to prove topical fit."""
    post = make_post(
        title="How do you all do this?",   # 0 keyword hits, but has a question
        body="Just wondering, no specifics.",
    )
    sub = make_sub()
    passes, reason = score.evaluate_authority_gate(
        post, sub, "tier2_no_saas_brand", WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "authority_keyword_density"


def test_authority_rejects_absolute_reject_vendor():
    """Absolute rejects are re-checked in the authority gate, not inferred."""
    post = make_post(
        title="I built an invoicing reconciliation tool, would you use it?",
    )
    sub = make_sub()
    passes, reason = score.evaluate_authority_gate(
        post, sub, "tier2_no_saas_brand", WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "authority_absolute_reject"


def test_authority_rejects_tier3():
    post = make_post()
    sub = make_sub(tier=3, weight=0.0)
    passes, reason = score.evaluate_authority_gate(
        post, sub, "tier2_no_saas_brand", WEIGHTS, KEYWORDS, now=NOW)
    assert not passes
    assert reason == "authority_absolute_reject"


def test_authority_rejects_failed_author_vet():
    post = make_post()
    sub = make_sub()
    passes, reason = score.evaluate_authority_gate(
        post, sub, "tier2_no_saas_brand", WEIGHTS, KEYWORDS,
        vet={"verdict": "fail", "reason": "low_karma"}, now=NOW)
    assert not passes
    assert reason == "authority_author_vet"


def test_authority_eligible_reasons_excludes_keyword_density():
    """Contract: the brandless keyword-density miss reason is NEVER eligible."""
    assert "tier1_keyword_density" not in score.AUTHORITY_ELIGIBLE_REASONS
    assert "tier2_keyword_density" not in score.AUTHORITY_ELIGIBLE_REASONS
    # And the absolute rejects are not eligible either.
    for r in score.ABSOLUTE_REJECT_REASONS:
        assert r not in score.AUTHORITY_ELIGIBLE_REASONS


# ─── DT-2 scorer: reweighted ordering ──────────────────────────────────

def test_authority_score_high_reach_outranks_low_reach():
    """Reweighted authority ordering favors reach: a high-velocity answerable
    question outranks a low-velocity one with equal keywords + age."""
    high = make_post(id="hi", score=80, num_comments=40, created_utc=NOW - 3600)
    low = make_post(id="lo", score=3, num_comments=1, created_utc=NOW - 3600)
    sub = make_sub()
    s_high = score.compute_authority_score(high, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    s_low = score.compute_authority_score(low, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    assert s_high > s_low


def test_authority_score_blog_coverage_lifts():
    """Blog coverage is an up-weighted answerability/citable-authority lever."""
    post = make_post()
    sub = make_sub()
    no_blog = score.compute_authority_score(post, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    with_blog = score.compute_authority_score(
        post, sub,
        [{"url": "x", "title": "Invoicing playbook", "match_score": 1.0, "matched_keywords": []}],
        WEIGHTS, KEYWORDS, now=NOW)
    assert with_blog > no_blog


def test_authority_score_pain_downweighted_vs_buyer():
    """Pain markers are down-weighted in authority scoring relative to the buyer
    scorer. The same pain-laden post contributes far less pain bonus on the
    authority track."""
    painful = make_post(
        title="invoicing reconciliation is too expensive and frustrating, anyone?",
        body="hate the pricing, tired of it",
    )
    calm = make_post(
        id="calm",
        title="How do you set up invoicing reconciliation for clients?",
        body="just planning the workflow",
    )
    sub = make_sub()
    # On the buyer scorer, the painful post gets a clear pain-bonus lift.
    buyer_painful = score.compute_score(painful, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    buyer_calm = score.compute_score(calm, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    buyer_gap = buyer_painful - buyer_calm
    # On the authority scorer, the pain advantage is dialed down (pain_weight 0.25).
    auth_painful = score.compute_authority_score(painful, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    auth_calm = score.compute_authority_score(calm, sub, [], WEIGHTS, KEYWORDS, now=NOW)
    auth_gap = auth_painful - auth_calm
    assert auth_gap < buyer_gap, (
        f"pain should be down-weighted on authority: buyer_gap={buyer_gap}, "
        f"auth_gap={auth_gap}")


def test_authority_score_quarantine_zero():
    post = make_post()
    sub = make_sub(tier=3, weight=0.0)
    assert score.compute_authority_score(post, sub, [], WEIGHTS, KEYWORDS, now=NOW) == 0.0


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
