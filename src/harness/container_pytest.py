"""Admit container pytest reports. The host does not run the project suite."""

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .execution_proof import runs

SCHEMA = "container-pytest/v1"
_FIELDS = frozenset({
    "schema", "run_id", "attempt", "command", "exit_code", "errors", "collected", "passed",
    "failed", "skipped", "assertion_failures", "target", "source_fingerprint",
})
_NODE_KEYS = ("collected", "passed", "failed", "skipped", "assertion_failures")


class ContainerRefusal(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _directory(value, *, absolute):
    if absolute:
        if not value.startswith("/") or value == "/":
            return False
        body = value[1:]
    elif value == "":
        return True
    elif value.startswith("/"):
        return False
    else:
        body = value
    if body.endswith(".py"):
        return False
    return all(part not in {"", ".", ".."} for part in body.split("/"))


def parse_maps(entries):
    """Directory prefixes only. A basename pair cannot select a node."""
    parsed = []
    for entry in entries:
        container, separator, repo = entry.partition("=")
        if separator != "=" or not _directory(container, absolute=True) or not _directory(repo, absolute=False):
            raise ContainerRefusal("CONTAINER_PATH_MAP_MISMATCH")
        parsed.append((container.rstrip("/"), repo.strip("/")))
    if not parsed:
        raise ContainerRefusal("CONTAINER_PATH_MAP_MISMATCH")
    return tuple(parsed)


def map_node(node, path_map):
    file, separator, suffix = node.partition("::")
    if not isinstance(node, str) or not file.startswith("/"):
        raise ContainerRefusal("CONTAINER_PATH_MAP_MISMATCH")
    matches = []
    for container, repo in path_map:
        if file == container or file.startswith(container + "/"):
            matches.append((len(container), repo, file[len(container):].lstrip("/")))
    if not matches:
        raise ContainerRefusal("CONTAINER_PATH_MAP_MISMATCH")
    longest = max(item[0] for item in matches)
    chosen = [item for item in matches if item[0] == longest]
    if len(chosen) != 1:
        raise ContainerRefusal("CONTAINER_PATH_MAP_MISMATCH")
    _, repo, rest = chosen[0]
    mapped = "/".join(part for part in (repo, rest) if part)
    if not mapped:
        raise ContainerRefusal("CONTAINER_PATH_MAP_MISMATCH")
    return mapped + (separator + suffix if separator else "")


def _pytest_args(payload):
    try:
        words = shlex.split(payload)
    except ValueError as exc:
        raise ContainerRefusal("CONTAINER_PYTEST_PAYLOAD_REQUIRED") from exc
    while words and "=" in words[0] and not words[0].startswith("-"):
        words = words[1:]
    if not words:
        raise ContainerRefusal("CONTAINER_PYTEST_PAYLOAD_REQUIRED")
    executable = Path(words[0]).name
    if executable in {"pytest", "py.test"}:
        return words[1:]
    if executable.startswith("python") and words[1:3] == ["-m", "pytest"]:
        return words[3:]
    raise ContainerRefusal("CONTAINER_PYTEST_PAYLOAD_REQUIRED")


def payload_command(command):
    from .collect_evidence import execution_environment

    environment = execution_environment(command)
    if environment is None or environment.get("transport") != "kubectl_exec":
        raise ContainerRefusal("CONTAINER_TRANSPORT_REQUIRED")
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise ContainerRefusal("CONTAINER_TRANSPORT_REQUIRED") from exc
    if "--" not in tokens:
        raise ContainerRefusal("CONTAINER_PYTEST_PAYLOAD_REQUIRED")
    payload = shlex.join(tokens[tokens.index("--") + 1:])
    _pytest_args(payload)
    target = {key: environment[key] for key in ("namespace", "workload", "container") if key in environment}
    if "workload" not in target:
        raise ContainerRefusal("CONTAINER_TARGET_MISMATCH")
    return payload, target, environment.get("cwd")


@dataclass(frozen=True)
class Attempt:
    run_id: str
    attempt: str
    command: str
    target: dict
    before_fingerprint: str
    after_fingerprint: str
    path_map: tuple
    retired_run_ids: frozenset = frozenset()
    accepted_attempts: frozenset = frozenset()


def admit(report, attempt):
    """Return pytest-execution/v1 proof, or refuse. Does not rewrite receipts."""
    if not isinstance(report, dict) or set(report) != _FIELDS or report.get("schema") != SCHEMA:
        raise ContainerRefusal("CONTAINER_REPORT_TRANSFER_FAILED")
    if report["run_id"] in attempt.retired_run_ids or report["attempt"] != attempt.attempt:
        raise ContainerRefusal("CONTAINER_REPORT_STALE")
    if report["run_id"] != attempt.run_id:
        raise ContainerRefusal("CONTAINER_RUN_ID_MISMATCH")
    if report["attempt"] in attempt.accepted_attempts:
        raise ContainerRefusal("CONTAINER_REPORT_DUPLICATE")
    if report["command"] != attempt.command:
        raise ContainerRefusal("CONTAINER_COMMAND_MISMATCH")
    if (attempt.before_fingerprint != attempt.after_fingerprint
            or report["source_fingerprint"] != attempt.before_fingerprint):
        raise ContainerRefusal("CONTAINER_SOURCE_DRIFT")
    if report["target"] != attempt.target:
        raise ContainerRefusal("CONTAINER_TARGET_MISMATCH")
    if type(report["errors"]) is not int or type(report["exit_code"]) is not int:
        raise ContainerRefusal("CONTAINER_REPORT_TRANSFER_FAILED")
    observed = {"errors": report["errors"], "exit_code": report["exit_code"]}
    for key in _NODE_KEYS:
        if not isinstance(report[key], list):
            raise ContainerRefusal("CONTAINER_REPORT_TRANSFER_FAILED")
        observed[key] = sorted({map_node(node, attempt.path_map) for node in report[key]})
    proof = {"schema": "pytest-execution/v1", "runs": [observed]}
    if runs({"test_execution": proof}) is None:
        raise ContainerRefusal("CONTAINER_REPORT_TRANSFER_FAILED")
    return proof


def classify(run):
    if run["errors"]:
        return "collect_error"
    if not run["collected"]:
        return "empty"
    if run["assertion_failures"]:
        return "red"
    if run["skipped"] and not run["passed"] and not run["failed"]:
        return "skipped"
    if run["passed"] and not run["failed"] and run["exit_code"] == 0:
        return "passed"
    return "failed"


def kubectl_argv(command, attempt, path_map):
    payload, target, cwd = payload_command(command)
    tokens = shlex.split(command)
    prefix = tokens[:tokens.index("--")]
    root = cwd or path_map[0][0]
    environment = {
        "HARNESS_RUN_ID": attempt.run_id,
        "HARNESS_ATTEMPT": attempt.attempt,
        "HARNESS_COMMAND": payload,
        "HARNESS_TARGET": json.dumps(target, sort_keys=True, separators=(",", ":")),
        "HARNESS_SOURCE_FINGERPRINT": attempt.before_fingerprint,
        "HARNESS_CONTAINER_ROOT": root,
        "HARNESS_PYTEST_ARGS": json.dumps(_pytest_args(payload), separators=(",", ":")),
    }
    return [*prefix, "--", "env", *[f"{key}={value}" for key, value in environment.items()], "python", "-"]


def interpret(stdout, returncode, attempt, *, timed_out=False):
    if timed_out:
        return None, "CONTAINER_REPORT_TIMEOUT", 124
    if not stdout:
        return None, "CONTAINER_PROCESS_EXIT" if returncode else "CONTAINER_REPORT_MISSING", returncode or 1
    try:
        report = json.loads(stdout)
    except json.JSONDecodeError:
        return None, "CONTAINER_REPORT_TRANSFER_FAILED", returncode or 1
    if not isinstance(report, dict) or report.get("exit_code") != returncode:
        return None, "CONTAINER_PROCESS_EXIT", returncode or 1
    try:
        return admit(report, attempt), None, report["exit_code"]
    except ContainerRefusal as exc:
        return None, exc.code, returncode or 1


def run_report(command, attempt, path_map, spawn):
    """spawn(argv, stdin) -> (returncode, stdout, stderr) or raises subprocess.TimeoutExpired."""
    argv = kubectl_argv(command, attempt, path_map)
    if Path(argv[0]).name not in {"kubectl", "kubectl.exe"}:
        raise ContainerRefusal("CONTAINER_TRANSPORT_REQUIRED")
    reporter = Path(__file__).with_name("container_reporter.py").read_bytes()
    try:
        returncode, stdout, stderr = spawn(argv, reporter)
    except subprocess.TimeoutExpired:
        return None, "CONTAINER_REPORT_TIMEOUT", 124, "", ""
    proof, error, exit_code = interpret(stdout, returncode, attempt)
    return proof, error, exit_code, stdout, stderr
