"""Pure admission rules for actual pytest execution, never command inference."""

TEST_TYPES = frozenset({"unit_test", "integration_test", "contract_test"})
FIELDS = frozenset({"collected", "passed", "failed", "skipped", "assertion_failures", "errors", "exit_code"})


def requires_test_execution(record):
    """Classify declared test claims regardless of the receipt's nominal type."""
    return (record.get("type") in TEST_TYPES or record.get("subject") is not None
            or record.get("test") is not None or record.get("phase") in {"red", "green"}
            or bool(record.get("covered_tests")))


def _canonical_node(node):
    if not isinstance(node, str) or not node or node.endswith("::") or "\x00" in node:
        return False
    path = node.split("::", 1)[0]
    return ("\\" not in path and ":" not in path
            and all(part not in {"", ".", ".."} for part in path.split("/")))


def _nodes(value):
    return (isinstance(value, list) and all(_canonical_node(node) for node in value)
            and len(set(value)) == len(value))


def runs(record):
    if not isinstance(record, dict):
        return None
    proof = record.get("test_execution")
    if not isinstance(proof, dict) or set(proof) != {"schema", "runs"}:
        return None
    if proof["schema"] != "pytest-execution/v1" or not isinstance(proof["runs"], list) or not proof["runs"]:
        return None
    for run in proof["runs"]:
        if not isinstance(run, dict) or set(run) != FIELDS:
            return None
        if type(run["errors"]) is not int or run["errors"] < 0 or type(run["exit_code"]) is not int:
            return None
        if not all(_nodes(run[key]) for key in ("collected", "passed", "failed", "skipped", "assertion_failures")):
            return None
        known = set(run["collected"])
        outcomes = [set(run[key]) for key in ("passed", "failed", "skipped")]
        if not set(run["assertion_failures"]) <= set(run["failed"]):
            return None
        if any(not nodes <= known for nodes in outcomes):
            return None
        if any(outcomes[i] & outcomes[j] for i in range(3) for j in range(i + 1, 3)):
            return None
    return proof["runs"]


def _under(node, target):
    if node == target:
        return True
    _, separator, scope = target.partition("::")
    if not separator:
        return node.startswith(target + "::")
    if "[" in scope:
        return False  # An explicit parameterized node is exact, not a family prefix.
    return node.startswith((target + "::", target + "["))


def covers(record, target, success=True):
    observations = runs(record)
    if observations is None or not isinstance(target, str):
        return False
    collected = {node for run in observations for node in run["collected"] if _under(node, target)}
    actual = {node for run in observations for node in run["passed" if success else "assertion_failures"]}
    return bool(collected) and (collected <= actual if success else bool(collected & actual))


def valid(record, success):
    observations = runs(record)
    if (observations is None or type(record.get("exit_code")) is not int
            or any(run["errors"] for run in observations)
            or record.get("error") is not None or record.get("error_detail") is not None
            or record.get("test_execution_error") is not None):
        return False
    targets = record.get("covered_tests", [])
    subject = record.get("test")
    if not isinstance(targets, list) or any(not isinstance(target, str) or not target for target in targets):
        return False
    if subject is not None and (not isinstance(subject, dict) or not isinstance(subject.get("node_id"), str) or not subject["node_id"]):
        return False
    if success:
        if record.get("exit_code") != 0 or any(run["exit_code"] != 0 or run["failed"] for run in observations):
            return False
        if not any(run["passed"] for run in observations):
            return False
        node = subject["node_id"] if subject else None
        return all(covers(record, target) for target in [*targets, *([node] if node else [])])
    return (record.get("exit_code") == 1 and all(run["exit_code"] in {0, 1} for run in observations)
            and any(run["assertion_failures"] for run in observations)
            and all(covers(record, target, False) for target in targets)
            and (not subject or covers(record, subject["node_id"], False)))
