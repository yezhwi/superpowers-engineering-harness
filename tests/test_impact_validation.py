"""Impact normalization must precede mutation and preserve unrelated content."""
import pytest
import yaml
from test_cli_task_recovery import run_cli
from test_task_replacement import committed_repo


@pytest.mark.parametrize("body", [
    {"impact": {"changed": [], "required_tests": []}, "user_data": {"keep": 1}},
    {"impact": {}},
])
def test_partial_impact_can_add_risk_without_losing_fields(tmp_path, body):
    repo = committed_repo(tmp_path)
    path = repo / ".harness/impact.yaml"
    path.write_text(yaml.safe_dump(body))
    result = run_cli(repo, "impact", "add-risk", "fixture-risk")
    assert result.returncode == 0, result.stdout + result.stderr
    after = yaml.safe_load(path.read_text())
    assert after["impact"]["risks"] == ["fixture-risk"]
    if "user_data" in body:
        assert after["user_data"] == body["user_data"]


@pytest.mark.parametrize("body", [
    None, [], {"impact": None}, {"impact": {"changed": "not a list"}},
    {"impact": {"risks": {}}}, {"impact": {"interfaces": ["not a record"]}},
    {"impact": {"contracts": [{"ref": "x", "kind": "unknown"}]}},
])
def test_invalid_impact_refuses_without_task_or_document_mutation(tmp_path, body):
    repo = committed_repo(tmp_path)
    path = repo / ".harness/impact.yaml"
    path.write_text(yaml.safe_dump(body))
    task = repo / ".harness/current-task.yaml"
    before = task.read_bytes(), path.read_bytes()
    result = run_cli(repo, "impact", "add-risk", "fixture-risk")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "IMPACT_CONTRACT_INVALID" in result.stderr
    assert "Traceback" not in result.stderr
    assert (task.read_bytes(), path.read_bytes()) == before
