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

## Architecture decisions (documented for Anthropic-best-practices audit)

**Provider priority** (configured at runtime, auto-detected at startup):

1. **`anthropic_api`** (default if `ANTHROPIC_API_KEY` env set) — uses the SDK
   directly. Cheapest per call (~$0.0009 with Haiku 4.5). Recommended.

2. **`claude_cli_bare`** (if `claude` CLI present AND `ANTHROPIC_API_KEY` set) —
   subprocess `claude --bare -p ...`. Functionally equivalent to SDK; useful if
   the user doesn't have the `anthropic` Python lib installed but does have CLI.

3. **`claude_cli_full`** — NOT USED. Discovered during Phase 2 dev: default
   `claude -p` (no `--bare`) loads the entire Claude Code session context
   (CLAUDE.md, hooks, plugin sync) which costs ~$0.17/call regardless of
   prompt size. Not viable for 5K posts/day. Hence `--bare` is required if
   using the CLI path.

4. **`disabled`** (fallback) — no provider available → skip classifier silently,
   regex gate alone decides. Logs once per run.

## Prompt + schema

System prompt + JSON schema live in `engine/reddit_engage/prompts/classify.md`.
The prompt is small (cached automatically by Anthropic's 5min cache) so repeat
calls within a daily run hit the cache. Per-post tokens: ~400 input + ~80 output
= ~$0.0005 with Haiku 4.5.

## Cost cap

Each call enforces `max_tokens_out` AND defers retry on rate-limit per SDK
exponential backoff. Daily budget capped via per-call ceiling, not a global
counter (simpler, prevents accidental runaway).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
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


Provider = Literal["anthropic_api", "claude_cli_bare", "disabled"]


def _log(msg: str) -> None:
    sys.stderr.write(f"[classify] {msg}\n")
    sys.stderr.flush()


def llm_config_path() -> Path:
    return store.xdg_config_dir() / "llm.json"


def detect_provider() -> Provider:
    """Auto-detect best available provider.

    Returns 'disabled' (not an exception) if no path works. Callers must
    handle this gracefully — classification is optional, not required.
    """
    # User override?
    cfg_path = llm_config_path()
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            if cfg.get("provider") in ("anthropic_api", "claude_cli_bare", "disabled"):
                return cfg["provider"]  # type: ignore
        except (json.JSONDecodeError, OSError):
            pass

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_key:
        return "disabled"

    # Prefer SDK if installed
    try:
        import anthropic  # noqa: F401
        return "anthropic_api"
    except ImportError:
        pass

    # CLI fallback (still needs API key for --bare mode)
    if shutil.which("claude"):
        return "claude_cli_bare"

    return "disabled"


def _load_prompt() -> str:
    """Load system prompt from prompts/classify.md. Cached on first call."""
    global _CACHED_PROMPT
    if _CACHED_PROMPT is not None:
        return _CACHED_PROMPT
    p = Path(__file__).resolve().parent.parent / "prompts" / "classify.md"
    try:
        _CACHED_PROMPT = p.read_text()
    except OSError:
        # Fallback prompt if file missing (e.g. partial install)
        _CACHED_PROMPT = (
            "You classify Reddit posts for a B2B SaaS lead-surfacing tool. "
            "Return JSON matching the schema. Be concise and accurate."
        )
    return _CACHED_PROMPT


_CACHED_PROMPT: str | None = None


def _format_user_message(post: dict[str, Any]) -> str:
    """One post → user-message text. Body capped at 800 chars to stay under
    ~400 input tokens including prompt overhead."""
    sub = post.get("subreddit", "?")
    title = (post.get("title") or "")[:300]
    body = (post.get("body") or "")[:800]
    return (
        f"subreddit: r/{sub}\n"
        f"title: {title}\n"
        f"body: {body}"
    )


def _call_anthropic_api(post: dict[str, Any], model: str) -> dict[str, Any] | None:
    """Direct SDK call. Returns parsed verdict dict or None on failure."""
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None

    client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY
    sys_prompt = _load_prompt()
    user_msg = _format_user_message(post)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS_OUT,
            system=[
                # Anthropic prompt-cache: marking system prompt as cacheable
                # gives us ~90% cost reduction on repeat calls within 5min TTL.
                {"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        _log(f"SDK error: {e}")
        return None

    # Extract first text block
    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    if not text_parts:
        return None
    return _parse_json_safely(text_parts[0])


def _call_claude_cli(post: dict[str, Any], model: str) -> dict[str, Any] | None:
    """Subprocess call to `claude --bare -p`. Uses --json-schema for
    structured output validation server-side. Returns parsed verdict or None.

    Cost note: `--bare` is REQUIRED. Default `claude -p` loads full Claude Code
    session context (~136K tokens of CLAUDE.md / hooks / plugins) which makes
    each call cost ~$0.17. With --bare, only the explicit system-prompt counts.
    """
    if not shutil.which("claude"):
        return None
    sys_prompt = _load_prompt()
    user_msg = _format_user_message(post)
    cmd = [
        "claude", "--bare", "-p",
        "--model", model,
        "--output-format", "json",
        "--system-prompt", sys_prompt,
        "--json-schema", json.dumps(CLASSIFY_SCHEMA),
        "--max-budget-usd", "0.05",  # per-call ceiling; classification should be <$0.001
        "--no-session-persistence",
    ]
    try:
        result = subprocess.run(
            cmd, input=user_msg, capture_output=True, text=True, timeout=60
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        _log(f"CLI error: {e}")
        return None

    if result.returncode != 0:
        _log(f"CLI exit {result.returncode}: {result.stderr[:200]}")
        return None

    # `--output-format json` wraps the model output in metadata. Parse the envelope, extract `result`.
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if envelope.get("is_error"):
        _log(f"CLI is_error: {envelope.get('result', '')[:200]}")
        return None
    inner = envelope.get("result", "")
    return _parse_json_safely(inner)


def _parse_json_safely(text: str) -> dict[str, Any] | None:
    """Extract JSON from model output. Handles markdown-wrapped JSON ('''json ... ''')
    and best-effort recovery."""
    text = text.strip()
    # Strip markdown code fence if present
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
    """Public classifier entrypoint.

    Returns the verdict dict on success, or None if:
      - Provider is disabled (no API key, no SDK, no CLI)
      - Network/SDK/CLI call failed
      - Response was malformed and couldn't be salvaged

    Callers MUST treat None as "classifier unavailable" and fall through to
    regex-only gating. Never raise.
    """
    p: Provider = provider or detect_provider()
    if p == "disabled":
        return None
    m = model or DEFAULT_MODEL

    if p == "anthropic_api":
        raw = _call_anthropic_api(post, m)
    elif p == "claude_cli_bare":
        raw = _call_claude_cli(post, m)
    else:
        return None

    if raw is None:
        return None
    return _validate(raw)


def status() -> dict[str, Any]:
    """Diagnostic: what's the active provider? Used by `reddit-engage status`."""
    p = detect_provider()
    return {
        "provider": p,
        "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "anthropic_sdk_installed": _has_module("anthropic"),
        "claude_cli_in_path": bool(shutil.which("claude")),
        "config_override": llm_config_path().exists(),
    }


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False
