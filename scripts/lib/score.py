"""Tier-aware gate + scoring.

Pipeline:
  1. evaluate_gate(post, sub, blog_matches) -> (passes: bool, reason: str)
  2. compute_score(post, sub, blog_matches) -> float

Gate failures short-circuit. Survivors are ranked by score.
"""
from __future__ import annotations

import time
from typing import Any


def now_utc() -> int:
    return int(time.time())


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


def evaluate_gate(
    post: dict[str, Any],
    sub: dict[str, Any],
    blog_matches: list[dict[str, Any]],
    weights: dict[str, Any],
    bucket_keywords: list[str],
    now: int | None = None,
) -> tuple[bool, str]:
    """Evaluate the gate for a single post. Returns (passes, reason)."""
    if post.get("removed") or post.get("locked"):
        return False, "removed_or_locked"

    ah = age_hours(post, now)
    if sub["tier"] == 1:
        return _tier1_gate(post, sub, weights, bucket_keywords, ah, now)
    return _tier2_gate(post, sub, weights, bucket_keywords, ah, now)


def _tier1_gate(post: dict[str, Any], sub: dict[str, Any], weights: dict[str, Any],
                bucket_keywords: list[str], ah: float, now: int | None) -> tuple[bool, str]:
    """Tier 1 hard gate: age, comment ceiling, at least one keyword."""
    g = _apply_overrides(weights.get("tier1_gates", {}), sub.get("gate_overrides"))

    if ah > float(g.get("post_age_hours", 48)):
        return False, "tier1_post_age"

    ceiling = int(g.get("comment_ceiling", 100))
    if ceiling > 0 and post["num_comments"] > ceiling:
        return False, "tier1_comment_ceiling"

    n_hits, _ = count_keyword_hits(post, bucket_keywords)
    if n_hits < int(g.get("pain_keywords_min", 1)):
        return False, "tier1_keyword_density"

    return True, "tier1_pass"


def _tier2_gate(post: dict[str, Any], sub: dict[str, Any], weights: dict[str, Any],
                bucket_keywords: list[str], ah: float, now: int | None) -> tuple[bool, str]:
    """Tier 2 hard gate: age, at least one (or two) keyword."""
    g = _apply_overrides(weights.get("tier2_gates", {}), sub.get("gate_overrides"))

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

    raw = freshness + uv_score + cv_score + kw_score + bc_score

    tw_cfg = scoring.get("tier_weight", {})
    tier_mul = float(tw_cfg.get(f"tier_{sub['tier']}", 1.0))
    sub_mul = float(sub.get("weight", 1.0))

    return round(raw * sub_mul * tier_mul, 2)
