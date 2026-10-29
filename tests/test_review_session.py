"""A managed review session reports incomplete work instead of PASS."""

import json

from harness.cli import _review_batches, _review_session
from harness.review_session import Session, conclude, meter, switch_model


def _session():
    return Session(10, 2, 100, frozenset({"src/a.py"}), {"src/a.py"}, historical_obligations=("TASK-115",),
                   increment=("b1",))


def test_metered_cover_can_pass_and_exhaustion_cannot(tmp_path):
    session = _session()
    meter(session, seconds=1, calls=1, tokens=20)
    assert conclude(session, "PASS")["accepted_pass"] is True

    switch_model(session)
    switch_model(session)
    refused = conclude(session, "PASS")
    assert refused["verdict"] == "INCOMPLETE"
    assert refused["accepted_pass"] is False
    assert refused["partial_done"] is False
    assert refused["historical_obligations"] == ["TASK-115"]
    assert refused["enforcement"] == "managed-session-only"

    missing = _session()
    missing.reviewed_paths.clear()
    meter(missing, seconds=1, calls=1, tokens=1)
    assert conclude(missing, "PASS")["missing_paths"] == ["src/a.py"]

    document = {
        "budget_seconds": 10, "budget_calls": 2, "budget_tokens": 100,
        "required_paths": ["src/a.py"], "reviewed_paths": ["src/a.py"],
        "usage": [{"seconds": 9, "calls": 3, "tokens": 1}], "verdict": "PASS",
        "historical_obligations": ["TASK-115"], "increment": ["b1"],
    }
    path = tmp_path / "session.json"
    path.write_text(json.dumps(document))
    assert _review_session(path) == 1


def test_batches_command_reports_affected_work_without_partial_done(tmp_path, capsys):
    document = {
        "batches": [
            {"id": "b1", "selector": "tests/test_a.py", "report": "reports/b1.json",
             "tests": ["tests/test_a.py::test_a"], "resources": ["port"]},
            {"id": "b2", "selector": "tests/test_b.py", "report": "reports/b2.json",
             "tests": ["tests/test_b.py::test_b"], "resources": ["port"]},
        ],
        "owners": {"tests/test_a.py::test_a": ["src/a.py"]},
        "changed": ["src/a.py"],
        "historical_obligations": ["TASK-115"],
        "passed": ["b1"],
    }
    path = tmp_path / "batches.json"
    path.write_text(json.dumps(document))
    assert _review_batches(path) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["rerun"] == ["b1"]
    assert body["serial_groups"] == [["b1", "b2"]]
    assert body["partial_done"] is False
    assert body["historical_obligations"] == ["TASK-115"]
    assert body["increment_complete"] is False
