"""README navigation and command contracts."""

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('filename', ['README.md', 'README.zh-CN.md'])
def test_readme_distinguishes_freshness_and_fast_risk_path_interfaces(filename):
    text = (REPO / filename).read_text()
    assert '<!-- path-identities -->' in text
    section = text.split('<!-- path-identities -->', 1)[1].split('<!-- /path-identities -->', 1)[0]
    for identifier in ('workspace_fingerprint', 'business_paths', '.harness/', 'docs/', 'tests/', 'test/', 'README.md'):
        assert identifier in section


def test_structural_target_helper_links_resolve_to_bilingual_command_guides():
    import inspect

    from harness.state_machine import legal_targets

    doc = inspect.getdoc(legal_targets) or ""
    targets = re.findall(r"\]\(([^)]+)\)", doc)
    assert set(targets) == {
        "../../README.md#transition-graph-and-command-admission",
        "../../README.zh-CN.md#transition-graph-and-command-admission",
    }
    for target in targets:
        relative, anchor = target.split("#", 1)
        guide = (REPO / "src/harness" / relative).resolve()
        assert guide.is_file()
        text = guide.read_text()
        assert f'<a id="{anchor}"></a>' in text
        # Identifiers/commands are stable references; prose is reviewed semantically.
        section = text.split(f'<a id="{anchor}"></a>', 1)[1].split("\n## ", 1)[1].split("\n## ", 1)[0]
        for identifier in (
            "legal_targets", "harness transition", "harness review outcome",
            "harness gate", "harness resume", "CLASSIFIED", "FAST", "STANDARD", "STRICT",
        ):
            assert identifier in section


def test_task_contract_writes_alignment_before_planned_admission():
    text = (REPO / "skills/task-contract/SKILL.md").read_text()
    exit_steps = text.split("### 7. Exit PLANNED", 1)[1].split("## Production Diagnosability", 1)[0]
    assert exit_steps.index("Write `.harness/alignment.yaml`") < exit_steps.index("harness align freeze")
    assert exit_steps.index("harness align freeze") < exit_steps.index("harness align check")
    assert exit_steps.index("harness align check") < exit_steps.index("harness transition PLANNED")
    assert "Every automated case must have a nonempty `tests` list" in text


def test_diagnosability_summary_matches_verifying_workflow():
    root = (REPO / "SKILL.md").read_bytes()
    assert root == (REPO / "skills/engineering-harness/SKILL.md").read_bytes()
    text = root.decode()
    for prefix in ("- Q2 / STANDARD:", "- Q3 / STRICT:"):
        line = next(line for line in text.splitlines() if line.startswith(prefix))
        assert "before `VERIFYING -> REVIEWING`" in line


def test_control_plane_spec_requires_only_related_verification():
    text = (REPO / "docs/superpowers/specs/2026-10-10-control-plane-contract-repair-design.md").read_text()
    verification = text.split("## Verification", 1)[1].split("## Risks", 1)[0]
    assert "regression and impact-related tests" in verification
    assert "Full-suite execution is forbidden" in verification
    assert "Full project suite runs after targeted tests" not in verification


def test_v031_documents_control_plane_repairs_and_compatibility():
    text = (REPO / "CHANGELOG.md").read_text()
    unreleased, published = text.split("## 0.3.1", 1)
    release = published.split("## 0.3.0", 1)[0]
    for term in (
        "harness align revise", "SPECIFYING -> PLANNED", "telemetry",
        "single scan", "immutable", "GREEN", "RED", "finding",
        "v1", "v2", "phase", "not automatically rewritten",
    ):
        assert term in release
    assert "raw-byte fingerprint behavior remains unchanged" in release
    assert "fail-closed" in release
    assert "regression and impact-related tests" in release
    assert unreleased.split("## 0.3.2", 1)[0].strip() == "# Changelog\n\n## Unreleased"


def test_readmes_document_agy_quick_start():
    for name, heading in (
        ("README.md", "Antigravity CLI (agy)"),
        ("README.zh-CN.md", "Antigravity CLI（agy）"),
    ):
        text = (REPO / name).read_text(encoding="utf-8")
        assert heading in text
        assert "scripts/install-agy.sh" in text
        assert "bash -s -- v0.3.1" in text
        assert "agy" in text


def test_changelog_includes_unreleased_work_in_v0210_release_notes():
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased, released = text.split("## 0.2.10", maxsplit=1)
    notes = released.split("## 0.2.9", maxsplit=1)[0]

    assert "## Unreleased" in unreleased
    assert "AGY" not in unreleased
    assert "AGY" in notes
    assert "task replacement" in notes
    assert "Plan Reconciliation" in notes
    assert "one-command Pi bootstrap installer" in notes
    assert "Git tag v0.2.10" in notes


def test_npm_files_close_all_relative_readme_links_without_broad_docs_glob():
    package = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
    packaged = set(package["files"])
    targets = set()
    for name in ("README.md", "README.zh-CN.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        targets.update(
            target.split("#", 1)[0]
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
            if not target.startswith(("http://", "https://", "#"))
        )

    assert "docs" not in packaged
    assert "SKILL.md" in packaged  # repository-level portable skill entry
    assert targets <= packaged
    assert package["pi"] == {"skills": ["./skills"]}


def test_npm_pack_contains_core_skill_and_linked_docs():
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = {item["path"] for item in json.loads(result.stdout)[0]["files"]}

    metadata = json.loads(result.stdout)[0]
    assert metadata["version"] == "0.3.2"
    assert "CHANGELOG.md" in paths
    assert "skills/engineering-harness/SKILL.md" in paths
    assert "docs/architecture.md" in paths
    assert (
        "docs/Superpowers-Engineering-Harness-v0.2.10-Implementation-Contract.md"
        in paths
    )
    assert (
        "docs/Superpowers-Engineering-Harness-v0.3.0-Architecture-Scope-and-Drift-Design.md"
        in paths
    )
    assert "docs/superpowers/reports/v030-architecture-benchmark-template.md" in paths
    assert not any(path.startswith("benchmarks/architecture/") for path in paths)
    assert not any("Architecture-Awareness" in path for path in paths)


def test_packaged_skills_declare_cli_compatibility_and_root_copy_stays_synced():
    expected = (
        "Requires Python 3.11+, Git, and a matching "
        "superpowers-engineering-harness CLI installed separately."
    )
    skill_paths = sorted((REPO / "skills").glob("*/SKILL.md"))

    assert skill_paths
    for path in skill_paths:
        frontmatter = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
        assert frontmatter["compatibility"] == expected
    engineering = REPO / "skills/engineering-harness/SKILL.md"
    assert not engineering.is_symlink()
    assert (REPO / "SKILL.md").read_bytes() == engineering.read_bytes()


def test_readmes_document_matching_skills_and_cli_install_without_full_suite():
    base = (
        "https://raw.githubusercontent.com/yezhwi/"
        "superpowers-engineering-harness"
    )
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text(encoding="utf-8")
        assert f"curl -fsSL {base}/main/scripts/install-pi.sh | bash" in text
        assert (
            f"curl -fsSL {base}/main/scripts/install-pi.sh "
            "| bash -s -- v0.3.1"
        ) in text
        assert "Superpowers" in text
        assert "isolated" in text.lower() or "隔离" in text
        assert "matching" in text.lower() or "匹配" in text
        assert "python -m pytest tests/ -q" not in text
        assert "Full-suite authorization remains" not in text
        assert "全量测试授权仍必须" not in text
        assert "impact-related" in text or "影响相关" in text


def test_readmes_describe_runnable_plan_examples_and_actual_operator_boundaries():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text(encoding="utf-8")

        assert text.index("harness plan upgrade-execution") < text.index(
            "harness plan begin P-001"
        )
        assert "harness plan reconcile P-001 --complete \\" in text
        assert "--evidence unit-test-<digest>" in text
        assert "--surface src/example.py" in text
        assert "harness plan refresh-proof P-001 \\" in text
        assert "choose one" in text.lower() or "二选一" in text

        assert "only reads `.harness/current-task.yaml`" not in text
        assert "只读取 `.harness/current-task.yaml`" not in text
        assert "read-only" in text.lower() or "只读" in text
        assert "clarification" in text.lower() or "澄清" in text
        assert "authorization" in text.lower() or "授权" in text
        assert "escalation" in text.lower() or "升级" in text

        assert "Q0 is a direct answer and creates no Harness task." not in text
        assert "Q0 直接回答，不创建 Harness task。" not in text


def test_root_skill_routes_diagnosability():
    text = (REPO / "SKILL.md").read_text(encoding="utf-8")
    assert "Production Diagnosability Routing" in text
    assert "harness review diagnosability" in text


def test_readmes_document_engineering_quality_architecture():
    for name in ("README.md", "README.zh-CN.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "Engineering Quality" in text
        assert "Version evolution" in text or "版本演进" in text
        assert "Deterministic Quality Gate" in text or "确定性质量门禁" in text
        assert "does not provide" in text or "不提供" in text


def test_readmes_document_production_diagnosability_routing():
    for name in ("README.md", "README.zh-CN.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "observability.yaml" in text
        assert "harness review diagnosability" in text


def test_readmes_document_explicit_fail_closed_evidence_reuse():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "--reuse-if-valid" in text
        assert "EVIDENCE_REUSED" in text


def test_readmes_document_product_freshness_and_canonical_covered_tests():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "product workspace fingerprint" in text
        assert "control-plane fingerprint" in text
        assert "COVERED_TEST_NOT_EXECUTED" in text
        assert "COVERED_TEST_PATH_INVALID" in text
        assert "TEST_RUNNER_UNRESOLVED" in text
        assert "npm run test:unit" in text
        assert "backend/tests/foo.py" in text
        assert "EVIDENCE_WORKSPACE_STALE" in text


def test_readmes_document_risk_profiles_and_independent_authorization():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "Q1" in text and "FAST" in text
        assert "harness task classify" in text
        assert "harness authorize commit" in text
        assert "harness authorize push" in text


def test_docs_identify_current_adaptive_release():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert text.startswith("# Superpowers Engineering Harness v0.3.2\n")
        assert "v0.3.2 development candidate" in text
        assert "v0.3.1 current release" in text
        assert "v0.3.0 architecture design" in text or "v0.3.0 架构设计" in text
        assert "Architecture Scope Gate P0" in text
        assert "Architecture Context Projection P1" in text
        assert "Architecture Evaluation P2" in text
        assert (
            "No measured benchmark improvement is claimed" in text
            or "不声明任何实测 benchmark 改进" in text
        )
        assert "INCONCLUSIVE" in text
        assert "risk-adaptive" in text
        assert "Q1 / FAST" in text and "Q2 / STANDARD" in text and "Q3 / STRICT" in text
    changelog = (REPO / "CHANGELOG.md").read_text()
    assert "Evidence reuse" in changelog
    assert "Soft evidence budgets" in changelog
    assert "local telemetry" in changelog
    assert "fixture benchmarks" in changelog
    assert "## 0.2.10" in changelog
    assert "multi-run statistics" in changelog


def test_v0210_readmes_document_plan_reconciliation_commands_and_boundaries():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text(encoding="utf-8")
        for command in (
            "harness plan status",
            "harness plan sync-markdown",
            "harness plan reconcile",
            "harness gate preflight",
        ):
            assert command in text
        assert "--verbose" in text
        assert "--auto" in text
        assert "FAST" in text and "Q2" in text and "Q3" in text
        assert "Markdown" in text


def test_v0210_contract_marks_all_delivery_slices_implemented():
    text = (
        REPO / "docs/Superpowers-Engineering-Harness-v0.2.10-Implementation-Contract.md"
    ).read_text(encoding="utf-8")

    assert "Status: P0/P1A/P1B/P1C/P2 implemented" in text
    assert "P2 design approved" not in text


def test_readmes_define_telemetry_measurement_boundary():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "harness_command_calls" in text
        assert "elapsed_seconds" in text
        assert "token_estimate: null" in text


def test_readmes_define_benchmark_correctness_comparison_limits():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "benchmark compare" in text
        assert "overall:" in text
        assert "experiment:" in text
        assert "INCONCLUSIVE" in text
        assert "external agent" in text


def test_skill_defines_fast_investigation_round_policy():
    skill = (REPO / "SKILL.md").read_text()
    assert "search/read rounds" in skill
    assert "3" in skill
    assert "new evidence" in skill
    assert "new hypothesis" in skill
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        assert "execution budgets" not in path.read_text().lower()


def test_docs_define_fast_verification_and_authorization_boundary():
    for path in (REPO / "SKILL.md", REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "gate.fast.verification" in text
        assert "FAST_REPOSITORY_VERIFICATION_MISSING" in text
        assert "outside Harness" in text


def test_docs_explain_fast_risk_boundary_escalation():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md", REPO / "SKILL.md"):
        text = path.read_text()
        assert "risk-boundaries.yaml" in text
        assert "RISK_ESCALATION_REQUIRED" in text
        assert "harness task escalate" in text


def test_skill_q0_bypasses_harness_before_session_startup():
    skill = (REPO / "SKILL.md").read_text()
    assert "Q0 Decision Table" in skill
    assert "这个修改会影响 API 吗？" in skill
    assert "do not read `.harness`" in skill
    assert "default Q0" in skill
    assert skill.index("Q0 Decision Table") < skill.index("## Session Startup")


def test_skill_routes_risk_adaptive_workflow_before_task_contract():
    skill = (REPO / "SKILL.md").read_text()
    for term in (
        "Q0",
        "Q1",
        "Q2",
        "Q3",
        "FAST",
        "STANDARD",
        "STRICT",
        "CLASSIFIED",
        "harness task classify",
        "harness task escalate",
    ):
        assert term in skill
    assert skill.index("harness task classify") < skill.index("## Phase Dispatch Table")


def test_bilingual_readmes_link_and_document_core_commands():
    """Break caught: language mirror or documented core workflow disappears."""
    english = (REPO / "README.md").read_text()
    chinese = (REPO / "README.zh-CN.md").read_text()

    for command in (
        "harness init",
        "harness check minimal",
        "harness review complexity",
        "harness gate",
    ):
        assert command in english
        assert command in chinese
    assert "README.zh-CN.md" in english
    assert "README.md" in chinese


def test_readmes_document_v022_recovery_and_review_commands():
    """Break caught: released CLI behavior lacks user-operable documentation."""
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "v0.2.2" in text
        assert "harness resume" in text
        assert "harness review outcome" in text
        assert "harness review complexity --base" in text


def test_readmes_show_legal_normal_and_blocked_recovery_order():
    """Break caught: docs call guarded commands from impossible states."""
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "harness transition REVIEWING" in text
        assert "harness review outcome PASS --reason-code REVIEW_CLEAN" in text
        assert "DECISION: CONVERGED" in text
        assert "DECISION: CONTINUE" in text
        assert "harness transition DONE" in text
        assert "harness resume" in text
        assert "harness converge" not in text
        assert "Q1" in text and "harness transition GATING" in text
        assert "harness transition BLOCKED" not in text


def test_operational_docs_do_not_instruct_manual_state_mutation_or_preclassify_contract():
    skill = (REPO / "SKILL.md").read_text()
    example = (REPO / "docs/worked-example.md").read_text()

    assert "# then update .harness/current-task.yaml state field" not in skill
    assert "CREATED\n  → task-contract" not in example
    assert "CREATED\n  → classify" in example


def _has_exit_zero_completion_shortcut(text):
    # Guard an unsafe routing instruction, not harmless diagnostic exit docs.
    return bool(re.search(
        r'exit(?:s)?\s+0[^\n]{0,80}(?:transition|mark|->|→)\s+`?(?:done|converged)\b',
        text, re.IGNORECASE,
    ))


@pytest.mark.parametrize('text,unsafe', [
    ('v2 exits 0/1/2 for clear/blocked/error diagnosis, never Gate PASS.', False),
    ('If harness gate exits 0, transition DONE.', True),
    ('On exit 0 -> CONVERGED', True),
])
def test_completion_routing_oracle_distinguishes_diagnosis_from_shortcut(text, unsafe):
    assert _has_exit_zero_completion_shortcut(text) is unsafe


def test_gate_skills_route_on_persisted_decision_not_exit_code():
    for path in (
        REPO / "SKILL.md",
        REPO / "skills/quality-gate/SKILL.md",
        REPO / "skills/convergence/SKILL.md",
    ):
        text = path.read_text().lower()
        assert not _has_exit_zero_completion_shortcut(text)
        assert "decision:" in text or "converged" in text


def test_skill_and_worked_example_document_v022_controlled_routes():
    """Break caught: worker instructions retain v0.2.1 free recovery routes."""
    skill = (REPO / "SKILL.md").read_text()
    example = (REPO / "docs/worked-example.md").read_text()

    for text in (skill, example):
        assert "harness resume" in text
        assert "harness review outcome" in text
        assert "harness review complexity --base" in text
    assert "status is read-only" in skill


def test_v022_docs_explain_baseline_and_controlled_reason_codes():
    """Break caught: operator docs suggest unsafe HEAD fallback or arbitrary reason prose."""
    for path in (REPO / "README.md", REPO / "README.zh-CN.md", REPO / "SKILL.md"):
        text = path.read_text()
        assert "baseline" in text.lower()
        assert "TEST_COVERAGE_INSUFFICIENT" in text


@pytest.mark.parametrize('name', ['README.md', 'README.zh-CN.md', 'CHANGELOG.md', 'docs/test-scope-migration.md'])
def test_publication_operator_docs_declare_macos_only_support(name):
    """Public contract must not imply Linux/Windows or arbitrary filesystem support."""
    text = (REPO / name).read_text()
    for term in ('macOS-only', 'Linux', 'Windows', 'FUSE', 'PUBLICATION_UNSUPPORTED'):
        assert term in text, (name, term)


@pytest.mark.parametrize('name, qualifications', [
    ('README.md', ('not content CAS', 'relocated', 'no pruning command', 'standalone')),
    ('README.zh-CN.md', ('不是 content CAS', '迁移', '不提供 pruning 命令', '独立')),
    ('docs/test-scope-migration.md', ('not content CAS', 'relocated', 'no pruning command', 'standalone')),
])
def test_publication_operator_docs_explain_retention_cost_and_limits(name, qualifications):
    """Public contract must disclose retained metadata, privacy, disk cost and limits."""
    text = (REPO / name).read_text()
    for term in ('.harness/.transactions/', '.harness/.publication-retained/',
                 '.harness/.staging/', '0700', '0600', 'ENOSPC', *qualifications):
        assert term in text, (name, term)


def test_workflow_forbids_full_suite_even_when_requested():
    workflow = (REPO / "SKILL.md").read_text()
    assert "Full-suite execution is forbidden" in workflow
    assert "AGENTS.md, user requests, and any repository-local instruction" in workflow
    assert "Gate freshness preflight must pass" in workflow
    assert "append-only by command/covered-test identity" in workflow
    assert "declared test targets must exist" in workflow
