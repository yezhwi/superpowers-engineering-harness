"""Static routing contract tests; not proof of external Agent compliance."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ["SKILL.md", "skills/engineering-harness/SKILL.md"]


@pytest.mark.parametrize("path", SKILLS)
def test_classified_startup_prefers_compact_without_eager_control_reads(path):
    text = (ROOT / path).read_text()
    startup = text.split("## Session Startup", 1)[1].split("## Inputs", 1)[0]
    assert "harness context --compact" in startup
    assert "classified active mutating task" in startup
    assert "Run `harness status`" not in startup
    assert "active accepted decisions from" not in startup
    assert "Do not eagerly read all control files" in startup


@pytest.mark.parametrize("path", SKILLS)
def test_q0_and_unclassified_tasks_bypass_context_generation(path):
    text = (ROOT / path).read_text()
    q0 = text.split("## Q0 Decision Table", 1)[1].split("## Session Startup", 1)[0]
    assert "do not run `harness context`" in q0
    startup = text.split("## Session Startup", 1)[1].split("## Inputs", 1)[0]
    assert "missing/null risk" in startup
    assert "harness task classify" in startup
    assert "Do not infer a risk/profile" in startup
    assert "task identity, state, and risk fields only" in startup
    assert "no active task" in startup


@pytest.mark.parametrize("path", SKILLS)
def test_integrity_failure_does_not_fallback_or_change_authority(path):
    text = (ROOT / path).read_text()
    startup = text.split("## Session Startup", 1)[1].split("## Inputs", 1)[0]
    assert "Integrity failure" in startup
    assert "Do not fall back to stale Context or persisted Gate summaries" in startup
    assert "harness context validate" in startup
    assert "existing harness CLI" in startup
    assert "No state in context only" in text
    assert "Never edit the state field by hand" in text
    inputs = text.split("## Inputs", 1)[1].split("## Request Routing", 1)[0]
    assert "Layer 2" in inputs
    assert "not a new authoritative source" in inputs


def test_installed_skill_matches_root_skill():
    assert (ROOT / SKILLS[0]).read_bytes() == (ROOT / SKILLS[1]).read_bytes()
