"""Shared networking utilities: SSRF guard, redacted error logging.

Extracted from classify.py during ENR-2 so the same SSRF discipline applies
to DataForSEO + Firecrawl adapters in enrich.py.
"""
from __future__ import annotations

import ipaddress
import urllib.parse


# Hosts allowed despite resolving to private/loopback IPs (local dev servers).
# Everything else hitting RFC-1918 or link-local is rejected as a likely SSRF
# attempt against cloud metadata, internal services, or LAN devices.
_LOCAL_ALLOWLIST = {"localhost", "127.0.0.1", "::1"}


def validate_url(url: str, kind: str = "url") -> str:
    """SSRF guard: reject URLs that target internal/metadata services.

    Allows:
      - https://* with public hostnames
      - http://localhost or http://127.0.0.1 (local Ollama / dev servers)

    Rejects:
      - http://* to non-localhost hosts
      - URLs targeting RFC-1918, link-local, or AWS-metadata-style IPs
      - Non-http(s) schemes

    `kind` flavors the error message so callers can surface "llm_base_url"
    vs "firecrawl scrape target" vs anything else they pass in.
    """
    try:
        p = urllib.parse.urlparse(url)
    except ValueError as e:
        raise ValueError(f"Invalid {kind}: {url!r} ({e})")
    if p.scheme not in ("http", "https"):
        raise ValueError(f"{kind} must be http(s), got {p.scheme!r}")
    host = (p.hostname or "").lower()
    if not host:
        raise ValueError(f"{kind} has no host: {url!r}")
    if p.scheme == "http" and host not in _LOCAL_ALLOWLIST:
        raise ValueError(
            f"{kind} uses http:// for non-local host {host!r}. "
            "Use https:// for remote endpoints; http:// is only allowed for localhost."
        )
    ip = None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and host not in _LOCAL_ALLOWLIST and (
        ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast
    ):
        raise ValueError(
            f"{kind} targets private/link-local IP {host!r}. "
            "If running a local server, use 'localhost' instead."
        )
    return url
