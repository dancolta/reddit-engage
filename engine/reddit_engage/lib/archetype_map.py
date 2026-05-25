"""6 pre-baked ICP archetypes for the `/reddit-engage:profile` fallback path.

When a user can't name the subs their audience uses (or pre-launch with no
named competitors), the wizard falls back on matching the user's interview
answers to one of these archetypes. Each is a starting config — the user
refines after they see Week 1 surfaces.

Sourced from the reddit-community-builder agent's 2026 mapping (Phase 9.2).
Quarantine lists are the 2026 watch list — subs that USED to work and
stopped (mod culture shift, audience drift).
"""
from __future__ import annotations

from typing import Any


ARCHETYPES: dict[str, dict[str, Any]] = {
    # ── 1. Bootstrapped B2B SaaS founder, devtool category ──
    "bootstrapped-b2b-saas-devtool": {
        "label": "Bootstrapped B2B SaaS founder · devtool · 1-5 employees",
        "ideal_for": [
            "selling developer tools / API products to other small teams",
            "<$1M ARR, no VC funding",
            "founder also writes code",
        ],
        "tier_1": [
            {"name": "SaaS", "weight": 1.0, "bucket": "operator", "saturation": "high"},
            {"name": "microsaas", "weight": 1.2, "bucket": "builder", "saturation": "low"},
            {"name": "indiehackers", "weight": 1.1, "bucket": "builder", "saturation": "medium"},
            {"name": "devops", "weight": 1.0, "bucket": "builder", "saturation": "medium"},
            {"name": "selfhosted", "weight": 1.1, "bucket": "builder", "saturation": "low"},
        ],
        "tier_2": [
            "programming", "webdev", "sysadmin", "ExperiencedDevs",
            "opensource", "homelab", "Database",
        ],
        "quarantine": ["Entrepreneur", "startups", "EntrepreneurRideAlong"],
    },

    # ── 2. Agency owner (marketing / web / design) ──
    "agency-owner": {
        "label": "Agency owner · marketing or web dev · 5-20 employees",
        "ideal_for": [
            "service-delivery agency selling to SMB or mid-market",
            "retainer model + project work",
            "founder hires + manages team",
        ],
        "tier_1": [
            {"name": "agency", "weight": 1.2, "bucket": "operator", "saturation": "medium"},
            {"name": "PPC", "weight": 1.1, "bucket": "operator", "saturation": "medium"},
            {"name": "SEO", "weight": 1.0, "bucket": "operator", "saturation": "medium"},
            {"name": "web_design", "weight": 0.9, "bucket": "operator", "saturation": "medium"},
        ],
        "tier_2": [
            "AskMarketing", "freelance", "smallbusiness", "Wordpress",
            "FacebookAds", "GoogleAds", "copywriting",
        ],
        "quarantine": ["Entrepreneur", "digital_marketing", "socialmedia"],
    },

    # ── 3. Indie hacker / solo builder ──
    "indie-hacker": {
        "label": "Indie hacker · solo · pre-revenue or <$5K MRR",
        "ideal_for": [
            "shipping niche product alone (or 2-person team)",
            "building in public, pre-product-market-fit",
            "limited budget, no API keys for premium tools",
        ],
        "tier_1": [
            {"name": "indiehackers", "weight": 1.3, "bucket": "builder", "saturation": "medium"},
            {"name": "SideProject", "weight": 1.2, "bucket": "builder", "saturation": "low"},
            {"name": "microsaas", "weight": 1.1, "bucket": "builder", "saturation": "low"},
            {"name": "SaaS", "weight": 0.9, "bucket": "builder", "saturation": "high"},
        ],
        "tier_2": [
            "Entrepreneur",  # exception — indie hackers DO read this
            "startups", "nocode", "webdev", "learnprogramming", "SoloFounders",
        ],
        "quarantine": ["business", "smallbusiness", "venturecapital"],
    },

    # ── 4. Independent consultant (fractional CFO/CTO/RevOps) ──
    "consultant-fractional": {
        "label": "Independent consultant · fractional CFO/CTO/RevOps · referral-driven",
        "ideal_for": [
            "advisory engagements, not product",
            "books work via referral + LinkedIn presence",
            "deep functional expertise in one area",
        ],
        "tier_1": [
            {"name": "consulting", "weight": 1.2, "bucket": "operator", "saturation": "medium"},
            {"name": "fractional", "weight": 1.3, "bucket": "operator", "saturation": "low"},
            {"name": "FPandA", "weight": 1.1, "bucket": "operator", "saturation": "low"},
        ],
        "tier_2": [
            "smallbusiness", "ExperiencedDevs", "CFO", "managers",
            "ExecutiveAssistants", "startups",
        ],
        "quarantine": ["Entrepreneur", "freelance", "digitalnomad"],
    },

    # ── 5. VP/Director RevOps at mid-market SaaS ──
    "revops-leader": {
        "label": "VP/Director RevOps · 50-500 person B2B SaaS",
        "ideal_for": [
            "selling to RevOps/SalesOps leaders",
            "post-Series A, pre-IPO",
            "buyer has budget but rigorous evaluation cycle",
        ],
        "tier_1": [
            {"name": "RevOps", "weight": 1.4, "bucket": "operator", "saturation": "low"},
            {"name": "SalesOperations", "weight": 1.3, "bucket": "operator", "saturation": "low"},
            {"name": "CRM", "weight": 1.1, "bucket": "operator", "saturation": "medium"},
            {"name": "sales", "weight": 1.0, "bucket": "operator", "saturation": "high"},
        ],
        "tier_2": [
            "SaaS", "ExperiencedDevs", "ProductManagement", "startups",
            "AskMarketing", "FPandA", "CustomerSuccess",
        ],
        "quarantine": [
            "Entrepreneur", "smallbusiness", "marketing", "business",
        ],
    },

    # ── 6. Founder at PLG SaaS targeting developers ──
    "plg-devtool": {
        "label": "Founder at PLG SaaS · targeting developers · API-first",
        "ideal_for": [
            "self-serve product with free tier",
            "developers as both buyer and user",
            "growth via OSS / community, not enterprise sales",
        ],
        "tier_1": [
            {"name": "devops", "weight": 1.2, "bucket": "builder", "saturation": "medium"},
            {"name": "programming", "weight": 1.0, "bucket": "builder", "saturation": "high"},
            {"name": "webdev", "weight": 1.0, "bucket": "builder", "saturation": "medium"},
            {"name": "ExperiencedDevs", "weight": 1.3, "bucket": "builder", "saturation": "low"},
            {"name": "selfhosted", "weight": 1.1, "bucket": "builder", "saturation": "low"},
        ],
        "tier_2": [
            "SaaS", "kubernetes", "golang", "rust", "Python",
            "node", "opensource", "sre",
        ],
        "quarantine": ["Entrepreneur", "startups", "learnprogramming"],
    },
}


# 2026 quarantine universal — these are nuked across ALL archetypes unless
# the archetype explicitly opts them in (indie-hacker keeps Entrepreneur).
UNIVERSAL_WATCH_LIST: set[str] = {
    "Entrepreneur",            # coaching/dropshipping noise since 2023
    "startups",                # mods aggressive on self-promotion
    "marketing",               # drifted junior, homework-heavy
    "smallbusiness",           # pivoted to brick-and-mortar post-2024
    "digital_marketing",       # bot-heavy thread spam
}


def list_archetypes() -> list[dict[str, str]]:
    """Return picker-friendly list of archetype keys + labels."""
    return [{"key": k, "label": v["label"]} for k, v in ARCHETYPES.items()]


def get(archetype_key: str) -> dict[str, Any] | None:
    """Return the full archetype dict, or None if key not found."""
    return ARCHETYPES.get(archetype_key)


def best_match(interview_answers: dict[str, str]) -> str:
    """Heuristic: pick the most likely archetype from interview answers.

    Used in the "I don't know" fallback when the user explicitly cannot
    name subs OR when the LLM synthesis produces low-confidence results.
    Cheap keyword scoring — not LLM. Tunable, easy to debug.

    Returns archetype key (always picks ONE — never None).
    """
    blob = " ".join(str(v).lower() for v in interview_answers.values())

    scores: dict[str, int] = {k: 0 for k in ARCHETYPES}

    # bootstrapped-b2b-saas-devtool
    for kw in ("devtool", "api", "developer tool", "infrastructure",
               "self-host", "open source", "engineer", "bootstrap"):
        if kw in blob:
            scores["bootstrapped-b2b-saas-devtool"] += 1

    # agency-owner
    for kw in ("agency", "client", "retainer", "deliverable", "billable",
               "scope", "agency owner", "service business"):
        if kw in blob:
            scores["agency-owner"] += 1

    # indie-hacker
    for kw in ("indie", "solo", "side project", "bootstrap", "$0 mrr",
               "$1k mrr", "$5k mrr", "no team", "just me"):
        if kw in blob:
            scores["indie-hacker"] += 1

    # consultant-fractional
    for kw in ("consult", "fractional", "advisory", "advisor", "engagement",
               "fractional cfo", "fractional cto", "client work"):
        if kw in blob:
            scores["consultant-fractional"] += 1

    # revops-leader
    for kw in ("revops", "rev ops", "salesops", "sales operations",
               "pipeline", "salesforce", "hubspot",
               "50-500", "series a", "series b", "head of"):
        if kw in blob:
            scores["revops-leader"] += 1

    # plg-devtool
    for kw in ("plg", "product-led", "free tier", "self-serve",
               "free trial", "api-first", "developer-first", "freemium"):
        if kw in blob:
            scores["plg-devtool"] += 1

    # Pick highest scorer; ties broken by archetype-list order
    return max(scores.items(), key=lambda kv: kv[1])[0]
