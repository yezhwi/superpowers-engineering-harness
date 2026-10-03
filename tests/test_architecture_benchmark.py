"""Architecture benchmark corpus and experiment contracts."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from harness.architecture import architecture_fingerprint, load_architecture_document
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
            "git": [{"path": "src/shared/change.py", "kind": "modified"}],
        },
        "expected": {
            "label": "drift",
            "blockers": [
                {
                    "code": "ARCHITECTURE_SCOPE_DRIFT",
                    "source": "path:src/shared/change.py|module:shared",
                }
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
            "architecture_mode": "required",
            "architecture_assessment": {
                "status": "current",
                "fingerprint": architecture_fingerprint(
                    load_architecture_document(model)
                ),
                "declared_modules": ["app"],
                "relevant_modules": [
                    {
                        "id": module["id"],
                        "name": module["name"],
                        "responsibility": module["responsibility"],
                        "depends_on": module["depends_on"],
                    }
                    for module in model["modules"]
                ],
            },
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
        lambda row: row.update(version=True),
        lambda row: row["treatment"].update(
            baseline={"architecture_mode": "required"}
        ),
        lambda row: row["inputs"]["architecture"]["modules"][0].update(id="src/app"),
        lambda row: row["inputs"]["task"].update(declared_modules=["src/app"]),
        lambda row: row["expected"].update(expected_modules=["src/app"]),
        lambda row: row["inputs"]["git"][0].update(path="src/\ud800.py"),
        lambda row: row["inputs"]["architecture"]["ownership"][0].update(id="bad"),
        lambda row: row["expected"].update(unknown=True),
        lambda row: row["expected"].update(declaration_quality="omits_true_owner"),
        lambda row: row["expected"]["blockers"][0].update(source="module:shared"),
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
                "run_id": f"{fixture['id']}-{arm}-{index}",
                "provenance": {
                    "session_id": f"session-{fixture['id']}-{arm}-{index}",
                    "started_at": f"2026-10-01T00:00:0{index}Z",
                },
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


def test_drift_fixture_rejects_unknown_declared_module(tmp_path):
    fixture = drift_fixture()
    fixture["inputs"]["task"]["declared_modules"] = ["ghost"]
    write_fixture(tmp_path / "drift", fixture)

    with pytest.raises(ValueError, match="ARCHITECTURE_BENCHMARK_CORPUS_INVALID"):
        validate_architecture_corpus(tmp_path)


def test_independent_run_variance_uses_unique_mode(tmp_path):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    full = {"projected_modules": fixture["expected"]["projected_modules"]}
    partial = {"projected_modules": fixture["expected"]["projected_modules"][:1]}
    write_artifact(tmp_path / "baseline", fixture, "baseline", [full, full, partial])
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", [full, partial, full])

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="context_recovery",
    )

    assert report["status"] == "CORRECTNESS_PRESERVED"
    assert report["baseline"]["metrics"]["context_factual_recovery"] == metric(2, 2)
    assert report["adaptive"]["metrics"]["context_factual_recovery"] == metric(2, 2)


def test_declaration_quality_case_is_excluded_from_detector_metrics(tmp_path):
    fixture = drift_fixture()
    fixture["expected"]["label"] = "declaration_quality"
    fixture["expected"]["declaration_quality"] = "omits_true_owner"
    fixture["expected"]["expected_modules"] = ["shared"]
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "drift", fixture)
    observed = {"blocked": False, "blockers": [], "diagnostics": []}
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="drift_detection",
    )

    assert report["adaptive"]["metrics"] == {
        "drift_recall": metric(0, 0, 1),
        "diagnostic_precision": metric(0, 0, 0),
        "false_positive_rate": metric(0, 0, 1),
    }
    assert report["declaration_quality"]["missed_impact_proxy"] == metric(1, 1)


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
            {
                "code": "ARCHITECTURE_SCOPE_DRIFT",
                "source": "path:src/shared/change.py|module:shared",
            }
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
    "defect", [
        "two_runs", "fingerprint", "inputs", "input_type", "estimated", "arm"
    ]
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
    if defect in {"fingerprint", "inputs", "input_type", "arm"}:
        document = __import__("json").loads(path.read_text())
        if defect == "inputs":
            document["inputs"]["token_budget"] += 1
        elif defect == "input_type":
            document["inputs"]["token_budget"] = 4096.0
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
        run["usage"]["source"] = "estimated"
    adaptive_path.write_text(__import__("json").dumps(document))

    cheaper = compare_architecture_experiment(
        fixtures,
        tmp_path / "baseline",
        tmp_path / "adaptive",
        experiment="context_recovery",
    )
    assert cheaper["status"] == "FAIL"
    assert cheaper["correctness_precedes_efficiency"] is True
    assert cheaper["baseline"]["efficiency"] == INCONCLUSIVE
    assert cheaper["adaptive"]["efficiency"] == INCONCLUSIVE


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


def test_baseline_integrity_failure_is_inconclusive_and_suppresses_efficiency(tmp_path):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    observed = {"projected_modules": fixture["expected"]["projected_modules"]}
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))
    path = tmp_path / "baseline" / f"{fixture['id']}.json"
    document = __import__("json").loads(path.read_text())
    document["runs"][0]["integrity"] = False
    path.write_text(__import__("json").dumps(document))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="context_recovery",
    )

    assert report["status"] == INCONCLUSIVE
    assert report["baseline"]["efficiency"] == INCONCLUSIVE
    assert report["adaptive"]["efficiency"] == INCONCLUSIVE


@pytest.mark.parametrize("usage_defect", ["estimated", "missing"])
def test_adaptive_integrity_failure_fails_and_suppresses_efficiency(
    tmp_path, usage_defect
):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    observed = {"projected_modules": fixture["expected"]["projected_modules"]}
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))
    path = tmp_path / "adaptive" / f"{fixture['id']}.json"
    document = __import__("json").loads(path.read_text())
    document["runs"][0]["integrity"] = False
    if usage_defect == "estimated":
        document["runs"][0]["usage"]["source"] = "estimated"
    else:
        del document["runs"][0]["usage"]
    path.write_text(__import__("json").dumps(document))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="context_recovery",
    )

    assert report["status"] == "FAIL"
    assert report["baseline"]["efficiency"] == INCONCLUSIVE
    assert report["adaptive"]["efficiency"] == INCONCLUSIVE


def test_supported_nonprecision_blocker_is_scored_not_rejected(tmp_path):
    fixture = drift_fixture()
    fixture["expected"] = {
        "label": "clean",
        "blockers": [],
        "diagnostics": [],
        "expected_modules": ["app"],
        "declaration_quality": "complete",
    }
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "drift", fixture)
    observed = {
        "blocked": True,
        "blockers": [
            {"code": "ARCHITECTURE_OWNERSHIP_EMPTY", "source": "ownership:OWN-001"}
        ],
        "diagnostics": [],
    }
    write_artifact(
        tmp_path / "baseline",
        fixture,
        "baseline",
        repeated({"blocked": False, "blockers": [], "diagnostics": []}),
    )
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="drift_detection",
    )
    assert report["status"] == "FAIL"
    assert report["adaptive"]["metrics"]["false_positive_rate"] == metric(1, 1)


def test_adaptive_incorrect_diagnostic_fails_when_baseline_is_not_applicable(tmp_path):
    fixture = drift_fixture()
    fixture["expected"]["diagnostics"] = [
        {"code": "ARCHITECTURE_OWNERSHIP_UNRESOLVED", "source": "path:src/x.py"}
    ]
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "drift", fixture)
    baseline_seen = {"blocked": False, "blockers": [], "diagnostics": []}
    adaptive_seen = {
        "blocked": True,
        "blockers": fixture["expected"]["blockers"],
        "diagnostics": [
            {"code": "ARCHITECTURE_OWNERSHIP_UNRESOLVED", "source": "path:wrong.py"}
        ],
    }
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(baseline_seen))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(adaptive_seen))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="drift_detection",
    )

    assert report["status"] == "FAIL"
    assert report["adaptive"]["efficiency"] == INCONCLUSIVE


@pytest.mark.parametrize(
    ("experiment", "field", "value"),
    [
        ("drift_detection", "diagnostics", [{"code": "UNKNOWN", "source": "bad"}]),
        (
            "context_recovery",
            "projected_modules",
            [{"id": "src/app", "responsibility": "bad", "depends_on": []}],
        ),
    ],
)
def test_malformed_observed_identity_is_inconclusive(tmp_path, experiment, field, value):
    fixture = drift_fixture() if experiment == "drift_detection" else recovery_fixture()
    directory = "drift" if experiment == "drift_detection" else "context"
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / directory, fixture)
    observed = (
        {"blocked": False, "blockers": [], "diagnostics": []}
        if experiment == "drift_detection"
        else {"projected_modules": []}
    )
    observed[field] = value
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment=experiment,
    )
    assert report["status"] == INCONCLUSIVE


def test_reused_run_provenance_across_arms_is_inconclusive(tmp_path):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    observed = {"projected_modules": fixture["expected"]["projected_modules"]}
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))
    baseline = __import__("json").loads(
        (tmp_path / "baseline" / f"{fixture['id']}.json").read_text()
    )
    path = tmp_path / "adaptive" / f"{fixture['id']}.json"
    adaptive = __import__("json").loads(path.read_text())
    adaptive["runs"][0]["provenance"] = baseline["runs"][0]["provenance"]
    path.write_text(__import__("json").dumps(adaptive))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="context_recovery",
    )
    assert report["status"] == INCONCLUSIVE


def test_context_fixture_requires_current_required_assessment(tmp_path):
    fixture = recovery_fixture()
    fixture["inputs"]["architecture_mode"] = "off"
    write_fixture(tmp_path / "context", fixture)

    with pytest.raises(ValueError, match="ARCHITECTURE_BENCHMARK_CORPUS_INVALID"):
        validate_architecture_corpus(tmp_path)


def test_boolean_artifact_version_is_inconclusive(tmp_path):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    observed = {"projected_modules": fixture["expected"]["projected_modules"]}
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))
    path = tmp_path / "adaptive" / f"{fixture['id']}.json"
    document = __import__("json").loads(path.read_text())
    document["version"] = True
    path.write_text(__import__("json").dumps(document))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="context_recovery",
    )
    assert report["status"] == INCONCLUSIVE


def test_invalid_utf8_artifact_is_inconclusive(tmp_path):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    observed = {"projected_modules": fixture["expected"]["projected_modules"]}
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))
    (tmp_path / "adaptive" / f"{fixture['id']}.json").write_bytes(b"\xff")

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="context_recovery",
    )
    assert report["status"] == INCONCLUSIVE


def test_context_ground_truth_must_equal_assessment_projection(tmp_path):
    fixture = recovery_fixture()
    fixture["expected"]["projected_modules"] = [
        fixture["expected"]["projected_modules"][1]
    ]
    write_fixture(tmp_path / "context", fixture)

    with pytest.raises(ValueError, match="ARCHITECTURE_BENCHMARK_CORPUS_INVALID"):
        validate_architecture_corpus(tmp_path)


def test_diagnostic_precision_becoming_not_applicable_is_regression(tmp_path):
    fixture = drift_fixture()
    expected = {
        "code": "ARCHITECTURE_OWNERSHIP_UNRESOLVED",
        "source": "path:src/expected.py",
    }
    fixture["expected"]["diagnostics"] = [expected]
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "drift", fixture)
    blockers = fixture["expected"]["blockers"]
    write_artifact(
        tmp_path / "baseline", fixture, "baseline",
        repeated({"blocked": True, "blockers": blockers, "diagnostics": [expected]}),
    )
    write_artifact(
        tmp_path / "adaptive", fixture, "adaptive",
        repeated({"blocked": True, "blockers": blockers, "diagnostics": []}),
    )

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="drift_detection",
    )
    assert report["status"] == "FAIL"


def test_removing_only_false_diagnostics_is_not_a_regression(tmp_path):
    fixture = drift_fixture()
    expected = {
        "code": "ARCHITECTURE_OWNERSHIP_UNRESOLVED",
        "source": "path:src/expected.py",
    }
    fixture["expected"]["diagnostics"] = [expected]
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "drift", fixture)
    wrong = {
        "code": "ARCHITECTURE_OWNERSHIP_AMBIGUOUS",
        "source": "path:src/wrong.py",
    }
    blockers = fixture["expected"]["blockers"]
    write_artifact(
        tmp_path / "baseline", fixture, "baseline",
        repeated({"blocked": True, "blockers": blockers, "diagnostics": [wrong]}),
    )
    write_artifact(
        tmp_path / "adaptive", fixture, "adaptive",
        repeated({"blocked": True, "blockers": blockers, "diagnostics": []}),
    )

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="drift_detection",
    )

    assert report["baseline"]["metrics"]["diagnostic_precision"]["numerator"] == 0
    assert report["adaptive"]["metrics"]["diagnostic_precision"]["value"] == "not_applicable"
    assert report["status"] == "CORRECTNESS_PRESERVED"


def test_improved_nonperfect_diagnostic_precision_is_not_a_regression(tmp_path):
    fixture = drift_fixture()
    expected_diagnostic = {
        "code": "ARCHITECTURE_OWNERSHIP_UNRESOLVED",
        "source": "path:src/expected.py",
    }
    fixture["expected"]["diagnostics"] = [expected_diagnostic]
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "drift", fixture)
    wrong_one = {
        "code": "ARCHITECTURE_OWNERSHIP_UNRESOLVED",
        "source": "path:src/wrong-one.py",
    }
    wrong_two = {
        "code": "ARCHITECTURE_OWNERSHIP_AMBIGUOUS",
        "source": "path:src/wrong-two.py",
    }
    blockers = fixture["expected"]["blockers"]
    write_artifact(
        tmp_path / "baseline",
        fixture,
        "baseline",
        repeated({"blocked": True, "blockers": blockers, "diagnostics": [wrong_one, wrong_two]}),
    )
    write_artifact(
        tmp_path / "adaptive",
        fixture,
        "adaptive",
        repeated({"blocked": True, "blockers": blockers, "diagnostics": [expected_diagnostic, wrong_one]}),
    )

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="drift_detection",
    )

    assert report["status"] == "CORRECTNESS_IMPROVED"
    assert report["adaptive"]["efficiency"] != INCONCLUSIVE


@pytest.mark.parametrize(
    "source", ["path:.", "path:./wrong.py", "path:a//b", "path:a/"]
)
def test_noncanonical_observed_path_identity_is_inconclusive(tmp_path, source):
    fixture = drift_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "drift", fixture)
    observed = {
        "blocked": True,
        "blockers": fixture["expected"]["blockers"],
        "diagnostics": [
            {"code": "ARCHITECTURE_OWNERSHIP_UNRESOLVED", "source": source}
        ],
    }
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="drift_detection",
    )
    assert report["status"] == INCONCLUSIVE


@pytest.mark.parametrize(
    ("timestamp", "expected_status"),
    [
        ("2026-10-01T00:00:01+00:00", "CORRECTNESS_PRESERVED"),
        ("2026-10-01t00:00:01z", "CORRECTNESS_PRESERVED"),
        ("1990-12-31T23:59:60Z", "CORRECTNESS_PRESERVED"),
        ("2026-10-01T00:00:60Z", INCONCLUSIVE),
        ("0001-01-01T00:00:60Z", INCONCLUSIVE),
        ("2026-99-99T99:99:99Z", INCONCLUSIVE),
        ("2026-10-01T00:00:01+00:60", INCONCLUSIVE),
    ],
)
def test_provenance_timestamp_uses_rfc3339_calendar_validation(
    tmp_path, timestamp, expected_status
):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    observed = {"projected_modules": fixture["expected"]["projected_modules"]}
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))
    path = tmp_path / "adaptive" / f"{fixture['id']}.json"
    document = __import__("json").loads(path.read_text())
    document["runs"][0]["provenance"]["started_at"] = timestamp
    path.write_text(__import__("json").dumps(document))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="context_recovery",
    )
    assert report["status"] == expected_status


@pytest.mark.parametrize(
    ("experiment", "mutation"),
    [
        (
            "drift_detection",
            lambda document: document["runs"][0]["observed"]["blockers"][0].update(
                code=[]
            ),
        ),
        (
            "context_recovery",
            lambda document: document["runs"][0]["observed"]["projected_modules"][0].update(
                depends_on=[[]]
            ),
        ),
    ],
)
def test_unhashable_observed_identity_is_inconclusive(tmp_path, experiment, mutation):
    fixture = drift_fixture() if experiment == "drift_detection" else recovery_fixture()
    directory = "drift" if experiment == "drift_detection" else "context"
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / directory, fixture)
    observed = (
        {
            "blocked": True,
            "blockers": fixture["expected"]["blockers"],
            "diagnostics": [],
        }
        if experiment == "drift_detection"
        else {"projected_modules": fixture["expected"]["projected_modules"]}
    )
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(observed))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(observed))
    path = tmp_path / "adaptive" / f"{fixture['id']}.json"
    document = __import__("json").loads(path.read_text())
    mutation(document)
    path.write_text(__import__("json").dumps(document))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment=experiment,
    )
    assert report["status"] == INCONCLUSIVE


def test_invalid_efficiency_success_does_not_mask_context_regression(tmp_path):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    expected = {"projected_modules": fixture["expected"]["projected_modules"]}
    empty = {"projected_modules": []}
    write_artifact(tmp_path / "baseline", fixture, "baseline", repeated(expected))
    write_artifact(tmp_path / "adaptive", fixture, "adaptive", repeated(empty))
    path = tmp_path / "adaptive" / f"{fixture['id']}.json"
    document = __import__("json").loads(path.read_text())
    document["runs"][0]["success"] = "bad"
    path.write_text(__import__("json").dumps(document))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="context_recovery",
    )
    assert report["status"] == "FAIL"
    assert report["adaptive"]["efficiency"] == INCONCLUSIVE


def test_adaptive_integrity_failure_wins_when_both_arms_fail_integrity(tmp_path):
    fixture = recovery_fixture()
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "context", fixture)
    observed = {"projected_modules": fixture["expected"]["projected_modules"]}
    for arm in ("baseline", "adaptive"):
        write_artifact(tmp_path / arm, fixture, arm, repeated(observed))
        path = tmp_path / arm / f"{fixture['id']}.json"
        document = __import__("json").loads(path.read_text())
        document["runs"][0]["integrity"] = False
        path.write_text(__import__("json").dumps(document))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="context_recovery",
    )
    assert report["status"] == "FAIL"


def test_other_experiment_artifact_cannot_change_selected_verdict(tmp_path):
    drift = drift_fixture("drift-global")
    context = recovery_fixture("context-global")
    context["version"] = True
    fixtures = tmp_path / "fixtures"
    write_fixture(fixtures / "drift", drift, "drift.yaml")
    write_fixture(fixtures / "context", context, "context.yaml")
    drift_seen = {
        "blocked": True,
        "blockers": drift["expected"]["blockers"],
        "diagnostics": [],
    }
    context_seen = {"projected_modules": context["expected"]["projected_modules"]}
    for arm in ("baseline", "adaptive"):
        write_artifact(tmp_path / arm, drift, arm, repeated(drift_seen))
        write_artifact(tmp_path / arm, context, arm, repeated(context_seen))
    drift_artifact = __import__("json").loads(
        (tmp_path / "baseline" / f"{drift['id']}.json").read_text()
    )
    path = tmp_path / "baseline" / f"{context['id']}.json"
    context_artifact = __import__("json").loads(path.read_text())
    context_artifact["runs"][0]["run_id"] = drift_artifact["runs"][0]["run_id"]
    context_artifact["runs"][0]["provenance"] = drift_artifact["runs"][0]["provenance"]
    context_artifact["runs"][0]["observed"]["projected_modules"][0]["id"] = "src/bad"
    path.write_text(__import__("json").dumps(context_artifact))

    report = compare_architecture_experiment(
        fixtures, tmp_path / "baseline", tmp_path / "adaptive",
        experiment="drift_detection",
    )
    assert report["status"] == "CORRECTNESS_PRESERVED"


def test_scope_invalid_identity_enforces_module_id_length(tmp_path):
    fixture = drift_fixture()
    fixture["expected"]["blockers"] = [
        {"code": "ARCHITECTURE_SCOPE_INVALID", "source": "module:" + "a" * 65}
    ]
    write_fixture(tmp_path / "drift", fixture)

    with pytest.raises(ValueError, match="ARCHITECTURE_BENCHMARK_CORPUS_INVALID"):
        validate_architecture_corpus(tmp_path)


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
