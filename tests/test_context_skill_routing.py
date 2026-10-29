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


@pytest.mark.parametrize("path", SKILLS)
def test_efficiency_routing_preserves_authority_and_final_freshness(path):
    text = (ROOT / path).read_text()
    section = text.split("## Efficient Evidence Scheduling", 1)[1].split("\n## ", 1)[0]
    for required in (
        "harness evidence plan --json",
        "harness impact reconcile --file proposal.yaml --dry-run",
        "not execution authority",
        "MIGRATE does not authorize RETIRE or REBIND",
        "Once metadata is stable",
        "harness context --compact",
        "harness context validate",
        "serial",
    ):
        assert required in section


@pytest.mark.parametrize("path", SKILLS)
def test_efficiency_routing_declares_guidance_only_batch_manifest(path):
    text = (ROOT / path).read_text()
    section = text.split("## Efficient Evidence Scheduling", 1)[1].split("\n## ", 1)[0]
    for required in (
        "planned batch manifest",
        "repository-root `--covered-test` selectors",
        "preserve the original selectors",
        "complete required-test union",
        "no required test is skipped",
        "guidance only",
        "automated scheduler",
    ):
        assert required in section


def _denies_diagnostic_authority(text):
    return any(phrase in text for phrase in (
        'not execution authority', 'no diagnostic grants execution authority',
    ))


@pytest.mark.parametrize('text,denied', [
    ('It is advice, not execution authority.', True),
    ('No diagnostic grants execution authority.'.lower(), True),
    ('A diagnostic grants execution authority.', False),
])
def test_diagnostic_authority_oracle_retains_negative_counterexample(text, denied):
    assert _denies_diagnostic_authority(text) is denied


def test_collection_guidance_uses_exact_reuse_and_preserves_red():
    text = (ROOT / "skills/collect-evidence/SKILL.md").read_text()
    section = text.split("## Plan and Reuse Before Execution", 1)[1].split("\n## ", 1)[0]
    for required in (
        "harness evidence plan --json",
        "--reuse-if-valid",
        "can_reuse_evidence",
        "RED and finding",
        "cross-HEAD",
        "serial",
    ):
        assert required in section
    assert _denies_diagnostic_authority(section)
    assert '--scope related' in section and '--covered-test tests/example.py' in section


def test_contract_guidance_persists_actual_plan_proof_without_scope_shortcut():
    text = (ROOT / "skills/task-contract/SKILL.md").read_text()
    section = text.split("## Preserve Verification Bindings and Plan Proof", 1)[1].split("\n## ", 1)[0]
    for required in (
        "harness evidence plan --json",
        "harness plan reconcile P-001 --auto",
        "PLAN_PROOF_MISSING",
        "promptly",
        "RETIRE or REBIND",
        "not mark COMPLETE",
    ):
        assert required in section


def test_installed_skill_matches_root_skill():
    assert (ROOT / SKILLS[0]).read_bytes() == (ROOT / SKILLS[1]).read_bytes()
