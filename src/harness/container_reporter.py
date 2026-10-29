"""Stdlib-and-pytest reporter copied into the container. No host control plane."""

import io
import json
import os
import sys

import pytest

_state = None


def _forbidden(args):
    return any(arg == "-d" or arg.startswith(("-n", "--numprocesses", "--dist", "--tx")) for arg in args)


def _absolute(node, root):
    file, separator, suffix = node.partition("::")
    if not file.startswith("/"):
        file = root.rstrip("/") + "/" + file
    return file + (separator + suffix if separator else "")


def pytest_sessionstart(session):
    global _state
    _state = {"collected": set(), "passed": set(), "failed": set(), "skipped": set(),
              "assertion_failures": set(), "errors": 0}
    config = session.config
    if (hasattr(config, "workerinput")
            or config.getoption("numprocesses", default=None) not in (None, 0, "0")
            or config.getoption("dist", default="no") not in (None, "no")
            or config.getoption("tx", default=[])):
        _state["errors"] += 1


def pytest_itemcollected(item):
    if _state is not None:
        _state["collected"].add(item.nodeid)


def pytest_collection_modifyitems(session, config, items):
    if _state is not None:
        _state["collected"] = {item.nodeid for item in items}


def pytest_sessionfinish(session, exitstatus):
    if _state is not None:
        _state["collected"] = {item.nodeid for item in session.items}


def pytest_collectreport(report):
    if _state is not None and report.failed:
        _state["errors"] += 1


def pytest_internalerror(excrepr, excinfo):
    if _state is not None:
        _state["errors"] += 1


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    yield
    if (_state is not None and call.when == "call" and call.excinfo is not None
            and isinstance(call.excinfo.value, (AssertionError, pytest.fail.Exception))):
        _state["assertion_failures"].add(item.nodeid)


def pytest_runtest_logreport(report):
    if _state is None:
        return
    if report.when == "call":
        _state[report.outcome].add(report.nodeid)
    elif report.failed:
        _state["errors"] += 1
    elif report.skipped:
        _state["skipped"].add(report.nodeid)


def _document(exit_code, root):
    document = {key: sorted(value) if isinstance(value, set) else value for key, value in _state.items()}
    document["assertion_failures"] = sorted(_state["assertion_failures"] & _state["failed"])
    for key in ("collected", "passed", "failed", "skipped", "assertion_failures"):
        document[key] = [_absolute(node, root) for node in document[key]]
    document.update(
        schema="container-pytest/v1",
        run_id=os.environ["HARNESS_RUN_ID"],
        attempt=os.environ["HARNESS_ATTEMPT"],
        command=os.environ["HARNESS_COMMAND"],
        exit_code=int(exit_code),
        target=json.loads(os.environ["HARNESS_TARGET"]),
        source_fingerprint=os.environ["HARNESS_SOURCE_FINGERPRINT"],
    )
    return document


def main():
    required = ("HARNESS_RUN_ID", "HARNESS_ATTEMPT", "HARNESS_COMMAND", "HARNESS_TARGET",
                "HARNESS_SOURCE_FINGERPRINT", "HARNESS_CONTAINER_ROOT", "HARNESS_PYTEST_ARGS")
    if any(not os.environ.get(name) for name in required):
        return 2
    root = os.environ["HARNESS_CONTAINER_ROOT"]
    args = json.loads(os.environ["HARNESS_PYTEST_ARGS"])
    if not isinstance(args, list) or any(type(arg) is not str for arg in args):
        return 2
    os.chdir(root)
    if _forbidden(args):
        global _state
        _state = {"collected": set(), "passed": set(), "failed": set(), "skipped": set(),
                  "assertion_failures": set(), "errors": 1}
        json.dump(_document(1, root), sys.stdout)
        return 1
    stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        exit_code = pytest.main(args, plugins=[sys.modules[__name__]])
    finally:
        sys.stdout = stdout
    json.dump(_document(exit_code, root), sys.stdout)
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
