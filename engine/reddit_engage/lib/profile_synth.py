"""Profile synthesis: turn 8 interview answers into a personalized reddit-engage config.

Used by `/reddit-engage:profile`. Three modes:

  1. LLM synthesis (Anthropic API key path) — full personalized config
  2. Archetype-mapped synthesis (subscription / no-key path) — Claude-in-chat
     reasons over the same prompt, falls back to archetype_map.best_match()
     if synthesis fails
  3. Pure archetype fallback (no LLM available) — interview answers used only
     to pick the closest of 6 pre-baked archetypes

Output: 4 YAML files written under XDG config dir:
  - subreddits.yml     (tier 1/2/3 with reasoning per sub)
  - keywords.yml       (shared/operator/builder buckets)
  - brand-anchor.yml   (competitor list)
  - example-pains.yml  (5 made-up titles for LLM classifier few-shots)

Plus a validation pass that enforces caps from weights.yml config_ceilings.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from . import archetype_map, classify, store


# ─── JSON schema for LLM output (validated before YAML emit) ──────────
SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "tier_1", "tier_2", "tier_3", "candidates_to_verify",
        "keywords", "brand_anchor", "example_pains",
    ],
    "properties": {
        "tier_1": {"type": "array", "minItems": 3, "maxItems": 5},
        "tier_2": {"type": "array", "minItems": 3, "maxItems": 12},
        "tier_3": {"type": "array"},
        "candidates_to_verify": {"type": "array"},
        "keywords": {
            "type": "object",
            "required": ["shared", "operator", "builder"],
            "properties": {
                "shared": {"type": "array", "minItems": 3},
                "operator": {"type": "array", "minItems": 3},
                "builder": {"type": "array", "minItems": 3},
            },
        },
        "brand_anchor": {"type": "array", "minItems": 8, "maxItems": 25},
        "example_pains": {"type": "array", "minItems": 5, "maxItems": 5},
    },
}


# Phrases that are too generic to live in a personalized keyword bucket.
# The base engine adds these as baseline; the profile must produce SHARP
# ICP-specific phrases, not these.
BANNED_GENERIC_KEYWORDS = {
    "alternative to", "switching from", "looking for a tool",
    "anyone use", "recommendations for", "what's the best",
    "any good", "recommended",
}

# 2026 universal watch list — never tier 1 or tier 2 regardless of synthesis.
# Mirror of archetype_map.UNIVERSAL_WATCH_LIST plus a few extras observed
# during Phase -1 reddit-community-builder research.
WATCH_LIST = archetype_map.UNIVERSAL_WATCH_LIST | {
    "entrepreneurridealong",
}


def validate_synthesis(payload: dict[str, Any], weights_cfg: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    """Return (ok, problems). Used between LLM output and disk write."""
    problems: list[str] = []
    ceilings = (weights_cfg or {}).get("config_ceilings", {})

    # Required fields
    for key in SYNTHESIS_SCHEMA["required"]:
        if key not in payload:
            problems.append(f"missing required field: {key}")
    if problems:
        return False, problems

    # Tier 1 cap (hard requirement)
    t1_max = int(ceilings.get("tier1_subs_max", 5))
    if len(payload["tier_1"]) > t1_max:
        problems.append(f"tier_1 has {len(payload['tier_1'])} subs, max {t1_max}")

    # Tier 2 ceiling
    t2_max = int(ceilings.get("tier2_subs_max", 8))
    if len(payload["tier_2"]) > t2_max:
        problems.append(f"tier_2 has {len(payload['tier_2'])} subs, max {t2_max}")

    # No duplicate sub names across tiers
    seen: dict[str, str] = {}
    for tier_name in ("tier_1", "tier_2", "tier_3"):
        for entry in payload[tier_name]:
            name = (entry.get("name") or "").lower()
            if not name:
                problems.append(f"{tier_name} entry missing name: {entry}")
                continue
            if name in seen:
                problems.append(f"sub r/{name} appears in both {seen[name]} and {tier_name}")
            seen[name] = tier_name

    # Watch list — any sub in WATCH_LIST must NOT be in tier 1/2
    for tier_name in ("tier_1", "tier_2"):
        for entry in payload[tier_name]:
            name = (entry.get("name") or "").lower()
            if name in {w.lower() for w in WATCH_LIST}:
                problems.append(f"r/{name} is on 2026 watch list, cannot be in {tier_name}")

    # Every sub in tier_1/tier_2 has a reason field referencing interview
    for tier_name in ("tier_1", "tier_2"):
        for entry in payload[tier_name]:
            reason = entry.get("reason") or ""
            if len(reason) < 15:
                problems.append(f"{tier_name} r/{entry.get('name','?')} missing or short reason field")

    # Weight bounds
    for tier_name in ("tier_1", "tier_2"):
        for entry in payload[tier_name]:
            w = entry.get("weight")
            if w is None or not 0.0 <= float(w) <= 2.0:
                problems.append(f"{tier_name} r/{entry.get('name','?')} weight {w} out of [0,2]")

    # Bucket field present
    for tier_name in ("tier_1", "tier_2"):
        for entry in payload[tier_name]:
            if entry.get("bucket") not in ("operator", "builder"):
                problems.append(f"{tier_name} r/{entry.get('name','?')} bucket must be operator|builder")

    # Keyword anti-generic filter
    for bucket_name in ("shared", "operator", "builder"):
        kws = payload["keywords"].get(bucket_name) or []
        for kw in kws:
            kw_lower = kw.lower().strip()
            if any(banned in kw_lower for banned in BANNED_GENERIC_KEYWORDS):
                problems.append(f"keywords.{bucket_name} contains generic phrase: '{kw}'")

    # Keyword bucket size ceiling
    kw_max = int(ceilings.get("keywords_per_bucket_max", 50))
    for bucket_name in ("shared", "operator", "builder"):
        n = len(payload["keywords"].get(bucket_name) or [])
        if n > kw_max:
            problems.append(f"keywords.{bucket_name} has {n} entries, max {kw_max}")

    # Brand anchor bounds
    ba = payload.get("brand_anchor") or []
    ba_max = int(ceilings.get("brand_anchor_max", 20))
    if len(ba) > ba_max:
        problems.append(f"brand_anchor has {len(ba)} entries, max {ba_max}")
    if len(ba) < 8:
        problems.append(f"brand_anchor has {len(ba)} entries, min 8")

    # Example pains — must be 5 strings, 20-160 chars each
    pains = payload.get("example_pains") or []
    if len(pains) != 5:
        problems.append(f"example_pains must have exactly 5 entries, got {len(pains)}")
    for p in pains:
        if not isinstance(p, str) or not 20 <= len(p) <= 160:
            problems.append(f"example_pain length out of [20,160]: '{p[:40]}...'")

    return (len(problems) == 0, problems)


def to_yaml_files(payload: dict[str, Any]) -> dict[str, str]:
    """Convert a validated synthesis payload into 4 commented YAML strings.

    Returns {filename: content}. Caller writes to XDG config dir.
    """
    # subreddits.yml — commented per-sub
    subs_lines = ["# Generated by /reddit-engage:profile.",
                  "# Edit freely; re-running /profile preserves your manual edits.", ""]
    subs_lines.append("subreddits:")

    def _emit_tier(label: str, entries: list[dict[str, Any]], tier_num: int):
        if not entries:
            return
        subs_lines.append(f"")
        subs_lines.append(f"  # === Tier {tier_num} {label} ===")
        for e in entries:
            reason = (e.get("reason") or "").strip().replace("\n", " ")[:80]
            if reason:
                subs_lines.append(f"  # {reason}")
            tail_parts = [
                f"name: {e['name']}",
                f"tier: {tier_num}",
                f"bucket: {e.get('bucket', 'operator')}",
                f"weight: {float(e.get('weight', 1.0))}",
            ]
            if e.get("saturation"):
                tail_parts.append(f"saturation: {e['saturation']}")
            subs_lines.append(f"  - {{{', '.join(tail_parts)}}}")

    _emit_tier("(daily scan, lenient gates)", payload["tier_1"], 1)
    _emit_tier("(opportunistic, strict gates)", payload["tier_2"], 2)
    if payload.get("tier_3"):
        subs_lines.append("")
        subs_lines.append("  # === Tier 3 quarantined (fetched for telemetry, never surfaced) ===")
        for e in payload["tier_3"]:
            reason = (e.get("reason") or "").strip().replace("\n", " ")[:80]
            if reason:
                subs_lines.append(f"  # {reason}")
            subs_lines.append(
                f"  - {{name: {e['name']}, tier: 3, bucket: operator, weight: 0.0}}"
            )
    subs_yaml = "\n".join(subs_lines) + "\n"

    # keywords.yml
    kw = payload["keywords"]
    kw_lines = ["# Generated by /reddit-engage:profile.",
                "# Buckets: shared = both audiences; operator = ICP work-pain;",
                "#          builder = founder/dev/indie-hacker shop-talk.", ""]
    for bucket in ("shared", "operator", "builder"):
        kw_lines.append(f"{bucket}:")
        for k in (kw.get(bucket) or []):
            kw_lines.append(f"  - {json.dumps(k)}")
        kw_lines.append("")
    kw_yaml = "\n".join(kw_lines)

    # brand-anchor.yml
    ba_lines = [
        "# Competitors + adjacent SaaS the ICP touches. Used to anchor surface",
        "# scoring — a post that names one of these gets a brand-anchor boost.",
        "",
        "brand_anchor:",
    ]
    for b in payload["brand_anchor"]:
        ba_lines.append(f"  - {json.dumps(b)}")
    ba_yaml = "\n".join(ba_lines) + "\n"

    # example-pains.yml (for LLM classifier few-shots)
    ex_lines = [
        "# Example pain-post titles in the voice of your ICP.",
        "# Used as few-shot examples for the optional LLM classifier (Phase 2).",
        "",
        "example_pains:",
    ]
    for p in payload["example_pains"]:
        ex_lines.append(f"  - {json.dumps(p)}")
    ex_yaml = "\n".join(ex_lines) + "\n"

    return {
        "subreddits.yml": subs_yaml,
        "keywords.yml": kw_yaml,
        "brand-anchor.yml": ba_yaml,
        "example-pains.yml": ex_yaml,
    }


def write_to_xdg(yaml_files: dict[str, str], backup: bool = True) -> dict[str, Path]:
    """Write the 4 YAML files to ~/.config/reddit-engage/. Returns paths written.

    If `backup` and the target exists, copy to `<name>.bak.<timestamp>` first.
    """
    import shutil
    import time
    config_dir = store.xdg_config_dir()
    written: dict[str, Path] = {}
    for filename, content in yaml_files.items():
        path = config_dir / filename
        if backup and path.exists():
            ts = int(time.time())
            shutil.copy2(path, path.with_suffix(path.suffix + f".bak.{ts}"))
        path.write_text(content)
        path.chmod(0o600)
        written[filename] = path
    return written


def llm_synthesize(interview_summary: str, model: str = "claude-haiku-4-5") -> dict[str, Any] | None:
    """Bulk-LLM path: call Anthropic SDK with the synthesis prompt.

    Returns the parsed JSON payload, or None if classifier provider disabled
    (no ANTHROPIC_API_KEY) — caller falls back to archetype path.
    """
    if classify.detect_provider() == "disabled":
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None

    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "profile_synth.md"
    system_prompt = prompt_path.read_text()
    client = anthropic.Anthropic()
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4000,
            system=[{"type": "text", "text": system_prompt,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": interview_summary}],
        )
    except Exception:
        return None
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    # Strip code fence if present
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n", "", text)
        text = text.rstrip("`").rstrip()
    try:
        # The prompt may emit both JSON and YAML blocks; pick the first JSON object
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace < 0 or last_brace < 0:
            return None
        return json.loads(text[first_brace : last_brace + 1])
    except json.JSONDecodeError:
        return None


def fallback_from_archetype(interview_answers: dict[str, str]) -> dict[str, Any]:
    """Build a synthesis payload from archetype_map when LLM is unavailable.

    Less personalized than LLM synthesis but always produces a usable config.
    Used as the "no API key" path AND as a last-resort fallback when LLM
    synthesis fails validation.
    """
    arch_key = archetype_map.best_match(interview_answers)
    arch = archetype_map.get(arch_key)
    assert arch is not None, f"archetype {arch_key} not found"

    # Coerce archetype shape → synthesis schema shape
    tier_1 = [
        {**entry, "reason": f"Archetype '{arch_key}': {arch['label']}"}
        for entry in arch["tier_1"]
    ]
    tier_2 = [
        {
            "name": name, "weight": 1.0, "bucket": "operator",
            "saturation": "medium",
            "reason": f"Archetype '{arch_key}': tier-2 candidate",
        }
        for name in arch["tier_2"]
    ]
    tier_3 = [
        {"name": name, "reason": f"Archetype '{arch_key}': quarantined"}
        for name in arch.get("quarantine", [])
    ]

    # Best-effort keyword seeds from interview answers
    pain_quote = (interview_answers.get("pain_quote") or "").lower()
    competitors_raw = interview_answers.get("competitors") or ""
    competitors = [c.strip() for c in competitors_raw.split(",") if c.strip()]

    keywords = {
        "shared": ["pain", "stuck", "broken", "expensive", "frustrating"],
        "operator": ["workflow", "stack", "tool sprawl", "ROI", "switching from"],
        "builder": ["build vs buy", "rolled our own", "internal tool"],
    }
    if pain_quote:
        keywords["shared"].insert(0, pain_quote[:80])

    return {
        "tier_1": tier_1,
        "tier_2": tier_2,
        "tier_3": tier_3,
        "candidates_to_verify": [],
        "keywords": keywords,
        "brand_anchor": competitors[:12] if len(competitors) >= 8 else (
            competitors + ["HubSpot", "Salesforce", "Slack", "Notion", "Linear",
                           "Stripe", "Vercel", "Supabase"][: 12 - len(competitors)]
        ),
        "example_pains": [
            f"Stuck on: {pain_quote[:100] or 'finding alternatives that actually work for our team'}",
            "Anyone else seeing pricing creep at renewal time?",
            "We rolled our own internal tool — is this insane or normal?",
            "What's the right time to switch from a no-code stack?",
            "Looking for someone who has actually shipped this end-to-end",
        ],
    }
