"""Tests for onboard_synth: 3-answer routing flow.

The onboard flow's LLM reasoning happens in Claude chat (subscription),
not via subprocess. This module is the receiver + validator + YAML
emitter — those are the testable units.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import profile_synth as onboard_synth  # noqa: E402


VALID_3Q_ANSWERS = {
    "who_to_reach": "RevOps leaders at Series B SaaS",
    "what_offering": "Notion-for-RevOps — single source of truth for pipeline data",
    "homepage_url": "",
}


def test_archetype_seed_picks_revops_for_revops_input():
    """Sanity: input that says RevOps should pick the revops-leader archetype."""
    seed = onboard_synth.archetype_seed(VALID_3Q_ANSWERS)
    assert "tier_1" in seed
    assert "RevOps" in [s.get("name") for s in seed["tier_1"]]


def test_archetype_seed_for_indie_picks_indie_archetype():
    indie_answers = {
        "who_to_reach": "indie devs shipping AI tools",
        "what_offering": "tiny SaaS, solo, $1k MRR",
        "homepage_url": "",
    }
    seed = onboard_synth.archetype_seed(indie_answers)
    sub_names = [s.get("name") for s in seed["tier_1"]]
    # Indie hacker archetype features indiehackers + SideProject
    assert any("indie" in name.lower() for name in sub_names) or "SideProject" in sub_names


def test_save_and_load_draft(tmp_path, monkeypatch):
    """Scratchpad round-trip works."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    saved_path = onboard_synth.save_draft(VALID_3Q_ANSWERS)
    assert saved_path.exists()
    assert saved_path.stat().st_mode & 0o777 == 0o600
    loaded = onboard_synth.load_draft()
    assert loaded == VALID_3Q_ANSWERS


def test_load_draft_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    assert onboard_synth.load_draft() is None


def test_clear_draft_removes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    onboard_synth.save_draft(VALID_3Q_ANSWERS)
    onboard_synth.clear_draft()
    assert onboard_synth.load_draft() is None


def test_load_draft_handles_malformed_json(tmp_path, monkeypatch):
    """Stale/corrupt scratchpad returns None, doesn't crash."""
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(tmp_path))
    draft_path = tmp_path / ".onboard-draft.json"
    draft_path.write_text("not-json{{{")
    assert onboard_synth.load_draft() is None


def test_merge_url_extracts_adds_new_competitors():
    """URL-extracted competitor list extends brand_anchor without dups."""
    payload = {
        "brand_anchor": ["HubSpot", "Salesforce"],
        "keywords": {"shared": [], "operator": [], "builder": []},
    }
    extracts = {
        "competitors": ["Clari", "Gong", "HubSpot"],  # HubSpot is dup
        "pain_phrases": [],
    }
    result = onboard_synth.merge_url_extracts(payload, extracts)
    assert "Clari" in result["brand_anchor"]
    assert "Gong" in result["brand_anchor"]
    # No duplicate
    assert result["brand_anchor"].count("HubSpot") == 1


def test_merge_url_extracts_caps_brand_anchor_at_20():
    """brand_anchor never exceeds 20 even with aggressive URL extracts."""
    payload = {
        "brand_anchor": [f"Brand{i}" for i in range(15)],
        "keywords": {"shared": [], "operator": [], "builder": []},
    }
    extracts = {
        "competitors": [f"Extra{i}" for i in range(20)],  # would push past 20
        "pain_phrases": [],
    }
    result = onboard_synth.merge_url_extracts(payload, extracts)
    assert len(result["brand_anchor"]) <= 20


def test_merge_url_extracts_no_url_returns_unchanged():
    """Empty extracts dict → payload comes back untouched."""
    payload = {
        "brand_anchor": ["HubSpot"],
        "keywords": {"shared": ["pricing"], "operator": [], "builder": []},
    }
    result = onboard_synth.merge_url_extracts(payload, {})
    assert result["brand_anchor"] == ["HubSpot"]


def test_validate_delegates_to_profile_synth():
    """validate() is an alias for profile_synth.validate_synthesis — same schema."""
    payload = onboard_synth.archetype_seed(VALID_3Q_ANSWERS)
    # archetype seed may not always pass full validation (it's a starting
    # point Claude refines), but the function call must not raise
    ok, problems = onboard_synth.validate(payload)
    assert isinstance(ok, bool)
    assert isinstance(problems, list)
