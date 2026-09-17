from pathlib import Path

import pytest

import harness.collect_evidence as evidence_module
from harness.collect_evidence import execution_environment, main


def test_public_module_has_no_shell_command_executor():
    """Break caught: external callers can invoke shell executor directly."""
    assert not hasattr(evidence_module, "collect")
    assert not hasattr(evidence_module, "TrustedLocalCommand")


def test_only_main_invokes_private_shell_executor():
    source = Path(evidence_module.__file__).read_text()
    assert source.count("_collect(") == 2  # definition plus main call


def test_readme_marks_shell_executor_as_unsupported_internal_api():
    readme = Path("README.md").read_text()
    assert "unsupported internal API" in readme


def test_kubectl_exec_records_namespace_workload_and_cwd():
    env = execution_environment(
        "kubectl -n coagents-dev exec deploy/frontend -- "
        "sh -lc 'cd /workspaces/coagents_service/agents-frontend && pytest'"
    )
    assert env == {
        "transport": "kubectl_exec",
        "namespace": "coagents-dev",
        "workload": "deploy/frontend",
        "cwd": "/workspaces/coagents_service/agents-frontend",
    }


def test_kubectl_exec_without_namespace_omits_namespace():
    env = execution_environment(
        "kubectl exec deploy/app -- sh -lc 'cd /workspace && pytest'"
    )
    assert env["transport"] == "kubectl_exec"
    assert env["workload"] == "deploy/app"
    assert env["cwd"] == "/workspace"
    assert "namespace" not in env
    assert "container" not in env


def test_kubectl_exec_without_container_flag_does_not_guess_container():
    env = execution_environment(
        "kubectl -n ns exec deploy/frontend -- sh -lc 'cd /app && true'"
    )
    assert "container" not in env
    assert env["namespace"] == "ns"


def test_kubectl_exec_records_container_when_flag_present():
    env = execution_environment(
        "kubectl -n ns exec deploy/frontend -c frontend -- sh -lc 'cd /app && true'"
    )
    assert env["container"] == "frontend"


def test_non_kubectl_command_has_no_execution_environment():
    assert execution_environment("pytest tests/test_x.py") is None
    assert execution_environment("sh -lc 'cd backend && pytest'") is None


def test_unparseable_kubectl_stores_unknown_transport():
    assert execution_environment("kubectl get pods") == {"transport": "unknown"}
    assert execution_environment("kubectl exec") == {"transport": "unknown"}


def test_main_records_kubectl_provenance_without_changing_result(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.collect_evidence.git_head", lambda: "a" * 40)
    monkeypatch.setattr(
        "harness.collect_evidence.workspace_fingerprint", lambda: "workspace"
    )
    monkeypatch.setattr(
        "harness.collect_evidence.subprocess.run",
        lambda *args, **kwargs: type(
            "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )(),
    )
    command = (
        ".devkind/kubectl -n coagents-dev exec deploy/frontend -- "
        "sh -lc 'cd /workspaces/coagents_service/agents-frontend && true'"
    )
    assert (
        main(
            [
                "--type",
                "custom",
                "--command",
                command,
                "--harness-dir",
                str(tmp_path / ".harness"),
            ]
        )
        == 0
    )
    import json

    record = json.loads((tmp_path / ".harness/evidence/custom.json").read_text())
    assert record["exit_code"] == 0
    assert record["runtime"]["executable"]
    assert record["execution_environment"] == {
        "transport": "kubectl_exec",
        "namespace": "coagents-dev",
        "workload": "deploy/frontend",
        "cwd": "/workspaces/coagents_service/agents-frontend",
    }


def test_main_marks_cli_command_as_trusted_local(tmp_path, monkeypatch):
    """Break caught: CLI passes raw command text past trust boundary."""
    monkeypatch.setattr("harness.collect_evidence.git_head", lambda: "a" * 40)
    monkeypatch.setattr(
        "harness.collect_evidence.workspace_fingerprint", lambda: "workspace"
    )

    assert (
        main(
            [
                "--type",
                "custom",
                "--command",
                "printf ok",
                "--harness-dir",
                str(tmp_path / ".harness"),
            ]
        )
        == 0
    )
