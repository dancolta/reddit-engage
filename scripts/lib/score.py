"""Tier-aware gate + scoring.

Pipeline:
  1. evaluate_gate(post, sub, blog_matches) -> (passes: bool, reason: str)
  2. compute_score(post, sub, blog_matches) -> float

Gate failures short-circuit. Survivors are ranked by score.

Intent classification (added 2026-05-24 after first 10-surface scan
revealed too many vendor-content and retrospective posts):

  - QUESTION posts (title with "?" or asking-phrasing) get scored higher
    and bypass vendor-content rejection.
  - VENDOR-CONTENT posts (title with "I built", "we shipped", "X things
    I learned", "case study", "introducing") get gate-rejected on Tier 2,
    score-penalized on Tier 1.
  - PAIN-WORD posts (title or body with rant signals: "expensive",
    "frustrated", "tired of", "killing me", "renewal", "pricing") get
    scored higher.
"""
from __future__ import annotations

import re
import time
from typing import Any


def now_utc() -> int:
    return int(time.time())


# === Intent signals ===

QUESTION_PHRASES = (
    "anyone", "any one", "how do you", "how do i", "what do you",
    "what's the best", "whats the best", "looking for", "should i",
    "any recommendations", "what's a good", "whats a good",
    "alternative to", "alternatives to", "tips for", "advice on",
    "help with", "how to deal with", "anybody", "anyone else",
    "can i", "is there a", "is it possible", "where do i", "wondering if",
)

VENDOR_CONTENT_PHRASES = (
    # Self-promotional retrospectives / launches / case studies
    "i built", "we built", "i shipped", "we shipped", "i launched",
    "we launched", "introducing", "here's how i", "here's how we",
    "heres how i", "heres how we", "here is how",
    "i created", "we created", "i made", "we made", "i developed",
    "we developed", "case study", "case-study",
    # Listicle/lessons-learned (retrospective format, not pain)
    "things i learned", "things we learned", "things about",
    "lessons learned", "5 lessons", "five lessons", "5 things",
    "five things", "6 things", "six things", "7 things", "seven things",
    "10 things", "ten things",
    "complete guide", "a guide to", "a guide with", "guide with",
    "the ultimate guide", "ultimate guide",
    "from scratch", "in production", "production system",
    # Promotional verbs in title
    "is dead, long live", "is dead", "long live",
    "why we chose", "why i chose", "how i scaled", "how we scaled",
    # Round-2 expansions: caught real vendor posts that slipped through
    "the exact playbook", "exact playbook", "playbook i used",
    "playbook we used", "the playbook",
    "made $", "mrr in", "arr in", "in 10 days", "in 30 days",
    "[idea validation]", "idea validation", "validating my",
    "would you use", "would you pay", "would you buy",
    "is finally", "finally enforceable", "finally possible",
    "what do you think of my", "what do you think about my",
    "the invisible founder", "invisible founder",
    "tell me what you think", "feedback on my",
    # Round-3 expansions: "gatekeeping" / hype-method posts
    "gatekeeping this", "done gatekeeping", "insane method",
    "insane cold-email", "insane way", "insane trick",
    "shouldn't be free", "should not be free",
    "free for now", "secret method", "the trick is",
    "this changed my life", "game changing",
)

# Posts that contain these phrases (in title or body) are explicitly NOT ICP
# pain even if they hit keyword density (e.g. fraud PSAs, scam warnings,
# generic life advice).
NEGATIVE_PHRASES = (
    "fraud", "scam", "phishing", "fake invoice", "fake consulting",
    "ai to summarize", "ai-summarize", "summarize with ai",
    "what's the meaning of", "meaning of life",
    "any meme", "meme template", "shitpost",
)

PAIN_PHRASES = (
    "too expensive", "expensive", "renewal", "price hike", "pricing",
    "frustrated", "frustrating", "tired of", "fed up", "stuck",
    "killing me", "killing us", "hate", "annoying", "wish there",
    "ripping off", "ripped off", "nickel and dime", "nickel-and-dime",
    "switching from", "moved off", "moving off", "ditch",
    "cancel", "cancelled", "canceling", "alternative",
    "cheap", "cheaper", "affordable", "free alternative",
)

# Specific SaaS / tool brand names. A surface MUST name one of these to
# confirm the post is about a real tool pain.
#
# Brand list rules:
# - Only names unambiguous enough to not collide with common English.
# - Excluded for false-positive risk: "clay", "later", "loom", "monday",
#   "asana", "notion", "outreach" (verb), "make" (verb), "lever" (noun),
#   "ramp" (noun), "stripe" (noun), "sentry" (noun), "ashby" (place).
# - Multi-word brands and ".com"-suffixed versions stay because they
#   resolve unambiguously.
SAAS_BRANDS = (
    "apollo.io", "bill.com", "hubspot", "salesforce", "calendly",
    "zapier", "make.com", "n8n", "intercom", "zendesk", "gainsight",
    "outreach.io", "lemlist", "instantly.ai", "zoominfo",
    "mailchimp", "klaviyo", "active campaign", "activecampaign",
    "greenhouse", "lever.co", "workable", "gem.com",
    "pipedrive", "monday.com", "airtable",
    "typeform", "tally.so", "docusign", "pandadoc",
    "ramp.com", "brex", "stripe.com", "quickbooks", "xero", "freshbooks",
    "retool", "tooljet", "appsmith", "bubble.io", "webflow",
    "datadog", "newrelic", "new relic", "sentry.io", "loggly",
    "mixpanel", "amplitude", "posthog", "plausible analytics", "fathom analytics",
    "dext", "hubdoc", "expensify",
    "phantombuster", "apify", "clay.com", "smartlead",
    "prospeo", "hunter.io", "anymail finder", "proxycurl",
    "buffer.com", "hootsuite", "later.com", "sprout social",
    "loom.com", "vidyard", "wistia",
    "chatwoot", "freshdesk", "helpscout", "crisp.chat",
)


def names_specific_saas(title: str, body: str) -> bool:
    """Word-boundary match against the brand list. Avoids "monday" matching
    "monday meeting" and similar collisions with common English."""
    full = (title + " " + body).lower()
    for brand in SAAS_BRANDS:
        # Brands with dots / spaces use literal substring (they're already specific)
        if "." in brand or " " in brand:
            if brand in full:
                return True
        else:
            # Word-boundary for single-word brands
            if re.search(rf"\b{re.escape(brand)}\b", full):
                return True
    return False


def has_question_intent(title: str, body: str) -> bool:
    full = (title + " " + body).lower()
    if "?" in title:
        return True
    return any(p in full for p in QUESTION_PHRASES)


def has_vendor_content_markers(title: str, body: str) -> bool:
    full = (title + " " + body[:400]).lower()
    return any(p in full for p in VENDOR_CONTENT_PHRASES)


def has_pain_markers(title: str, body: str) -> bool:
    full = (title + " " + body).lower()
    return any(p in full for p in PAIN_PHRASES)


def has_negative_markers(title: str, body: str) -> bool:
    full = (title + " " + body[:400]).lower()
    return any(p in full for p in NEGATIVE_PHRASES)


def age_hours(post: dict[str, Any], now: int | None = None) -> float:
    t = now if now is not None else now_utc()
    return max(0.0, (t - int(post["created_utc"])) / 3600.0)


def velocity_per_hour(post: dict[str, Any], now: int | None = None) -> float:
    ah = age_hours(post, now)
    if ah <= 0.0:
        return float(post.get("score", 0))
    return float(post["score"]) / ah


def comment_velocity(post: dict[str, Any], now: int | None = None) -> float:
    ah = age_hours(post, now)
    if ah <= 0.0:
        return float(post.get("num_comments", 0))
    return float(post["num_comments"]) / ah


def count_keyword_hits(post: dict[str, Any], keywords: list[str]) -> tuple[int, list[str]]:
    """Case-insensitive substring count over title + first 1000 chars of body.

    Returns (count, matched_keywords). Multiple matches of the same keyword count once.
    """
    haystack = (post.get("title", "") + " " + (post.get("body") or "")[:1000]).lower()
    matched = [kw for kw in keywords if kw.lower() in haystack]
    return len(matched), matched


def find_blog_matches(post: dict[str, Any], blog_posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return blog posts whose signature keywords overlap the Reddit post."""
    matches: list[dict[str, Any]] = []
    for blog in blog_posts:
        kws_str = blog.get("keywords", "")
        kws = [k for k in kws_str.split("|") if k] if isinstance(kws_str, str) else list(kws_str or [])
        count, matched = count_keyword_hits(post, kws)
        if count >= 1:
            score = min(1.0, count / max(1, len(kws)) * 3.0)
            matches.append({
                "url": blog["url"],
                "title": blog["title"],
                "match_score": score,
                "matched_keywords": matched,
            })
    matches.sort(key=lambda m: m["match_score"], reverse=True)
    return matches


def _apply_overrides(defaults: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(defaults)
    if overrides:
        out.update({k: v for k, v in overrides.items() if v is not None})
    return out


ABSOLUTE_REJECT_REASONS = {"removed_or_locked", "negative_topic", "vendor_content"}


def evaluate_gate(
    post: dict[str, Any],
    sub: dict[str, Any],
    blog_matches: list[dict[str, Any]],
    weights: dict[str, Any],
    bucket_keywords: list[str],
    now: int | None = None,
) -> tuple[bool, str]:
    """Evaluate the gate for a single post. Returns (passes, reason).

    Absolute rejects (removed/locked, negative topic, vendor content) are
    checked first and bypass the backfill path so they NEVER surface.
    """
    title = post.get("title", "")
    body = post.get("body", "") or ""

    if post.get("removed") or post.get("locked"):
        return False, "removed_or_locked"
    if has_negative_markers(title, body):
        return False, "negative_topic"
    if has_vendor_content_markers(title, body):
        return False, "vendor_content"

    ah = age_hours(post, now)
    if sub["tier"] == 1:
        return _tier1_gate(post, sub, weights, bucket_keywords, ah, now)
    return _tier2_gate(post, sub, weights, bucket_keywords, ah, now)


def _tier1_gate(post: dict[str, Any], sub: dict[str, Any], weights: dict[str, Any],
                bucket_keywords: list[str], ah: float, now: int | None) -> tuple[bool, str]:
    """Tier 1 soft signals (absolute rejects already passed).

    Tier 1 is more lenient than Tier 2 but still requires either a specific
    SaaS brand OR a clear pain phrase. Pure-keyword matches without ICP
    signal (e.g. "alternative" used in marketing-copy context) don't pass.
    """
    g = _apply_overrides(weights.get("tier1_gates", {}), sub.get("gate_overrides"))
    title = post.get("title", "")
    body = post.get("body", "") or ""

    if ah > float(g.get("post_age_hours", 48)):
        return False, "tier1_post_age"

    ceiling = int(g.get("comment_ceiling", 100))
    if ceiling > 0 and post["num_comments"] > ceiling:
        return False, "tier1_comment_ceiling"

    n_hits, _ = count_keyword_hits(post, bucket_keywords)
    if n_hits < int(g.get("pain_keywords_min", 1)):
        return False, "tier1_keyword_density"

    # Tier 1 ICP gate: must name a specific SaaS tool. NodeSparks' whole
    # value proposition is "replace your SaaS" — without a named tool in
    # the post, there's nothing to reply about substantively.
    if not names_specific_saas(title, body):
        return False, "tier1_no_saas_brand"

    return True, "tier1_pass"


def _tier2_gate(post: dict[str, Any], sub: dict[str, Any], weights: dict[str, Any],
                bucket_keywords: list[str], ah: float, now: int | None) -> tuple[bool, str]:
    """Tier 2 soft signals (absolute rejects already passed). Adds intent check."""
    g = _apply_overrides(weights.get("tier2_gates", {}), sub.get("gate_overrides"))
    title = post.get("title", "")
    body = post.get("body", "") or ""

    if ah > float(g.get("post_age_hours", 72)):
        return False, "tier2_post_age"

    n_hits, _ = count_keyword_hits(post, bucket_keywords)
    saturation = sub.get("saturation") or "medium"
    min_kw = int(
        g.get("pain_keywords_min_wide_open", 1) if saturation == "wide_open"
        else g.get("pain_keywords_min", 1)
    )
    if n_hits < min_kw:
        return False, "tier2_keyword_density"

    if not (has_question_intent(title, body) or has_pain_markers(title, body)):
        return False, "tier2_no_intent"

    # Hard requirement: name a specific SaaS/tool brand. No exceptions.
    # Without this, culture/career posts in r/Accounting, r/sales, etc.
    # flood the surface even when they hit keyword density on phrases
    # like "alternative" or "build vs buy".
    if not names_specific_saas(title, body):
        return False, "tier2_no_saas_brand"

    return True, "tier2_pass"


def compute_score(
    post: dict[str, Any],
    sub: dict[str, Any],
    blog_matches: list[dict[str, Any]],
    weights: dict[str, Any],
    bucket_keywords: list[str],
    now: int | None = None,
) -> float:
    """Compute internal score for a gate-passing post."""
    scoring = weights.get("scoring", {})
    ah = age_hours(post, now)
    v = velocity_per_hour(post, now)
    cv = comment_velocity(post, now)

    f_cfg = scoring.get("freshness_decay", {})
    zero_h = float(f_cfg.get("zero_hours", 30)) or 30.0
    freshness = max(0.0, (zero_h - ah) / zero_h) * float(f_cfg.get("max_points", 30))

    uv_cfg = scoring.get("upvote_velocity", {})
    uv_score = min(float(uv_cfg.get("max_points", 20)),
                   v * float(uv_cfg.get("multiplier", 4)))

    cv_cfg = scoring.get("comment_velocity", {})
    cv_score = min(float(cv_cfg.get("max_points", 15)),
                   cv * float(cv_cfg.get("multiplier", 6)))

    kw_cfg = scoring.get("pain_keyword_match", {})
    n_hits, _ = count_keyword_hits(post, bucket_keywords)
    kw_score = min(float(kw_cfg.get("max_points", 30)),
                   n_hits * float(kw_cfg.get("points_per_keyword", 6)))

    bc_cfg = scoring.get("blog_coverage_bonus", {})
    bc_score = min(float(bc_cfg.get("max_points", 50)),
                   len(blog_matches) * float(bc_cfg.get("points_per_match", 25)))

    title = post.get("title", "")
    body = post.get("body", "") or ""
    intent_cfg = scoring.get("intent_bonus", {})
    intent_score = 0.0
    if has_question_intent(title, body):
        intent_score += float(intent_cfg.get("question_bonus", 20))
    if has_pain_markers(title, body):
        intent_score += float(intent_cfg.get("pain_bonus", 15))

    raw = freshness + uv_score + cv_score + kw_score + bc_score + intent_score

    tw_cfg = scoring.get("tier_weight", {})
    tier_mul = float(tw_cfg.get(f"tier_{sub['tier']}", 1.0))
    sub_mul = float(sub.get("weight", 1.0))

    return round(raw * sub_mul * tier_mul, 2)
