"""Tests for the bulk LLM classifier (post-9.6 refactor).

Single code path: OpenAI-compatible SDK. Works with Anthropic (via /openai/v1),
OpenAI, Groq, OpenRouter, Together, Fireworks, local Ollama, etc. The
`_call_anthropic_native` path was removed in 9.6 (Anthropic's /openai/v1
makes a separate Anthropic SDK redundant for our usage).

Interactive subscription-powered classification lives in the `/subscope-judge`
SKILL, not this module.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import classify  # noqa: E402


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


def _build_openai_mock(monkeypatch, verdict_dict):
    """Wire up a fake openai SDK that returns the given verdict."""
    fake_choice = SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(verdict_dict))
    )
    fake_resp = SimpleNamespace(choices=[fake_choice])
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp
    fake_openai = MagicMock()
    fake_openai.OpenAI.return_value = mock_client
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    return mock_client


def test_disabled_provider_returns_none():
    with patch.object(classify, "detect_provider", return_value="disabled"):
        assert classify.classify(make_post()) is None


def test_openai_compat_sdk_success(monkeypatch):
    """Happy path: a properly-shaped JSON response gets parsed + validated."""
    _build_openai_mock(monkeypatch, VALID_VERDICT)
    with patch.object(
        classify, "_resolve_llm_endpoint",
        return_value=("sk-test", "https://api.openai.com/v1", "gpt-4o-mini"),
    ), patch.object(classify, "detect_provider", return_value="openai_compatible"):
        result = classify.classify(make_post())

    assert result is not None
    assert result["intent"] == "pain_post"
    assert result["fit_score"] == 9
    assert result["competitor_mentioned"] == "HubSpot"


def test_max_tokens_capped(monkeypatch):
    """Cost discipline: max_tokens must be set and small (~200)."""
    mock_client = _build_openai_mock(monkeypatch, VALID_VERDICT)
    with patch.object(
        classify, "_resolve_llm_endpoint",
        return_value=("sk-test", "https://api.openai.com/v1", "gpt-4o-mini"),
    ), patch.object(classify, "detect_provider", return_value="openai_compatible"):
        classify.classify(make_post())
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["max_tokens"] <= 500


def test_system_prompt_in_messages(monkeypatch):
    """OpenAI-compat layer puts the system prompt in messages[0] (role=system).
    Prompt caching is provider-specific and lives in v0.2 — for now we just
    verify the prompt is sent."""
    mock_client = _build_openai_mock(monkeypatch, VALID_VERDICT)
    with patch.object(
        classify, "_resolve_llm_endpoint",
        return_value=("sk-test", "https://api.openai.com/v1", "gpt-4o-mini"),
    ), patch.object(classify, "detect_provider", return_value="openai_compatible"):
        classify.classify(make_post())
    msgs = mock_client.chat.completions.create.call_args.kwargs["messages"]
    assert msgs[0]["role"] == "system"
    assert len(msgs[0]["content"]) > 100  # not the fallback stub


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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("SUBSCOPE_CONFIG", "/tmp/nonexistent-classify-test")
    assert classify.detect_provider() == "disabled"


def test_status_returns_diagnostic():
    """status() must never raise — it's used by `subscope status`."""
    result = classify.status()
    assert "provider" in result
    assert "mode" in result
    assert "interactive_judge_available" in result
    assert result["interactive_judge_available"] is True  # always


def test_load_prompt_is_public():
    """Public so /subscope-judge skill can reuse the exact same prompt."""
    prompt = classify.load_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 100  # not the fallback stub


def test_format_user_message_is_public():
    """Public so judge skill formats input identically to bulk path."""
    msg = classify.format_user_message(make_post())
    assert "subreddit:" in msg
    assert "HubSpot" in msg


# ─── F2 SSRF allowlist tests ───────────────────────────────────────────

def test_ssrf_blocks_aws_metadata_ip():
    """The exact SSRF target this guard was added to defuse."""
    # AWS metadata is at http://169.254.169.254. Either layer can reject:
    # the http-on-public-host check OR the link-local-IP check. Both count.
    try:
        classify._validate_base_url("http://169.254.169.254/latest/")
    except ValueError:
        # Also try with https — should still be rejected by the link-local IP check
        try:
            classify._validate_base_url("https://169.254.169.254/latest/")
        except ValueError as e:
            assert "private" in str(e).lower() or "link-local" in str(e).lower()
            return
        raise AssertionError("https + link-local IP must also be rejected")
    raise AssertionError("AWS metadata IP must be rejected")


def test_ssrf_blocks_rfc1918_private_ip():
    for ip in ("http://10.0.0.1/", "http://192.168.1.1/", "http://172.16.0.1/"):
        try:
            classify._validate_base_url(ip)
        except ValueError:
            continue
        raise AssertionError(f"Private IP {ip} must be rejected")


def test_ssrf_allows_localhost_for_ollama():
    """Local LLM use case must continue to work."""
    classify._validate_base_url("http://localhost:11434/v1")
    classify._validate_base_url("http://127.0.0.1:11434/v1")


def test_ssrf_blocks_http_for_remote_hosts():
    """http:// for non-localhost is rejected (downgrade attack guard)."""
    try:
        classify._validate_base_url("http://api.openai.com/v1")
    except ValueError as e:
        assert "http://" in str(e) or "localhost" in str(e).lower()
        return
    raise AssertionError("http:// to public host must be rejected")


def test_ssrf_allows_https_to_known_providers():
    for url in (
        "https://api.openai.com/v1",
        "https://api.anthropic.com/v1/",
        "https://api.groq.com/openai/v1",
        "https://openrouter.ai/api/v1",
    ):
        classify._validate_base_url(url)  # must not raise


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
