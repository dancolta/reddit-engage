"""Optional Slack push for the daily surface list.

The integration market researcher's audit picked exactly one push surface as
worth the LOC: a chat-app webhook. Every paid Reddit listening tool ships
Slack alerts; nothing else is universally adopted. Notion + Obsidian already
cover the pull/triage and weekly archive flows.

Design:
  - Optional. If no config file and no SLACK_WEBHOOK_URL env var, silent no-op.
  - No new dependency — uses urllib from stdlib.
  - Auto-runs at the end of `subscope run`. CLI flag `--no-slack` disables.
  - Config lives in ~/.config/subscope/slack.json:
        {"webhook_url": "https://hooks.slack.com/services/..."}
    with chmod 600 (webhook URL is a bearer-equivalent secret).
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import store


def _log(msg: str) -> None:
    sys.stderr.write(f"[slack] {msg}\n")
    sys.stderr.flush()


def slack_config_path():
    return store.xdg_config_dir() / "slack.json"


def webhook_url() -> str | None:
    """Resolve the webhook URL: file > env var. Validates scheme + host."""
    url: str | None = None
    p = slack_config_path()
    if p.exists():
        try:
            cfg = json.loads(p.read_text())
            url = cfg.get("webhook_url") or None
        except (json.JSONDecodeError, OSError):
            url = None
    if not url:
        url = os.environ.get("SLACK_WEBHOOK_URL") or None
    if not url:
        return None
    # Only allow Slack's actual webhook host. Defense-in-depth against a
    # mis-edited config or env that points elsewhere — same posture as the
    # SSRF guard on llm_base_url.
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "hooks.slack.com":
        _log(f"slack webhook must be https://hooks.slack.com/...; got {url!r}. Ignoring.")
        return None
    return url


def is_configured() -> bool:
    return webhook_url() is not None


def _format_message(payload: dict[str, Any]) -> dict[str, Any]:
    """Turn the engine's JSON payload into a Slack message.

    Uses simple `text` + plaintext block. Keeps the message dense — Slack's
    block-kit JSON would add lines without adding signal.
    """
    surfaced = payload.get("surfaced", 0)
    fetched = payload.get("fetched", 0)
    mode = payload.get("mode") or "default"
    surfaces = payload.get("surfaces") or []
    if surfaced == 0:
        text = f":mag: subscope ({mode}): 0 surfaces today from {fetched} fetched. Empty days are fine."
        return {"text": text}

    lines = [f":bell: *subscope* ({mode}): {surfaced} surface{'' if surfaced == 1 else 's'} today"]
    for i, s in enumerate(surfaces[:10], start=1):  # cap at 10 in chat
        tier = s.get("tier") or "?"
        sub = s.get("subreddit") or "?"
        title = (s.get("title") or "").replace("\n", " ")
        url = s.get("url") or ""
        op = s.get("op_score") or ""
        op_chunk = f" · {op}" if op else ""
        lines.append(f"  *{i}.* T{tier} r/{sub}{op_chunk}\n     <{url}|{title[:140]}>")
    if surfaced > 10:
        lines.append(f"  _… +{surfaced - 10} more in the full output_")
    return {"text": "\n".join(lines), "unfurl_links": False, "unfurl_media": False}


def notify_if_configured(payload: dict[str, Any], timeout: float = 5.0) -> bool:
    """Push the daily surface list to Slack if a webhook is configured.

    Returns True on success, False on no-op or failure. NEVER raises — Slack
    failures must not break the daily run.
    """
    url = webhook_url()
    if not url:
        return False
    msg = _format_message(payload)
    body = json.dumps(msg).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "subscope/0.1"},
        method="POST",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            ok = 200 <= resp.status < 300
            if not ok:
                _log(f"webhook returned HTTP {resp.status}")
            return ok
    except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, ssl.SSLError) as e:
        _log(f"webhook failed: {e}")
        return False
    except Exception as e:  # very defensive — we never want this to crash the run
        _log(f"webhook unexpected error: {e}")
        return False


def status() -> dict[str, Any]:
    """Diagnostic dict for `subscope status`."""
    return {
        "configured": is_configured(),
        "source": "file" if slack_config_path().exists()
                  else ("env" if os.environ.get("SLACK_WEBHOOK_URL") else None),
    }
