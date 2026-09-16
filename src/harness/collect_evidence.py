#!/usr/bin/env python3
"""Harness evidence collection and persistence.

Usage:
  python scripts/collect_evidence.py --type unit_test --command "pytest"

Writes <harness-dir>/evidence/<type-with-dashes>.json containing:
  type, timestamp, command, exit_code, commit (git HEAD),
  stdout_tail, stderr_tail.

Evidence is saved even when the command fails.
Exit codes: 0 = evidence written; 2 = invalid harness state / usage.
"""

import argparse
import datetime
import json
import os
import platform
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from .paths import EvidenceReferenceError, evidence_output_path
from .budget import (
    BudgetOverrideRequired,
    budget_action,
    check_budget,
    is_retry,
    record_budget,
    record_failure,
)
from .evidence_validator import ReuseRequest, can_reuse_evidence
from .telemetry import update_telemetry
from .workspace import git_head as workspace_head, snapshot

TEST_EVIDENCE_TYPES = {"unit_test", "integration_test", "contract_test"}

VALID_TYPES = {
    "build",
    "lint",
    "typecheck",
    "unit_test",
    "integration_test",
    "contract_test",
    "security",
    "review",
    "custom",
}

TAIL_CHARS = 4000
COMMAND_TIMEOUT_SECONDS = 1800
FINDING_ID_PATTERN = re.compile(r"^(?:FND|CPLX|DIAG)-[0-9]+$")
_SHELL_SEP = frozenset({"&&", ";", "|", "||"})
_TEST_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".jsx")


@dataclass(frozen=True)
class _TrustedLocalCommand:
    """Shell text entered directly by local Harness operator."""

    value: str


def git_head() -> str:
    """Compatibility wrapper for shared workspace HEAD lookup."""
    try:
        return workspace_head()
    except RuntimeError as exc:
        raise RuntimeError(f"not a git repository or git failed: {exc}") from exc


def runtime_metadata() -> dict[str, str]:
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "executable": sys.executable,
        "platform": f"{platform.system()}-{platform.machine()}",
    }



def workspace_fingerprint(repo_root: Path | None = None) -> str:
    """Compatibility wrapper for shared workspace snapshot fingerprint."""
    return snapshot(repo_root).fingerprint


def evidence_filename(
    evidence_type: str, *, finding_id: str | None = None, phase: str | None = None
) -> str:
    """Return deterministic generic or finding evidence filename."""
    stem = evidence_type.replace("_", "-")
    if finding_id is None:
        if phase is None:
            return f"{stem}.json"
        if phase not in {"red", "green"}:
            raise ValueError("task phase must be red or green")
        return f"fast-{phase}-{stem}.json"
    if phase not in {"red", "green", "full"}:
        raise ValueError("finding evidence requires phase red, green, or full")
    if not FINDING_ID_PATTERN.fullmatch(finding_id):
        raise ValueError("FINDING_ID_INVALID")
    return f"{finding_id}-{phase}-{stem}.json"


def test_selectors(command: str) -> tuple[str, ...] | None:
    """Return explicit pytest or Vitest selectors, including ``sh -lc`` payloads."""
    pending = [command]
    selectors: list[str] = []
    found_runner = False
    while pending:
        try:
            tokens = shlex.split(pending.pop())
        except ValueError:
            continue
        for index, token in enumerate(tokens):
            if (
                Path(token).name in {"sh", "bash"}
                and tokens[index + 1:index + 2] == ["-lc"]
                and index + 2 < len(tokens)
            ):
                pending.append(tokens[index + 2])
            if Path(token).name.startswith("pytest"):
                found_runner = True
                start = index + 1
            elif (
                Path(token).name.startswith("python")
                and tokens[index + 1:index + 3] == ["-m", "pytest"]
            ) or (token == "npx" and tokens[index + 1:index + 3] == ["vitest", "run"]):
                found_runner = True
                start = index + 3
            else:
                continue
            selectors.extend(
                value
                for value in tokens[start:tokens.index("&&", start) if "&&" in tokens[start:] else len(tokens)]
                if not value.startswith("-")
                and (".py" in value or value.endswith((".js", ".ts", ".tsx", ".jsx")))
            )
    return tuple(dict.fromkeys(selectors)) if found_runner else None


def pytest_selectors(command: str) -> tuple[str, ...] | None:
    """Compatibility alias for callers that only need explicit test selectors."""
    return test_selectors(command)


def _split_test_id(value: str) -> tuple[str, str | None]:
    path, separator, node = value.partition("::")
    return path, (node if separator else None)


def _join_test_id(path: str, node: str | None) -> str:
    return f"{path}::{node}" if node else path


def _has_glob(path: str) -> bool:
    return any(character in path for character in "*?[")


def _repo_root(repo_root: Path | None) -> Path:
    return (repo_root or Path.cwd()).resolve()


def _relative_to_repo(path: Path, repo_root: Path) -> str | None:
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return None
    if ".." in relative.parts:
        return None
    return relative.as_posix()


def canonicalize_path(path: str, cwd: Path, repo_root: Path) -> str | None:
    """Return a repo-root-relative path, or None when the path escapes the repo."""
    repo_root = repo_root.resolve()
    raw = Path(path)
    joined = raw if raw.is_absolute() else cwd / path
    normalized = Path(os.path.normpath(str(joined)))
    if _has_glob(path):
        return _relative_to_repo(normalized, repo_root)
    try:
        return _relative_to_repo(normalized.resolve(strict=False), repo_root)
    except OSError:
        return None


def _cwd_is_local_repo_path(cwd: Path, repo_root: Path) -> bool:
    repo_root = repo_root.resolve()
    joined = cwd if cwd.is_absolute() else repo_root / cwd
    return _relative_to_repo(Path(os.path.normpath(str(joined))), repo_root) is not None


def _local_cwd_missing(cwd: Path, repo_root: Path) -> bool:
    if not _cwd_is_local_repo_path(cwd, repo_root):
        return False
    joined = cwd if cwd.is_absolute() else repo_root / cwd
    return not Path(os.path.normpath(str(joined))).is_dir()


def _concrete_path_missing(path: str, repo_root: Path) -> bool:
    target = repo_root / path
    if _has_glob(path):
        return not target.parent.is_dir()
    return not target.is_file()


def _selector_start(tokens: list[str], index: int) -> int | None:
    token = tokens[index]
    if Path(token).name.startswith("pytest"):
        return index + 1
    if Path(token).name.startswith("python") and tokens[index + 1 : index + 3] == [
        "-m",
        "pytest",
    ]:
        return index + 3
    if token == "npx" and tokens[index + 1 : index + 3] == ["vitest", "run"]:
        return index + 3
    if Path(token).name == "vitest" and tokens[index + 1 : index + 2] == ["run"]:
        return index + 2
    return None


def _npm_unresolved(script: str, package_json: str) -> str:
    return f"TEST_RUNNER_UNRESOLVED: script {script!r} package.json {package_json!r}"


def _package_json_ref(cwd: Path, repo_root: Path) -> str:
    package = cwd / "package.json"
    relative = _relative_to_repo(Path(os.path.normpath(str(package))), repo_root.resolve())
    return relative if relative else "package.json"


def _load_npm_script(cwd: Path, name: str) -> str | None:
    package = cwd / "package.json"
    if not package.is_file():
        return None
    try:
        document = json.loads(package.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    scripts = document.get("scripts")
    if not isinstance(scripts, dict):
        return None
    value = scripts.get(name)
    return value if isinstance(value, str) and value.strip() else None


def _npm_run_span(tokens: list[str], index: int) -> tuple[str, int, int] | None:
    if Path(tokens[index]).name not in {"npm", "npm.cmd"}:
        return None
    if tokens[index + 1 : index + 2] != ["run"]:
        return None
    if (
        index + 2 >= len(tokens)
        or tokens[index + 2] in _SHELL_SEP
        or tokens[index + 2].startswith("-")
    ):
        return None
    name = tokens[index + 2]
    cursor = index + 3
    if cursor < len(tokens) and tokens[cursor] == "--":
        cursor += 1
    extra_start = cursor
    while cursor < len(tokens) and tokens[cursor] not in _SHELL_SEP:
        cursor += 1
    return name, extra_start, cursor


def _script_has_allowed_runner(script: str) -> bool:
    try:
        tokens = shlex.split(script)
    except ValueError:
        return False
    return any(_selector_start(tokens, index) is not None for index in range(len(tokens)))


def _is_selector_token(value: str) -> bool:
    return not value.startswith("-") and (
        ".py" in value or value.endswith(_TEST_SUFFIXES)
    )


def _selectors_from(tokens: list[str], start: int) -> tuple[str, ...]:
    end = len(tokens)
    for index, token in enumerate(tokens[start:], start):
        if token in _SHELL_SEP:
            end = index
            break
    return tuple(
        value for value in tokens[start:end] if _is_selector_token(value)
    )


def iter_test_invocations(
    command: str,
    cwd: Path,
    repo_root: Path | None = None,
    unresolved: list[str] | None = None,
):
    """Yield `(cwd, selectors)` for each pytest/Vitest invocation in `command`."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return
    yield from _iter_test_tokens(
        tokens, cwd, _repo_root(repo_root if repo_root is not None else cwd), unresolved
    )


def _iter_test_tokens(
    tokens: list[str],
    current: Path,
    repo_root: Path,
    unresolved: list[str] | None,
):
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _SHELL_SEP:
            index += 1
            continue
        if (
            Path(token).name in {"sh", "bash"}
            and tokens[index + 1 : index + 2] == ["-lc"]
            and index + 2 < len(tokens)
        ):
            try:
                nested = shlex.split(tokens[index + 2])
            except ValueError:
                nested = []
            yield from _iter_test_tokens(nested, current, repo_root, unresolved)
            index += 3
            continue
        if token == "cd" and index + 1 < len(tokens) and tokens[index + 1] not in _SHELL_SEP:
            destination = tokens[index + 1]
            current = (
                Path(destination)
                if Path(destination).is_absolute()
                else current / destination
            )
            current = Path(os.path.normpath(str(current)))
            index += 2
            continue
        if Path(token).name in {"npm", "npm.cmd"} and tokens[index + 1 : index + 2] == [
            "run"
        ]:
            parsed = _npm_run_span(tokens, index)
            package_ref = _package_json_ref(current, repo_root)
            if parsed is None:
                if unresolved is not None:
                    unresolved.append(_npm_unresolved("run", package_ref))
                index += 1
                continue
            name, extra_start, consumed = parsed
            script = _load_npm_script(current, name)
            if script is None or not _script_has_allowed_runner(script):
                if unresolved is not None:
                    unresolved.append(_npm_unresolved(name, package_ref))
                index = consumed
                continue
            try:
                script_tokens = shlex.split(script)
            except ValueError:
                if unresolved is not None:
                    unresolved.append(_npm_unresolved(name, package_ref))
                index = consumed
                continue
            yield from _iter_test_tokens(
                script_tokens + tokens[extra_start:consumed],
                current,
                repo_root,
                unresolved,
            )
            index = consumed
            continue
        start = _selector_start(tokens, index)
        if start is not None:
            yield current, _selectors_from(tokens, start)
            index = start
            while index < len(tokens) and tokens[index] not in _SHELL_SEP:
                index += 1
            continue
        index += 1


def _path_candidates(path: str, cwd: Path, repo_root: Path) -> tuple[str, ...]:
    found: list[str] = []
    for base in (cwd, repo_root):
        canonical = canonicalize_path(path, base, repo_root)
        if canonical and canonical not in found:
            found.append(canonical)
    return tuple(found)


def _suffix_paths_match(left: str, right: str) -> bool:
    return left == right or left.endswith(f"/{right}") or right.endswith(f"/{left}")


def claimed_matches_selector(
    claimed: str, selector: str, cwd: Path, repo_root: Path
) -> bool:
    """Return True when `claimed` is the same test as executed `selector`."""
    claimed_path, claimed_node = _split_test_id(claimed)
    selector_path, selector_node = _split_test_id(selector)
    claimed_ids = [
        _join_test_id(path, claimed_node)
        for path in _path_candidates(claimed_path, cwd, repo_root)
    ] or [claimed]
    selector_ids = [
        _join_test_id(path, selector_node)
        for path in _path_candidates(selector_path, cwd, repo_root)
    ] or [selector]
    for claimed_id in (*claimed_ids, claimed):
        for selector_id in (*selector_ids, selector):
            if claimed_id == selector_id or claimed_id.startswith(f"{selector_id}::"):
                return True
    if not _suffix_paths_match(claimed_path, selector_path):
        return False
    longer = claimed_path if len(claimed_path) >= len(selector_path) else selector_path
    return _join_test_id(longer, claimed_node) == _join_test_id(
        longer, selector_node
    ) or _join_test_id(longer, claimed_node).startswith(
        f"{_join_test_id(longer, selector_node)}::"
    )


def _local_cwd_relative(cwd: Path, repo_root: Path) -> str | None:
    if not _cwd_is_local_repo_path(cwd, repo_root):
        return None
    joined = cwd if cwd.is_absolute() else repo_root / cwd
    return _relative_to_repo(Path(os.path.normpath(str(joined))), repo_root)


def canonicalize_test_id(
    value: str, command: str, repo_root: Path | None = None
) -> str:
    """Resolve a test id against command cwd into a repo-root-relative path."""
    repo_root = _repo_root(repo_root)
    path, node = _split_test_id(value)
    invocations = list(iter_test_invocations(command, repo_root))
    cwd = invocations[-1][0] if invocations else repo_root
    bases: list[Path] = []
    cwd_rel = _local_cwd_relative(cwd, repo_root)
    already_repo_path = cwd_rel in {None, ".", ""} or path == cwd_rel or path.startswith(
        f"{cwd_rel}/"
    )
    if cwd_rel not in {None, ".", ""} and not already_repo_path:
        bases.append(cwd)
    bases.append(repo_root)
    seen: list[Path] = []
    for base in bases:
        resolved = base.resolve() if base.exists() else Path(os.path.normpath(str(base)))
        if resolved in seen:
            continue
        seen.append(resolved)
        canonical = canonicalize_path(path, base, repo_root)
        if canonical:
            return _join_test_id(canonical, node)
    return value


def bind_covered_tests(
    covered_tests: tuple[str, ...],
    command: str,
    repo_root: Path | None = None,
) -> tuple[str, ...] | str:
    """Canonicalize covered tests or return a fail-closed error code."""
    repo_root = _repo_root(repo_root)
    unresolved: list[str] = []
    invocations = list(
        iter_test_invocations(
            command, repo_root, repo_root=repo_root, unresolved=unresolved
        )
    )
    if unresolved:
        return unresolved[0]
    for cwd, _selectors in invocations:
        if _local_cwd_missing(cwd, repo_root):
            return "COVERED_TEST_PATH_INVALID"
    canonical: list[str] = []
    for item in covered_tests:
        path, _node = _split_test_id(item)
        if Path(path).is_absolute() and canonicalize_path(path, repo_root, repo_root) is None:
            return "COVERED_TEST_PATH_INVALID"
        canonical.append(canonicalize_test_id(item, command, repo_root))
    if any(selectors for _cwd, selectors in invocations):
        for item in canonical:
            executed = any(
                claimed_matches_selector(item, selector, cwd, repo_root)
                for cwd, selectors in invocations
                for selector in selectors
            )
            if not executed:
                return "COVERED_TEST_NOT_EXECUTED"
        for item in canonical:
            path, _node = _split_test_id(item)
            cwd = invocations[-1][0]
            if _cwd_is_local_repo_path(cwd, repo_root) and _concrete_path_missing(
                path, repo_root
            ):
                return "COVERED_TEST_PATH_INVALID"
    return tuple(canonical)


def record_covers_test(
    record: dict, node_id: str, repo_root: Path | None = None
) -> bool:
    """Return True when evidence covered_tests bind to `node_id`."""
    repo_root = _repo_root(repo_root)
    command = record.get("command") or ""
    invocations = list(iter_test_invocations(command, repo_root))
    cwd = invocations[-1][0] if invocations else repo_root
    return any(
        claimed_matches_selector(node_id, covered, cwd, repo_root)
        for covered in record.get("covered_tests", [])
    )


def command_covers_test(
    command: str, node_id: str, repo_root: Path | None = None
) -> bool:
    """Return True when `command` executed a selector covering `node_id`."""
    repo_root = _repo_root(repo_root)
    invocations = list(iter_test_invocations(command, repo_root))
    if invocations:
        return any(
            claimed_matches_selector(node_id, selector, cwd, repo_root)
            for cwd, selectors in invocations
            for selector in selectors
        )
    selectors = test_selectors(command)
    if not selectors:
        return False
    return any(
        node_id == selector
        or node_id.startswith(f"{selector}::")
        or node_id.endswith(f"/{selector}")
        for selector in selectors
    )


def _text_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _tail(text: str | bytes | None) -> str:
    return _text_output(text)[-TAIL_CHARS:]


def _collect(
    evidence_type: str,
    command: _TrustedLocalCommand,
    finding_id: str | None = None,
    test_id: str | None = None,
    scope: str = "related",
    covered_tests: tuple[str, ...] = (),
    covered_test_cases: tuple[str, ...] = (),
    phase: str | None = None,
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
) -> dict:
    if not isinstance(command, _TrustedLocalCommand):
        raise ValueError("TRUSTED_LOCAL_COMMAND_REQUIRED")
    command_text = command.value
    before = workspace_fingerprint()
    error = None
    try:
        run = subprocess.run(
            command_text,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        exit_code, stdout, stderr = run.returncode, run.stdout, run.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = exc.stdout
        stderr = exc.stderr
        error = "EVIDENCE_COMMAND_TIMEOUT"
    after = workspace_fingerprint()
    evidence = {
        "type": evidence_type,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "command": command_text,
        "exit_code": exit_code,
        "commit": git_head(),
        "workspace_fingerprint": before,
        "workspace_fingerprint_after": after,
        "runtime": runtime_metadata(),
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }
    if error is not None:
        evidence["error"] = error
        evidence["error_detail"] = {
            "code": error,
            "kind": "timeout",
            "timeout_seconds": timeout_seconds,
        }
    if finding_id is not None:
        evidence["scope"] = scope
    if covered_tests:
        evidence["covered_tests"] = list(covered_tests)
    if covered_test_cases:
        evidence["covered_test_cases"] = list(covered_test_cases)
    if finding_id is not None:
        evidence["subject"] = {"kind": "finding", "id": finding_id}
        evidence["test"] = {"node_id": test_id}
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect harness evidence")
    parser.add_argument("--type", required=True, choices=sorted(VALID_TYPES))
    parser.add_argument("--command", required=True)
    parser.add_argument("--harness-dir", default=".harness")
    parser.add_argument("--finding")
    parser.add_argument("--test")
    parser.add_argument("--scope", choices=["related", "full_suite"], default="related")
    parser.add_argument("--covered-test", action="append", default=[])
    parser.add_argument("--covered-test-case", action="append", default=[])
    parser.add_argument("--phase", choices=["red", "green", "full"])
    parser.add_argument("--reuse-if-valid", action="store_true")
    parser.add_argument("--budget-override-reason")
    parser.add_argument("--budget-override-evidence")
    parser.add_argument("--budget-override-hypothesis")
    args = parser.parse_args(argv)

    try:
        head = git_head()
    except RuntimeError as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 2

    if bool(args.finding) != bool(args.test):
        print("INVALID_USAGE: --finding and --test must be paired", file=sys.stderr)
        return 2
    if args.finding and not FINDING_ID_PATTERN.fullmatch(args.finding):
        print("FINDING_ID_INVALID", file=sys.stderr)
        return 2
    if args.finding and not args.phase:
        print("INVALID_USAGE: --finding requires --phase", file=sys.stderr)
        return 2
    if not args.finding and args.phase == "full":
        print("INVALID_USAGE: task phase must be red or green", file=sys.stderr)
        return 2
    if args.covered_test and args.type not in TEST_EVIDENCE_TYPES:
        print("COVERED_TEST_TYPE_INVALID", file=sys.stderr)
        return 2
    if args.type == "unit_test" and args.scope == "related" and not args.covered_test:
        print("RELATED_COVERED_TEST_REQUIRED", file=sys.stderr)
        return 2
    covered_tests = tuple(args.covered_test)
    bound = bind_covered_tests(covered_tests, args.command)
    if isinstance(bound, str):
        print(bound, file=sys.stderr)
        return 2
    covered_tests = bound
    out_dir = Path(args.harness_dir) / "evidence"
    try:
        out_file = evidence_output_path(
            Path(args.harness_dir),
            evidence_filename(args.type, finding_id=args.finding, phase=args.phase),
        )
    except (ValueError, EvidenceReferenceError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.reuse_if_valid and not args.finding and args.phase is None:
        request = ReuseRequest(
            args.type,
            args.command,
            args.scope,
            covered_tests,
            args.phase,
            args.finding,
            args.test,
            tuple(args.covered_test_case),
        )
        try:
            candidate = json.loads(out_file.read_text())
            if can_reuse_evidence(
                candidate,
                request,
                current_head=head,
                current_workspace=workspace_fingerprint(),
                current_runtime=runtime_metadata(),
            ):
                print(f"EVIDENCE_REUSED: {out_file.name}")
                return 0
        except (OSError, json.JSONDecodeError):
            pass

    override_values = (
        args.budget_override_reason,
        args.budget_override_evidence,
        args.budget_override_hypothesis,
    )
    if any(override_values) and not all(override_values):
        print("BUDGET_OVERRIDE_REQUIRED", file=sys.stderr)
        return 2
    task_path = Path(args.harness_dir) / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text()) if task_path.exists() else None
    action = budget_action(args.type, 0, args.command)
    override = (
        {
            "reason": args.budget_override_reason,
            "evidence": args.budget_override_evidence,
            "hypothesis": args.budget_override_hypothesis,
        }
        if all(override_values)
        else None
    )
    try:
        if task and action:
            check_budget(task, action, override)
            if is_retry(task, args.command):
                check_budget(task, "retry", override)
    except BudgetOverrideRequired as exc:
        print(str(exc), file=sys.stderr)
        return 2

    evidence = _collect(
        args.type,
        _TrustedLocalCommand(args.command),
        args.finding,
        args.test,
        args.scope,
        covered_tests,
        tuple(args.covered_test_case),
        args.phase,
    )
    evidence["commit"] = head

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(evidence, indent=2))
    if task and action:
        record_budget(task, action, override)
        if is_retry(task, args.command):
            record_budget(task, "retry", override)
        if evidence["exit_code"]:
            record_failure(task, args.command)
        task_path.write_text(yaml.safe_dump(task, sort_keys=False))
        update_telemetry(Path(args.harness_dir), task)

    print(
        f"evidence written: {out_file} "
        f"(exit_code={evidence['exit_code']}, commit={head[:12]})"
    )
    # Evidence collection itself succeeds even when the command fails;
    # the gate decides based on exit_code in the evidence.
    return 0


if __name__ == "__main__":
    sys.exit(main())
