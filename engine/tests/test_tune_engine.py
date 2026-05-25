"""Tests for tune_engine: mark parsing + weight back-prop + delta readout."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subseek.lib import tune_engine  # noqa: E402


def test_parse_marks_simple():
    marks = tune_engine.parse_marks("1g 2g 3b 4m 5g 6b 7g 8m 9g 10b")
    assert marks == {1: "g", 2: "g", 3: "b", 4: "m", 5: "g",
                     6: "b", 7: "g", 8: "m", 9: "g", 10: "b"}


def test_parse_marks_tolerant_to_whitespace():
    marks = tune_engine.parse_marks("1g, 2g,  3b,4m  5g")
    assert marks[1] == "g"
    assert marks[3] == "b"
    assert marks[5] == "g"


def test_parse_marks_missing_default_to_meh():
    marks = tune_engine.parse_marks("1g 3b")
    # 2, 4-10 should all be 'm'
    assert marks[2] == "m"
    assert marks[4] == "m"
    assert marks[10] == "m"


def test_parse_marks_ignores_out_of_range():
    marks = tune_engine.parse_marks("11g 12b 1g", expected_count=10)
    # 11 and 12 ignored, 1 captured
    assert marks.get(1) == "g"
    assert 11 not in marks
    assert 12 not in marks


def test_apply_marks_nudges_weights_correctly(tmp_path):
    subs = {
        "subreddits": [
            {"name": "RevOps", "tier": 1, "bucket": "operator", "weight": 1.0},
            {"name": "SaaS", "tier": 2, "bucket": "operator", "weight": 1.0},
            {"name": "Entrepreneur", "tier": 3, "bucket": "operator", "weight": 0.0},
        ]
    }
    subs_path = tmp_path / "subreddits.yml"
    subs_path.write_text(yaml.safe_dump(subs))

    surfaces = [
        {"id": "p1", "subreddit": "RevOps", "title": "good"},
        {"id": "p2", "subreddit": "RevOps", "title": "good"},
        {"id": "p3", "subreddit": "SaaS", "title": "bad"},
        {"id": "p4", "subreddit": "SaaS", "title": "bad"},
    ]
    marks = {1: "g", 2: "g", 3: "b", 4: "b"}
    result = tune_engine.apply_marks_to_subs(surfaces, marks, subs_path)

    # Reload and verify weights moved
    after = yaml.safe_load(subs_path.read_text())
    by_name = {s["name"]: s for s in after["subreddits"]}
    assert by_name["RevOps"]["weight"] > 1.0    # boosted by 2 good marks
    assert by_name["SaaS"]["weight"] < 1.0      # cut by 2 bad marks

    # Changes list captured the deltas
    changes_by_name = {c["name"]: c for c in result["changes"]}
    assert "RevOps" in changes_by_name
    assert changes_by_name["RevOps"]["good_marks"] == 2
    assert "SaaS" in changes_by_name
    assert changes_by_name["SaaS"]["bad_marks"] == 2


def test_apply_marks_respects_floor():
    """Even with 10 bad marks, weight never drops below WEIGHT_FLOOR."""
    surfaces = [{"id": f"p{i}", "subreddit": "BadSub", "title": "x"} for i in range(10)]
    marks = {i: "b" for i in range(1, 11)}
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as tmpdir:
        subs_path = pathlib.Path(tmpdir) / "subreddits.yml"
        subs_path.write_text(yaml.safe_dump({"subreddits": [
            {"name": "BadSub", "tier": 1, "bucket": "operator", "weight": 0.3}
        ]}))
        tune_engine.apply_marks_to_subs(surfaces, marks, subs_path)
        after = yaml.safe_load(subs_path.read_text())
        weight = after["subreddits"][0]["weight"]
    assert weight >= tune_engine.WEIGHT_FLOOR
    # Confirm it dropped though
    assert weight < 0.3


def test_apply_marks_doesnt_delete_user_added_sub(tmp_path):
    """User added a sub manually with weight 1.5. /tune nudges down but
    never silently removes it from the YAML."""
    subs = {"subreddits": [
        {"name": "MyUserSub", "tier": 1, "bucket": "operator", "weight": 1.5},
    ]}
    subs_path = tmp_path / "subreddits.yml"
    subs_path.write_text(yaml.safe_dump(subs))

    surfaces = [{"id": f"p{i}", "subreddit": "MyUserSub", "title": "x"} for i in range(10)]
    marks = {i: "b" for i in range(1, 11)}
    tune_engine.apply_marks_to_subs(surfaces, marks, subs_path)

    after = yaml.safe_load(subs_path.read_text())
    names = [s["name"] for s in after["subreddits"]]
    assert "MyUserSub" in names, "user-added sub must NEVER be deleted by /tune"


def test_unknown_sub_in_skipped_list(tmp_path):
    """Surface mentions a sub that's not in subreddits.yml → goes to `skipped`."""
    subs = {"subreddits": [
        {"name": "RevOps", "tier": 1, "bucket": "operator", "weight": 1.0},
    ]}
    subs_path = tmp_path / "subreddits.yml"
    subs_path.write_text(yaml.safe_dump(subs))

    surfaces = [
        {"id": "p1", "subreddit": "UnknownSub", "title": "x"},
    ]
    marks = {1: "g"}
    result = tune_engine.apply_marks_to_subs(surfaces, marks, subs_path)
    assert "unknownsub" in result["skipped"]


def test_format_deltas_readout_shows_top_5():
    changes = [
        {"name": f"Sub{i}", "old_weight": 1.0, "new_weight": 1.0 + 0.1 * (10 - i),
         "good_marks": 2, "bad_marks": 0, "meh_marks": 0}
        for i in range(8)
    ]
    output = tune_engine.format_deltas_readout(changes, round_num=1, total_rounds=3)
    # Top 5 only
    assert "Sub0" in output
    assert "Sub4" in output
    assert "Sub5" not in output  # 6th-largest, not shown
    assert "Round 2 of 3" in output


def test_format_deltas_readout_final_round():
    changes = [{"name": "X", "old_weight": 1.0, "new_weight": 1.2,
                "good_marks": 1, "bad_marks": 0, "meh_marks": 0}]
    output = tune_engine.format_deltas_readout(changes, round_num=3, total_rounds=3)
    assert "Tuning complete" in output


def test_format_deltas_readout_no_changes():
    output = tune_engine.format_deltas_readout([], round_num=1)
    assert "no significant changes" in output


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
