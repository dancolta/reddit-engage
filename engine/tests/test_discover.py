"""Tests for live subreddit discovery (engine/subscope/lib/discover.py).

Covers all five spec concerns in one file:
1. derive_queries — query construction from interview answers + scrape + competitors
2. search_dfs — DFS SERP harvest (mocks enrich.dfs_serp_advanced)
3. search_reddit — Reddit native search (mocks reddit.fetch_json)
4. rank_subs — scoring, noise downrank, freshness cutoff
5. fallback + e2e — needs_clarification triggers, discovery_unreachable, full flow

Mocks are surgical: we patch the HTTP seams (enrich.dfs_serp_advanced /
reddit.fetch_json) not the higher-level functions, so the test exercises the
real harvest + dedup + scoring code paths.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import discover, enrich, reddit, store  # noqa: E402


NOW = int(time.time())


# ─── Helpers ───────────────────────────────────────────────────────────


def _conn():
    """In-memory SQLite with enrichment_cache table installed."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    store._ensure_enrichment_cache_table(c)
    return c


def _reddit_search_response(*threads_args) -> dict:
    """Build a /search.json-shaped response. Titles include a buyer-intent
    token by default so threads pass the intent gate."""
    children = []
    for sub, score, num_comments, age_days in threads_args:
        children.append({"data": {
            "subreddit": sub,
            "title": f"alternative to thing in {sub}?",
            "score": score,
            "num_comments": num_comments,
            "created_utc": NOW - age_days * 86400,
            "permalink": f"/r/{sub}/comments/abc123/",
        }})
    return {"data": {"children": children}}


def _dfs_serp_response(*urls) -> dict:
    """Build a dfs_serp_advanced-shaped payload. Snippets include a buyer-intent
    token so threads pass the intent gate."""
    return {
        "query": "test",
        "items": [{"url": u, "title": f"title for {u}",
                   "snippet": "looking for an alternative"} for u in urls],
    }


# ─── 1. derive_queries ────────────────────────────────────────────────


def test_derive_queries_dan_real_case():
    """The exact case Dan ran: AI automations / SME founders / saas price + cold email."""
    answers = {
        "what_offering": "ai automations and replacements for saas subscriptions",
        "who_to_reach": "founders of sme's 5-15 people",
        "pain_quote": "saas price increased, expensive infrastructure for cold email outreaches",
    }
    queries = discover.derive_queries(answers, scrape_markdown=None,
                                      competitors=["instantly.ai", "smartlead.ai"])
    # Must include the verbatim pain (rule 1) and price-rage anchor (rule 4)
    assert any("saas price increased" in q for q in queries)
    assert any("price increase alternatives" in q for q in queries)
    # Competitors get cleaned and queried (rule 3)
    assert any("instantly" in q for q in queries)
    # Capped at MAX_QUERIES
    assert len(queries) <= discover.MAX_QUERIES


def test_derive_queries_empty_answers_returns_empty():
    queries = discover.derive_queries({"what_offering": "", "who_to_reach": "",
                                       "pain_quote": ""})
    assert queries == []


def test_derive_queries_jaccard_dedup():
    """Two near-identical inputs should not produce duplicate queries."""
    answers = {
        "what_offering": "saas tool",
        "who_to_reach": "founders",
        "pain_quote": "saas tool too expensive",
    }
    queries = discover.derive_queries(answers)
    # Rule 1 ("saas tool too expensive") and rule 5 (offering pain
    # "saas tool too expensive") would collide — Jaccard dedup must catch it
    norm = [q.replace(" ", "") for q in queries]
    assert len(set(norm)) == len(norm), f"duplicate queries: {queries}"


def test_derive_queries_vertical_clarifier_adds_query():
    answers = {
        "what_offering": "automation",
        "who_to_reach": "founders",
        "pain_quote": "tools cost too much",
    }
    base = discover.derive_queries(answers)
    with_vertical = discover.derive_queries(answers, vertical="accounting")
    assert any("accounting" in q for q in with_vertical)
    assert len(with_vertical) >= len(base)


def test_derive_queries_no_company_name_injection():
    """Company name from T2 must not bleed into the queries."""
    answers = {
        "what_offering": "nodesparks helps you automate everything",
        "who_to_reach": "saas founders",
        "pain_quote": "manual work is killing us",
    }
    queries = discover.derive_queries(answers)
    # We don't extract company names, but we do extract offering pain. Make
    # sure no query is literally the company name.
    for q in queries:
        assert "nodesparks" not in q, f"company name leaked into query: {q}"


def test_derive_queries_homepage_pain_extraction():
    answers = {"what_offering": "x", "who_to_reach": "y", "pain_quote": "billing pain"}
    md = "We help teams tired of paying for legacy CRM tools every month."
    queries = discover.derive_queries(answers, scrape_markdown=md)
    assert any("paying for legacy crm tools" in q for q in queries), queries


# ─── 2. search_dfs ────────────────────────────────────────────────────


def test_search_dfs_harvests_subs_from_urls():
    c = _conn()
    resp = _dfs_serp_response(
        "https://www.reddit.com/r/microsaas/comments/abc/foo/",
        "https://reddit.com/r/Bookkeeping/comments/def/bar/",
        "https://example.com/not-reddit",
        "https://www.reddit.com/r/SaaS/comments/xyz/baz/",
    )
    with patch.object(enrich, "dfs_serp_advanced", return_value=resp):
        threads = discover.search_dfs("test query", c)
    subs = [t["sub"] for t in threads]
    assert "microsaas" in subs
    assert "Bookkeeping" in subs
    assert "SaaS" in subs
    # Non-reddit URL skipped
    assert all("not-reddit" not in t.get("permalink", "") for t in threads)


def test_search_dfs_empty_query_returns_empty():
    c = _conn()
    assert discover.search_dfs("", c) == []


def test_search_dfs_disabled_returns_empty():
    """When dfs_serp_advanced returns None (creds absent), discover handles it."""
    c = _conn()
    with patch.object(enrich, "dfs_serp_advanced", return_value=None):
        threads = discover.search_dfs("anything", c)
    assert threads == []


# ─── 3. search_reddit ─────────────────────────────────────────────────


def test_search_reddit_extracts_threads():
    # Each thread needs a buyer-intent title or it's filtered out.
    resp = {"data": {"children": [
        {"data": {"subreddit": "microsaas", "title": "alternative to Mailchimp?",
                  "score": 50, "num_comments": 12, "created_utc": NOW - 30 * 86400,
                  "permalink": "/r/microsaas/comments/a/x/"}},
        {"data": {"subreddit": "EntrepreneurRideAlong", "title": "switching from Apollo",
                  "score": 80, "num_comments": 5, "created_utc": NOW - 60 * 86400,
                  "permalink": "/r/Era/comments/b/y/"}},
        {"data": {"subreddit": "SaaS", "title": "looking for cheaper CRM",
                  "score": 200, "num_comments": 40, "created_utc": NOW - 14 * 86400,
                  "permalink": "/r/SaaS/comments/c/z/"}},
    ]}}
    with patch.object(reddit, "fetch_json", return_value=resp):
        threads = discover.search_reddit("cold email expensive", sleep_between=0)
    subs = [t["sub"] for t in threads]
    assert subs == ["microsaas", "EntrepreneurRideAlong", "SaaS"]
    assert all(t["source"] == "reddit_native" for t in threads)


def test_search_reddit_filters_non_intent_titles():
    """Thread titles without buyer-intent tokens (alternative/switch/replace/etc)
    must be dropped before harvest. This is the bigger fix from live smoke:
    r/wallstreetbets matched 'saas subscriptions too expensive' as stock chatter."""
    resp = {"data": {"children": [
        # Has intent → kept
        {"data": {"subreddit": "microsaas", "title": "alternatives to Klaviyo?",
                  "score": 10, "num_comments": 2, "created_utc": NOW - 30 * 86400,
                  "permalink": "/x/"}},
        # No intent token → dropped (stock analysis lexical match)
        {"data": {"subreddit": "wallstreetbets", "title": "SaaS subscriptions are too expensive, sell SF",
                  "score": 5000, "num_comments": 800, "created_utc": NOW - 7 * 86400,
                  "permalink": "/y/"}},
        # No intent token → dropped (venting)
        {"data": {"subreddit": "mildlyinfuriating", "title": "my saas keeps raising prices",
                  "score": 100, "num_comments": 30, "created_utc": NOW - 3 * 86400,
                  "permalink": "/z/"}},
    ]}}
    with patch.object(reddit, "fetch_json", return_value=resp):
        threads = discover.search_reddit("saas subscriptions expensive", sleep_between=0)
    subs = [t["sub"] for t in threads]
    assert subs == ["microsaas"]


def test_has_buyer_intent_token_matrix():
    """Spot-check the regex word-boundary matching."""
    assert discover._has_buyer_intent("alternative to Mailchimp")
    assert discover._has_buyer_intent("Switching from Apollo, recommendations?")
    assert discover._has_buyer_intent("Looking for a cheaper CRM")
    assert discover._has_buyer_intent("Anyone use Smartlead instead of Instantly?")
    # Negative cases
    assert not discover._has_buyer_intent("My saas keeps raising prices")
    assert not discover._has_buyer_intent("Just venting about pricing today")
    assert not discover._has_buyer_intent("")


def test_noise_denylist_includes_finance_and_venting():
    """The live smoke caught wallstreetbets + mildlyinfuriating as noise.
    Both must now be in NOISE_DOWNRANK_SUBS (lowercase)."""
    for sub in ("wallstreetbets", "valueinvesting", "mildlyinfuriating",
                "middleclasshq", "layoffs", "personalfinance"):
        assert sub in discover.NOISE_DOWNRANK_SUBS, f"missing from denylist: {sub}"


def test_search_reddit_rejects_bad_sub_names():
    """Sub names that don't match Reddit's rules must be dropped."""
    # All titles include a buyer-intent token so the intent gate isn't the
    # discriminator; this test is specifically about sub-name validation.
    resp = {"data": {"children": [
        {"data": {"subreddit": "fine_sub", "title": "alternative to Mailchimp?", "score": 1,
                  "num_comments": 0, "created_utc": NOW - 86400, "permalink": "/r/fine_sub/c/x/"}},
        {"data": {"subreddit": "this-has-dashes-too-long-for-reddit",
                  "title": "switching from Apollo",
                  "score": 1, "num_comments": 0, "created_utc": NOW, "permalink": ""}},
        {"data": {"subreddit": "", "title": "looking for cheaper CRM", "score": 0,
                  "num_comments": 0, "created_utc": NOW, "permalink": ""}},
    ]}}
    with patch.object(reddit, "fetch_json", return_value=resp):
        threads = discover.search_reddit("x", sleep_between=0)
    assert [t["sub"] for t in threads] == ["fine_sub"]


def test_search_reddit_network_failure_returns_empty():
    with patch.object(reddit, "fetch_json", return_value=None):
        threads = discover.search_reddit("anything", sleep_between=0)
    assert threads == []


# ─── 4. rank_subs ─────────────────────────────────────────────────────


def test_rank_subs_orders_by_frequency_first():
    """A sub appearing in 3 distinct query results should rank higher than
    a sub appearing once with higher per-thread quality."""
    threads = [
        # 3 distinct queries hit "microsaas" — frequency wins
        {"sub": "microsaas", "score": 10, "num_comments": 1, "created_utc": NOW - 86400,
         "source_query": "q1", "source": "reddit_native"},
        {"sub": "microsaas", "score": 10, "num_comments": 1, "created_utc": NOW - 86400,
         "source_query": "q2", "source": "reddit_native"},
        {"sub": "microsaas", "score": 10, "num_comments": 1, "created_utc": NOW - 86400,
         "source_query": "q3", "source": "reddit_native"},
        # 1 query hit "shinyhighscore" with very high upvotes
        {"sub": "shinyhighscore", "score": 5000, "num_comments": 200,
         "created_utc": NOW - 86400, "source_query": "q1", "source": "reddit_native"},
    ]
    ranked = discover.rank_subs(threads)
    assert ranked[0]["name"] == "microsaas"


def test_rank_subs_applies_noise_downrank():
    """r/SaaS (noise) with same raw signal as r/microsaas (clean) must rank lower."""
    threads = []
    for sub in ("microsaas", "SaaS"):
        for q in ("q1", "q2"):
            threads.append({
                "sub": sub, "score": 50, "num_comments": 10,
                "created_utc": NOW - 7 * 86400,
                "source_query": q, "source": "reddit_native",
            })
    ranked = discover.rank_subs(threads)
    by_name = {r["name"]: r for r in ranked}
    assert by_name["microsaas"]["score"] > by_name["SaaS"]["score"]
    assert by_name["SaaS"]["noise_downranked"] is True
    assert by_name["microsaas"]["noise_downranked"] is False


def test_rank_subs_drops_threads_older_than_cutoff():
    threads = [
        {"sub": "old", "score": 50, "num_comments": 10,
         "created_utc": NOW - 1000 * 86400,
         "source_query": "q1", "source": "reddit_native"},
        {"sub": "fresh", "score": 10, "num_comments": 1,
         "created_utc": NOW - 30 * 86400,
         "source_query": "q1", "source": "reddit_native"},
    ]
    ranked = discover.rank_subs(threads)
    assert [r["name"] for r in ranked] == ["fresh"]


def test_rank_subs_case_insensitive_aggregation():
    """`microSaaS` and `microsaas` should aggregate into one bucket."""
    threads = [
        {"sub": "MicroSaaS", "score": 10, "num_comments": 1,
         "created_utc": NOW - 86400, "source_query": "q1", "source": "reddit_native"},
        {"sub": "microsaas", "score": 10, "num_comments": 1,
         "created_utc": NOW - 86400, "source_query": "q2", "source": "reddit_native"},
    ]
    ranked = discover.rank_subs(threads)
    assert len(ranked) == 1
    assert ranked[0]["thread_count"] == 2


def test_rank_subs_why_line_format():
    threads = [
        {"sub": "Bookkeeping", "score": 50, "num_comments": 10,
         "created_utc": NOW - 86400,
         "source_query": "saas price increase alternatives", "source": "reddit_native"},
    ]
    ranked = discover.rank_subs(threads)
    assert ranked[0]["why"] == "found in 1 thread matching 'saas price increase alternatives'"


# ─── 5. Fallback + end-to-end ─────────────────────────────────────────


def test_e2e_dan_case_returns_subs_and_no_clarification():
    """End-to-end on Dan's real input. Mock both providers with realistic
    responses. Expect non-noise subs in the top of the ranking."""
    c = _conn()
    answers = {
        "what_offering": "ai automations and replacements for saas subscriptions",
        "who_to_reach": "founders of sme's 5-15 people",
        "pain_quote": "saas price increased, expensive infrastructure for cold email outreaches",
    }

    def fake_fetch_json(url, timeout=15):
        # Return a varied set of subs per query, with non-noise dominating
        if "saas+price+increased" in url or "saas%20price%20increased" in url:
            return _reddit_search_response(
                ("microsaas", 80, 20, 14),
                ("EntrepreneurRideAlong", 50, 15, 30),
                ("Bookkeeping", 40, 10, 21),
            )
        if "instantly" in url.lower():
            return _reddit_search_response(
                ("coldemail", 30, 8, 60),
                ("EmailMarketing", 60, 12, 45),
                ("smallbusiness", 100, 20, 30),
            )
        # default: mixed
        return _reddit_search_response(
            ("automation", 25, 5, 14),
            ("SaaS", 200, 50, 7),
            ("smallbusinessIT", 15, 3, 90),
        )

    with patch.object(reddit, "fetch_json", side_effect=fake_fetch_json):
        with patch.object(enrich, "detect_providers", return_value={"dataforseo": False,
                                                                    "firecrawl": False}):
            result = discover.discover_subs_for_profile(
                answers, "https://nodesparks.com", c,
            )

    assert result["needs_clarification"] is False
    assert len(result["subs"]) >= discover.MIN_SUBS_THRESHOLD
    # Top sub should not be r/SaaS (noise downrank in effect)
    assert result["subs"][0]["name"].lower() != "saas"
    # Queries used must be reported
    assert len(result["queries_used"]) >= 3
    assert result["source_mix"]["reddit_native"] > 0


def test_e2e_thin_results_trigger_clarification():
    """When only 1-2 non-noise subs come back, needs_clarification is set."""
    c = _conn()
    answers = {
        "what_offering": "thing",
        "who_to_reach": "people",
        "pain_quote": "it costs a lot",
    }
    # Every query returns only noise-list subs
    noise_resp = _reddit_search_response(
        ("SaaS", 50, 10, 14),
        ("Entrepreneur", 30, 5, 21),
    )
    with patch.object(reddit, "fetch_json", return_value=noise_resp):
        with patch.object(enrich, "detect_providers", return_value={"dataforseo": False,
                                                                    "firecrawl": False}):
            result = discover.discover_subs_for_profile(answers, "", c)
    assert result["needs_clarification"] is True
    assert result["clarifier_prompt"] is not None


def test_e2e_no_provider_response_flags_discovery_unreachable():
    """When fetch_json returns None for everything, discovery_unreachable=True."""
    c = _conn()
    answers = {
        "what_offering": "automation tool",
        "who_to_reach": "ops leaders",
        "pain_quote": "manual work is killing us",
    }
    with patch.object(reddit, "fetch_json", return_value=None):
        with patch.object(enrich, "detect_providers", return_value={"dataforseo": False,
                                                                    "firecrawl": False}):
            result = discover.discover_subs_for_profile(answers, "", c)
    assert result["discovery_unreachable"] is True
    assert result["subs"] == []


def test_e2e_vertical_param_suppresses_second_clarification():
    """If vertical was already provided (Tier-A retry), we don't ask again."""
    c = _conn()
    answers = {
        "what_offering": "thing",
        "who_to_reach": "people",
        "pain_quote": "it costs",
    }
    noise_resp = _reddit_search_response(("SaaS", 50, 10, 14))
    with patch.object(reddit, "fetch_json", return_value=noise_resp):
        with patch.object(enrich, "detect_providers", return_value={"dataforseo": False,
                                                                    "firecrawl": False}):
            result = discover.discover_subs_for_profile(
                answers, "", c, vertical="accounting",
            )
    assert result["needs_clarification"] is False


# ─── Misc: regex / hygiene ─────────────────────────────────────────────


def test_normalize_query_trims_leading_pronoun():
    assert discover._normalize_query("I'm tired of bad CRM") == "tired of bad crm"
    assert discover._normalize_query("We're paying too much") == "paying too much"


def test_normalize_query_word_boundary_trim():
    long_input = "this is a very long pain phrase that exceeds the maximum allowed query length cap"
    out = discover._normalize_query(long_input)
    assert len(out) <= 80
    # Must end on a word boundary, not mid-word
    assert not out.endswith(" ")


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
