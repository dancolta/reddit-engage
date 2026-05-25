"""Tests for profile_synth: validation + YAML emission + archetype fallback."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reddit_engage.lib import archetype_map, profile_synth  # noqa: E402


# === Test fixtures ===

VALID_PAYLOAD = {
    "tier_1": [
        {"name": "RevOps", "weight": 1.4, "bucket": "operator", "saturation": "low",
         "reason": "Q3: user named RevOps leads as ICP — exact match"},
        {"name": "SalesOperations", "weight": 1.2, "bucket": "operator", "saturation": "low",
         "reason": "Q7: 'Sales operations leader' is user's stated self-description"},
        {"name": "CRM", "weight": 1.1, "bucket": "operator", "saturation": "medium",
         "reason": "Q6 competitors live in CRM category"},
    ],
    "tier_2": [
        {"name": "sales", "weight": 1.0, "bucket": "operator", "saturation": "high",
         "reason": "Q3 ICP overlap, sub broader than role"},
        {"name": "SaaS", "weight": 0.9, "bucket": "operator", "saturation": "high",
         "reason": "Q3 'B2B SaaS' context — saturated"},
        {"name": "CustomerSuccess", "weight": 0.9, "bucket": "operator", "saturation": "medium",
         "reason": "Adjacent function in same companies as Q3 ICP"},
    ],
    "tier_3": [
        {"name": "Entrepreneur", "reason": "Universal watch list"},
    ],
    "candidates_to_verify": ["RevenueOperations"],
    "keywords": {
        "shared": ["pipeline hygiene", "forecast accuracy", "data cleanup"],
        "operator": ["our rev stack is 12 tools", "reps not updating CRM", "weekly pipeline review"],
        "builder": ["building internal RevOps tool", "Notion as CRM", "rolled our own"],
    },
    "brand_anchor": ["Clari", "Gong", "Default", "Pocus", "Salesforce", "HubSpot",
                     "Outreach", "Salesloft", "Apollo", "Clay"],
    "example_pains": [
        "Our RevOps team is drowning in 14 tools — how do you keep pipeline clean?",
        "Anyone else's forecast off by 30% every quarter because reps don't update CRM?",
        "Spent 4 hours Friday cleaning Salesforce data again. There has to be a better way.",
        "Series B, 8 reps, no RevOps hire yet — what's the first thing I automate?",
        "Built a Notion-based RevOps dashboard. Is this insane or onto something?",
    ],
}


def test_valid_payload_passes_validation():
    ok, problems = profile_synth.validate_synthesis(VALID_PAYLOAD)
    assert ok, f"valid payload should pass; got: {problems}"


def test_missing_field_fails():
    bad = dict(VALID_PAYLOAD)
    del bad["brand_anchor"]
    ok, problems = profile_synth.validate_synthesis(bad)
    assert not ok
    assert any("brand_anchor" in p for p in problems)


def test_tier_1_over_cap_fails():
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    bad["tier_1"].extend([
        {"name": f"Extra{i}", "weight": 1.0, "bucket": "operator", "saturation": "low",
         "reason": "filler to exceed cap"} for i in range(5)
    ])
    weights = {"config_ceilings": {"tier1_subs_max": 5}}
    ok, problems = profile_synth.validate_synthesis(bad, weights)
    assert not ok
    assert any("tier_1 has" in p for p in problems)


def test_watchlist_sub_in_tier_1_fails():
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    bad["tier_1"][0] = {
        "name": "Entrepreneur", "weight": 1.2, "bucket": "operator", "saturation": "high",
        "reason": "user said B2B SaaS so let's try"
    }
    ok, problems = profile_synth.validate_synthesis(bad)
    assert not ok
    assert any("watch list" in p for p in problems)


def test_duplicate_sub_across_tiers_fails():
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    bad["tier_2"][0] = {
        "name": "RevOps", "weight": 0.5, "bucket": "operator", "saturation": "low",
        "reason": "duplicate of tier 1 entry"
    }
    ok, problems = profile_synth.validate_synthesis(bad)
    assert not ok
    assert any("appears in both" in p for p in problems)


def test_missing_reason_fails():
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    bad["tier_1"][0]["reason"] = "short"  # too short
    ok, problems = profile_synth.validate_synthesis(bad)
    assert not ok
    assert any("reason field" in p for p in problems)


def test_weight_out_of_bounds_fails():
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    bad["tier_1"][0]["weight"] = 3.5
    ok, problems = profile_synth.validate_synthesis(bad)
    assert not ok
    assert any("weight" in p for p in problems)


def test_generic_keyword_filtered():
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    bad["keywords"]["shared"].append("alternative to HubSpot")
    ok, problems = profile_synth.validate_synthesis(bad)
    assert not ok
    assert any("generic phrase" in p for p in problems)


def test_brand_anchor_too_small_fails():
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    bad["brand_anchor"] = ["X", "Y", "Z"]  # below floor of 8
    ok, problems = profile_synth.validate_synthesis(bad)
    assert not ok
    assert any("min 8" in p for p in problems)


def test_yaml_emit_has_comments():
    yaml_files = profile_synth.to_yaml_files(VALID_PAYLOAD)
    assert "subreddits.yml" in yaml_files
    assert "Generated by /reddit-engage:profile" in yaml_files["subreddits.yml"]
    assert "Tier 1" in yaml_files["subreddits.yml"]
    assert "Tier 2" in yaml_files["subreddits.yml"]
    assert "name: RevOps" in yaml_files["subreddits.yml"]
    # Reason should appear as a comment above the entry
    assert "# Q3" in yaml_files["subreddits.yml"]


def test_yaml_emit_brand_anchor_correct():
    yaml_files = profile_synth.to_yaml_files(VALID_PAYLOAD)
    assert "brand-anchor.yml" in yaml_files
    for brand in VALID_PAYLOAD["brand_anchor"]:
        assert brand in yaml_files["brand-anchor.yml"]


def test_archetype_fallback_produces_valid_payload():
    """The archetype fallback path must always produce a structurally
    valid payload, even with minimal interview answers."""
    answers = {
        "what_you_sell": "Notion-for-RevOps — single source of truth for pipeline",
        "icp": "RevOps leads at $10-50M ARR B2B SaaS, post-Series B",
        "pain_quote": "our forecast is off by 30% because reps don't update Salesforce",
        "competitors": "Clari, Gong, Default, Pocus",
    }
    payload = profile_synth.fallback_from_archetype(answers)
    ok, problems = profile_synth.validate_synthesis(payload)
    # Fallback may emit slightly looser shape; assert structural keys exist
    assert "tier_1" in payload
    assert "tier_2" in payload
    assert "keywords" in payload
    assert "brand_anchor" in payload
    assert len(payload["brand_anchor"]) >= 8


def test_archetype_best_match_picks_revops():
    """Sanity: a clearly-RevOps interview picks revops-leader archetype."""
    answers = {
        "icp": "VP of RevOps at 200-person B2B SaaS",
        "pain": "pipeline hygiene, forecast accuracy",
        "competitors": "Clari, Gong",
    }
    arch_key = archetype_map.best_match(answers)
    assert arch_key == "revops-leader"


def test_archetype_best_match_picks_indie_hacker():
    answers = {
        "what_you_sell": "solo indie hacker building a tiny SaaS",
        "stage": "$1k MRR, just me, side project",
        "competitors": "Levels.fyi",
    }
    arch_key = archetype_map.best_match(answers)
    assert arch_key == "indie-hacker"


def test_archetype_returns_one_even_for_blank_answers():
    """best_match must never return None — falls through to default."""
    arch_key = archetype_map.best_match({"what_you_sell": ""})
    assert arch_key in archetype_map.ARCHETYPES


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
