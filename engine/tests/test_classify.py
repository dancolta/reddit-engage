"""Tests for the bulk LLM classifier abstraction (post-2.8 refactor).

The classifier is now SDK-only — the dead `claude_cli_bare` provider was
removed. Interactive subscription-powered classification lives in the
`/reddit-engage:judge` SKILL, not this module.

We mock the SDK at module-import level (per test_classify imports anthropic
lazily inside _call_anthropic_native).
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

    with patch.object(classify, "detect_provider", return_value="anthropic_native"):
        result = classify.classify(make_post())

    assert result is not None
    assert result["intent"] == "pain_post"
    assert result["fit_score"] == 9
    assert result["competitor_mentioned"] == "HubSpot"


def test_sdk_call_uses_prompt_cache(monkeypatch):
    """Anthropic-best-practices check: system prompt MUST be marked cacheable
    or repeat calls within a daily run pay full price."""
    mock_block = MagicMock(type="text", text=json.dumps(VALID_VERDICT))
    mock_resp = MagicMock(content=[mock_block])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic_module)

    with patch.object(classify, "detect_provider", return_value="anthropic_native"):
        classify.classify(make_post())

    call_kwargs = mock_client.messages.create.call_args.kwargs
    system_blocks = call_kwargs.get("system")
    assert isinstance(system_blocks, list)
    assert any(
        block.get("cache_control", {}).get("type") == "ephemeral"
        for block in system_blocks
    ), "System prompt must be cache-tagged for 90% repeat-call cost reduction"


def test_max_tokens_capped(monkeypatch):
    """Cost discipline: max_tokens must be set and small (~200)."""
    mock_block = MagicMock(type="text", text=json.dumps(VALID_VERDICT))
    mock_resp = MagicMock(content=[mock_block])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp
    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic_module)

    with patch.object(classify, "detect_provider", return_value="anthropic_native"):
        classify.classify(make_post())
    assert mock_client.messages.create.call_args.kwargs["max_tokens"] <= 500


def test_markdown_wrapped_json_is_recovered():
    wrapped = "```json\n" + json.dumps(VALID_VERDICT) + "\n```"
    parsed = classify._parse_json_safely(wrapped)
    assert parsed["intent"] == "pain_post"


def test_validate_rejects_missing_fields():
    incomplete = {"intent": "pain_post", "fit_score": 5}
    assert classify._validate(incomplete) is None


def test_validate_rejects_out_of_range_fit_score():
    bad = dict(VALID_VERDICT)
    bad["fit_score"] = 15
    assert classify._validate(bad) is None
    bad2 = dict(VALID_VERDICT)
    bad2["fit_score"] = -1
    assert classify._validate(bad2) is None


def test_validate_coerces_string_fit_score():
    s_v = dict(VALID_VERDICT)
    s_v["fit_score"] = "9"
    result = classify._validate(s_v)
    assert result["fit_score"] == 9


def test_detect_provider_no_api_key_returns_disabled(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("REDDIT_ENGAGE_CONFIG", "/tmp/nonexistent-classify-test")
    assert classify.detect_provider() == "disabled"


def test_status_returns_diagnostic():
    """status() must never raise — it's used by `reddit-engage status`."""
    result = classify.status()
    assert "provider" in result
    assert "mode" in result
    assert "interactive_judge_available" in result
    assert result["interactive_judge_available"] is True  # always


def test_load_prompt_is_public():
    """Public so /reddit-engage:judge skill can reuse the exact same prompt."""
    prompt = classify.load_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 100  # not the fallback stub


def test_format_user_message_is_public():
    """Public so judge skill formats input identically to bulk path."""
    msg = classify.format_user_message(make_post())
    assert "subreddit:" in msg
    assert "HubSpot" in msg


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
