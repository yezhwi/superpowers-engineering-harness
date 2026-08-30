"""Cross-layer diagnosability control-plane scenarios."""

import yaml

from test_cli_diagnosability import make_repo, review_source, run_cli


def test_e2e_contract_mismatch_leaves_no_canonical_artifacts(tmp_path):
    repo = make_repo(tmp_path)
    source = review_source(tmp_path)
    document = yaml.safe_load(source.read_text())
    document["contract_required"] = False
    source.write_text(yaml.safe_dump(document))

    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(source))

    assert result.returncode == 2
    assert "DIAG_CONTRACT_REQUIRED_MISMATCH" in result.stderr
    assert not (repo / ".harness/evidence/diagnosability-review.json").exists()


def test_e2e_out_of_scope_finding_rejects_without_artifacts(tmp_path):
    repo = make_repo(tmp_path)
    source = review_source(tmp_path, external_result="fail")
    document = yaml.safe_load(source.read_text())
    document["finding_ids"] = ["FND-011"]
    document["findings"] = [{
        "id": "FND-011", "kind": "requirement_violation", "target": "REQ-001",
        "category": "diagnosability", "reason_code": "DIAG_MISSING_EXTERNAL_FAILURE_CONTEXT",
        "severity": "major", "status": "PROPOSED", "scenario": "outside scope",
        "location": {"file": "src/other.py"},
        "compliance": {"evidence_kind": "static_compliance", "required_checks": ["external_failure_context"]},
    }]
    source.write_text(yaml.safe_dump(document))

    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(source))

    assert result.returncode == 2
    assert "DIAG_FINDING_LINKAGE_INVALID" in result.stderr
    assert not (repo / ".harness/findings/FND-011.yaml").exists()


def test_e2e_not_applicable_required_dimension_rejects(tmp_path):
    repo = make_repo(tmp_path)
    source = review_source(tmp_path)
    document = yaml.safe_load(source.read_text())
    document["checks"]["business_keys"] = "not_applicable"
    source.write_text(yaml.safe_dump(document))

    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(source))

    assert result.returncode == 2
    assert "DIAG_NOT_APPLICABLE_INVALID" in result.stderr
