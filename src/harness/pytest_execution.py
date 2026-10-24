"""Child-side pytest plugin. Nested pytest sessions are test internals, not proof."""
import json
import os
import uuid
from pathlib import Path

import pytest

_state = None
_depth = 0
_previous_active = None


def pytest_sessionstart(session):
    global _state, _depth, _previous_active
    active = os.environ.get("HARNESS_PYTEST_ACTIVE")
    if active and active != str(os.getpid()):
        return
    _depth += 1
    if _depth != 1:
        return
    _previous_active = active
    os.environ["HARNESS_PYTEST_ACTIVE"] = str(os.getpid())
    _state = {"root": str(session.config.rootpath), "collected": set(), "passed": set(),
              "failed": set(), "skipped": set(), "assertion_failures": set(), "errors": 0}
    # Inspect effective configuration too: ini/PYTEST_ADDOPTS can hide worker flags.
    config = session.config
    if (hasattr(config, "workerinput")
            or config.getoption("numprocesses", default=None) not in (None, 0, "0")
            or config.getoption("dist", default="no") not in (None, "no")
            or config.getoption("tx", default=[])):
        _state["errors"] += 1


def pytest_itemcollected(item):
    if _depth == 1:
        _state["collected"].add(item.nodeid)


def pytest_collectreport(report):
    if _depth == 1 and report.failed:
        _state["errors"] += 1


def pytest_internalerror(excrepr, excinfo):
    if _depth == 1:
        _state["errors"] += 1


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    yield
    if (_depth == 1 and call.when == "call" and call.excinfo is not None
            and isinstance(call.excinfo.value, (AssertionError, pytest.fail.Exception))):
        _state["assertion_failures"].add(item.nodeid)


def pytest_runtest_logreport(report):
    if _depth != 1:
        return
    if report.when == "call":
        _state[report.outcome].add(report.nodeid)
    elif report.failed:
        _state["errors"] += 1
    elif report.skipped:
        _state["skipped"].add(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    global _depth, _state
    if _depth > 1:
        _depth -= 1
        return
    if _depth != 1:
        return
    _depth = 0
    try:
        directory = os.environ.get("HARNESS_PYTEST_REPORT_DIR")
        nonce = os.environ.get("HARNESS_PYTEST_REPORT_NONCE")
        if not directory or not nonce:
            return
        document = {key: sorted(value) if isinstance(value, set) else value
                    for key, value in _state.items()}
        # An expected xfail may raise an assertion but is reported as skipped.
        document["assertion_failures"] = sorted(_state["assertion_failures"] & _state["failed"])
        document.update(nonce=nonce, exit_code=int(exitstatus))
        path = Path(directory) / (uuid.uuid4().hex + ".json")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(document, stream, sort_keys=True)
    finally:
        _state = None
        if _previous_active is None:
            os.environ.pop("HARNESS_PYTEST_ACTIVE", None)
        else:
            os.environ["HARNESS_PYTEST_ACTIVE"] = _previous_active
