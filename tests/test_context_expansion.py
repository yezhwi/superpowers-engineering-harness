"""Persisted expansion changes Context breadth, never task risk or authority."""

import json

import pytest
import test_context_builder
import yaml
from test_context_builder import write_yaml
from test_context_cli import run_cli

harness = test_context_builder.harness
TRIGGERS = [
    "SYMBOL_UNRESOLVED",
    "REQUIREMENT_UNMAPPED",
    "CROSS_MODULE_DEPENDENCY",
    "API_OR_CONFIG_CHANGE",
    "INSUFFICIENT_CONTEXT",
]


@pytest.mark.parametrize("trigger", TRIGGERS)
def test_reported_expansion_changes_policy_not_risk_or_authority(harness, trigger):
    task_path = harness / "current-task.yaml"
    before = yaml.safe_load(task_path.read_text())
    result = run_cli(
        harness.parent,
        "expand",
        "--trigger",
        trigger,
        "--reason",
        "Need declared dependency context",
    )
    assert result.returncode == 0, result.stderr
    event = yaml.safe_load(result.stdout)
    assert event["from"] == "LOCAL"
    assert event["to"] == "BOUNDED"
    assert event["trigger"] == trigger
    assert event["task_id"] == "TASK-028"
    assert event["source_hash"].startswith("sha256:")
    after = yaml.safe_load(task_path.read_text())
    assert after["budget"].pop("context_expansions") == 1
    assert after == before
    generated = run_cli(harness.parent, "--json")
    assert generated.returncode == 0, generated.stderr
    document = json.loads(generated.stdout)
    assert document["base_policy"] == "LOCAL"
    assert document["policy"] == "BOUNDED"
    assert document["expansions"] == [event]
    evidence = yaml.safe_load((harness / "context/evidence.yaml").read_text())
    assert evidence["expansions"] == [event]
    assert run_cli(harness.parent, "validate").returncode == 0


def test_expansion_is_monotonic_even_at_maximum(harness):
    for policy in ["BOUNDED", "EXPANDED", "EXPANDED"]:
        result = run_cli(
            harness.parent,
            "expand",
            "--trigger",
            "INSUFFICIENT_CONTEXT",
            "--reason",
            "More context",
            "--json",
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["to"] == policy
    assert (
        yaml.safe_load((harness / "current-task.yaml").read_text())["budget"][
            "context_expansions"
        ]
        == 3
    )


@pytest.mark.parametrize(
    "trigger", ["UNKNOWN", "FINDING_OUTSIDE_SCOPE", "CONTEXT_INTEGRITY_UNPROVEN"]
)
def test_cli_does_not_accept_unknown_or_core_only_reports(harness, trigger):
    before = (harness / "current-task.yaml").read_bytes()
    result = run_cli(
        harness.parent, "expand", "--trigger", trigger, "--reason", "Report"
    )
    assert result.returncode == 2
    assert (harness / "current-task.yaml").read_bytes() == before
    assert not (harness / "context/expansions.yaml").exists()


def test_blank_reason_fails_without_writes(harness):
    result = run_cli(
        harness.parent, "expand", "--trigger", "INSUFFICIENT_CONTEXT", "--reason", " "
    )
    assert result.returncode == 2
    assert "CONTEXT_SCHEMA_INVALID" in result.stderr
    assert not (harness / "context/expansions.yaml").exists()


def test_expansion_invalidates_old_snapshot_without_overwriting_it(harness):
    assert run_cli(harness.parent).returncode == 0
    before = (harness / "context/current.yaml").read_bytes()
    assert (
        run_cli(
            harness.parent,
            "expand",
            "--trigger",
            "SYMBOL_UNRESOLVED",
            "--reason",
            "Missing symbol",
        ).returncode
        == 0
    )
    stale = run_cli(harness.parent, "validate")
    assert stale.returncode == 2
    assert "CONTEXT_STALE" in stale.stderr
    assert (harness / "context/current.yaml").read_bytes() == before


def test_stale_before_publish_does_not_revert_concurrent_task_edit(
    harness, monkeypatch
):
    from harness import transaction
    from harness.context.escalation import expand_context
    from harness.context.model import ContextBuildError

    original = transaction.stage
    task_path = harness / "current-task.yaml"
    edited = None

    def change_task(*args, **kwargs):
        nonlocal edited
        result = original(*args, **kwargs)
        edited = task_path.read_bytes() + b"\n# concurrent user edit\n"
        task_path.write_bytes(edited)
        return result

    monkeypatch.setattr(transaction, "stage", change_task)
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        expand_context(harness, "INSUFFICIENT_CONTEXT", "Need context")
    assert task_path.read_bytes() == edited
    assert not (harness / "context/expansions.yaml").exists()


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_expansion_publication_failure_restores_event_and_budget(
    harness, monkeypatch, failure
):
    from pathlib import Path

    from harness.context.escalation import expand_context

    before = (harness / "current-task.yaml").read_bytes()
    original = Path.replace

    def fail_task(self, target):
        if Path(target) == harness / "current-task.yaml":
            raise failure("injected task publication failure")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", fail_task)
    with pytest.raises(failure):
        expand_context(harness, "INSUFFICIENT_CONTEXT", "Need context")
    assert (harness / "current-task.yaml").read_bytes() == before
    assert not (harness / "context/expansions.yaml").exists()


@pytest.mark.parametrize("change", ["delete_log", "decrease", "unknown", "counter"])
def test_corrupt_expansion_authority_fails_closed(harness, change):
    assert (
        run_cli(
            harness.parent,
            "expand",
            "--trigger",
            "INSUFFICIENT_CONTEXT",
            "--reason",
            "Need context",
        ).returncode
        == 0
    )
    path = harness / "context/expansions.yaml"
    log = yaml.safe_load(path.read_text())
    if change == "delete_log":
        path.unlink()
    elif change == "counter":
        task_path = harness / "current-task.yaml"
        task = yaml.safe_load(task_path.read_text())
        task["budget"]["context_expansions"] += 1
        write_yaml(task_path, task)
    else:
        log["expansions"][0]["to" if change == "decrease" else "trigger"] = (
            "LOCAL" if change == "decrease" else "UNKNOWN"
        )
        write_yaml(path, log)
    result = run_cli(harness.parent)
    assert result.returncode == 2
    assert "CONTEXT_POLICY_MISMATCH" in result.stderr
    assert result.stdout == ""


def test_concurrent_reports_do_not_lose_events_or_counter(harness):
    from concurrent.futures import ThreadPoolExecutor

    from harness.context.escalation import expand_context

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(expand_context, harness, "INSUFFICIENT_CONTEXT", f"Report {n}")
            for n in range(2)
        ]
        events = [future.result(timeout=20) for future in futures]
    assert {event["to"] for event in events} == {"BOUNDED", "EXPANDED"}
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    log = yaml.safe_load((harness / "context/expansions.yaml").read_text())
    assert task["budget"]["context_expansions"] == len(log["expansions"]) == 2


def test_higher_risk_remains_policy_floor_after_expansion(harness):
    from harness.context.escalation import expand_context
    from harness.context.integrity import build_context

    expand_context(harness, "INSUFFICIENT_CONTEXT", "Need context")
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"]["level"], task["risk"]["profile"] = "Q3", "STRICT"
    write_yaml(task_path, task)
    document = build_context(harness)
    assert document["base_policy"] == document["policy"] == "EXPANDED"
    assert len(document["expansions"]) == 1


def test_new_task_does_not_inherit_old_expansion(harness):
    assert (
        run_cli(
            harness.parent,
            "expand",
            "--trigger",
            "SYMBOL_UNRESOLVED",
            "--reason",
            "Missing symbol",
        ).returncode
        == 0
    )
    path = harness / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["task"]["id"] = "TASK-029"
    task["budget"].pop("context_expansions")
    write_yaml(path, task)
    result = run_cli(harness.parent, "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["policy"] == "LOCAL"
    assert json.loads(result.stdout)["expansions"] == []
