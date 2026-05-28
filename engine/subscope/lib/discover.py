"""Live subreddit discovery for `/subscope-onboard` step 5.

Replaces the static archetype-map seed list with subs harvested from real
Reddit threads matching the user's buyer-pain phrasing.

## Pipeline

1. `derive_queries(answers, scrape_markdown, competitors)` → 3-6 search queries
   built deterministically from T2/T3/T4 answers + Firecrawl scrape + DFS
   competitor list. No LLM in this path.
2. `search_dfs(query, conn)` → site:reddit.com SERP via DataForSEO. Harvests
   `r/<sub>/comments/...` URLs.
3. `search_reddit(query)` → Reddit's public /search.json. Always available,
   no creds, no cost.
4. `rank_subs(threads)` → per-sub score = (freq*2 + quality + recency*1.5) ×
   noise_mult. Top 8 with why-lines.
5. `discover_subs_for_profile(answers, homepage_url, conn)` → end-to-end
   entry point. Returns ranked subs + clarification signals for the skill.

## Fallback

- < 5 candidates after dedup + age filter + noise mult → `needs_clarification=True`
  with a vertical-clarifier prompt the skill renders as T4.5
- All providers down or hard timeout → returns whatever Tier B got, with a
  `discovery_unreachable=True` flag the skill renders as a warning on T5

The archetype map is NOT replaced for downstream scoring (keywords,
brand_anchor, example_pains still flow from `profile_synth.fallback_from_archetype`).
Only the T5 candidate-sub surface uses discovery output.
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
import urllib.parse
from typing import Any

from . import enrich, net, reddit, store


# ─── Tunables (mirrored in config/weights.yml `discovery:` block) ──────

NOISE_DOWNRANK_FACTOR = 0.5
MIN_SUBS_THRESHOLD = 5
MAX_SUBS_RETURNED = 8
MAX_QUERIES = 6
FRESHNESS_CUTOFF_DAYS = 730
DISCOVERY_HARD_TIMEOUT_S = 20.0

# Per-sub quality is capped at 3.0 (was 5.0). Quality is a tiebreaker, not a
# dominator. Cross-query frequency is the real signal that a sub is a place
# people discuss the buyer's problem, not a single viral thread.
QUALITY_CEILING = 3.0

# Hard gate: a sub MUST have at least this many threads matched across all
# queries to make the output. Single-thread matches are almost always
# coincidental lexical overlap (r/PleX matching "saas subscriptions" because
# someone said "my Plex subscription is too expensive"). Real buyer subs
# show up multiple times when the user's pain is genuinely discussed there.
MIN_THREAD_COUNT = 2

# Vocabulary-overlap bonus: when the sub name shares a token with the user's
# own answers (T2/T3/T4 lowercase, stopwords stripped, ≥4 chars), the sub
# gets a score boost. This is fully data-driven: an accounting SaaS seller
# gets r/Accounting bonused but NOT r/ecommerce, while a Shopify app seller
# gets r/ecommerce bonused but NOT r/Accounting. Replaces the brittle static
# operator-token list (which had no awareness of who the buyer actually is).
USER_VOCAB_BONUS = 2.5

# Generic vocabulary stopwords stripped from token overlap.
# Conservative list: ONLY true linguistic stopwords + the most generic
# nouns. Domain-meaningful words like "saas", "alternatives", "expensive"
# stay in vocabulary so that when a user explicitly writes them, subs with
# those tokens in their names (r/microsaas, r/B2BSaaS) get vocab match.
_VOCAB_STOPWORDS = {
    # function words
    "the", "and", "for", "with", "that", "this", "have", "from", "your",
    "you", "our", "their", "they", "are", "was", "were", "been", "being",
    "any", "all", "some", "more", "most", "much", "many", "few", "such",
    "very", "just", "only", "also", "into", "onto", "out", "off",
    "good", "bad", "new", "old", "big", "small", "high", "low",
    # extremely generic nouns/verbs
    "want", "wants", "need", "needs", "like", "likes", "use", "uses",
    "make", "makes", "made", "get", "gets", "got",
    "thing", "things", "stuff", "people", "team", "teams",
    "company", "companies", "service", "services",
}

# Subreddit names that overlap the user's likely intent but are noise-heavy.
# Downrank 50%, do not drop. Three sub-groups:
#  (a) generic founder / SaaS noise, original list per market researcher
#  (b) finance / investing subs that match "SaaS subscriptions expensive" as
#      stock-analysis chatter, not buyer-intent (caught in live smoke)
#  (c) general-venting / lifestyle subs that match price-rage queries because
#      Reddit's search is lexical, not semantic (also caught in live smoke)
NOISE_DOWNRANK_SUBS = {
    # (a) generic founder / SaaS noise
    "entrepreneur", "saas", "smallbusiness", "startups",
    "coldemail", "emailmarketing", "marketing", "digital_marketing",
    "business", "entrepreneurridealong",
    # (b) finance / investing, false positives on SaaS-pricing queries
    "wallstreetbets", "valueinvesting", "stocks", "investing",
    "personalfinance", "frugal", "fire",
    # (c) general venting / lifestyle, false positives on price-rage
    "mildlyinfuriating", "middleclasshq", "antiwork", "layoffs",
    "politics", "news", "worldnews", "askreddit", "showerthoughts",
    "rant", "venting", "complaints",
    # (d) drama / relationship / meta repost subs that lexically match
    # any phrase containing "expensive", "switching", "alternative" in
    # personal-life contexts (caught in accounting-persona smoke)
    "aitah", "amitheasshole", "amioverreacting", "relationships",
    "relationship_advice", "bestofredditorupdates", "tifu",
    "twoxchromosomes", "askmen", "askwomen", "futurology",
}

# Buyer-intent signal: a thread is dropped from discovery if its title contains
# none of these tokens. The bar is "the OP is shopping, comparing, or switching"
# not "the OP is venting about prices." Tokens are matched as whole words
# (case-insensitive, word-boundary).
BUYER_INTENT_TOKENS = (
    "alternative", "alternatives", "switching", "switch",
    "replace", "replacing", "replacement", "instead of",
    "vs", "versus", "compare", "comparison",
    "looking for", "recommend", "recommendation", "suggestions",
    "cheaper", "migrate", "moving from", "moving off",
    "ditching", "ditch", "ditched", "best", "better than",
    "any good", "anyone use", "anyone tried", "what do you use",
    "experience with", "thoughts on",
)

_BUYER_INTENT_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in BUYER_INTENT_TOKENS) + r")\b",
    re.IGNORECASE,
)


def _build_user_vocabulary(answers: dict[str, str]) -> set[str]:
    """Extract the user's domain vocabulary from T2/T3/T4.

    Returns lowercase tokens ≥4 chars, stripped of generic stopwords. This
    becomes the "is this sub topically related to what the user sells"
    signal for the ranking bonus.
    """
    blob = " ".join([
        answers.get("what_offering", "") or "",
        answers.get("who_to_reach", "") or "",
        answers.get("pain_quote", "") or "",
    ]).lower()
    tokens = re.findall(r"[a-z][a-z\-]{3,}", blob)
    return {t for t in tokens if t not in _VOCAB_STOPWORDS}


def _sub_matches_user_vocab(sub_key: str, vocab: set[str]) -> bool:
    """True if any vocabulary token appears as a substring of the sub name.

    Substring match (not word-boundary) because sub names compress tokens:
    'aiautomations' contains 'automation', 'salesops' contains 'sales'.
    """
    if not sub_key or not vocab:
        return False
    s = sub_key.lower()
    return any(tok in s for tok in vocab)


# Legacy alias kept for tests / external callers; semantics now require
# vocabulary context.
def _is_operator_sub(sub_key: str, vocab: set[str] | None = None) -> bool:
    """Compatibility shim. Pass `vocab` for the new vocabulary-aware check.

    When vocab is None, falls back to a conservative built-in list of
    business/operator tokens so old callers don't crash, but the new ranking
    pipeline always supplies a vocab set.
    """
    if vocab is not None:
        return _sub_matches_user_vocab(sub_key, vocab)
    # Conservative legacy fallback (only used by tests and ad-hoc inspection)
    fallback = {"ops", "founder", "owner", "agency", "accounting",
                "automation", "nocode", "sales", "marketing"}
    return _sub_matches_user_vocab(sub_key, fallback)


def _has_buyer_intent(title: str) -> bool:
    """True if the thread title looks like the OP is shopping / comparing /
    switching, not just venting. Empty title is treated as no-intent."""
    if not title:
        return False
    return bool(_BUYER_INTENT_RE.search(title))

# Reddit sub-name rule: alphanumerics + underscore, 2-21 chars.
_SUBNAME_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")

# DFS SERP harvest: r/<sub>/comments/<id>/...
_DFS_SUB_RE = re.compile(r"reddit\.com/r/([A-Za-z0-9_]{2,21})/comments/", re.IGNORECASE)

# T2 noun-phrase extraction: noun after "for" or before "tool"/"platform"/"software".
_OFFERING_HEAD_RE = re.compile(
    r"\bfor\s+([A-Za-z][\w\s\-]{2,40})|"
    r"([A-Za-z][\w\s\-]{2,40})\s+(?:tool|platform|software|app|service)\b",
    re.IGNORECASE,
)

# Homepage pain extraction (rule 6 in spec).
_HOMEPAGE_PAIN_RE = re.compile(
    r"(?:stuck on|tired of|frustrated with|hate|switching from|replacing)\s+([^.\n]{8,60})",
    re.IGNORECASE,
)

# T4 price-rage trigger.
_PRICE_RAGE_RE = re.compile(r"\b(expensive|price|raised|increase|cost|bill|charging|hike)\b", re.IGNORECASE)

# Stopwords for buyer-noun rule.
_BUYER_STOPWORDS = {
    "the", "a", "an", "for", "of", "in", "at", "to", "and", "or",
    "with", "people", "person", "user", "users", "team", "teams",
    "company", "companies", "business", "businesses",
}

# Leading prefixes to strip from the verbatim T4 pain.
_T4_LEADING_PREFIXES = ("i'm ", "i am ", "we're ", "we are ", "my ", "our ", "the ")

_QUERY_MAX_CHARS = 80


def _log(msg: str) -> None:
    sys.stderr.write(f"[discover] {msg}\n")
    sys.stderr.flush()


# ─── 1. Query derivation ────────────────────────────────────────────────


def _normalize_query(s: str) -> str:
    """Lowercase, strip, collapse whitespace, trim to 80 chars at word boundary.

    Only strips matched outer quote pairs (so a fully quoted competitor query
    `"drake software"` becomes `drake software`) but preserves internal quotes
    needed for Reddit's exact-phrase search (`replacing "drake software"`
    survives intact).
    """
    s = re.sub(r"\s+", " ", (s or "").strip().lower())
    # Only strip if BOTH ends are the same quote char (matched pair)
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        s = s[1:-1].strip()
    for prefix in _T4_LEADING_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    if len(s) <= _QUERY_MAX_CHARS:
        return s
    cut = s.rfind(" ", 0, _QUERY_MAX_CHARS)
    return (s[:cut] if cut > 0 else s[:_QUERY_MAX_CHARS]).strip()


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _add_query(out: list[str], token_sets: list[set[str]], candidate: str) -> bool:
    """Append `candidate` to `out` if (a) non-empty and (b) Jaccard < 0.7 vs
    all previously added queries. Returns True if added."""
    c = _normalize_query(candidate)
    if not c or len(c) < 6:
        return False
    cs = _tokens(c)
    for existing in token_sets:
        if _jaccard(cs, existing) >= 0.7:
            return False
    out.append(c)
    token_sets.append(cs)
    return True


_BUYER_NOUN_PRIORITY = (
    "founder", "founders", "operator", "operators", "owner", "owners",
    "ceo", "cto", "coo", "cfo", "manager", "managers", "director",
    "principal", "head", "lead", "leader", "leaders", "freelancer",
    "agency", "agencies", "consultant", "consultants",
)


def _extract_buyer_noun(t3: str) -> str | None:
    """Head noun from T3. Prefers known buyer-role tokens when present
    anywhere in the answer (founder, operator, owner, ceo, etc.), falls back
    to the first noun-before-preposition pattern, then the last non-stopword
    alphabetic token."""
    if not t3:
        return None
    s = t3.lower().strip()
    # Priority pass: known buyer-role tokens anywhere in T3
    for role in _BUYER_NOUN_PRIORITY:
        if re.search(rf"\b{role}\b", s):
            # Drop trailing 's' for singular form (founders -> founder still works)
            return role
    # Fallback: "founders at a SaaS startup" → "founders"
    m = re.match(r"^([\w\-]+)\s+(?:at|of|in)\s+", s)
    if m:
        cand = m.group(1)
    else:
        # Take last alphabetic token > 2 chars not in stopwords
        words = re.findall(r"[a-z][a-z\-]+", s)
        cand = None
        for w in reversed(words):
            if len(w) > 2 and w not in _BUYER_STOPWORDS:
                cand = w
                break
    if not cand or cand in _BUYER_STOPWORDS:
        return None
    return cand


def _extract_offering_pain(t2: str) -> str | None:
    """T2 offering pain phrase per rule 5."""
    if not t2:
        return None
    m = _OFFERING_HEAD_RE.search(t2)
    if not m:
        return None
    phrase = (m.group(1) or m.group(2) or "").strip()
    return phrase if phrase else None


def _extract_homepage_pain(markdown: str) -> str | None:
    """First match of homepage pain regex (rule 6)."""
    if not markdown:
        return None
    m = _HOMEPAGE_PAIN_RE.search(markdown)
    if not m:
        return None
    return m.group(1).strip(" .,;:")


def derive_queries(
    answers: dict[str, str],
    scrape_markdown: str | None = None,
    competitors: list[str] | None = None,
    vertical: str | None = None,
) -> list[str]:
    """Build 3-6 search queries from interview answers + scrape + competitor list.

    Rules fire in fixed order; each adds to `out` only if Jaccard < 0.7 vs
    already-queued. Maximum MAX_QUERIES queries. See module docstring for the
    derivation spec.
    """
    t2 = (answers.get("what_offering") or "").strip()
    t3 = (answers.get("who_to_reach") or "").strip()
    t4 = (answers.get("pain_quote") or "").strip()
    competitors = competitors or []

    out: list[str] = []
    token_sets: list[set[str]] = []

    # Rule 1: T4 pain, truncated at first major punctuation. The full T4 can
    # be 200+ chars (Claude synthesizes a paragraph after the URL fetch); a
    # short cleaned phrase searches better than a comma-spliced paragraph.
    if len(t4) >= 8:
        t4_first = re.split(r"[.,;:!?]|\s+\(", t4, maxsplit=1)[0].strip()
        if len(t4_first) >= 8:
            _add_query(out, token_sets, t4_first)
        elif t4:
            _add_query(out, token_sets, t4)

    # Rule 2: pain + buyer-noun
    if t4 and len(out) < MAX_QUERIES:
        buyer = _extract_buyer_noun(t3)
        if buyer:
            _add_query(out, token_sets, f"{t4} {buyer}")

    # Rule 2.5: vertical (only fires on Tier-A retry after clarifier)
    if vertical and len(out) < MAX_QUERIES:
        v_norm = vertical.strip().lower()
        if v_norm and v_norm != "general":
            buyer = _extract_buyer_noun(t3) or ""
            _add_query(out, token_sets, f"{v_norm} {buyer} {t4}".strip())

    # Rule 3: replacing-competitor (up to 2 competitors).
    # Multi-word names get wrapped in quotes so Reddit treats them as exact
    # phrases. Without quotes, "Drake Software" matches gaming subs that
    # mention "Drake" (the rapper). With quotes, only threads with the literal
    # two-word phrase match. Single-word names (n8n, Salesforce, Zapier)
    # skip the wrap since they're already unambiguous.
    used_competitors = 0
    for c in competitors:
        if used_competitors >= 2 or len(out) >= MAX_QUERIES:
            break
        c = (c or "").strip().lower()
        if not c or "." in c[:3]:  # skip TLD-only or empty
            continue
        # Drop TLD for cleaner phrasing: "instantly.ai" -> "instantly"
        c_clean = c.split(".")[0] if "." in c else c
        # Quote-wrap if multi-word for Reddit's exact-phrase search
        c_phrase = f'"{c_clean}"' if " " in c_clean else c_clean
        if _add_query(out, token_sets, f"replacing {c_phrase}"):
            used_competitors += 1
        if used_competitors < 2 and len(out) < MAX_QUERIES:
            _add_query(out, token_sets, f"{c_phrase} alternative")

    # Rule 4: price-rage variant (conditional on T4 matching the trigger)
    if t4 and _PRICE_RAGE_RE.search(t4) and len(out) < MAX_QUERIES:
        _add_query(out, token_sets, "saas price increase alternatives")

    # Rule 5: offering pain (T2 noun + "too expensive" or "replacement")
    offering = _extract_offering_pain(t2)
    if offering and len(out) < MAX_QUERIES:
        # Pick the suffix that adds new tokens vs what's already queued
        for suffix in ("too expensive", "replacement", "alternatives"):
            if _add_query(out, token_sets, f"{offering} {suffix}"):
                break

    # Rule 6: homepage-derived pain
    if scrape_markdown and len(out) < MAX_QUERIES:
        homepage_pain = _extract_homepage_pain(scrape_markdown)
        if homepage_pain:
            _add_query(out, token_sets, homepage_pain)

    # Rule 7: T4 noun-phrase extraction. Pulls 2-3 word phrases that aren't
    # stopwords (e.g. "GTM tool stack", "per-seat pricing", "cold email infra")
    # and appends " alternatives" so Reddit's index matches buying intent.
    if t4 and len(out) < MAX_QUERIES:
        for phrase in _extract_noun_phrases(t4):
            if len(out) >= MAX_QUERIES:
                break
            _add_query(out, token_sets, f"{phrase} alternatives")

    return out


def _extract_noun_phrases(text: str) -> list[str]:
    """Pull 2-3 word noun phrases from T4 / T2 free text.

    Heuristic: split on punctuation, then on each chunk pull groups of
    consecutive alphabetic tokens (each > 2 chars, none in stopwords) of
    length 2-3. Returns deduped phrases in order of appearance.

    Example input: "SaaS price hikes, per-seat tax compounding as team grows,
    expensive GTM tool stacks (outreach, scrapers, enrichment)"
    Example output: ["saas price hikes", "per-seat tax compounding",
    "gtm tool stacks"]
    """
    if not text:
        return []
    chunks = re.split(r"[.,;:!?()\[\]]|\s+(?:and|or|with|of|the|for|as|in|at)\s+",
                      text.lower())
    out: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        tokens = re.findall(r"[a-z][a-z\-]{2,}", chunk)
        # Walk windows of 2-3 consecutive non-stopword tokens
        for size in (3, 2):
            for i in range(len(tokens) - size + 1):
                window = tokens[i:i + size]
                if all(w not in _BUYER_STOPWORDS and len(w) > 2 for w in window):
                    phrase = " ".join(window)
                    if phrase not in seen and len(phrase) >= 8:
                        seen.add(phrase)
                        out.append(phrase)
        if len(out) >= 4:
            break
    return out[:4]


# ─── 2. Search execution ───────────────────────────────────────────────


def search_reddit(query: str, sleep_between: float = 0.5) -> list[dict[str, Any]]:
    """Reddit native /search.json. Always available, no creds, no cost.

    Returns list of normalized threads: {sub, title, score, num_comments,
    created_utc, source_query, source: "reddit_native", permalink}.
    """
    if not query:
        return []
    encoded = urllib.parse.quote(query)
    # `old.reddit.com` historically rate-limits /search.json less aggressively
    # than the www subdomain. If old gives 403 too, fall back to www.
    primary = (
        f"https://old.reddit.com/search.json?q={encoded}"
        f"&restrict_sr=off&sort=relevance&limit=25&t=year"
    )
    raw = reddit.fetch_json(primary)
    if raw is None:
        fallback = (
            f"https://www.reddit.com/search.json?q={encoded}"
            f"&restrict_sr=off&sort=relevance&limit=25&t=year"
        )
        raw = reddit.fetch_json(fallback)
    if not raw:
        return []
    threads: list[dict[str, Any]] = []
    for child in (raw.get("data") or {}).get("children", []):
        d = child.get("data") or {}
        sub = (d.get("subreddit") or "").strip()
        if not sub or not _SUBNAME_RE.match(sub):
            continue
        title = d.get("title", "")
        # Intent gate (hybrid): noise-listed subs MUST have a buyer-intent
        # token in the title (otherwise wallstreetbets + venting subs leak in
        # via lexical match). Subs NOT in the denylist get a free pass; the
        # fact that a clean operator sub is surfacing for the user's pain
        # phrasing is itself the signal, even if the specific title doesn't
        # contain "alternative" or "switching".
        sub_key = sub.lower()
        if sub_key in NOISE_DOWNRANK_SUBS and not _has_buyer_intent(title):
            continue
        threads.append({
            "sub": sub,
            "title": title,
            "score": int(d.get("score") or 0),
            "num_comments": int(d.get("num_comments") or 0),
            "created_utc": int(d.get("created_utc") or 0),
            "permalink": d.get("permalink", ""),
            "source_query": query,
            "source": "reddit_native",
        })
    if sleep_between > 0:
        time.sleep(sleep_between)
    return threads


def search_dfs(query: str, conn) -> list[dict[str, Any]]:
    """site:reddit.com SERP via DataForSEO. Empty when DFS not configured.

    The query is prefixed with `site:reddit.com` so Google returns
    Reddit-only results; otherwise DFS does general-web SERP and we get a
    handful of off-platform mentions.
    """
    if not query:
        return []
    scoped = f'site:reddit.com "{query}"' if " " in query else f"site:reddit.com {query}"
    raw = enrich.dfs_serp_advanced(scoped, conn)
    if not raw:
        return []
    threads: list[dict[str, Any]] = []
    for item in raw.get("items", []) or []:
        url = item.get("url") or ""
        m = _DFS_SUB_RE.search(url)
        if not m:
            continue
        sub = m.group(1)
        if not _SUBNAME_RE.match(sub):
            continue
        title = item.get("title", "") or ""
        snippet = item.get("snippet", "") or ""
        # Intent gate (hybrid, same rule as Reddit native): noise-listed subs
        # require buyer-intent in title or snippet; clean subs leak through.
        sub_key = sub.lower()
        if (sub_key in NOISE_DOWNRANK_SUBS
                and not (_has_buyer_intent(title) or _has_buyer_intent(snippet))):
            continue
        threads.append({
            "sub": sub,
            "title": title,
            # DFS doesn't give us upvotes / comment counts. Treat them as
            # neutral signals; rank() handles zeros via log(1+x) gracefully.
            "score": 0,
            "num_comments": 0,
            # Approximate recency: DFS gives no thread timestamp. Treat as
            # "indexed recently" by setting now-180d so it doesn't dominate
            # or get dropped. The rank function weights this less than
            # frequency anyway.
            "created_utc": int(time.time()) - 180 * 86400,
            "permalink": url,
            "source_query": query,
            "source": "dfs",
        })
    return threads


# ─── 3. Subreddit harvesting + ranking ─────────────────────────────────


def rank_subs(threads: list[dict[str, Any]],
              user_vocab: set[str] | None = None) -> list[dict[str, Any]]:
    """Aggregate threads per subreddit, score, sort desc by final_score.

    Args:
        threads: harvested threads from search_reddit + search_dfs.
        user_vocab: optional set of lowercase tokens from T2/T3/T4. When
            provided, subs whose names contain any of these tokens get the
            USER_VOCAB_BONUS. This is the "topically related to what the user
            sells" signal that prevents an accounting SaaS from ranking
            r/ecommerce alongside r/Accounting.

    Returns list of {name, score, why, thread_count, sources, noise_downranked}
    sorted high-to-low. Threads older than FRESHNESS_CUTOFF_DAYS are dropped.
    Single-thread subs (< MIN_THREAD_COUNT) are dropped to kill coincidental
    lexical matches.
    """
    now = int(time.time())
    cutoff = now - FRESHNESS_CUTOFF_DAYS * 86400

    # Bucket threads by lowercase sub name (preserve original casing for display)
    buckets: dict[str, dict[str, Any]] = {}
    for t in threads:
        if int(t.get("created_utc") or 0) < cutoff:
            continue
        sub_raw = (t.get("sub") or "").strip()
        if not sub_raw:
            continue
        key = sub_raw.lower()
        b = buckets.setdefault(key, {
            "display_name": sub_raw,
            "threads": [],
            "queries": set(),
        })
        b["threads"].append(t)
        b["queries"].add(t.get("source_query", ""))

    ranked: list[dict[str, Any]] = []
    for key, b in buckets.items():
        ts = b["threads"]
        n = len(ts)
        # Hard gate 1: drop single-thread coincidental matches.
        if n < MIN_THREAD_COUNT:
            continue
        freq = len(b["queries"])
        # Hard gate 2: drop subs that don't pass relevance signal. A sub is
        # considered relevant if EITHER (a) its name shares a token with the
        # user's domain vocabulary (T2/T3/T4 keywords), OR (b) it appears in
        # the results of 2+ distinct queries (cross-query confirmation).
        # Subs that only match ONE generic query and don't share vocabulary
        # are almost always lexical noise (r/Helldivers, r/ecommerce on an
        # accounting query, etc).
        vocab_match = (user_vocab is not None
                       and _sub_matches_user_vocab(key, user_vocab))
        if not vocab_match and freq < 2:
            continue
        # quality: average of log1p(upvotes) + log1p(comments) per thread,
        # capped at QUALITY_CEILING. Capping is critical because a single
        # viral thread can crush the cross-query frequency signal otherwise.
        quality_sum = sum(
            math.log1p(max(0, t.get("score") or 0)) +
            math.log1p(max(0, t.get("num_comments") or 0))
            for t in ts
        )
        quality = min(quality_sum / n, QUALITY_CEILING)
        # recency: mean of exp(-age_days / 365)
        recency_sum = sum(
            math.exp(-max(0, (now - (t.get("created_utc") or now))) / 86400 / 365)
            for t in ts
        )
        recency = recency_sum / n
        # Score formula (v3): frequency is the dominant signal, thread count
        # adds volume, quality + recency are tiebreakers, vocabulary-overlap
        # bonus rewards subs whose name shares tokens with what the user
        # actually sells (data-driven, not a static list).
        vocab_bonus = USER_VOCAB_BONUS if vocab_match else 0.0
        raw_score = (
            freq * 5.0                       # cross-query confirmation
            + math.log1p(n) * 2.0            # thread volume
            + quality                        # per-thread engagement, capped
            + recency * 0.5                  # mild recency tiebreaker
            + vocab_bonus
        )
        noise_mult = NOISE_DOWNRANK_FACTOR if key in NOISE_DOWNRANK_SUBS else 1.0
        final_score = raw_score * noise_mult

        # Pick the highest-raw-score thread for why-line attribution
        top = max(
            ts,
            key=lambda t: (t.get("score") or 0) + (t.get("num_comments") or 0),
        )
        top_query = top.get("source_query", "")
        plural = "s" if n != 1 else ""
        why = f"found in {n} thread{plural} matching '{top_query}'"

        ranked.append({
            "name": b["display_name"],
            "score": round(final_score, 3),
            "why": why,
            "thread_count": n,
            "sources": sorted({t.get("source", "") for t in ts}),
            "noise_downranked": noise_mult < 1.0,
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:MAX_SUBS_RETURNED]


# ─── 4. Fallback + end-to-end entry point ──────────────────────────────


def _gather_inputs(homepage_url: str, conn) -> tuple[str, list[str]]:
    """Pull cached Firecrawl markdown + DFS competitors for the homepage.

    Both are cache-reads. If the warmup hasn't fired yet (or DFS/FC are
    disabled), returns empty strings/lists; derivation falls back to T2/T3/T4
    only, which is still useful.
    """
    markdown = ""
    competitors: list[str] = []

    # Firecrawl scrape cache
    if homepage_url:
        # Normalize for cache key match: enrich.fc_scrape uses validated URL
        try:
            normalized = net.validate_url(homepage_url, kind="discover homepage")
        except ValueError:
            normalized = homepage_url
        fc_key = enrich.cache_key("scrape", normalized)
        hit = store.enrich_get(conn, "firecrawl", "scrape", fc_key)
        if hit and not hit["error"]:
            try:
                payload = json.loads(hit["payload_json"])
                markdown = payload.get("markdown") or ""
            except json.JSONDecodeError:
                pass

    # DFS competitors cache. Domain-extract from homepage_url same way warmup does.
    domain = homepage_url
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
            break
    domain = domain.split("/")[0].strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if domain:
        dfs_key = enrich.cache_key("competitors_domain", domain, 10)
        hit = store.enrich_get(conn, "dataforseo", "competitors_domain", dfs_key)
        if hit and not hit["error"]:
            try:
                payload = json.loads(hit["payload_json"])
                competitors = payload.get("competitors") or []
            except json.JSONDecodeError:
                pass

    return markdown, competitors


def _vertical_clarifier_prompt() -> str:
    return (
        "Could not find specific communities from your pain phrasing.\n"
        "What industry vertical do your customers work in?\n\n"
        "→  e.g. e-commerce, healthtech, fintech, legal, real estate\n"
        "→  Or 'general' if you sell horizontally."
    )


def discover_subs_for_profile(
    answers: dict[str, str],
    homepage_url: str,
    conn,
    *,
    vertical: str | None = None,
    deadline: float | None = None,
    extra_competitors: list[str] | None = None,
) -> dict[str, Any]:
    """End-to-end discovery: derive → search (DFS + Reddit native) → rank → fallback.

    Args:
        answers: dict with keys what_offering, who_to_reach, pain_quote (T2/T3/T4).
        homepage_url: the user's homepage URL (used for cache lookups).
        conn: SQLite connection (with enrichment_cache table).
        vertical: optional, set on Tier-A retry after the clarifier sub-turn.
        deadline: optional wall-clock deadline (time.time() + N). Hard-limit on
            search loop. Defaults to start + DISCOVERY_HARD_TIMEOUT_S.

    Returns:
        {
          "subs": [{name, score, why, thread_count, sources, noise_downranked}, ...],
          "queries_used": [str, ...],
          "needs_clarification": bool,
          "clarifier_prompt": str | None,
          "discovery_unreachable": bool,
          "source_mix": {"dfs": int, "reddit_native": int},
        }
    """
    start = time.time()
    if deadline is None:
        deadline = start + DISCOVERY_HARD_TIMEOUT_S

    markdown, competitors = _gather_inputs(homepage_url, conn)
    # Merge any caller-supplied competitors (e.g. Claude's WebFetch results from
    # the skill) with cached DFS competitors. Skill-supplied ones go FIRST so
    # rule 3 picks the most accurate brands.
    if extra_competitors:
        seen = {c.lower() for c in extra_competitors}
        merged = list(extra_competitors)
        merged.extend(c for c in competitors if c.lower() not in seen)
        competitors = merged
    queries = derive_queries(answers, markdown, competitors, vertical=vertical)

    # Empty / pathological input: skip directly to Tier A
    if len(queries) < 1:
        return {
            "subs": [],
            "queries_used": [],
            "needs_clarification": True,
            "clarifier_prompt": _vertical_clarifier_prompt(),
            "discovery_unreachable": False,
            "source_mix": {"dfs": 0, "reddit_native": 0},
        }

    providers = enrich.detect_providers()
    dfs_available = providers.get("dataforseo", False)
    threads: list[dict[str, Any]] = []
    source_mix = {"dfs": 0, "reddit_native": 0}
    any_provider_responded = False

    for q in queries:
        if time.time() > deadline:
            _log(f"hard timeout after {len(threads)} threads")
            break

        # Reddit native (always)
        try:
            r_threads = search_reddit(q, sleep_between=0.5)
            if r_threads:
                any_provider_responded = True
            threads.extend(r_threads)
            source_mix["reddit_native"] += len(r_threads)
        except Exception as e:
            _log(f"reddit search error for '{q}': {type(e).__name__}")

        if time.time() > deadline:
            break

        # DFS (when configured)
        if dfs_available:
            try:
                d_threads = search_dfs(q, conn)
                if d_threads:
                    any_provider_responded = True
                threads.extend(d_threads)
                source_mix["dfs"] += len(d_threads)
            except Exception as e:
                _log(f"dfs search error for '{q}': {type(e).__name__}")

    user_vocab = _build_user_vocabulary(answers)
    ranked = rank_subs(threads, user_vocab=user_vocab)

    # All non-noise subs surviving?
    non_noise_count = sum(1 for r in ranked if not r["noise_downranked"])
    needs_clarification = (
        len(ranked) < MIN_SUBS_THRESHOLD
        or non_noise_count < 3
    ) and vertical is None  # don't ask twice

    discovery_unreachable = (
        not any_provider_responded
        and source_mix["reddit_native"] == 0
        and source_mix["dfs"] == 0
    )

    return {
        "subs": ranked,
        "queries_used": queries,
        "needs_clarification": needs_clarification,
        "clarifier_prompt": _vertical_clarifier_prompt() if needs_clarification else None,
        "discovery_unreachable": discovery_unreachable,
        "source_mix": source_mix,
    }
