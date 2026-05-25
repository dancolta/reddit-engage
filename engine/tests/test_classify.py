"""Tests for the LLM classifier abstraction.

We mock the SDK and CLI subprocess paths — no live API calls.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reddit_engage.lib import classify  # noqa: E402


VALID_VERDICT = {
    "intent": "pain_post",
    "buyer_stage": "ready",
    "sentiment": "negative",
    "competitor_mentioned": "HubSpot",
    "fit_score": 9,
    "suggested_angle": "ask what 3 features they actually use",
}


def make_post():
    return {
        "subreddit": "RevOps",
        "title": "HubSpot renewal is 28% higher, looking for alternatives",
        "body": "We're paying $890/seat/month and they're jacking it up. Done.",
    }


def test_disabled_provider_returns_none():
    with patch.object(classify, "detect_provider", return_value="disabled"):
        assert classify.classify(make_post()) is None


def test_anthropic_sdk_success(monkeypatch):
    """Mock the SDK call; verify verdict is parsed + validated."""
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = json.dumps(VALID_VERDICT)
    mock_resp = MagicMock()
    mock_resp.content = [mock_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic_module)

    with patch.object(classify, "detect_provider", return_value="anthropic_api"):
        result = classify.classify(make_post())

    assert result is not None
    assert result["intent"] == "pain_post"
    assert result["fit_score"] == 9
    assert result["competitor_mentioned"] == "HubSpot"


def test_markdown_wrapped_json_is_recovered():
    """Real LLMs sometimes wrap output in ```json ... ```. Parser must handle it."""
    wrapped = "```json\n" + json.dumps(VALID_VERDICT) + "\n```"
    parsed = classify._parse_json_safely(wrapped)
    assert parsed["intent"] == "pain_post"


def test_validate_rejects_missing_fields():
    """Schema validation: missing required field → None (caller falls through to regex)."""
    incomplete = {"intent": "pain_post", "fit_score": 5}  # missing buyer_stage, sentiment, etc.
    assert classify._validate(incomplete) is None


def test_validate_rejects_out_of_range_fit_score():
    bad = dict(VALID_VERDICT)
    bad["fit_score"] = 15
    assert classify._validate(bad) is None
    bad2 = dict(VALID_VERDICT)
    bad2["fit_score"] = -1
    assert classify._validate(bad2) is None


def test_validate_coerces_string_fit_score():
    """Some models return '9' instead of 9 — coerce silently."""
    s_v = dict(VALID_VERDICT)
    s_v["fit_score"] = "9"
    result = classify._validate(s_v)
    assert result["fit_score"] == 9


def test_cli_path_success(monkeypatch, tmp_path):
    """Mock subprocess + verify --bare flag is in the args (cost discipline)."""
    envelope = {
        "is_error": False,
        "result": json.dumps(VALID_VERDICT),
    }
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = json.dumps(envelope)
    mock_run.stderr = ""

    with patch.object(classify.shutil, "which", return_value="/usr/bin/claude"):
        with patch.object(classify.subprocess, "run", return_value=mock_run) as m_sub:
            with patch.object(classify, "detect_provider", return_value="claude_cli_bare"):
                result = classify.classify(make_post())

    assert result is not None
    assert result["intent"] == "pain_post"
    # Critical: --bare must be in the args, or per-call cost is ~$0.17
    args = m_sub.call_args.args[0]
    assert "--bare" in args, "Without --bare, classification costs are unsustainable"
    assert "--max-budget-usd" in args, "Per-call budget cap is required"


def test_cli_error_returns_none():
    """CLI returns is_error=True → None (caller falls through to regex)."""
    envelope = {"is_error": True, "result": "Not logged in"}
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = json.dumps(envelope)

    with patch.object(classify.shutil, "which", return_value="/usr/bin/claude"):
        with patch.object(classify.subprocess, "run", return_value=mock_run):
            with patch.object(classify, "detect_provider", return_value="claude_cli_bare"):
                result = classify.classify(make_post())
    assert result is None


def test_detect_provider_no_api_key_no_cli(monkeypatch):
    """Hardest path: nothing available → 'disabled' (never raises)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("REDDIT_ENGAGE_CONFIG", "/tmp/nonexistent-rev2-test")
    with patch.object(classify.shutil, "which", return_value=None):
        assert classify.detect_provider() == "disabled"


def test_status_returns_diagnostic():
    """status() must never raise — it's used by `reddit-engage status` for triage."""
    result = classify.status()
    assert "provider" in result
    assert "has_api_key" in result
    assert "claude_cli_in_path" in result


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
