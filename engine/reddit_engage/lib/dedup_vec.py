"""Semantic dedup via sqlite-vec + BGE-small embeddings.

Optional install:
    pip install -e '.[vec]'

That brings in `sqlite-vec` (the SQLite extension) and `sentence-transformers`
(the embedding model loader). Without both, this module's public functions
are no-ops — the daily run still works, just without semantic dedup.

## What it dedups against

For each new candidate post that passes the regex gate, we compute its
embedding and compare against embeddings of posts surfaced in the last
`window_days`. If max cosine similarity > `threshold`, we treat the new
post as a near-duplicate and drop it.

## Why BGE-small

`BAAI/bge-small-en-v1.5` (33M params, 384-dim) is the right cost-quality
balance for short-text social. Runs CPU-only at ~1s per post on M-series
Macs. No GPU required, no API calls. Free.

## Schema

Stored in the same sqlite-vec virtual table. Created on first call.

```sql
-- conceptual schema
CREATE VIRTUAL TABLE post_embeddings USING vec0(
    post_id TEXT PRIMARY KEY,
    embedding float[384]
);
```

## Graceful degradation

`is_available()` checks both deps + the sqlite-vec extension. If anything
is missing, all public functions short-circuit. Callers must always
treat "no match" as "novel post" — never block surfacing on dedup failure.
"""
from __future__ import annotations

import sys
from typing import Any

# Lazy globals — only loaded if is_available() returns True
_MODEL = None
_EMBEDDING_DIM = 384  # BGE-small-en-v1.5


def _log(msg: str) -> None:
    sys.stderr.write(f"[dedup_vec] {msg}\n")
    sys.stderr.flush()


def is_available() -> bool:
    """Return True if sqlite-vec extension AND sentence-transformers are installed."""
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        return False
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def _load_model():
    """Lazy-load BGE-small-en-v1.5. Cached process-wide.

    First call downloads ~130MB of model weights to HuggingFace cache.
    Subsequent calls reuse the loaded instance.
    """
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    from sentence_transformers import SentenceTransformer  # type: ignore
    _MODEL = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return _MODEL


def embed_text(text: str) -> list[float] | None:
    """Compute a 384-dim embedding for `text`. Returns None if model unavailable."""
    if not is_available():
        return None
    model = _load_model()
    vec = model.encode(text, normalize_embeddings=True)
    return [float(x) for x in vec]


def ensure_schema(conn) -> bool:
    """Create the sqlite-vec virtual table if missing. Returns True on success.

    The sqlite-vec extension must be loaded via `conn.enable_load_extension(True)`
    + `sqlite_vec.load(conn)`. Connection management is the caller's responsibility.
    """
    if not is_available():
        return False
    try:
        import sqlite_vec  # type: ignore
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS post_embeddings "
            f"USING vec0(post_id TEXT PRIMARY KEY, embedding float[{_EMBEDDING_DIM}])"
        )
        return True
    except Exception as e:
        _log(f"sqlite-vec schema setup failed: {e}")
        return False


def store_embedding(conn, post_id: str, embedding: list[float]) -> bool:
    """Persist a post's embedding. Idempotent (REPLACE)."""
    if not ensure_schema(conn):
        return False
    try:
        import struct
        blob = struct.pack(f"{_EMBEDDING_DIM}f", *embedding)
        conn.execute(
            "INSERT OR REPLACE INTO post_embeddings(post_id, embedding) VALUES(?, ?)",
            (post_id, blob),
        )
        return True
    except Exception as e:
        _log(f"store_embedding failed: {e}")
        return False


def is_duplicate(
    conn,
    candidate_text: str,
    threshold: float = 0.92,
    window_size: int = 1000,
) -> tuple[bool, float | None]:
    """Return (is_dupe, max_similarity).

    Compares candidate's embedding to the most recent `window_size` stored
    embeddings (proxy for "last 90 days") via sqlite-vec's L2 distance.
    L2 on normalized vectors converts to cosine: cos_sim = 1 - L2^2/2.

    If anything fails (no extension, no model, malformed cache), returns
    (False, None) — meaning "treat as novel". Never blocks a real surface.
    """
    if not is_available():
        return False, None

    emb = embed_text(candidate_text)
    if emb is None:
        return False, None

    if not ensure_schema(conn):
        return False, None

    try:
        import struct
        blob = struct.pack(f"{_EMBEDDING_DIM}f", *emb)
        rows = conn.execute(
            "SELECT distance FROM post_embeddings "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT 1",
            (blob,),
        ).fetchall()
    except Exception as e:
        _log(f"vector search failed: {e}")
        return False, None

    if not rows:
        return False, None

    l2 = float(rows[0][0])
    # Convert L2 (normalized vecs) to cosine similarity
    cos_sim = 1.0 - (l2 * l2) / 2.0
    return cos_sim >= threshold, cos_sim


def install_sqlite_vec_help() -> str:
    """Human-readable install instructions, for `reddit-engage status`."""
    return (
        "Semantic dedup requires:\n"
        "  pip install -e '.[vec]'\n\n"
        "On first use, BGE-small model (~130MB) downloads to ~/.cache/huggingface."
    )
