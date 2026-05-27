"""Dogfood Dan's hard rule: zero em dashes in user-facing output.

Scans every string the output module can produce. Code comments and docstrings
are allowed em dashes; user-facing rendered text is not.

Also scans non-docstring string literals in lib modules that emit user-facing
strings (currently enrich.py + net.py stderr/log messages).
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subscope.lib import output  # noqa: E402


EM = "—"  # —
EN = "–"  # –


def _non_docstring_string_literals(source: str) -> list[str]:
    """Walk an AST and collect every str-typed Constant node that is NOT the
    first statement of a module/function/class (i.e. not a docstring).

    Returns the list of string values. Comments are not in the AST so they're
    automatically exempt. Module-level docstring, function/class docstrings
    are skipped.
    """
    tree = ast.parse(source)
    docstring_node_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and \
               isinstance(body[0].value, ast.Constant) and \
               isinstance(body[0].value.value, str):
                docstring_node_ids.add(id(body[0].value))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstring_node_ids:
            out.append(node.value)
    return out


def _make_surfaces():
    return [
        {
            "post": {
                "id": "p1", "subreddit": "smallbusiness",
                "title": "Test post",
                "url": "https://reddit.com/r/smallbusiness/comments/p1/test/",
                "canonical_url": "https://reddit.com/comments/p1/",
                "author": "u", "created_utc": 1748100000 - 3600,
                "score": 10, "num_comments": 3, "body": "x",
            },
            "sub": {"name": "smallbusiness", "tier": 1, "saturation": None},
            "blog_matches": [],
            "score_internal": 50.0,
        },
        {
            "post": {
                "id": "p2", "subreddit": "Bookkeeping",
                "title": "Another",
                "url": "https://reddit.com/r/Bookkeeping/comments/p2/another/",
                "canonical_url": "https://reddit.com/comments/p2/",
                "author": "u2", "created_utc": 1748100000 - 7200,
                "score": 20, "num_comments": 5, "body": "y",
            },
            "sub": {"name": "Bookkeeping", "tier": 2, "saturation": "wide_open"},
            "blog_matches": [{"title": "Bill.com post", "url": "https://x/y", "matched_keywords": []}],
            "score_internal": 80.0,
        },
    ]


def test_render_has_no_em_dashes():
    surfaces = _make_surfaces()
    rendered = output.render(surfaces, run_notes="all good", dropped_counts={"tier2_velocity_floor": 12})
    assert EM not in rendered, f"em dash leaked into output:\n{rendered}"
    assert EN not in rendered, f"en dash leaked into output:\n{rendered}"


def test_render_empty_has_no_em_dashes():
    rendered = output.render([], run_notes="empty day")
    assert EM not in rendered
    assert EN not in rendered


def test_render_json_payload_has_no_em_dashes():
    payload = output.render_json_payload(_make_surfaces())
    import json
    text = json.dumps(payload, ensure_ascii=False)
    assert EM not in text, f"em dash leaked into JSON payload:\n{text}"
    assert EN not in text


def test_enrich_module_string_literals_have_no_em_dashes():
    """ENR-2 + DFS-1 + FC-1 added user-facing stderr messages. Scan them."""
    enrich_path = Path(__file__).resolve().parent.parent / "subscope" / "lib" / "enrich.py"
    literals = _non_docstring_string_literals(enrich_path.read_text())
    for lit in literals:
        assert EM not in lit, f"em dash in enrich.py string literal: {lit!r}"
        assert EN not in lit, f"en dash in enrich.py string literal: {lit!r}"


def test_net_module_string_literals_have_no_em_dashes():
    net_path = Path(__file__).resolve().parent.parent / "subscope" / "lib" / "net.py"
    literals = _non_docstring_string_literals(net_path.read_text())
    for lit in literals:
        assert EM not in lit, f"em dash in net.py string literal: {lit!r}"
        assert EN not in lit, f"en dash in net.py string literal: {lit!r}"


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
