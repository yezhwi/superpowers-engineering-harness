"""Architecture benchmark corpus and experiment contracts."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from harness.benchmark import (
    INCONCLUSIVE,
    architecture_fixture_fingerprint,
    compare_architecture_experiment,
    validate_architecture_corpus,
)

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
            "token_budget": 4096,
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
            "token_budget": 4096,
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


def write_artifact(root, fixture, arm, observations, *, usage_source="runtime"):
    root.mkdir(parents=True, exist_ok=True)
    runs = []
    for index, observed in enumerate(observations, 1):
        runs.append(
            {
                "run_id": f"{arm}-{index}",
                "success": True,
                "integrity": True,
                "observed": observed,
                "usage": {
                    "total_tokens": 100 + index,
                    "tool_calls": 10 + index,
                    "source": usage_source,
                },
            }
        )
    document = {
        "version": 1,
        "fixture_id": fixture["id"],
        "experiment": fixture["experiment"],
        "arm": arm,
        "treatment": fixture["treatment"][arm],
        "input_fingerprint": architecture_fixture_fingerprint(fixture),
        "inputs": deepcopy(fixture["inputs"]),
        "runs": runs,
    }
    (root / f"{fixture['id']}.json").write_text(
        __import__("json").dumps(document)
    )


def repeated(observed):
    return [deepcopy(observed) for _ in range(3)]


def metric(numerator, denominator, not_applicable=0):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "not_applicable": not_applicable,
        "value": numerator / denominator if denominator else "not_applicable",
    }


def test_drift_comparison_uses_exact_fixed_formulas(tmp_path):
    fixtures = tmp_path / "fixtures"
    drift = drift_fixture("drift-labeled")
    drift["inputs"]["task"]["declared_modules"] = ["app"]
    drift["expected"]["expected_modules"] = ["shared"]
    drift["expected"]["diagnostics"] = [
        {"code": "ARCHITECTURE_OWNERSHIP_UNRESOLVED", "source": "path:src/x.py"}
    ]
    clean = drift_fixture("clean-labeled")
    clean["expected"] = {
        "label": "clean",
        "blockers": [],
        "diagnostics": [],
        "expected_modules": ["app"],
        "declaration_quality": "complete",
    }
    write_fixture(fixtures / "drift", drift, "drift.yaml")
    write_fixture(fixtures / "drift", clean, "clean.yaml")

    no_detection = {"blocked": False, "blockers": [], "diagnostics": []}
    correct_drift = {
        "blocked": True,
        "blockers": drift["expected"]["blockers"],
        "diagnostics": drift["expected"]["diagnostics"],
    }
    wrong_clean = {
        "blocked": True,
        "blockers": [],
        "diagnostics": [
            {"code": "ARCHITECTURE_OWNERSHIP_UNRESOLVED", "source": "path:wrong.py"}
        ],
    }
    for fixture, baseline_seen, adaptive_seen in (
        (drift, no_detection, correct_drift),
        (clean, no_detection, wrong_clean),
    ):
        write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(baseline_seen))
        write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(adaptive_seen))

    report = compare_architecture_experiment(
        fixtures,
        tmp_path / "baseline",
        tmp_path / "adaptive",
        experiment="drift_detection",
    )

    assert report["status"] == "FAIL"
    assert report["baseline"]["metrics"] == {
        "drift_recall": metric(0, 1),
        "diagnostic_precision": metric(0, 0, 2),
        "false_positive_rate": metric(0, 1),
    }
    assert report["adaptive"]["metrics"] == {
        "drift_recall": metric(1, 1),
        "diagnostic_precision": metric(1, 2),
        "false_positive_rate": metric(1, 1),
    }
    assert report["declaration_quality"]["missed_impact_proxy"] == metric(1, 2)
    assert "efficiency" in report["baseline"]
    assert "efficiency" in report["adaptive"]


def test_scope_drift_blocker_does_not_count_as_diagnostic_precision(tmp_path):
    fixture = drift_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "drift", fixture)
    observed = {
        "blocked": True,
        "blockers": fixture["expected"]["blockers"],
        "diagnostics": [
            {"code": "ARCHITECTURE_SCOPE_DRIFT", "source": "module:shared"}
        ],
    }
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))

    report = compare_architecture_experiment(
        fixtures,
        tmp_path / "baseline",
        tmp_path / "adaptive",
        experiment="drift_detection",
    )

    assert report["adaptive"]["metrics"]["diagnostic_precision"] == metric(0, 0, 1)


@pytest.mark.parametrize(
    "defect", ["two_runs", "fingerprint", "inputs", "estimated", "arm"]
)
def test_comparison_is_inconclusive_for_incomplete_or_mismatched_runs(
    tmp_path, defect
):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    observed = {"projected_modules": fixture["expected"]["projected_modules"]}
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(
        tmp_path / "adaptive",
        fixture,
        "adaptive",
        repeated(observed)[: 2 if defect == "two_runs" else 3],
        usage_source="estimated" if defect == "estimated" else "runtime",
    )
    path = tmp_path / "adaptive" / f"{fixture['id']}.json"
    if defect in {"fingerprint", "inputs", "arm"}:
        document = __import__("json").loads(path.read_text())
        if defect == "inputs":
            document["inputs"]["token_budget"] += 1
        else:
            document["input_fingerprint" if defect == "fingerprint" else "arm"] = "wrong"
        path.write_text(__import__("json").dumps(document))

    report = compare_architecture_experiment(
        fixtures,
        tmp_path / "baseline",
        tmp_path / "adaptive",
        experiment="context_recovery",
    )

    assert report["status"] == INCONCLUSIVE


def test_context_recovery_exact_match_and_correctness_precede_cost(tmp_path):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    expected = fixture["expected"]["projected_modules"]
    baseline_seen = {"projected_modules": []}
    adaptive_seen = {"projected_modules": [expected[0]]}
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(baseline_seen))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(adaptive_seen))

    report = compare_architecture_experiment(
        fixtures,
        tmp_path / "baseline",
        tmp_path / "adaptive",
        experiment="context_recovery",
    )

    assert report["baseline"]["metrics"]["context_factual_recovery"] == metric(0, 2)
    assert report["adaptive"]["metrics"]["context_factual_recovery"] == metric(1, 2)
    assert report["status"] == "CORRECTNESS_IMPROVED"
    assert list(report)[:5] == [
        "experiment",
        "treatment",
        "status",
        "confidence",
        "correctness_precedes_efficiency",
    ]
    assert report["treatment"] == fixture["treatment"]
    assert report["fixtures"] == [
        {
            "id": fixture["id"],
            "baseline_runs": 3,
            "adaptive_runs": 3,
        }
    ]

    # Cheaper adaptive runs cannot hide lower factual recovery.
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated({"projected_modules": expected}))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(baseline_seen))
    adaptive_path = tmp_path / "adaptive" / f"{fixture['id']}.json"
    document = __import__("json").loads(adaptive_path.read_text())
    for run in document["runs"]:
        run["usage"]["total_tokens"] = 1
        run["usage"]["tool_calls"] = 1
    adaptive_path.write_text(__import__("json").dumps(document))

    cheaper = compare_architecture_experiment(
        fixtures,
        tmp_path / "baseline",
        tmp_path / "adaptive",
        experiment="context_recovery",
    )
    assert cheaper["status"] == "FAIL"
    assert cheaper["correctness_precedes_efficiency"] is True


def test_comparison_rejects_cross_experiment_fixture_selection(tmp_path):
    fixture = drift_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "drift", fixture)

    report = compare_architecture_experiment(
        fixtures,
        tmp_path / "baseline",
        tmp_path / "adaptive",
        experiment="context_recovery",
    )

    assert report["status"] == INCONCLUSIVE


def test_architecture_report_orders_fixture_rows_deterministically(tmp_path):
    fixtures = tmp_path / "fixtures"
    rows = [recovery_fixture("z-case"), recovery_fixture("a-case")]
    for fixture in rows:
        write_fixture(fixtures / "context", fixture, f"{fixture['id']}.yaml")
        observed = {"projected_modules": fixture["expected"]["projected_modules"]}
        write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
        write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))

    report = compare_architecture_experiment(
        fixtures,
        tmp_path / "baseline",
        tmp_path / "adaptive",
        experiment="context_recovery",
    )

    assert [row["id"] for row in report["fixtures"]] == ["a-case", "z-case"]
    assert report["baseline"]["efficiency"]["median_tokens"] == 102.0
    assert report["baseline"]["efficiency"]["tool_calls_per_success"] == 12.0


def test_repository_contains_no_synthetic_architecture_run_artifacts():
    assert not list((REPO / "benchmarks/architecture").rglob("*.json"))


def test_architecture_compare_cli_emits_json_without_mutating_harness(tmp_path):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.cli",
            "benchmark",
            "architecture-compare",
            "--experiment",
            "context_recovery",
            "--fixtures",
            str(fixtures),
            "--baseline",
            str(tmp_path / "baseline"),
            "--adaptive",
            str(tmp_path / "adaptive"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src")},
    )

    assert result.returncode == 0
    report = __import__("json").loads(result.stdout)
    assert result.stdout.index('"status"') < result.stdout.index('"efficiency"')
    assert report["experiment"] == "context_recovery"
    assert report["treatment"] == fixture["treatment"]
    assert report["status"] == INCONCLUSIVE
    assert report["fixtures"] == [
        {"id": fixture["id"], "baseline_runs": 0, "adaptive_runs": 0}
    ]
    assert report["baseline"]["metrics"]["context_factual_recovery"] == {
        "numerator": None,
        "denominator": 2,
        "not_applicable": 0,
        "value": INCONCLUSIVE,
    }
    assert report["baseline"]["efficiency"] == INCONCLUSIVE
    assert not (tmp_path / ".harness").exists()
