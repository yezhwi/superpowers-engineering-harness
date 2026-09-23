"""Explicit Harness schema resources, separate from project control inputs."""

import hashlib
import json
from importlib import resources
from pathlib import Path

SCHEMA_NAMES = (
    "adversarial-finding.schema.json",
    "alignment.schema.json",
    "alignment-finding.schema.json",
    "alignment-freeze.schema.json",
    "complexity-finding.schema.json",
    "context.schema.json",
    "decision.schema.json",
    "diagnosability-finding.schema.json",
    "diagnosability-proposal.schema.json",
    "diagnosability-review-evidence.schema.json",
    "diagnosability-review.schema.json",
    "evidence.schema.json",
    "gate.schema.json",
    "interface-contract.schema.json",
    "interface-finding.schema.json",
    "invariant.schema.json",
    "minimal-implementation.schema.json",
    "observability.schema.json",
    "requirement.schema.json",
    "task.schema.json",
)


def _resource_bytes(name: str) -> bytes:
    from harness import source_access
    from harness.context.model import ContextBuildError

    if name not in SCHEMA_NAMES:
        source_access.reject_resource()
    root = resources.files("harness").joinpath("schemas")
    resource = root.joinpath(name)
    if isinstance(resource, Path):
        if not resource.resolve().is_relative_to(root.resolve()):
            source_access.reject_resource()
        with source_access._package_open(resource):
            return resource.read_bytes()
    # Traversable supports packaged archives; no whole-directory I/O exemption.
    try:
        return resource.read_bytes()
    except OSError as exc:
        raise ContextBuildError(
            "CONTEXT_SCHEMA_INVALID", "schema resource unavailable"
        ) from exc


def read_schema(name: str) -> dict:
    from harness import source_access

    content = _resource_bytes(name)
    source_access.observe_resource(name, content)
    return json.loads(content)


def schema_versions() -> dict[str, str]:
    return {
        name: "sha256:" + hashlib.sha256(_resource_bytes(name)).hexdigest()
        for name in sorted(SCHEMA_NAMES)
    }
