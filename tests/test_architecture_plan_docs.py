from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
P0 = REPO / "docs/superpowers/plans/2026-09-30-v030-architecture-scope-drift-p0.md"
P1 = REPO / "docs/superpowers/plans/2026-09-30-v030-architecture-scope-drift-p1.md"
P2 = REPO / "docs/superpowers/plans/2026-09-30-v030-architecture-scope-drift-p2.md"


def test_p0_plan_closes_review_findings():
    text = P0.read_text(encoding="utf-8")
    required = (
        "canonical YAML: 1 MiB UTF-8",
        "maximum 256 modules",
        "maximum 1024 ownership rules",
        "maximum 64 declared modules/task",
        "maximum 32 dependencies/module",
        "maximum 16 evidence records/module",
        "module ID: 64 code points",
        "name: 128 code points",
        "responsibility: 512 code points",
        "path/pattern/empty reason: 512 code points",
        "copy as destination `added`",
        "canonical path index",
        "tracked or task-attributable path",
        "same-score conflict",
        "ARCHITECTURE_REALIGNMENT_REQUIRED",
        "one `ARCHITECTURE_SCOPE_DRIFT` per unexpected shared owner",
        'RECOVERY_POLICY["CONTRACT_CHANGED"] == "ESCALATED"',
        "artifact:.harness/alignment-freeze.yaml",
        "tests/test_workspace.py",
        "tests/test_workspace_untracked_scope.py",
        "tests/test_task_contract.py",
        "tests/test_cli_init.py",
        "tests/test_test_plan_transition.py",
        "tests/test_convergence_cli.py",
    )
    for term in required:
        assert term in text


def test_p1_plan_closes_review_findings():
    text = P1.read_text(encoding="utf-8")
    required = (
        "FAST/Q1 and mode off omit `control.architecture`",
        "required mode alone adds `control.architecture`",
        "status`, `fingerprint`, `declared_modules`, and `relevant_modules`",
        "blockers: [ARCHITECTURE_REQUIRED]",
        "ArchitectureModel` in memory",
        "serialized `dict | None`",
        "PROJECTION_VERSION = 4",
        '"projection_version": {"const": 4}',
        "do not add generated_from fields",
        "self-dependency remains invalid",
        "never truncate",
        "tests/test_context_remaining_triggers.py",
    )
    for term in required:
        assert term in text


def test_p2_plan_closes_review_findings():
    text = P2.read_text(encoding="utf-8")
    required = (
        "correctly blocked drift cases / all labeled drift cases",
        "correct unresolved-or-ambiguous diagnostics / all emitted unresolved-or-ambiguous diagnostics",
        "incorrectly blocked clean cases / all labeled clean cases",
        "expected modules absent from declared modules / all expected modules",
        "exact-match projected `(id, responsibility, depends_on)` records / all expected projected records",
        "token and tool-call",
        "numerator, denominator, and `not_applicable` case count",
        "scope-drift blockers do not enter Diagnostic precision",
    )
    for term in required:
        assert term in text


def test_plans_exclude_superseded_contracts():
    p0 = P0.read_text(encoding="utf-8")
    p2 = P2.read_text(encoding="utf-8")
    assert "2048 ownership rules" not in p0
    assert 'RECOVERY_POLICY["CONTRACT_CHANGED"] == "IMPLEMENTING"' not in p0
    assert "all `(code, source)` identities to calculate recall/precision" not in p2


def test_plans_remove_final_execution_ambiguities():
    p0 = P0.read_text(encoding="utf-8")
    p1 = P1.read_text(encoding="utf-8")
    p2 = P2.read_text(encoding="utf-8")

    for term in (
        "architecture.schema.json enforces 256 modules",
        "task.schema.json enforces 64 declared modules/task",
        "repairable PLANNED: `harness transition IMPLEMENTING` then `harness transition SPECIFYING --reason SCOPE_DRIFT`",
        "CONTRACT_CHANGED PLANNED: `harness task recover`",
        "CONTRACT_CHANGED GATING: `harness gate` to ESCALATED, then `harness task new`",
    ):
        assert term in p0

    for term in (
        "AuthoritativeContext.architecture` stores the complete validated canonical `dict | None`",
        "ArchitectureAssessment.model` stores the in-memory `ArchitectureModel | None`",
        "ControlCore[\"architecture\"]` stores only the projected dict",
        "optional `control.architecture`",
        "FAST/off file membership and existing file hashes remain unchanged",
        "projection_version changes from 3 to 4",
    ):
        assert term in p1

    assert "extra unresolved/ambiguous diagnostic identity" in p2
    assert "extra blocker identity" not in p2
