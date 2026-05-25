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

`subscope` does NOT bulk-classify every post by default. The default
daily run uses regex + author-vet + tier gates only (zero LLM cost, zero
auth requirement). LLM classification is opt-in per use case:

1. **`/subscope:run` (default)** — regex-only gate. No classifier call.
   Day-1 install works without any keys.

2. **`/subscope:judge <surface-id>`** — interactive, Claude-driven via
   your Claude Code subscription. Reads a single surface, runs the same
   classification prompt, returns verdict + reply angle. Free under
   subscription; cost lives with `claude` Code session, not this module.

3. **Bulk LLM (opt-in, via `LLM_API_KEY` + any OpenAI-compatible endpoint)** —
   `classify(post)` calls the OpenAI Python SDK against whichever endpoint the
   user configured (Anthropic via `/openai/v1`, OpenAI, Groq, OpenRouter,
   Together, Fireworks, local Ollama). Activated when `cmd_fetch_score` finds
   any of `LLM_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY` in env —
   every regex-passing post gets graded. Typical cost ~$0.0005/post with
   Haiku 4.5 / GPT-4o-mini class models. At 5K posts/day = ~$0.50/day.

## Why no `claude` CLI subprocess path

The Claude Code subscription's natural use is **interactive judgment** — one
call at a time, human-driven, in chat. That's the `/subscope:judge` skill
(skills/judge/SKILL.md). Bulk classification is what API keys are for —
subprocess invocation of `claude` either loads expensive session context
or requires an API key anyway.

## Prompt + schema

System prompt + JSON schema live in `engine/subscope/prompts/classify.md`.
Same prompt powers both the bulk SDK path AND the interactive judge skill,
so verdicts are consistent across modes. Prompt is cacheable; per-post
tokens are ~400 input + ~80 output = ~$0.0005 with Haiku 4.5.

## Cost cap

`max_tokens=200` per call (~$0.001 ceiling). No global counter — keep it
simple, prevent runaway by per-call enforcement.
"""
from __future__ import annotations

import ipaddress
import json
import os
import sys
import urllib.parse
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


Provider = Literal["openai_compatible", "disabled"]


# Default base URLs per provider key shape
_DEFAULT_BASE_URLS = {
    # When LLM_API_KEY starts with these prefixes, infer the right base URL
    "sk-ant-": "https://api.anthropic.com/v1/",          # Anthropic OpenAI-compat
    "sk-or-": "https://openrouter.ai/api/v1",            # OpenRouter
    "gsk_": "https://api.groq.com/openai/v1",            # Groq
}

# Hosts that are explicitly allowed even though they resolve to private/loopback
# IPs (local LLM servers). Everything else hitting RFC-1918 or link-local is
# rejected as a likely SSRF attempt against cloud metadata, internal services,
# or LAN devices.
_LOCAL_ALLOWLIST = {"localhost", "127.0.0.1", "::1"}


def _validate_base_url(url: str) -> str:
    """SSRF guard: reject base URLs that target internal/metadata services.

    Allows:
      - https://* with public hostnames
      - http://localhost or http://127.0.0.1 (local Ollama / dev servers)

    Rejects:
      - http://* to non-localhost hosts
      - URLs targeting RFC-1918, link-local, or AWS-metadata-style IPs
      - Non-http(s) schemes
    """
    try:
        p = urllib.parse.urlparse(url)
    except ValueError as e:
        raise ValueError(f"Invalid llm_base_url: {url!r} ({e})")
    if p.scheme not in ("http", "https"):
        raise ValueError(f"llm_base_url must be http(s), got {p.scheme!r}")
    host = (p.hostname or "").lower()
    if not host:
        raise ValueError(f"llm_base_url has no host: {url!r}")
    if p.scheme == "http" and host not in _LOCAL_ALLOWLIST:
        raise ValueError(
            f"llm_base_url uses http:// for non-local host {host!r}. "
            "Use https:// for remote endpoints; http:// is only allowed for localhost."
        )
    # Block private + link-local IPs (AWS metadata 169.254.169.254, etc.).
    # ipaddress.ip_address() raises ValueError on non-IP hostnames; capture
    # that case separately so our own validation ValueError doesn't get
    # swallowed by the same except block.
    ip = None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None  # hostname, not an IP literal — defer to DNS at request time
    if ip is not None and host not in _LOCAL_ALLOWLIST and (
        ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast
    ):
        raise ValueError(
            f"llm_base_url targets private/link-local IP {host!r}. "
            "If running a local LLM, use 'localhost' instead."
        )
    return url


def _resolve_llm_endpoint() -> tuple[str | None, str, str]:
    """Return (api_key, base_url, model) for the OpenAI-compatible client.

    Priority: explicit llm.json fields → env vars → key-prefix inference → defaults.
    Raises ValueError if a configured base_url fails SSRF validation.
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

    if base_url:
        base_url = _validate_base_url(base_url)

    model = cfg.get("model") or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    return api_key, base_url, model


def _log(msg: str) -> None:
    sys.stderr.write(f"[classify] {msg}\n")
    sys.stderr.flush()


# One-time privacy banner per process: tell the user their post bodies are
# leaving the machine the first time we call out to an LLM endpoint.
_PRIVACY_BANNER_SHOWN = False


def _show_privacy_banner_once(base_url: str) -> None:
    global _PRIVACY_BANNER_SHOWN
    if _PRIVACY_BANNER_SHOWN:
        return
    _PRIVACY_BANNER_SHOWN = True
    sys.stderr.write(
        f"[classify] LLM grading active. Reddit post bodies (capped at 800 chars) "
        f"will be sent to {base_url} for classification. "
        f"To disable: unset LLM_API_KEY (and OPENAI_API_KEY, ANTHROPIC_API_KEY).\n"
    )
    sys.stderr.flush()


def llm_config_path() -> Path:
    return store.xdg_config_dir() / "llm.json"


def detect_provider() -> Provider:
    """Auto-detect available LLM provider for bulk classification.

    Returns `disabled` (not an exception) if no key configured. Callers MUST
    handle `disabled` gracefully — the default daily run does regex-only
    gating and never calls classify() in the first place.

    Provider auto-detection:
      1. `~/.config/subscope/llm.json` explicit override (highest priority)
      2. `LLM_API_KEY` env var → OpenAI-compatible (base_url inferred from prefix)
      3. `ANTHROPIC_API_KEY` env var → routed via Anthropic's /openai/v1 endpoint
      4. `OPENAI_API_KEY` env var → OpenAI
      5. else: disabled

    The plugin is provider-agnostic: works with any OpenAI-compatible
    endpoint (Anthropic via /openai/v1, OpenAI, Groq, OpenRouter, Together,
    Fireworks, local Ollama, etc). Single code path — no provider-specific
    SDK branches.
    """
    cfg_path = llm_config_path()
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            v = cfg.get("provider")
            if v in ("openai_compatible", "disabled"):
                return v  # type: ignore
        except (json.JSONDecodeError, OSError):
            pass

    # Any of these env vars activates the bulk classifier
    if os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        try:
            import openai  # noqa: F401
            return "openai_compatible"
        except ImportError:
            _log("API key set but `openai` package not installed. "
                 "Run: pip install -e '.[llm]'")
            return "disabled"

    return "disabled"


def load_prompt() -> str:
    """Load system prompt from prompts/classify.md.

    Public so the `/subscope:judge` skill can share the exact same
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

    _show_privacy_banner_once(base_url)
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
        # Redact API key prefix from error string defensively, in case
        # an older SDK leaked it in the message.
        msg = str(e)
        if api_key:
            msg = msg.replace(api_key, "[REDACTED]")
        _log(f"LLM error ({base_url}): {msg}")
        return None
    text = resp.choices[0].message.content or ""
    return _parse_json_safely(text)


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

    NOT called by the interactive `/subscope:judge` skill — that path
    is Claude-driven in-chat, not subprocess.
    """
    p: Provider = provider or detect_provider()
    if p == "disabled":
        return None
    m = model or DEFAULT_MODEL

    raw = _call_openai_compat(post, m)
    if raw is None:
        return None
    return _validate(raw)


def status() -> dict[str, Any]:
    """Diagnostic: what's the active LLM provider? Used by `subscope status`."""
    p = detect_provider()
    try:
        api_key, base_url, model = _resolve_llm_endpoint()
        base_url_err = None
    except ValueError as e:
        api_key, base_url, model = None, None, None
        base_url_err = str(e)
    return {
        "provider": p,
        "mode": "bulk_llm" if p != "disabled" else "regex_only",
        "has_llm_api_key": bool(api_key),
        "base_url": base_url if p != "disabled" else None,
        "base_url_error": base_url_err,
        "model": model if p != "disabled" else None,
        "openai_sdk_installed": _has_module("openai"),
        "interactive_judge_available": True,  # always — uses Claude session, not subprocess
        "config_override": llm_config_path().exists(),
    }


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False
