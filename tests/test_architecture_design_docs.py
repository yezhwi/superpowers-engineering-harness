from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
OLD = REPO / "docs/Superpowers-Engineering-Harness-v0.2.10-Architecture-Awareness-Spec.md"
DESIGN = (
    REPO
    / "docs/Superpowers-Engineering-Harness-v0.3.0-Architecture-Scope-and-Drift-Design.md"
)


def test_v030_architecture_design_replaces_v0210_draft():
    assert not OLD.exists()
    text = DESIGN.read_text(encoding="utf-8")
    assert text.startswith("# Superpowers Engineering Harness v0.3.0")
    assert "Architecture Scope & Drift" in text
    assert "状态：Review Candidate" in text


def test_v030_architecture_design_records_approved_boundaries():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        ".harness/architecture.yaml",
        "alignment-freeze.yaml",
        "architecture_fingerprint",
        "current-task.scope.modules",
        "production | shared | support",
        "ARCHITECTURE_OWNERSHIP_UNRESOLVED",
        "ARCHITECTURE_OWNERSHIP_AMBIGUOUS",
        "ARCHITECTURE_OWNERSHIP_EMPTY",
        "ARCHITECTURE_SCOPE_DRIFT",
        "CONTRACT_CHANGED",
        "FAST/Q1",
        "mode: off",
        "source_access",
        "Hard bounds",
        "support-only task",
        "P0",
        "P1",
        "P2",
    )
    for term in required_terms:
        assert term in text

    assert "architecture-freeze.yaml" not in text
    assert "自动推断 module" in text
    assert "不能证明" in text


def test_v030_recovery_contract_matches_current_state_machine():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "RECOVERY_POLICY",
        "category: implementation",
        "BLOCKED → IMPLEMENTING",
        "harness transition SPECIFYING --reason SCOPE_DRIFT",
        "CONTRACT_CHANGED",
        "ESCALATED",
        "harness task new",
    )
    for term in required_terms:
        assert term in text

    for code in (
        "ARCHITECTURE_REQUIRED",
        "ARCHITECTURE_SCOPE_INVALID",
        "ARCHITECTURE_EVIDENCE_INVALID",
    ):
        assert f"| `{code}` |" in text
        assert f'"{code}": "IMPLEMENTING"' in text


def test_v030_change_set_contract_is_deterministic_and_task_local():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "git diff --name-status --no-renames --no-ext-diff --no-textconv -z <base>..HEAD -- .",
        "git ls-files --others --exclude-standard -z",
        "preexisting_user_paths - owned_paths",
        "docs/ 与 tests/",
        "不新增 File Scope Gate",
        "仅检查本任务 records 中含 `deleted` kind",
        "git ls-files -z",
        "tracked_paths - deleted_paths + untracked_paths",
        "--no-ext-diff --no-textconv",
        'WorkspaceError("ARCHITECTURE_CHANGESET_INVALID")',
    )
    for term in required_terms:
        assert term in text

    assert "File Scope Gate 与 Architecture Gate 保持独立" not in text


def test_v030_mode_identity_context_and_benchmark_contracts_are_closed():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "gate:\n  architecture:\n    mode: required",
        "architecture_mode: required",
        "architecture_mode: off",
        "architecture_fingerprint: null",
        "Compatibility/mode matrix",
        "id: OWN-001",
        "source: path:<canonical-path>",
        "source: module:<module-id>",
        "Architecture-local short-circuit",
        "independent Gate checks",
        "VERIFYING | `harness transition IMPLEMENTING`",
        "Preflight 检出时不改变 task state",
        "min(256, 64 + 64 × 32) = 256",
        "Context Recovery Experiment",
        "Drift Detection Experiment",
        "version input",
        "不得进入 `_declared_paths()`",
    )
    for term in required_terms:
        assert term in text


def test_v030_lifecycle_and_preflight_routes_are_legal():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "harness transition PLANNED",
        "harness check minimal",
        "SPECIFYING → PLANNED → IMPLEMENTING",
        "ARCHITECTURE_SCOPE_INCOMPLETE",
        "IMPLEMENTING | `harness transition SPECIFYING --reason SCOPE_DRIFT`",
        "VERIFYING | `harness transition IMPLEMENTING`",
        "REVIEWING | `harness review outcome VERIFICATION_GAP --reason-code ARCHITECTURE_SCOPE_INCOMPLETE`",
        "GATING | `harness gate`",
        "GATE_PREFLIGHT_BLOCKED",
    )
    for term in required_terms:
        assert term in text

    assert "→ harness transition IMPLEMENTING\n```" not in text


def test_v030_git_adapter_covers_index_worktree_and_exclusions():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "<base>..HEAD",
        "current-task.git.base_commit",
        "verify_git_ref()",
        "--cached",
        "HEAD --",
        ":(exclude).harness",
        "committed | staged | worktree | untracked",
        "同一路径可以保留多个不同 kind record",
        "不选择虚构的单一 final kind",
    )
    for term in required_terms:
        assert term in text

    assert "第一条命令直接比较 task baseline tree 与当前 index/worktree" not in text
    assert "add-then-delete 与 delete-then-restore 不产生 record" not in text


def test_v030_replacement_seal_scope_and_context_contracts_are_closed():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "trusted v2 seal",
        "task new",
        "task recover",
        "只有 `harness align freeze`",
        "bootstrap_legacy_off=False",
        "oneOf",
        "scope` 中必须显式存在 `modules` key",
        "显式 `modules: []`",
        "CONTEXT_SCHEMA_INVALID",
        "dependency_closure.ALLOWED",
        "不得加入 `ADAPTERS`",
        "不读取 `architecture.yaml`",
        "同一份 canonical Git path index",
    )
    for term in required_terms:
        assert term in text

    assert "旧 task/schema 在 modules 字段缺失时视为空集合" not in text
    assert "present malformed artifact 则抛出既有 Context invalid-state error" not in text
    assert "FAST/Q1 在 import、open、schema load" not in text


def test_v030_off_bootstrap_and_v2_writer_contract_is_explicit():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "bootstrap_legacy_off",
        "off phase-entry",
        "legacy v1 seal",
        "required phase-entry",
        "Gate 与 Context 固定 `bootstrap_legacy_off=False`",
        "只有 `harness align freeze` 发布 v2",
    )
    for term in required_terms:
        assert term in text

    assert "所有 consumer 的 `bootstrap=False`" not in text
    assert "缺 seal 要求操作者显式执行 freeze" not in text


def test_v030_planned_recovery_and_minimal_refresh_are_non_destructive():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "PLANNED | 先运行 `harness transition IMPLEMENTING`",
        "成功后立即运行 `harness transition SPECIFYING --reason SCOPE_DRIFT`",
        "`harness task recover` 仅作为 fallback",
        "harness check minimal --file <decision.yaml>",
        "既有 evidence/minimal-implementation.yaml",
        "不必重写",
    )
    for term in required_terms:
        assert term in text

    assert "PLANNED | 无向后 edge；使用 `harness task recover`" not in text


def test_v030_current_seal_deletion_and_refreeze_are_explicit():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "IMPLEMENTING → SPECIFYING 会删除当前 `alignment-freeze.yaml`",
        "`architecture.yaml` 保留",
        "`harness align freeze` 发布新的 v2 seal",
        "不承诺当前 seal 自动进入 history",
    )
    for term in required_terms:
        assert term in text

    assert "Downgrade 不删除 artifact 或历史 seal" not in text


def test_v030_contract_changed_preflight_has_separate_state_routes():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "User-authority CONTRACT_CHANGED preflight continuation",
        "IMPLEMENTING | 用户确认后运行 `harness transition SPECIFYING --reason SCOPE_DRIFT`",
        "VERIFYING | 用户确认后先 `harness transition IMPLEMENTING`",
        "REVIEWING | 用户确认后运行 `harness review outcome VERIFICATION_GAP --reason-code ARCHITECTURE_SCOPE_INCOMPLETE`",
        "PLANNED | 用户确认后使用 `harness task recover`",
        "GATING | 用户确认后运行 `harness gate`",
        "GATING → BLOCKED → ESCALATED",
        "再使用 `harness task new`",
        "不复用 repairable blocker table",
    )
    for term in required_terms:
        assert term in text

    assert "用户确认后按上表当前 state 进入 SPECIFYING" not in text


def test_v030_contract_changed_authority_matrix_covers_remaining_states():
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = (
        "BLOCKED | 按已持久化 blocker 运行 `harness resume`",
        "没有 recovery route 时任务应已是 ESCALATED",
        "REPRODUCING | 完成当前 Finding lifecycle",
        "FIXING | 完成 fix 与 Finding 状态更新后运行 `harness transition VERIFYING`",
        "不得跳过 Finding lifecycle",
        "CONVERGED | 使用 `harness task recover`",
        "`harness transition DONE` 会重新执行 Gate",
        "DONE / ESCALATED | 使用 `harness task new`",
        "PLANNED 不默认 recover 仅约束 repairable blocker table",
    )
    for term in required_terms:
        assert term in text
