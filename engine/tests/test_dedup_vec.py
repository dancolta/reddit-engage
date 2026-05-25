"""Tests for the semantic dedup wrapper.

The actual embedding model + sqlite-vec extension are optional deps. These
tests verify the graceful-degradation contract: when deps are missing, all
public functions return safe no-op values.

Live integration testing requires `pip install -e '.[vec]'` and is left
manual (we won't pull 130MB of model weights into CI for this).
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reddit_engage.lib import dedup_vec  # noqa: E402


def test_unavailable_when_sqlite_vec_missing(monkeypatch):
    """No sqlite-vec → all public functions short-circuit safely."""
    # Force ImportError on sqlite_vec
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sqlite_vec":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert dedup_vec.is_available() is False
    assert dedup_vec.embed_text("hello") is None
    # is_duplicate must NEVER raise — always return (False, None) on failure
    is_dupe, sim = dedup_vec.is_duplicate(None, "hello")
    assert is_dupe is False
    assert sim is None


def test_store_embedding_noop_when_unavailable(monkeypatch):
    """store_embedding gracefully returns False (not exception) when deps missing."""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sqlite_vec":
            raise ImportError()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert dedup_vec.store_embedding(None, "post-id", [0.0] * 384) is False


def test_install_help_is_human_readable():
    """status() consumers print this — must be coherent text."""
    msg = dedup_vec.install_sqlite_vec_help()
    assert "pip install" in msg
    assert "vec" in msg


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
