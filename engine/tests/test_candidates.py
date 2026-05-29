"""SS-110: judge-first candidate emission + brand_anchor-aware brand match.

The engine stops being the relevance decider: with --candidates it emits every
fetched post that clears the ABSOLUTE rejects, each carrying deterministic
features (brand match driven by the user's brand_anchor), for the skill-layer
offer-relevance judge. These tests pin that contract and the brand fallback.
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope import cli  # noqa: E402
from subscope.lib import reddit, store, score  # noqa: E402


# ─── names_relevant_brand (pure) ───────────────────────────────────────

def test_names_relevant_brand_uses_supplied_list():
    brands = ["Dentrix", "Eaglesoft", "Open Dental"]
    assert score.names_relevant_brand("Dentrix keeps crashing", "", brands)
    assert score.names_relevant_brand("", "we run Open Dental in our clinic", brands)
    assert not score.names_relevant_brand("our PMS is slow", "no brand here", brands)


def test_names_relevant_brand_falls_back_to_saas_when_empty():
    # None or [] -> built-in SAAS_BRANDS, preserving default-profile behavior.
    assert score.names_relevant_brand("HubSpot is too expensive", "", None)
    assert score.names_relevant_brand("HubSpot is too expensive", "", [])
    # A dental brand is NOT in SAAS_BRANDS, so the fallback must not match it.
    assert not score.names_relevant_brand("Dentrix is slow", "", None)


def test_names_specific_saas_wrapper_preserved():
    assert score.names_specific_saas("calendly link broke", "") is True
    assert score.names_specific_saas("my dental software", "") is False


# ─── candidate emission via cmd_fetch_score(--candidates) ──────────────

@pytest.fixture
def _cfg(tmp_path, monkeypatch):
    cfgd = tmp_path / "cfg"
    cfgd.mkdir()
    (cfgd / "subreddits.yml").write_text(yaml.safe_dump({"subreddits": [
        {"name": "Dentistry", "tier": 1, "bucket": "operator", "weight": 1.0},
    ]}))
    (cfgd / "keywords.yml").write_text(yaml.safe_dump({
        "shared": ["dental practice management"], "operator": [], "builder": [],
    }))
    (cfgd / "weights.yml").write_text(yaml.safe_dump({
        "tier1_gates": {"post_age_hours": 48, "comment_ceiling": 100, "pain_keywords_min": 1},
        "tier2_gates": {"post_age_hours": 72, "pain_keywords_min": 1, "pain_keywords_min_wide_open": 1},
        "daily_output": {"default_target": 10},
        "cooling": {"default_minutes": 0},
        "judge_candidates": {"max": 5},
        "scoring": {},
    }))
    (cfgd / "brand-anchor.yml").write_text(yaml.safe_dump({"brand_anchor": ["Dentrix", "Eaglesoft"]}))
    monkeypatch.setenv("SUBSCOPE_CONFIG", str(cfgd))
    monkeypatch.setenv("SUBSCOPE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "CONFIG_DIR", cfgd)
    store.bootstrap()
    reddit.reset_fetch_stats()
    reddit._last_request_at = 0.0
    monkeypatch.setattr(reddit, "_sleep", lambda s: None)
    return cfgd


def _post(pid, title, body="", **over):
    base = 1780000000
    d = {
        "id": pid, "subreddit": "Dentistry", "title": title,
        "url": f"https://reddit.com/r/Dentistry/comments/{pid}/x/",
        "canonical_url": f"https://reddit.com/comments/{pid}/",
        "author": "op", "created_utc": base, "score": 0, "num_comments": 0,
        "body": body, "upvote_ratio": None, "removed": False, "locked": False,
        "over_18": False, "is_crosspost": False,
    }
    d.update(over)
    return d


def _run(monkeypatch, posts, now=1780000600, **kw):
    monkeypatch.setattr(reddit, "fetch_delta", lambda sub, cur, max_limit=50: list(posts))
    monkeypatch.setattr(score, "now_utc", lambda: now)
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.cmd_fetch_score(no_slack=True, no_enrich=True, **kw)
    return json.loads(buf.getvalue().strip())


def test_candidates_emitted_with_features(_cfg, monkeypatch):
    posts = [_post("p1", "Dentrix keeps crashing, looking for alternatives?",
                   "our dental practice management keeps failing")]
    out = _run(monkeypatch, posts, candidates=True)
    cands = out["candidates"]
    assert len(cands) == 1
    c = cands[0]
    assert c["id"] == "p1"
    assert c["names_brand"] is True          # Dentrix is in the user's brand_anchor
    assert c["kw_hits"] >= 1                  # "dental practice management"
    assert c["question_intent"] is True
    assert c["engagement_available"] is False  # RSS carries no upvote_ratio
    assert "body" in c and "title" in c and "url" in c


def test_brand_feature_uses_brand_anchor_not_hardcoded_saas(_cfg, monkeypatch):
    # A post naming the user's competitor must read names_brand=True even though
    # that brand is absent from the hardcoded SAAS_BRANDS list. This is the bug
    # the whole judge-first recall fix turns on.
    posts = [_post("d1", "Eaglesoft server down again, any cloud option?",
                   "dental practice management")]
    out = _run(monkeypatch, posts, candidates=True)
    assert out["candidates"][0]["names_brand"] is True


def test_candidates_excludes_absolute_rejects(_cfg, monkeypatch):
    posts = [
        _post("ok1", "Dentrix crashing, any alternative?", "dental practice management pain"),
        _post("nsfw", "explicit thing", over_18=True),
        _post("vendor", "I built a dental scheduling tool", "introducing my case study"),
    ]
    out = _run(monkeypatch, posts, candidates=True)
    ids = {c["id"] for c in out["candidates"]}
    assert "ok1" in ids
    assert "nsfw" not in ids       # absolute reject (nsfw_post)
    assert "vendor" not in ids     # absolute reject (vendor_content)


def test_candidates_absent_without_flag(_cfg, monkeypatch):
    posts = [_post("p1", "Dentrix crashing?", "dental practice management")]
    out = _run(monkeypatch, posts)
    assert "candidates" not in out


def test_candidates_cap_respected(_cfg, monkeypatch):
    # weights judge_candidates.max = 5; emit 8 eligible posts.
    posts = [_post(f"p{i}", "Dentrix crashing, alternative?", "dental practice management")
             for i in range(8)]
    out = _run(monkeypatch, posts, candidates=True)
    assert out["candidate_total"] == 8
    assert out["candidate_count"] == 5
    assert len(out["candidates"]) == 5
    # internal sort key must not leak into the contract
    assert all("_rank" not in c for c in out["candidates"])
