"""Architecture benchmark corpus and experiment contracts."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from harness.benchmark import validate_architecture_corpus

REPO = Path(__file__).resolve().parents[1]


def architecture_model():
    return {
        "version": 1,
        "modules": [
            {
                "id": "app",
                "name": "Application",
                "responsibility": "Run application behavior.",
                "depends_on": ["shared"],
                "evidence": [{"type": "source", "path": "src/app.py"}],
            },
            {
                "id": "shared",
                "name": "Shared",
                "responsibility": "Provide shared behavior.",
                "depends_on": [],
                "evidence": [{"type": "source", "path": "src/shared.py"}],
            },
        ],
        "ownership": [
            {
                "id": "OWN-001",
                "pattern": "src/app/**",
                "kind": "production",
                "modules": ["app"],
            },
            {
                "id": "OWN-002",
                "pattern": "src/shared/**",
                "kind": "production",
                "modules": ["shared"],
            },
        ],
    }


def drift_fixture(identifier="drift-case"):
    return {
        "version": 1,
        "id": identifier,
        "experiment": "drift_detection",
        "scenario": "unexpected module",
        "treatment": {
            "name": "architecture_gate",
            "baseline": {"architecture_mode": "off"},
            "adaptive": {"architecture_mode": "required"},
        },
        "inputs": {
            "task": {
                "declared_modules": ["app"],
                "protected_paths": [],
                "adopted_paths": [],
            },
            "architecture": architecture_model(),
            "git": [{"path": "src/shared/change.py", "kind": "worktree"}],
        },
        "expected": {
            "label": "drift",
            "blockers": [
                {"code": "ARCHITECTURE_SCOPE_DRIFT", "source": "module:shared"}
            ],
            "diagnostics": [],
            "expected_modules": ["shared"],
            "declaration_quality": "complete",
        },
    }


def recovery_fixture(identifier="recovery-case"):
    model = architecture_model()
    return {
        "version": 1,
        "id": identifier,
        "experiment": "context_recovery",
        "scenario": "recover declared architecture facts",
        "treatment": {
            "name": "architecture_projection",
            "baseline": {"architecture_projection": "omitted"},
            "adaptive": {"architecture_projection": "included"},
        },
        "inputs": {
            "task": {
                "declared_modules": ["app"],
                "protected_paths": [],
                "adopted_paths": [],
            },
            "architecture": model,
            "git": [],
        },
        "expected": {
            "projected_modules": [
                {
                    "id": module["id"],
                    "responsibility": module["responsibility"],
                    "depends_on": module["depends_on"],
                }
                for module in model["modules"]
            ]
        },
    }


def write_fixture(root, document, name="case.yaml"):
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(yaml.safe_dump(document, sort_keys=False))


def test_architecture_corpus_contains_ten_required_scenarios():
    rows = validate_architecture_corpus(REPO / "benchmarks/architecture")

    assert len(rows) == 10
    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
    assert {row["scenario"] for row in rows} == {
        "normal ownership",
        "unexpected module",
        "unresolved path",
        "ambiguous ownership",
        "shared ownership",
        "support path",
        "rename delete plus add",
        "adopted protected paths",
        "false positive control",
        "context recovery",
    }
    assert sum(row["experiment"] == "context_recovery" for row in rows) == 1


def test_architecture_corpus_is_independent_from_q0_q3_distribution():
    from harness.benchmark import validate_corpus

    before = validate_corpus(REPO / "benchmarks/corpus")
    validate_architecture_corpus(REPO / "benchmarks/architecture")
    after = validate_corpus(REPO / "benchmarks/corpus")

    assert before == after


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(unexpected=True),
        lambda row: row["treatment"].update(
            baseline={"architecture_mode": "required"}
        ),
        lambda row: row["inputs"]["architecture"]["modules"][0].update(id="src/app"),
        lambda row: row["inputs"]["architecture"]["ownership"][0].update(id="bad"),
        lambda row: row["expected"].update(unknown=True),
    ],
)
def test_architecture_corpus_rejects_unknown_fields_treatment_and_model_ids(
    tmp_path, mutation
):
    document = drift_fixture()
    mutation(document)
    write_fixture(tmp_path / "drift", document)

    with pytest.raises(ValueError, match="ARCHITECTURE_BENCHMARK_CORPUS_INVALID"):
        validate_architecture_corpus(tmp_path)


def test_architecture_corpus_rejects_duplicate_ids_across_experiments(tmp_path):
    write_fixture(tmp_path / "drift", drift_fixture("duplicate"))
    write_fixture(tmp_path / "context", recovery_fixture("duplicate"))

    with pytest.raises(ValueError, match="ARCHITECTURE_BENCHMARK_CORPUS_INVALID"):
        validate_architecture_corpus(tmp_path)


def test_architecture_corpus_rejects_mixed_experiment_treatment(tmp_path):
    document = recovery_fixture()
    document["treatment"] = deepcopy(drift_fixture()["treatment"])
    write_fixture(tmp_path / "context", document)

    with pytest.raises(ValueError, match="ARCHITECTURE_BENCHMARK_CORPUS_INVALID"):
        validate_architecture_corpus(tmp_path)


def test_empty_architecture_corpus_is_valid_for_library_composition(tmp_path):
    assert validate_architecture_corpus(tmp_path) == []
