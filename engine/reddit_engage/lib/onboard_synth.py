"""Lightweight synthesizer for the 3-question /reddit-engage:onboard skill.

Compared to profile_synth.py (which takes 8 interview answers and builds a
deep custom config), this module is the minimal viable middle path between
generic preset and full /profile:

  - 3 inputs: who_to_reach, what_offering, homepage_url (optional)
  - Claude reasons through them IN CHAT (subscription, free)
  - This module just provides the structured output contract + writes YAML

The actual synthesis happens in the /onboard skill instructions (Claude's
turn), not via a subprocess LLM call. This module is the receiver +
validator + YAML emitter.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import archetype_map, profile_synth, store


# The 3 answers come in as a dict
OnboardAnswers = dict[str, str]


# Reuse profile_synth's validator (same shape requirements)
validate = profile_synth.validate_synthesis


def write_to_xdg(payload: dict[str, Any], backup: bool = True) -> dict[str, Path]:
    """Write the synthesized config files. Delegates to profile_synth's writer."""
    yaml_files = profile_synth.to_yaml_files(payload)
    return profile_synth.write_to_xdg(yaml_files, backup=backup)


def archetype_seed(answers: OnboardAnswers) -> dict[str, Any]:
    """Best-effort archetype-mapped seed, used when Claude wants a starting
    point before refining with the user's specific answers.

    The /onboard skill calls this to get a baseline payload, then layers
    the user's specific competitors / pain language / homepage findings
    on top before final write.
    """
    # Reuse archetype_map but pass through answers in a shape it understands
    return profile_synth.fallback_from_archetype({
        "what_you_sell": answers.get("what_offering", ""),
        "icp": answers.get("who_to_reach", ""),
        "pain_quote": answers.get("who_to_reach", "") + " " + answers.get("what_offering", ""),
        "competitors": "",
    })


def merge_url_extracts(payload: dict[str, Any], url_extracts: dict[str, Any]) -> dict[str, Any]:
    """Merge homepage-URL-derived intelligence into the synthesis payload.

    The /onboard skill WebFetches the user's homepage and pulls:
      - H1 + tagline
      - first 400 chars of body
      - any visible competitor logos (if Claude can identify them)
      - pricing tier (rough — for ACV-aware ranker weighting later)

    This function takes those extracts and amplifies the relevant payload
    fields (more competitors in brand_anchor, sharper keywords, better
    example pains).
    """
    if not url_extracts:
        return payload

    # Append URL-extracted competitors to brand_anchor (dedup)
    new_competitors = url_extracts.get("competitors") or []
    existing = {b.lower() for b in payload.get("brand_anchor", [])}
    for comp in new_competitors:
        if comp.lower() not in existing:
            payload.setdefault("brand_anchor", []).append(comp)
            existing.add(comp.lower())
    # Cap at sweet spot
    payload["brand_anchor"] = payload.get("brand_anchor", [])[:20]

    # Append URL-extracted pain phrases to shared keywords
    new_pain = url_extracts.get("pain_phrases") or []
    existing_kw = {k.lower() for k in payload.get("keywords", {}).get("shared", [])}
    for phrase in new_pain:
        if phrase.lower() not in existing_kw and len(phrase) < 80:
            payload.setdefault("keywords", {}).setdefault("shared", []).append(phrase)
            existing_kw.add(phrase.lower())

    return payload


def save_draft(answers: OnboardAnswers, draft_name: str = ".onboard-draft.json") -> Path:
    """Persist the answers so /onboard is resumable mid-interview."""
    draft_path = store.xdg_config_dir() / draft_name
    draft_path.write_text(json.dumps(answers, indent=2))
    draft_path.chmod(0o600)
    return draft_path


def load_draft(draft_name: str = ".onboard-draft.json") -> OnboardAnswers | None:
    draft_path = store.xdg_config_dir() / draft_name
    if not draft_path.exists():
        return None
    try:
        return json.loads(draft_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def clear_draft(draft_name: str = ".onboard-draft.json") -> None:
    draft_path = store.xdg_config_dir() / draft_name
    if draft_path.exists():
        draft_path.unlink()
