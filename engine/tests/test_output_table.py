"""Tests for render_table() — the inline Claude Code surface introduced in 9.7."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import output  # noqa: E402


def _surface(idx: int, tier: int, sub: str, title: str, score: int = 5,
             vet: dict | None = None) -> dict:
    """Construct a minimal surface dict matching what cli.py builds."""
    return {
        "post": {
            "id": f"post_{idx}", "title": title, "subreddit": sub,
            "score": score, "num_comments": 0, "created_utc": 1700000000,
            "url": f"https://reddit.com/r/{sub}/comments/post_{idx}/",
        },
        "sub": {"name": sub, "tier": tier, "saturation": None},
        "blog_matches": [],
        "vet": vet or {},
        "score_internal": 100.0,
        "pain_summary": title,
        "fit_summary": f"r/{sub}",
    }


def test_render_table_empty_returns_empty_day_message():
    out = output.render_table([])
    assert "No qualifying posts today" in out


def test_render_table_renders_tier_1_header_and_row():
    surfaces = [_surface(1, 1, "RevOps", "HubSpot is dropping us", 47)]
    out = output.render_table(surfaces)
    assert "TIER 1, daily-scan (1)" in out
    assert "| 1 |" in out
    assert "r/RevOps" in out
    assert "HubSpot is dropping us" in out
    assert "[open](https://reddit.com/r/RevOps/" in out
    assert "47" in out  # upvote count


def test_render_table_separates_tiers():
    surfaces = [
        _surface(1, 1, "RevOps", "Tier 1 post"),
        _surface(2, 2, "SaaS", "Tier 2 post"),
    ]
    out = output.render_table(surfaces)
    assert "TIER 1, daily-scan (1)" in out
    assert "TIER 2, opportunistic (1)" in out
    # Tier 2 row gets index offset by tier 1 count
    assert "| 2 |" in out


def test_render_table_truncates_long_titles():
    long_title = "x" * 200
    surfaces = [_surface(1, 1, "RevOps", long_title)]
    out = output.render_table(surfaces)
    assert "..." in out
    # The full 200-char title should not appear
    assert "x" * 200 not in out


def test_render_table_escapes_pipe_in_title():
    """Pipe in title would break the markdown table format."""
    surfaces = [_surface(1, 1, "RevOps", "Vendor X | competitor Y")]
    out = output.render_table(surfaces)
    # The pipe inside the title must be escaped, not corrupt the row
    assert r"Vendor X \|" in out


def test_render_table_includes_op_score_when_vet_present():
    surfaces = [
        _surface(1, 1, "RevOps", "Post",
                 vet={"account_age_days": 730, "comment_karma": 4200,
                      "wrong_audience_fraction": 0.12})
    ]
    out = output.render_table(surfaces)
    # Compact form: drops verbose labels for column reuse
    assert "2y/" in out or "2y" in out


def test_render_table_includes_dropped_summary():
    surfaces = [_surface(1, 1, "RevOps", "Post")]
    out = output.render_table(surfaces, dropped_counts={"low_karma": 3})
    assert "1 surfaces today" in out
    assert "Dropped at gate" in out
    assert "3 low_karma" in out


# ─── --max-surfaces selector test ──────────────────────────────────────

def test_select_daily_respects_max_surfaces_override():
    """Power-user override beats weights.yml hard_ceiling."""
    from subscope.cli import _select_daily  # noqa: E402

    candidates = [
        {"post": {"score_internal": 100.0 - i, "title": f"t{i}", "id": f"p{i}"},
         "sub": {"name": f"sub{i}", "tier": 1}, "blog_matches": []}
        for i in range(20)
    ]
    weights = {
        "daily_output": {
            "hard_ceiling": 5, "minimum": 0,
            "tier1_per_sub_cap": 2, "tier2_per_sub_cap": 1,
        }
    }
    # Default: clipped to hard_ceiling=5
    out_default = _select_daily(candidates, [], weights, daily_cap=5)
    assert len(out_default) == 5

    # Override: should accept 15
    out_override = _select_daily(candidates, [], weights, daily_cap=5, max_surfaces=15)
    assert len(out_override) == 15
