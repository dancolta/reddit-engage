"""LLM-backed intent classifier for surfaced Reddit posts.

Returns a structured verdict per post:
    {
        "intent":              "pain_post" | "question" | "vendor_content" | "neutral",
        "buyer_stage":         "unaware" | "considering" | "evaluating" | "ready" | "post_purchase",
        "sentiment":           "positive" | "neutral" | "negative",
        "competitor_mentioned": str | null,
        "fit_score":           int 0-10,
        "suggested_angle":     str   (short reply angle, <120 chars)
    }

## Three-tier classification model

`reddit-engage` does NOT bulk-classify every post by default. The default
daily run uses regex + author-vet + tier gates only (zero LLM cost, zero
auth requirement). LLM classification is opt-in per use case:

1. **`/reddit-engage:run` (default)** — regex-only gate. No classifier call.
   Day-1 install works without any keys.

2. **`/reddit-engage:judge <surface-id>`** — interactive, Claude-driven via
   your Claude Code subscription. Reads a single surface, runs the same
   classification prompt, returns verdict + reply angle. Free under
   subscription; cost lives with `claude` Code session, not this module.

3. **Bulk LLM (opt-in, via `ANTHROPIC_API_KEY`)** — `classify(post)` in
   this module calls the Anthropic SDK directly. Prompt-cached at
   ~$0.0005/post with Haiku 4.5. Activated when `cmd_fetch_score` finds
   `ANTHROPIC_API_KEY` in env — every regex-passing post gets graded.
   At 5K posts/day = ~$0.50/day.

## Why no `claude` CLI subprocess path

PLAN.md originally proposed using `claude -p` subprocess for the
"subscription-as-default" case. Measured cost: ~$0.17/call because the
CLI in non-bare mode loads the full Claude Code session context (~136K
tokens of CLAUDE.md / hooks / plugin sync) for every invocation. At
volume that's $850/day — unusable.

`claude --bare -p` strips the context BUT enforces `ANTHROPIC_API_KEY`
auth (OAuth/keychain are explicitly blocked in bare mode). So there's no
viable subprocess path that uses subscription auth at scale.

The subscription's natural use is **interactive judgment** — one call at
a time, human-driven, in chat. That's the `/reddit-engage:judge` skill
(skills/judge/SKILL.md). Bulk classification is what API keys are for.

## Prompt + schema

System prompt + JSON schema live in `engine/reddit_engage/prompts/classify.md`.
Same prompt powers both the bulk SDK path AND the interactive judge skill,
so verdicts are consistent across modes. Prompt is cacheable; per-post
tokens are ~400 input + ~80 output = ~$0.0005 with Haiku 4.5.

## Cost cap

`max_tokens=200` per call (~$0.001 ceiling). No global counter — keep it
simple, prevent runaway by per-call enforcement.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

from . import store


# Default model. Haiku 4.5 is the cheap classifier; users can override via llm.json.
DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS_OUT = 200  # ~80 expected; cap at 200 prevents runaway

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["pain_post", "question", "vendor_content", "neutral"],
        },
        "buyer_stage": {
            "type": "string",
            "enum": ["unaware", "considering", "evaluating", "ready", "post_purchase"],
        },
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "competitor_mentioned": {"type": ["string", "null"]},
        "fit_score": {"type": "integer", "minimum": 0, "maximum": 10},
        "suggested_angle": {"type": "string"},
    },
    "required": [
        "intent", "buyer_stage", "sentiment", "competitor_mentioned",
        "fit_score", "suggested_angle",
    ],
    "additionalProperties": False,
}


Provider = Literal["openai_compatible", "anthropic_native", "disabled"]


# Default base URLs per provider key shape
_DEFAULT_BASE_URLS = {
    # When LLM_API_KEY starts with these prefixes, infer the right base URL
    "sk-ant-": "https://api.anthropic.com/v1/",          # Anthropic OpenAI-compat
    "sk-or-": "https://openrouter.ai/api/v1",            # OpenRouter
    "gsk_": "https://api.groq.com/openai/v1",            # Groq
}


def _resolve_llm_endpoint() -> tuple[str | None, str, str]:
    """Return (api_key, base_url, model) for the OpenAI-compatible client.

    Priority: explicit llm.json fields → env vars → key-prefix inference → defaults.
    """
    cfg = {}
    cfg_path = llm_config_path()
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
        except (json.JSONDecodeError, OSError):
            cfg = {}

    api_key = (
        cfg.get("api_key")
        or os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )

    base_url = cfg.get("base_url") or os.environ.get("LLM_BASE_URL")
    if not base_url and api_key:
        # Infer from key prefix
        for prefix, url in _DEFAULT_BASE_URLS.items():
            if api_key.startswith(prefix):
                base_url = url
                break
        if not base_url:
            base_url = "https://api.openai.com/v1"

    model = cfg.get("model") or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    return api_key, base_url, model


def _log(msg: str) -> None:
    sys.stderr.write(f"[classify] {msg}\n")
    sys.stderr.flush()


def llm_config_path() -> Path:
    return store.xdg_config_dir() / "llm.json"


def detect_provider() -> Provider:
    """Auto-detect best available LLM provider for bulk classification.

    Returns `disabled` (not an exception) if no key configured. Callers MUST
    handle `disabled` gracefully — the default daily run does regex-only
    gating and never calls classify() in the first place.

    Provider auto-detection:
      1. `~/.config/reddit-engage/llm.json` explicit override (highest priority)
      2. `LLM_API_KEY` env var → use base_url + model from llm.json or defaults
      3. `ANTHROPIC_API_KEY` env var (legacy compat) → Anthropic
      4. `OPENAI_API_KEY` env var → OpenAI
      5. else: disabled

    The plugin is provider-agnostic: works with any OpenAI-compatible
    endpoint (Anthropic via /openai/v1, OpenAI, Groq, OpenRouter, Together,
    Fireworks, local Ollama, etc).
    """
    cfg_path = llm_config_path()
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            v = cfg.get("provider")
            if v in ("openai_compatible", "anthropic_native", "disabled"):
                return v  # type: ignore
        except (json.JSONDecodeError, OSError):
            pass

    # Generic LLM_API_KEY (user-chosen provider, OpenAI-compatible)
    if os.environ.get("LLM_API_KEY"):
        try:
            import openai  # noqa: F401
            return "openai_compatible"
        except ImportError:
            _log("LLM_API_KEY set but `openai` package not installed. "
                 "Run: pip install -e '.[llm]'")
            return "disabled"

    # Legacy: ANTHROPIC_API_KEY → native Anthropic SDK
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # noqa: F401
            return "anthropic_native"
        except ImportError:
            _log("ANTHROPIC_API_KEY set but `anthropic` SDK not installed. "
                 "Run: pip install -e '.[anthropic]' or '.[llm]' for OpenAI-compat")
            return "disabled"

    # OpenAI direct
    if os.environ.get("OPENAI_API_KEY"):
        try:
            import openai  # noqa: F401
            return "openai_compatible"
        except ImportError:
            return "disabled"

    return "disabled"


def load_prompt() -> str:
    """Load system prompt from prompts/classify.md.

    Public so the `/reddit-engage:judge` skill can share the exact same
    prompt as the bulk path. Cached on first call.
    """
    global _CACHED_PROMPT
    if _CACHED_PROMPT is not None:
        return _CACHED_PROMPT
    p = Path(__file__).resolve().parent.parent / "prompts" / "classify.md"
    try:
        _CACHED_PROMPT = p.read_text()
    except OSError:
        _CACHED_PROMPT = (
            "You classify Reddit posts for a B2B SaaS lead-surfacing tool. "
            "Return JSON matching the schema. Be concise and accurate."
        )
    return _CACHED_PROMPT


_CACHED_PROMPT: str | None = None


def format_user_message(post: dict[str, Any]) -> str:
    """One post → user-message text. Public so the judge skill can format
    identically. Body capped at 800 chars."""
    sub = post.get("subreddit", "?")
    title = (post.get("title") or "")[:300]
    body = (post.get("body") or "")[:800]
    return (
        f"subreddit: r/{sub}\n"
        f"title: {title}\n"
        f"body: {body}"
    )


def _call_openai_compat(post: dict[str, Any], model: str | None = None) -> dict[str, Any] | None:
    """OpenAI-compatible SDK call. Works with: OpenAI, Anthropic (via /openai/v1),
    Groq, OpenRouter, Together, Fireworks, local Ollama — any provider that
    exposes OpenAI's chat-completions API shape.

    Returns parsed verdict dict or None on failure.
    """
    try:
        import openai  # type: ignore
    except ImportError:
        _log("`openai` package not installed. Run: pip install -e '.[llm]'")
        return None

    api_key, base_url, resolved_model = _resolve_llm_endpoint()
    if not api_key:
        return None
    if model:
        resolved_model = model

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    sys_prompt = load_prompt()
    user_msg = format_user_message(post)
    try:
        resp = client.chat.completions.create(
            model=resolved_model,
            max_tokens=MAX_TOKENS_OUT,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg},
            ],
            # response_format would be nice but isn't universally supported;
            # the validator catches malformed JSON.
        )
    except Exception as e:
        _log(f"LLM error ({base_url}): {e}")
        return None
    text = resp.choices[0].message.content or ""
    return _parse_json_safely(text)


def _call_anthropic_native(post: dict[str, Any], model: str) -> dict[str, Any] | None:
    """Native Anthropic SDK with prompt caching enabled. Used when the user
    has ANTHROPIC_API_KEY + the `anthropic` package installed and prefers the
    native SDK over the OpenAI-compat layer.

    Why both: anthropic-native unlocks `cache_control: ephemeral` for ~90%
    cost reduction on repeat calls within 5min. The OpenAI-compat layer
    doesn't currently expose prompt caching.
    """
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None

    client = anthropic.Anthropic()
    sys_prompt = load_prompt()
    user_msg = format_user_message(post)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS_OUT,
            system=[
                {"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        _log(f"SDK error: {e}")
        return None

    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    if not text_parts:
        return None
    return _parse_json_safely(text_parts[0])


def _parse_json_safely(text: str) -> dict[str, Any] | None:
    """Extract JSON from model output. Handles markdown-fenced JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[: -3].rstrip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _validate(verdict: dict[str, Any]) -> dict[str, Any] | None:
    """Cheap shape check. Returns verdict if shape OK, else None."""
    required = {"intent", "buyer_stage", "sentiment", "competitor_mentioned",
                "fit_score", "suggested_angle"}
    if not required.issubset(verdict.keys()):
        return None
    try:
        fs = int(verdict["fit_score"])
        if fs < 0 or fs > 10:
            return None
        verdict["fit_score"] = fs
    except (TypeError, ValueError):
        return None
    return verdict


def classify(
    post: dict[str, Any],
    provider: Provider | None = None,
    model: str | None = None,
) -> dict[str, Any] | None:
    """Bulk classifier entrypoint. Used by `cmd_fetch_score` when API key set.

    Returns the verdict dict on success, or None if:
      - Provider is disabled (no API key)
      - SDK call failed
      - Response was malformed

    Callers MUST treat None as "classifier unavailable" and fall through to
    regex-only gating. Never raises.

    NOT called by the interactive `/reddit-engage:judge` skill — that path
    is Claude-driven in-chat, not subprocess.
    """
    p: Provider = provider or detect_provider()
    if p == "disabled":
        return None
    m = model or DEFAULT_MODEL

    if p == "openai_compatible":
        raw = _call_openai_compat(post, m)
    elif p == "anthropic_native":
        raw = _call_anthropic_native(post, m)
    else:
        return None

    if raw is None:
        return None
    return _validate(raw)


def status() -> dict[str, Any]:
    """Diagnostic: what's the active LLM provider? Used by `reddit-engage status`."""
    p = detect_provider()
    api_key, base_url, model = _resolve_llm_endpoint()
    return {
        "provider": p,
        "mode": "bulk_llm" if p != "disabled" else "regex_only",
        "has_llm_api_key": bool(api_key),
        "base_url": base_url if p != "disabled" else None,
        "model": model if p != "disabled" else None,
        "openai_sdk_installed": _has_module("openai"),
        "anthropic_sdk_installed": _has_module("anthropic"),
        "interactive_judge_available": True,  # always — uses Claude session, not subprocess
        "config_override": llm_config_path().exists(),
    }


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False
