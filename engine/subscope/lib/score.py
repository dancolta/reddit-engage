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

# Authority-track precision filter. The authority gate recovers brandless,
# on-topic, answerable questions, so it loses the named-brand anchor that keeps
# the buyer gate precise. Without a deterministic negative filter, career /
# identity / meta questions ("should i switch careers into accounting", "is X a
# good career", "what salary should i ask for") flood the authority track: they
# hit keyword density and carry question intent, but there is no domain problem a
# domain expert could credibly answer to build authority. This list IS the
# deterministic precision mechanism for the keyless MVP (the brandless lexical
# ceiling is ~50% precision per CLAUDE.md discovery notes; this filter is what
# keeps the track from being a buyer-reject dump).
AUTHORITY_NEGATIVE_PHRASES = (
    "switch careers", "switching careers", "change careers", "career change",
    "career advice", "good career", "bad career", "career path",
    "into accounting", "into a career", "career in",
    "should i major", "should i study", "which degree", "what degree",
    "what major", "which major", "college degree", "go to college",
    "get a job", "find a job", "land a job", "job hunting", "job search",
    "salary", "how much should i charge", "how much do you make",
    "how much do you earn", "pay range", "compensation",
    "is it worth it as a career", "worth it as a career",
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


def names_relevant_brand(title: str, body: str, brands: list[str] | None = None) -> bool:
    """Word-boundary match against a brand list. Avoids "monday" matching
    "monday meeting" and similar collisions with common English.

    `brands` is the caller-supplied brand list, normally the user's profile
    brand_anchor (their competitors + the tools their ICP touches). When it is
    None or empty, falls back to the built-in SAAS_BRANDS so the default
    NodeSparks profile and existing callers behave exactly as before. This is
    what lets the gate reflect the USER's business (e.g. Dentrix, Eaglesoft for
    a dental SaaS) instead of a hardcoded SaaS-sales tool list.
    """
    brand_list = brands if brands else SAAS_BRANDS
    full = (title + " " + body).lower()
    for brand in brand_list:
        b = brand.lower().strip()
        if not b:
            continue
        # Brands with dots / spaces use literal substring (they're already specific)
        if "." in b or " " in b:
            if b in full:
                return True
        else:
            # Word-boundary for single-word brands
            if re.search(rf"\b{re.escape(b)}\b", full):
                return True
    return False


def names_specific_saas(title: str, body: str) -> bool:
    """Back-compat wrapper: brand match against the built-in SAAS_BRANDS list.

    Retained so existing callers and the OAuth-removed/brand tests keep their
    contract. New code should call names_relevant_brand(title, body, brands)
    with the user's brand_anchor.
    """
    return names_relevant_brand(title, body, None)


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


def has_authority_negative_markers(title: str, body: str) -> bool:
    """Authority-track precision filter: career / identity / meta questions.

    Scans title + first 400 chars of body for AUTHORITY_NEGATIVE_PHRASES. A hit
    disqualifies a post from the authority track even when it has question intent
    and keyword density. See AUTHORITY_NEGATIVE_PHRASES for the rationale.
    """
    full = (title + " " + body[:400]).lower()
    return any(p in full for p in AUTHORITY_NEGATIVE_PHRASES)


def age_hours(post: dict[str, Any], now: int | None = None) -> float:
    t = now if now is not None else now_utc()
    return max(0.0, (t - int(post["created_utc"])) / 3600.0)


def velocity_per_hour(post: dict[str, Any], now: int | None = None) -> float:
    # `score` is absent on RSS-sourced posts (the .rss feed carries no upvotes);
    # default to 0 so velocity degrades to 0 instead of raising KeyError.
    ah = age_hours(post, now)
    if ah <= 0.0:
        return float(post.get("score", 0))
    return float(post.get("score", 0)) / ah


def comment_velocity(post: dict[str, Any], now: int | None = None) -> float:
    # `num_comments` is absent on RSS-sourced posts; default to 0.
    ah = age_hours(post, now)
    if ah <= 0.0:
        return float(post.get("num_comments", 0))
    return float(post.get("num_comments", 0)) / ah


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


ABSOLUTE_REJECT_REASONS = {
    "removed_or_locked", "negative_topic", "vendor_content",
    "nsfw_post", "nsfw_sub", "crosspost_subreddit_mismatch",
    "tier3_quarantined",
}

# NSFW sub blocklist. Belt-and-braces: even if Reddit forgets to flag a post
# as over_18, posts originating from these subs are dropped. List can grow.
NSFW_SUB_BLOCKLIST = {
    "buttsandbarefeet", "gonewild", "nsfw", "porn", "porninfifteenseconds",
    "pornid", "pornandbros", "amateur", "amateurfans", "onlyfans",
    "footfetish", "feet", "feetpics", "ass", "boobs", "tits", "milf",
    "wetladies", "girlsfinishingthejob", "altgonewild", "realgirls",
    "sexygirls", "asiansgonewild", "nsfw_gif", "nsfwfunny", "nsfw411",
    "nsfwoutfits", "nsfwhardcore", "rule34", "hentai",
}


def evaluate_gate(
    post: dict[str, Any],
    sub: dict[str, Any],
    blog_matches: list[dict[str, Any]],
    weights: dict[str, Any],
    bucket_keywords: list[str],
    now: int | None = None,
) -> tuple[bool, str]:
    """Evaluate the gate for a single post. Returns (passes, reason).

    Absolute rejects (NSFW, removed/locked, negative topic, vendor content,
    crosspost-from-wrong-sub) are checked first and bypass the backfill
    path so they NEVER surface.
    """
    title = post.get("title", "")
    body = post.get("body", "") or ""

    # NSFW gate: post-level flag, sub-level blocklist, OR crosspost from NSFW.
    if post.get("over_18"):
        return False, "nsfw_post"
    post_sub_lower = post.get("subreddit", "").lower()
    if post_sub_lower in NSFW_SUB_BLOCKLIST:
        return False, "nsfw_sub"

    # Crosspost integrity check: the post's reported subreddit must match
    # the sub we fetched from. If it doesn't (rare but possible via Reddit
    # listing edge cases), drop the post. This catches NSFW content cross-
    # posted into a SFW sub where the JSON serves the original post data.
    fetched_sub = sub.get("name", "").lower()
    if post_sub_lower and fetched_sub and post_sub_lower != fetched_sub:
        return False, "crosspost_subreddit_mismatch"

    if post.get("removed") or post.get("locked"):
        return False, "removed_or_locked"
    if has_negative_markers(title, body):
        return False, "negative_topic"
    if has_vendor_content_markers(title, body):
        return False, "vendor_content"

    # Tier 3 quarantine: fetched for telemetry only, never surfaces.
    # Also catches accidentally-zero weights so they never poison the surface list.
    if int(sub.get("tier", 0)) >= 3 or float(sub.get("weight", 1.0)) == 0.0:
        return False, "tier3_quarantined"

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

    # `num_comments` is absent on RSS posts; default 0 so this gate fails open
    # (0 <= ceiling, never wrongly rejects a thread for missing engagement data).
    ceiling = int(g.get("comment_ceiling", 100))
    if ceiling > 0 and post.get("num_comments", 0) > ceiling:
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

    # Tier 3 / weight=0 short-circuit: quarantined subs never compete in scoring.
    # The gate already filters these out; this guards against direct callers
    # bypassing the gate and protects against future float-rounding edge cases.
    if int(sub.get("tier", 0)) >= 3 or float(sub.get("weight", 1.0)) == 0.0:
        return 0.0

    tw_cfg = scoring.get("tier_weight", {})
    tier_mul = float(tw_cfg.get(f"tier_{sub['tier']}", 1.0))
    sub_mul = float(sub.get("weight", 1.0))

    return round(raw * sub_mul * tier_mul, 2)


# === Authority track (DT-1 / DT-2) ===
#
# The authority track is a parallel SECOND pass over the soft-reject pool: posts
# that failed the buyer gate ONLY because they named no SaaS brand or showed no
# explicit buying intent, yet are topically on-target and answerable. These are
# worth a reply to build authority / credibility, not to close a sale.
#
# Design contract (do NOT relax):
# - This is a POSITIVE gate, not a buyer-reject dump. A post must independently
#   EARN the authority track (question intent + keyword density + clean of
#   career/identity noise + vetted author), on top of clearing every absolute
#   reject the buyer gate enforces.
# - The ONLY buyer-gate failures that feed this pass are no_saas_brand and
#   no_intent. Any other reason (keyword density, post age, absolute rejects)
#   is NOT authority-eligible. In particular a brandless keyword-density miss is
#   NOT eligible, which preserves the _is_backfill_eligible leak fix: a post too
#   thin to clear keyword density on the buyer gate carries the *_keyword_density
#   reason, never *_no_saas_brand, so it can never reach this gate.

# Buyer-gate failure reasons that make a post eligible for the authority pass.
# Strictly the "on-topic but not a confirmed buyer" reasons.
AUTHORITY_ELIGIBLE_REASONS = {
    "tier1_no_saas_brand", "tier2_no_saas_brand", "tier2_no_intent",
}


def evaluate_authority_gate(
    post: dict[str, Any],
    sub: dict[str, Any],
    buyer_reason: str,
    weights: dict[str, Any],
    bucket_keywords: list[str],
    vet: dict[str, Any] | None = None,
    now: int | None = None,
) -> tuple[bool, str]:
    """Second-pass authority gate. Returns (passes, reason).

    `buyer_reason` is the reason the post failed the buyer gate (from
    evaluate_gate). A post qualifies for the authority track when ALL hold:

      1. It passed every ABSOLUTE reject (NSFW / vendor / negative / removed or
         locked / tier3). Re-checked here, not inferred, so a direct caller
         cannot bypass the non-negotiables.
      2. It failed the buyer gate ONLY for no_saas_brand or no_intent (topically
         on-target, just not a confirmed buyer).
      3. has_question_intent is true (authority = answering questions).
      4. Domain keyword density >= authority_track.min_keyword_density (proves
         topical fit, the precision lever in place of the brand anchor).
      5. It passes AUTHORITY_NEGATIVE_PHRASES (no career / identity / meta noise).
      6. The author passes vetting (reuse author_vet verdict; pass when absent).

    The reason string on failure names the first failing check so dropped_counts
    can show authority disposition.
    """
    title = post.get("title", "")
    body = post.get("body", "") or ""

    # (1) Absolute rejects, re-checked. Mirror evaluate_gate's non-negotiables.
    if post.get("over_18"):
        return False, "authority_absolute_reject"
    if post.get("subreddit", "").lower() in NSFW_SUB_BLOCKLIST:
        return False, "authority_absolute_reject"
    if post.get("removed") or post.get("locked"):
        return False, "authority_absolute_reject"
    if has_negative_markers(title, body):
        return False, "authority_absolute_reject"
    if has_vendor_content_markers(title, body):
        return False, "authority_absolute_reject"
    if int(sub.get("tier", 0)) >= 3 or float(sub.get("weight", 1.0)) == 0.0:
        return False, "authority_absolute_reject"

    # (2) Only the on-topic, not-a-buyer soft rejects feed this pass.
    if buyer_reason not in AUTHORITY_ELIGIBLE_REASONS:
        return False, "authority_not_eligible_reason"

    # (3) Authority is about answering questions.
    if not has_question_intent(title, body):
        return False, "authority_no_question"

    # (4) Topical-fit floor. Stricter than the buyer keyword gate by design:
    # without the brand anchor, density is the proof the post is on-topic.
    at_cfg = weights.get("authority_track", {}) or {}
    min_density = int(at_cfg.get("min_keyword_density", 2))
    n_hits, _ = count_keyword_hits(post, bucket_keywords)
    if n_hits < min_density:
        return False, "authority_keyword_density"

    # (5) Career / identity / meta filter (deterministic precision mechanism).
    if has_authority_negative_markers(title, body):
        return False, "authority_career_identity"

    # (6) Author vetting. The pipeline already vets authors before scoring and
    # drops failures, so a candidate reaching here normally has verdict=pass.
    # Re-honor it defensively when a vet dict is supplied.
    if vet is not None and vet.get("verdict") == "fail":
        return False, "authority_author_vet"

    return True, "authority_pass"


def compute_authority_score(
    post: dict[str, Any],
    sub: dict[str, Any],
    blog_matches: list[dict[str, Any]],
    weights: dict[str, Any],
    bucket_keywords: list[str],
    now: int | None = None,
) -> float:
    """Authority score. Reweight the SAME signals compute_score uses, do not
    invent new ones.

    Buyer scoring optimizes for buying-pain + freshness. Authority optimizes for
    REACH (how many people see a helpful reply) and ANSWERABILITY (a real
    question you can credibly answer, ideally backed by content you can cite):

      - up-weight upvote_velocity + comment_velocity (reach)
      - up-weight question intent + blog_coverage_bonus (answerability + citable
        authority lever)
      - down-weight pain markers (not the point of an authority reply)
      - keep freshness decay (a dead thread is not worth answering)

    Sub-weights live under authority_track.scoring in weights.yml. Defaults are
    chosen so reach dominates and the buyer pain emphasis is dialed back.
    """
    at_cfg = weights.get("authority_track", {}) or {}
    a = at_cfg.get("scoring", {}) or {}
    scoring = weights.get("scoring", {})

    ah = age_hours(post, now)
    v = velocity_per_hour(post, now)
    cv = comment_velocity(post, now)

    # Freshness decay: kept (reuse the same window as buyer scoring).
    f_cfg = scoring.get("freshness_decay", {})
    zero_h = float(f_cfg.get("zero_hours", 30)) or 30.0
    freshness = max(0.0, (zero_h - ah) / zero_h) * float(
        a.get("freshness_max_points", f_cfg.get("max_points", 30))
    )

    # Reach: up-weighted upvote + comment velocity.
    reach_mult = float(a.get("reach_weight", 1.5))
    uv_cfg = scoring.get("upvote_velocity", {})
    uv_score = min(float(uv_cfg.get("max_points", 20)) * reach_mult,
                   v * float(uv_cfg.get("multiplier", 4)) * reach_mult)
    cv_cfg = scoring.get("comment_velocity", {})
    cv_score = min(float(cv_cfg.get("max_points", 15)) * reach_mult,
                   cv * float(cv_cfg.get("multiplier", 6)) * reach_mult)

    # Topical fit: keyword density still counts (proof of on-topic), but it is
    # not the headline signal here, so reuse the buyer points-per-keyword.
    kw_cfg = scoring.get("pain_keyword_match", {})
    n_hits, _ = count_keyword_hits(post, bucket_keywords)
    kw_score = min(float(kw_cfg.get("max_points", 30)),
                   n_hits * float(kw_cfg.get("points_per_keyword", 6)))

    # Answerability: blog coverage is a citable-authority lever, up-weighted.
    answer_mult = float(a.get("answerability_weight", 1.5))
    blog_mult = float(a.get("blog_weight", 1.5))
    bc_cfg = scoring.get("blog_coverage_bonus", {})
    bc_score = min(float(bc_cfg.get("max_points", 50)) * blog_mult,
                   len(blog_matches) * float(bc_cfg.get("points_per_match", 25)) * blog_mult)

    title = post.get("title", "")
    body = post.get("body", "") or ""
    intent_cfg = scoring.get("intent_bonus", {})
    intent_score = 0.0
    if has_question_intent(title, body):
        intent_score += float(intent_cfg.get("question_bonus", 20)) * answer_mult
    # Pain markers down-weighted: still a faint positive but not the point.
    if has_pain_markers(title, body):
        intent_score += float(intent_cfg.get("pain_bonus", 15)) * float(
            a.get("pain_weight", 0.25)
        )

    raw = freshness + uv_score + cv_score + kw_score + bc_score + intent_score

    # Quarantine short-circuit (mirror compute_score): tier3 / weight 0 never
    # competes even if a direct caller bypasses the gate.
    if int(sub.get("tier", 0)) >= 3 or float(sub.get("weight", 1.0)) == 0.0:
        return 0.0

    tw_cfg = scoring.get("tier_weight", {})
    tier_mul = float(tw_cfg.get(f"tier_{sub['tier']}", 1.0))
    sub_mul = float(sub.get("weight", 1.0))

    return round(raw * sub_mul * tier_mul, 2)
