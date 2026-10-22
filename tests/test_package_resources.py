"""Installed-package resource contracts."""

from importlib import resources


def test_package_contains_runtime_resources_and_state_machine():
    from harness import state_machine

    assert state_machine.is_legal("CREATED", "SPECIFYING")
    root = resources.files("harness")
    for name in (
        "task.schema.json",
        "evidence.schema.json",
        "observability.schema.json",
        "context-profile.schema.json",
        "context.schema.json",
        "alignment-freeze.schema.json",
        "test-scope-baseline.schema.json",
        "test-scope-audit.schema.json",
        "test-scope-seal.schema.json",
        "test-scope-migration.schema.json",
        "impact-reconcile.schema.json",
        "decision.schema.json",
        "candidate-prepared.schema.json",
        "candidate-proof-spec.schema.json",
        "candidate-proof.schema.json",
        "candidate-review.schema.json",
        "candidate-acceptance.schema.json",
        "candidate-operation.schema.json",
        "candidate-trace.schema.json",
        "candidate-command-result.schema.json",
    ):
        assert root.joinpath("schemas", name).is_file()
    for name in ("current-task.yaml", "gate.yaml", "observability.yaml"):
        assert root.joinpath("templates", name).is_file()
