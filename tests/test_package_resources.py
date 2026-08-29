"""Installed-package resource contracts."""

from importlib import resources


def test_package_contains_runtime_resources_and_state_machine():
    from harness import state_machine

    assert state_machine.is_legal("CREATED", "SPECIFYING")
    root = resources.files("harness")
    for name in ("task.schema.json", "evidence.schema.json", "observability.schema.json"):
        assert root.joinpath("schemas", name).is_file()
    for name in ("current-task.yaml", "gate.yaml", "observability.yaml"):
        assert root.joinpath("templates", name).is_file()
