"""SS-105: no user-facing surface may suggest Reddit OAuth or an API key.

The product is keyless by design. A stale build once told a user to "set up a
Reddit OAuth token" on a 403, which is exactly wrong. These tests lock the
invariant two ways:
  1. the engine's user-facing renderer never emits 'oauth' / 'api key'
  2. the run + onboard skills KEEP their explicit prohibition (so a future edit
     that drops the guardrail fails CI)
This complements test_reddit.test_no_oauth_surface (which guards the module API).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = Path(__file__).resolve().parents[2]
_SKILLS = _ROOT / "skills"
_ENGINE = _ROOT / "engine" / "subscope"


def test_engine_renderer_emits_no_oauth_or_apikey():
    out = (_ENGINE / "lib" / "output.py").read_text().lower()
    assert "oauth" not in out
    assert "api key" not in out
    assert "api-key" not in out


def test_run_skill_keeps_oauth_prohibition():
    text = (_SKILLS / "run" / "SKILL.md").read_text().lower()
    # OAuth is mentioned ONLY to forbid suggesting it; the guardrail must remain.
    assert "oauth" in text
    assert "do not" in text
    assert "keyless" in text


def test_onboard_skill_keeps_oauth_prohibition():
    text = (_SKILLS / "onboard" / "SKILL.md").read_text().lower()
    assert "oauth" in text
    assert "do not" in text
    assert "keyless" in text


def test_no_skill_positively_suggests_reddit_auth():
    # Catch positive-suggestion shapes while allowing the prohibition form the
    # guardrail uses ("Do NOT ... set up Reddit OAuth"). A line only fails if it
    # contains a suggestion phrase WITHOUT a negation on the same line.
    forbidden = [
        "set up a reddit oauth",
        "set up reddit oauth",
        "configure reddit oauth",
        "configure a reddit api key",
        "add a reddit api key",
        "you need a reddit api key",
        "create a reddit app",
    ]
    negations = ["do not", "don't", "never", "no such", "not suggest",
                 "there is no", "no login", "without"]
    for skill_md in _SKILLS.glob("**/SKILL.md"):
        for ln in skill_md.read_text().lower().splitlines():
            if any(p in ln for p in forbidden) and not any(n in ln for n in negations):
                raise AssertionError(
                    f"{skill_md.name} positively suggests Reddit auth: {ln.strip()!r}"
                )
