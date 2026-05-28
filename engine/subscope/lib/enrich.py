"""Conditional enrichment adapters: DataForSEO + Firecrawl.

Mirrors the `classify.py` activation contract: config present → activate,
config absent → silent no-op, any failure → fail open. The daily scan loop
never touches the network; all HTTP fires from `/subscope-onboard` (Phase A)
or out-of-band refresh callers, populating the `enrichment_cache` SQLite
table. Scan-time consumers (Phase B) only read from the cache.

## Activation contract

`detect_providers()` checks for two YAML files:
    ~/.config/subscope/dataforseo.yml  -> {"login", "password"}
    ~/.config/subscope/firecrawl.yml   -> {"api_key"}

Each provider is independently enabled. Both absent: scan runs unchanged.
Either present: that provider's path activates. Both present + a `dataforseo`
quota row in the negative cache: dfs short-circuits until the backoff window
clears, but firecrawl continues.

Global kill switches:
    env SUBSCOPE_NO_ENRICH=1   forces both disabled
    enrich.set_disabled(True)  module-level flag (set by `--no-enrich` CLI flag)

## HTTP seam

All outbound requests funnel through `_client_request(method, url, headers,
body, timeout)`. Tests `monkeypatch` this single seam (mirroring how
`test_classify.py` mocks `_call_openai_compat`). Stdlib `urllib.request`
only, no `requests` dependency.

## SSRF guard

Every URL (adapter base + any user-supplied scrape target) routes through
`net.validate_url` before the request goes out. The DFS API host is pinned
internally; Firecrawl scrape targets are user-controlled and validated on
every call.

## Privacy banner

First call to each provider prints a one-time stderr notice telling the
user their data is leaving the machine. Mirrors the `_show_privacy_banner_once`
pattern in `classify.py`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import yaml

from . import net, store


# ─── Module-level state ──────────────────────────────────────────────────

_MODULE_DISABLED = False
_BANNER_SHOWN: set[str] = set()
_PROVIDER_CACHE: dict[str, dict[str, Any] | None] = {}

# Adapter base URLs are pinned (not user-overridable) so the SSRF guard's
# job for these endpoints is to confirm the pin, not to police runtime input.
_DFS_BASE = "https://api.dataforseo.com"
_FC_BASE = "https://api.firecrawl.dev"

# Negative-cache TTLs by error class
_NEG_TTL_AUTH = 3600          # 401/403: try again in 1h, key may have rotated
_NEG_TTL_RATE_LIMIT = 86400   # 429: back off a full day
_NEG_TTL_SERVER = 600         # 5xx: 10 min, provider may recover quickly
_NEG_TTL_GENERIC = 1800       # network / parse / other: 30 min

# Positive-cache TTLs by data freshness expectation
_POS_TTL_DFS_LONG = 30 * 86400      # competitors, ranked_keywords: positioning is slow
_POS_TTL_DFS_SHORT = 7 * 86400      # SERP: shifts week to week
_POS_TTL_FC_SCRAPE = 90 * 86400     # marketing copy rarely changes

# Firecrawl scrape body limit (truncate before caching to keep SQLite rows small)
_FC_MARKDOWN_CHAR_CAP = 1500


# ─── Activation contract ─────────────────────────────────────────────────

def set_disabled(flag: bool) -> None:
    """Force-disable enrichment for this process. Wired to `--no-enrich`."""
    global _MODULE_DISABLED
    _MODULE_DISABLED = bool(flag)


def enrichment_enabled() -> bool:
    """Master kill switch. False if env or --no-enrich asked to disable."""
    if _MODULE_DISABLED:
        return False
    if os.environ.get("SUBSCOPE_NO_ENRICH"):
        return False
    return True


def reset_cache() -> None:
    """Test helper: clear module-level memoization between cases."""
    _PROVIDER_CACHE.clear()
    _BANNER_SHOWN.clear()


def load_yaml_config(name: str) -> dict[str, Any] | None:
    """Read a YAML file from `xdg_config_dir()`, fail-open on every error path.

    Returns None on missing file, malformed YAML, OS error, or non-dict
    top-level. Never raises. Callers treat None as "provider disabled".
    """
    path = store.xdg_config_dir() / name
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError as e:
        _log(f"could not read {name}: {e}")
        return None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        _log(f"malformed YAML in {name}: {e}")
        return None
    if not isinstance(data, dict):
        _log(f"{name} top-level is not a mapping; ignoring")
        return None
    return data


def _resolve_dfs_creds() -> tuple[str, str] | None:
    """Return (login, password) if dataforseo.yml is usable, else None."""
    if not enrichment_enabled():
        return None
    if "dataforseo" in _PROVIDER_CACHE:
        cached = _PROVIDER_CACHE["dataforseo"]
        return (cached["login"], cached["password"]) if cached else None
    cfg = load_yaml_config("dataforseo.yml")
    if cfg and isinstance(cfg.get("login"), str) and isinstance(cfg.get("password"), str):
        _PROVIDER_CACHE["dataforseo"] = cfg
        return (cfg["login"], cfg["password"])
    _PROVIDER_CACHE["dataforseo"] = None
    return None


def _resolve_fc_creds() -> str | None:
    """Return Firecrawl api_key if firecrawl.yml is usable, else None."""
    if not enrichment_enabled():
        return None
    if "firecrawl" in _PROVIDER_CACHE:
        cached = _PROVIDER_CACHE["firecrawl"]
        return cached["api_key"] if cached else None
    cfg = load_yaml_config("firecrawl.yml")
    if cfg and isinstance(cfg.get("api_key"), str):
        _PROVIDER_CACHE["firecrawl"] = cfg
        return cfg["api_key"]
    _PROVIDER_CACHE["firecrawl"] = None
    return None


def detect_providers() -> dict[str, bool]:
    """Cheap probe used by the scan loop and `subscope status`.

    Returns {"dataforseo": bool, "firecrawl": bool}. Memoized per process so
    we pay at most one `Path.exists()` + one yaml parse per provider per run.
    """
    return {
        "dataforseo": _resolve_dfs_creds() is not None,
        "firecrawl": _resolve_fc_creds() is not None,
    }


# ─── Quota / negative-cache short-circuit ────────────────────────────────

def is_quota_blocked(conn, provider: str) -> bool:
    """True if any recent negative-cache row marks this provider as backing off.

    Conservative: as soon as one endpoint hits 429, all endpoints on that
    provider hold off until the backoff expires. Avoids hammering an API
    that's already saying no.
    """
    row = conn.execute(
        "SELECT 1 FROM enrichment_cache "
        "WHERE provider = ? AND error IS NOT NULL AND expires_at > ? "
        "LIMIT 1",
        (provider, int(time.time())),
    ).fetchone()
    return row is not None


# ─── HTTP seam (single mock point for tests) ─────────────────────────────

def _client_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None = None,
    timeout: float = 10.0,
) -> tuple[int, bytes]:
    """Single outbound HTTP seam. Returns (status_code, body_bytes).

    Raises only on URL validation failure (SSRF). All HTTP-level failures
    (timeout, connection refused, DNS, 4xx, 5xx) are caught by callers and
    converted into a negative-cache row.
    """
    net.validate_url(url, kind="enrichment endpoint")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=net.ssl_context()) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        # Surface non-2xx with body so callers can classify (auth / rate-limit / 5xx)
        return e.code, (e.read() if e.fp else b"")


def cache_key(*parts: str) -> str:
    """Canonical cache key: sha256 over joined parts. Stable per call."""
    blob = "\x00".join(str(p) for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def negative_cache_ttl(status_code: int) -> int:
    """Map an HTTP status to a backoff window."""
    if status_code in (401, 403):
        return _NEG_TTL_AUTH
    if status_code == 429:
        return _NEG_TTL_RATE_LIMIT
    if 500 <= status_code < 600:
        return _NEG_TTL_SERVER
    return _NEG_TTL_GENERIC


# ─── Logging + privacy banner ────────────────────────────────────────────

def _log(msg: str) -> None:
    sys.stderr.write(f"[enrich] {msg}\n")
    sys.stderr.flush()


def show_banner_once(provider: str) -> None:
    """First call per provider per process: tell the user data is leaving.

    Mirrors the privacy banner in `classify.py`. Subsequent calls no-op.
    """
    if provider in _BANNER_SHOWN:
        return
    _BANNER_SHOWN.add(provider)
    if provider == "dataforseo":
        _log("first DataForSEO call this run. Sending domain + keyword queries "
             "to api.dataforseo.com (your Reddit post bodies stay local).")
    elif provider == "firecrawl":
        _log("first Firecrawl call this run. Sending URLs to api.firecrawl.dev "
             "for markdown extraction (your Reddit post bodies stay local).")
    else:
        _log(f"first {provider} call this run.")


# ─── Status (for `subscope status`) ──────────────────────────────────────

def _dfs_call(
    conn,
    endpoint_path: str,
    cache_endpoint: str,
    cache_key_str: str,
    request_payload: list[dict[str, Any]],
    pos_ttl: int,
    parse_items: Any,
) -> dict[str, Any] | None:
    """Common DataForSEO request + cache + fail-open pipeline.

    `endpoint_path` is the v3 path (e.g. "dataforseo_labs/google/competitors_domain/live").
    `parse_items` is a callable taking the parsed response dict and returning
    the payload dict to cache, or None if the response shape is unusable.

    Returns the payload dict on success, None on any failure (logged + cached).
    """
    creds = _resolve_dfs_creds()
    if creds is None:
        return None
    if is_quota_blocked(conn, "dataforseo"):
        return None

    hit = store.enrich_get(conn, "dataforseo", cache_endpoint, cache_key_str)
    if hit is not None:
        if hit["error"]:
            return None  # negative cache still in backoff
        return json.loads(hit["payload_json"])

    show_banner_once("dataforseo")
    login, password = creds
    auth = base64.b64encode(f"{login}:{password}".encode()).decode()
    url = f"{_DFS_BASE}/v3/{endpoint_path}"
    body = json.dumps(request_payload).encode("utf-8")

    try:
        status_code, raw = _client_request(
            "POST", url,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            body=body,
            timeout=10.0,
        )
    except Exception as e:
        _log(f"dfs {cache_endpoint} request error: {type(e).__name__}")
        store.enrich_put(conn, "dataforseo", cache_endpoint, cache_key_str,
                         "{}", _NEG_TTL_GENERIC, error=type(e).__name__)
        return None

    if status_code != 200:
        _log(f"dfs {cache_endpoint} returned HTTP {status_code}")
        store.enrich_put(conn, "dataforseo", cache_endpoint, cache_key_str,
                         "{}", negative_cache_ttl(status_code),
                         error=f"http_{status_code}")
        return None

    try:
        resp = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        _log(f"dfs {cache_endpoint} response not JSON")
        store.enrich_put(conn, "dataforseo", cache_endpoint, cache_key_str,
                         "{}", _NEG_TTL_GENERIC, error="malformed_json")
        return None

    if resp.get("status_code") != 20000:
        msg = resp.get("status_message", "unknown")
        _log(f"dfs {cache_endpoint} api error: {msg}")
        store.enrich_put(conn, "dataforseo", cache_endpoint, cache_key_str,
                         "{}", _NEG_TTL_GENERIC,
                         error=f"dfs_{resp.get('status_code')}")
        return None

    payload = parse_items(resp)
    if payload is None:
        store.enrich_put(conn, "dataforseo", cache_endpoint, cache_key_str,
                         "{}", _NEG_TTL_GENERIC, error="unexpected_shape")
        return None

    store.enrich_put(conn, "dataforseo", cache_endpoint, cache_key_str,
                     json.dumps(payload), ttl_seconds=pos_ttl)
    return payload


def dfs_competitors_domain(
    target: str,
    conn,
    limit: int = 10,
) -> dict[str, Any] | None:
    """Top N competitor domains for `target` (e.g. "acme.com").

    Used during onboarding (Phase A) to seed brand_anchor.yml. Returns
    {"competitors": [domain, ...]} or None on disabled / failure.
    Cached 30 days.
    """
    target = target.strip().lower()
    key = cache_key("competitors_domain", target, limit)

    def parse(resp: dict[str, Any]) -> dict[str, Any] | None:
        competitors: list[str] = []
        for task in resp.get("tasks", []) or []:
            # Task-level failures inside a 20000 envelope must not be cached as
            # real (architect's note: empty competitors:[] would otherwise live
            # in the positive cache for 30 days, masking the failure).
            if task.get("status_code") != 20000:
                return None
            for result in task.get("result") or []:
                for item in result.get("items") or []:
                    d = item.get("domain")
                    if d:
                        competitors.append(d)
        return {"target": target, "competitors": competitors[:limit]}

    return _dfs_call(
        conn,
        endpoint_path="dataforseo_labs/google/competitors_domain/live",
        cache_endpoint="competitors_domain",
        cache_key_str=key,
        request_payload=[{"target": target, "limit": limit,
                          "location_code": 2840, "language_code": "en"}],
        pos_ttl=_POS_TTL_DFS_LONG,
        parse_items=parse,
    )


def dfs_ranked_keywords(
    target: str,
    conn,
    limit: int = 50,
) -> dict[str, Any] | None:
    """Top keywords `target` ranks for. Used to extend blog keyword sets.

    Returns {"target": str, "keywords": [{"keyword": str, "rank": int,
    "search_volume": int|None}, ...]} or None. Cached 30 days.
    """
    target = target.strip().lower()
    key = cache_key("ranked_keywords", target, limit)

    def parse(resp: dict[str, Any]) -> dict[str, Any] | None:
        kws: list[dict[str, Any]] = []
        for task in resp.get("tasks", []) or []:
            if task.get("status_code") != 20000:
                return None
            for result in task.get("result") or []:
                for item in result.get("items") or []:
                    kw_data = item.get("keyword_data") or {}
                    info = kw_data.get("keyword_info") or {}
                    serp = item.get("ranked_serp_element") or {}
                    serp_item = serp.get("serp_item") or {}
                    keyword = kw_data.get("keyword")
                    rank = serp_item.get("rank_absolute")
                    if keyword and rank is not None:
                        kws.append({
                            "keyword": keyword,
                            "rank": rank,
                            "search_volume": info.get("search_volume"),
                        })
        return {"target": target, "keywords": kws[:limit]}

    return _dfs_call(
        conn,
        endpoint_path="dataforseo_labs/google/ranked_keywords/live",
        cache_endpoint="ranked_keywords",
        cache_key_str=key,
        request_payload=[{"target": target, "limit": limit,
                          "location_code": 2840, "language_code": "en"}],
        pos_ttl=_POS_TTL_DFS_LONG,
        parse_items=parse,
    )


def dfs_serp_advanced(
    query: str,
    conn,
    depth: int = 20,
) -> dict[str, Any] | None:
    """Google SERP advanced for `query`. Used by live subreddit discovery to
    harvest `reddit.com/r/<sub>/comments/...` hits.

    Returns {"query": str, "items": [{"url": str, "title": str,
    "snippet": str}, ...]} or None on disabled / failure. Cached 7 days.
    """
    query = (query or "").strip()
    if not query:
        return None
    key = cache_key("serp_advanced", query, depth)

    def parse(resp: dict[str, Any]) -> dict[str, Any] | None:
        items: list[dict[str, Any]] = []
        for task in resp.get("tasks", []) or []:
            if task.get("status_code") != 20000:
                return None
            for result in task.get("result") or []:
                for item in result.get("items") or []:
                    url = item.get("url") or ""
                    if not url:
                        continue
                    items.append({
                        "url": url,
                        "title": item.get("title", "") or "",
                        "snippet": item.get("description", "") or "",
                    })
        return {"query": query, "items": items}

    return _dfs_call(
        conn,
        endpoint_path="serp/google/organic/live/advanced",
        cache_endpoint="serp_advanced",
        cache_key_str=key,
        request_payload=[{
            "keyword": query,
            "location_code": 2840,
            "language_code": "en",
            "depth": depth,
            "device": "desktop",
            "se_domain": "google.com",
        }],
        pos_ttl=_POS_TTL_DFS_SHORT,
        parse_items=parse,
    )


def fc_scrape(
    url: str,
    conn,
) -> dict[str, Any] | None:
    """Scrape a URL via Firecrawl, return {"url": str, "title": str,
    "markdown": str (capped 1500 chars)} or None on any failure.

    SSRF-validates the target before sending. Cached 90 days.
    """
    try:
        url = net.validate_url(url, kind="firecrawl scrape target")
    except ValueError as e:
        _log(f"firecrawl scrape rejected SSRF target: {e}")
        return None

    api_key = _resolve_fc_creds()
    if api_key is None:
        return None
    if is_quota_blocked(conn, "firecrawl"):
        return None

    key = cache_key("scrape", url)
    hit = store.enrich_get(conn, "firecrawl", "scrape", key)
    if hit is not None:
        if hit["error"]:
            return None
        return json.loads(hit["payload_json"])

    show_banner_once("firecrawl")
    body = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }).encode("utf-8")

    try:
        status_code, raw = _client_request(
            "POST", f"{_FC_BASE}/v1/scrape",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            body=body,
            timeout=15.0,
        )
    except Exception as e:
        _log(f"firecrawl scrape request error: {type(e).__name__}")
        store.enrich_put(conn, "firecrawl", "scrape", key,
                         "{}", _NEG_TTL_GENERIC, error=type(e).__name__)
        return None

    if status_code != 200:
        _log(f"firecrawl scrape returned HTTP {status_code}")
        store.enrich_put(conn, "firecrawl", "scrape", key,
                         "{}", negative_cache_ttl(status_code),
                         error=f"http_{status_code}")
        return None

    try:
        resp = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        _log("firecrawl scrape response not JSON")
        store.enrich_put(conn, "firecrawl", "scrape", key,
                         "{}", _NEG_TTL_GENERIC, error="malformed_json")
        return None

    if not resp.get("success", False):
        msg = resp.get("error") or "unknown"
        _log(f"firecrawl scrape api error: {msg}")
        store.enrich_put(conn, "firecrawl", "scrape", key,
                         "{}", _NEG_TTL_GENERIC, error="fc_unsuccessful")
        return None

    data = resp.get("data") or {}
    markdown = (data.get("markdown") or "")[:_FC_MARKDOWN_CHAR_CAP]
    metadata = data.get("metadata") or {}
    payload = {
        "url": url,
        "title": metadata.get("title", ""),
        "markdown": markdown,
    }
    store.enrich_put(conn, "firecrawl", "scrape", key,
                     json.dumps(payload), ttl_seconds=_POS_TTL_FC_SCRAPE)
    return payload


# ─── URL extraction helper for Phase B (outbound links inside Reddit posts) ─

_URL_RE = None  # lazy compile

def extract_first_url(body: str) -> str | None:
    """Return the first https?:// URL found in `body`, or None.

    Used by Phase B to detect when a Reddit post links out to a comparison
    page (g2, capterra, etc.) that's worth scraping for context.
    """
    global _URL_RE
    if _URL_RE is None:
        import re
        _URL_RE = re.compile(r"https?://[^\s<>\")']+", re.IGNORECASE)
    if not body:
        return None
    m = _URL_RE.search(body)
    return m.group(0).rstrip(".,;:!?)") if m else None


def augment_scores(candidates: list[dict[str, Any]], conn) -> None:
    """Phase B: pure cache-read augmentation, called from cmd_fetch_score.

    Mutates each candidate in place when matching cache rows exist. Never
    fires HTTP. Default state (empty cache) is a no-op so this is safe to
    call unconditionally.

    For each candidate post body, extracts the first outbound URL. If that
    URL has a Firecrawl scrape cached, attaches the scraped markdown +
    title to `candidate["enrichment"]["link_context"]`. Surfaces gain a
    "what is the OP actually citing" preview in the inline table.
    """
    if not enrichment_enabled():
        return
    detected = detect_providers()
    if not (detected["dataforseo"] or detected["firecrawl"]):
        return

    for cand in candidates:
        post = cand.get("post") or {}
        body = post.get("body") or ""
        link = extract_first_url(body)
        if not link:
            continue
        key = cache_key("scrape", link)
        hit = store.enrich_get(conn, "firecrawl", "scrape", key)
        if hit is None or hit["error"]:
            continue
        try:
            payload = json.loads(hit["payload_json"])
        except json.JSONDecodeError:
            continue
        enr = cand.setdefault("enrichment", {})
        enr["link_context"] = {
            "url": payload.get("url", link),
            "title": payload.get("title", ""),
            "excerpt": payload.get("markdown", "")[:400],
        }


def warmup_for_onboarding(
    homepage_url: str,
    conn,
) -> dict[str, Any]:
    """Phase A: one-shot enrichment fired during /subscope-onboard.

    Called from the SKILL.md T7 step (after configs are written, before the
    first scan). When DFS+FC keys are present, fetches the user's homepage
    competitor list (DFS) and scrapes the homepage for positioning copy (FC).
    Both results land in the enrichment_cache for future scans to read.

    Returns a status dict the skill can render to the user:
      {"dataforseo": {"called": bool, "competitors_found": int|null,
                      "skipped_reason": str|null},
       "firecrawl":  {"called": bool, "markdown_chars": int|null,
                      "skipped_reason": str|null}}

    Never raises. Safe to call regardless of provider state.
    """
    result: dict[str, Any] = {
        "dataforseo": {"called": False, "competitors_found": None,
                       "skipped_reason": None},
        "firecrawl": {"called": False, "markdown_chars": None,
                      "skipped_reason": None},
    }

    if not enrichment_enabled():
        result["dataforseo"]["skipped_reason"] = "enrichment_disabled"
        result["firecrawl"]["skipped_reason"] = "enrichment_disabled"
        return result

    # Strip scheme + path to get bare domain for DFS competitor lookup
    domain = homepage_url
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
            break
    domain = domain.split("/")[0].strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]

    # DFS: competitor seed
    if _resolve_dfs_creds() is not None:
        payload = dfs_competitors_domain(domain, conn)
        result["dataforseo"]["called"] = True
        if payload is not None:
            result["dataforseo"]["competitors_found"] = len(
                payload.get("competitors", []))
        else:
            result["dataforseo"]["skipped_reason"] = "fetch_failed_or_cached_negative"
    else:
        result["dataforseo"]["skipped_reason"] = "no_credentials"

    # Firecrawl: homepage scrape
    if _resolve_fc_creds() is not None:
        payload = fc_scrape(homepage_url, conn)
        result["firecrawl"]["called"] = True
        if payload is not None:
            result["firecrawl"]["markdown_chars"] = len(payload.get("markdown", ""))
        else:
            result["firecrawl"]["skipped_reason"] = "fetch_failed_or_cached_negative"
    else:
        result["firecrawl"]["skipped_reason"] = "no_credentials"

    return result


def status(conn=None) -> dict[str, Any]:
    """Provider snapshot for the status JSON.

    {
      "dataforseo": {"configured": bool, "blocked": bool|null, "last_call_ok": bool|null},
      "firecrawl":  {"configured": bool, "blocked": bool|null, "last_call_ok": bool|null},
    }
    """
    detected = detect_providers()
    out: dict[str, Any] = {}
    for provider in ("dataforseo", "firecrawl"):
        configured = detected[provider]
        blocked: bool | None = None
        last_ok: bool | None = None
        if configured and conn is not None:
            blocked = is_quota_blocked(conn, provider)
            row = conn.execute(
                "SELECT error FROM enrichment_cache "
                "WHERE provider = ? ORDER BY fetched_at DESC LIMIT 1",
                (provider,),
            ).fetchone()
            if row is not None:
                last_ok = row["error"] is None
        out[provider] = {
            "configured": configured,
            "blocked": blocked,
            "last_call_ok": last_ok,
        }
    return out
