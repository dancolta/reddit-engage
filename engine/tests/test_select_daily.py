"""Tests for PIPE-1: _select_daily widening (backfill cap relax + freshness floor).

These tests exercise the daily-selection logic in cli._select_daily directly
with synthetic candidates. No Reddit network, no SQLite — pure function tests.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.cli import _select_daily  # noqa: E402


NOW = int(time.time())


def _candidate(post_id: str, sub_name: str, tier: int, score: float,
               created_utc: int | None = None) -> dict:
    return {
        "post": {
            "id": post_id,
            "title": f"title_{post_id}",
            "score_internal": score,
            "created_utc": created_utc if created_utc is not None else NOW - 7200,
            "score": 5,
            "num_comments": 1,
        },
        "sub": {"name": sub_name, "tier": tier},
        "blog_matches": [],
    }


def _weights(*, minimum=5, t1_cap=2, t2_cap=2, backfill_bonus=1,
             fresh_enabled=True, fresh_max_age_h=24, fresh_max_promoted=3,
             hard_ceiling=12) -> dict:
    return {
        "daily_output": {
            "hard_ceiling": hard_ceiling,
            "minimum": minimum,
            "tier1_per_sub_cap": t1_cap,
            "tier2_per_sub_cap": t2_cap,
            "backfill_sub_cap_bonus": backfill_bonus,
        },
        "freshness_floor": {
            "enabled": fresh_enabled,
            "max_age_hours": fresh_max_age_h,
            "max_promoted": fresh_max_promoted,
        },
    }


# ─── Backfill: relax sub cap during backfill phase ─────────────────────

def test_select_daily_backfill_when_below_minimum():
    """When gate survivors are < minimum, backfill from near_miss_pool kicks in.
    The relaxed sub cap (+1 during backfill) is the bug-fix from PIPE-1."""
    # 2 Tier 2 gate survivors from 2 different subs
    gate = [
        _candidate("g1", "sales", 2, score=100.0),
        _candidate("g2", "ops", 2, score=90.0),
    ]
    # 5 near-miss from sales (already at t2_cap=2 after the survivor) + 1 from a new sub
    near = [
        _candidate(f"n{i}", "sales", 2, score=80.0 - i) for i in range(5)
    ] + [
        _candidate("n6", "marketing", 2, score=50.0),
    ]
    out = _select_daily(gate, near, _weights(minimum=5), daily_cap=10)
    # We must hit minimum=5. Without backfill_sub_cap_bonus, sales would only
    # get 2 (= cap), so we'd be stuck at 3. With +1, sales can backfill +1 more.
    assert len(out) >= 5, f"backfill failed: only {len(out)} surfaces"


def test_select_daily_floor_enforced_at_minimum():
    gate = [
        _candidate("g1", "sales", 2, score=100.0),
    ]
    near = [_candidate(f"n{i}", f"sub{i}", 2, score=70.0 - i) for i in range(10)]
    out = _select_daily(gate, near, _weights(minimum=5), daily_cap=10)
    assert len(out) >= 5
    # At least one backfilled entry must be flagged
    assert any(c.get("backfilled") for c in out)


def test_backfill_respects_hard_ceiling():
    """Backfill must NOT exceed hard_ceiling even if minimum is misconfigured."""
    gate = [_candidate("g1", "sales", 2, score=100.0)]
    near = [_candidate(f"n{i}", f"sub{i}", 2, score=70.0 - i) for i in range(50)]
    out = _select_daily(gate, near, _weights(minimum=20, hard_ceiling=8), daily_cap=10)
    assert len(out) <= 8


# ─── Freshness floor: promote <24h near-misses ─────────────────────────

def test_freshness_floor_promotes_under_24h():
    """A 2h-old near-miss post must surface even when it failed keyword density."""
    gate = [_candidate("g1", "sales", 2, score=100.0)]
    fresh = _candidate("fresh1", "newsub", 2, score=20.0, created_utc=NOW - 2 * 3600)
    stale = _candidate("stale1", "oldsub", 2, score=50.0, created_utc=NOW - 48 * 3600)
    out = _select_daily(gate, [fresh, stale],
                        _weights(minimum=3, fresh_enabled=True, fresh_max_promoted=3),
                        daily_cap=10)
    surfaced_ids = {c["post"]["id"] for c in out}
    assert "fresh1" in surfaced_ids, "fresh <24h post should be promoted"
    # And it should be tagged for telemetry
    fresh_chosen = next(c for c in out if c["post"]["id"] == "fresh1")
    assert fresh_chosen.get("freshness_promoted") is True


def test_freshness_floor_respects_max_promoted():
    """max_promoted caps the number of freshness-promoted surfaces."""
    gate = [_candidate("g1", "sales", 2, score=100.0)]
    near = [
        _candidate(f"f{i}", f"sub{i}", 2, score=20.0,
                   created_utc=NOW - (i + 1) * 3600)  # all under 24h
        for i in range(8)
    ]
    out = _select_daily(gate, near,
                        _weights(minimum=3, fresh_enabled=True, fresh_max_promoted=2),
                        daily_cap=10)
    promoted = [c for c in out if c.get("freshness_promoted")]
    assert len(promoted) <= 2


def test_freshness_floor_disabled_by_config():
    """When freshness_floor.enabled is False, no posts are promoted via that path."""
    gate = [_candidate("g1", "sales", 2, score=100.0)]
    fresh = _candidate("fresh1", "newsub", 2, score=20.0, created_utc=NOW - 2 * 3600)
    out = _select_daily(gate, [fresh],
                        _weights(minimum=1, fresh_enabled=False),
                        daily_cap=10)
    # Backfill can still surface it (no freshness_promoted tag), but the
    # freshness_promoted flag should be absent
    for c in out:
        assert not c.get("freshness_promoted")


# ─── Replay test: Dan's actual live-run dropped_counts shape ───────────

def test_select_daily_replay_live_drop_distribution():
    """Replay test on the exact shape of Dan's live run: 2 Tier 2 gate survivors
    + a near_miss_pool roughly matching the 75-drop distribution. Must surface
    at least 5 (not 2)."""
    # 2 gate-passing Tier 2 from 2 distinct subs (like the live run)
    gate = [
        _candidate("g_accounting", "Accounting", 2, score=85.0),
        _candidate("g_automation", "automation", 2, score=80.0),
    ]
    # 36 keyword-density drops spread across 6 subs (the bulk of the near-miss pool)
    near = []
    for i in range(36):
        sub = f"sub{i % 6}"
        near.append(_candidate(f"kw{i}", sub, 2, score=60.0 - (i * 0.5),
                               created_utc=NOW - (i % 12 + 1) * 3600))
    # 7 vendor-content drops (NOT in near_miss_pool per cli.py — vendor IS reject)
    # 9 tier3_quarantined (also rejected before near_miss)
    # 20 author_vet drops (also rejected)
    # net: ~36 near-miss candidates is realistic
    out = _select_daily(gate, near, _weights(minimum=5), daily_cap=10)
    assert len(out) >= 5, f"replay only surfaced {len(out)}, expected >= 5"


# ─── No-op path: empty inputs do not crash ─────────────────────────────

def test_select_daily_empty_inputs():
    out = _select_daily([], [], _weights(minimum=5), daily_cap=10)
    assert out == []


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
