"""Publish and read the latest complete, validated Context bundle."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from harness import decision, source_access, transaction
from harness.workspace import snapshot as product_snapshot
from harness.telemetry_lock import telemetry_lock
from harness.transaction_recovery import require_no_pending_publications

from .evidence import context_evidence
from .freshness import capture, digest, require_fresh
from .integrity import build_context, validate_context
from .model import ContextBuildError
from .telemetry import active

MEMBERS = ("current.yaml", "manifest.yaml", "evidence.yaml")


def _paths(harness_dir: Path) -> dict[str, Path]:
    directory = harness_dir / "context"
    paths = {name: directory / name for name in MEMBERS}
    for path in (directory, *paths.values()):
        if path.is_symlink():
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN",
                f"Context storage cannot be a symlink: {path.name}",
            )
    if directory.exists() and not directory.is_dir():
        raise ContextBuildError(
            "CONTEXT_SCHEMA_INVALID", "Context storage is not a directory"
        )
    return paths


def _require_task(harness_dir: Path) -> None:
    if not (harness_dir / "current-task.yaml").is_file():
        raise ContextBuildError("INVALID_HARNESS_STATE", "missing current-task.yaml")


def _read(path: Path) -> dict:
    try:
        document = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ContextBuildError(
            "INVALID_HARNESS_STATE",
            f"missing context/{path.name}; generate Context first",
        ) from exc
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ContextBuildError(
            "CONTEXT_SCHEMA_INVALID", f"cannot read context/{path.name}"
        ) from exc
    if not isinstance(document, dict):
        raise ContextBuildError(
            "CONTEXT_SCHEMA_INVALID", f"context/{path.name} is not a mapping"
        )
    return document


def _manifest(document: dict) -> dict:
    return {"context_hash": document["context_hash"], **document["manifest"]}


def _equal(actual: dict, expected: dict, member: str) -> None:
    if digest(actual) != digest(expected):
        raise ContextBuildError(
            "CONTEXT_INACCURATE",
            f"context/{member} does not match the validated snapshot",
        )


def generate_context(harness_dir: Path, *, mode: str = "compact") -> dict:
    """Validate before durable commit; journal owns any publication abort.

    Shared task-publication lock also serializes Context readers/writers and
    task replacement. Unmanaged product/control edits are detected by hashes.
    """
    harness_dir = harness_dir.absolute()
    with telemetry_lock(harness_dir), decision._read_session():
        transaction.recover_pending_publications(harness_dir)
        _require_task(harness_dir)
        paths = _paths(harness_dir)
        before = {
            f"context/{name}": source_access.read_regular_bytes_beneath(path, harness_dir)
            if source_access.exists(path) else None
            for name, path in paths.items()
        }
        staging_root = harness_dir / ".staging"
        if staging_root.is_symlink():
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN", "Context staging cannot be a symlink"
            )
        from .escalation import apply_automatic_expansions

        # One product-tree fingerprint for the build. The closing fingerprint
        # is taken once, immediately before publication.
        opened = product_snapshot(harness_dir.parent)
        sources = []
        document = build_context(
            harness_dir, mode=mode, _retain_source=sources.append, workspace=opened,
        )
        document = apply_automatic_expansions(
            harness_dir, document, source=sources[0], workspace=opened,
        )
        integrity = validate_context(harness_dir, document, workspace=opened)
        evidence = context_evidence(document, integrity, datetime.now(UTC).isoformat())
        bundle = {
            "current.yaml": document,
            "manifest.yaml": _manifest(document),
            "evidence.yaml": evidence,
        }
        payloads = {
            name: yaml.safe_dump(value, sort_keys=False, allow_unicode=True).encode()
            for name, value in bundle.items()
        }
        closing = product_snapshot(harness_dir.parent)

        def validate_published():
            _paths(harness_dir)
            for name, path in paths.items():
                _equal(_read(path), bundle[name], name)
            require_fresh(document["generated_from"], capture(harness_dir, workspace=closing))

        def finalize():
            validate_published()
            validate_published()

        artifacts = tuple(transaction.StagedArtifact(f"context/{name}", value)
                          for name, value in payloads.items())
        staged = transaction.stage(harness_dir, artifacts, operation_id=f"context-{uuid4().hex}")
        require_fresh(document["generated_from"], capture(harness_dir, workspace=closing))
        _paths(harness_dir)
        outcome = transaction.PublicationOutcome()
        try:
            transaction.publish(
                harness_dir,
                staged,
                replace_paths=frozenset(before),
                expected_sources=before,
                expected_artifacts=artifacts,
                after_publish=finalize,
                durable=True,
                outcome=outcome,
            )
        finally:
            timer = active()
            if timer is not None and outcome.committed:
                timer.context_published = True
        return document


def load_context(harness_dir: Path) -> tuple[dict, dict]:
    """Read-only validation; refuse pending publication, never recover or regenerate."""
    harness_dir = harness_dir.absolute()
    with telemetry_lock(harness_dir):
        require_no_pending_publications(harness_dir)
        _require_task(harness_dir)
        paths = _paths(harness_dir)
        document = _read(paths["current.yaml"])
        manifest = _read(paths["manifest.yaml"])
        evidence = _read(paths["evidence.yaml"])
        integrity = validate_context(harness_dir, document)
        _equal(manifest, _manifest(document), "manifest.yaml")
        expected = context_evidence(document, integrity, evidence.get("generated_at"))
        _equal(evidence, expected, "evidence.yaml")
        return document, integrity


def explain_context(document: dict) -> dict:
    """Explain a validated saved view without reading new, possibly changed inputs."""
    global_items = [
        {"id": record["id"], "kind": group, "reason": "mandatory_global_core"}
        for group in ("requirements", "invariants", "decisions", "findings")
        for record in document["control"][group]
    ]
    for field in ("owned_paths", "protected_user_paths"):
        global_items.extend(
            {"id": path, "kind": field, "reason": "lossless_scope"}
            for path in (document["control"]["scope"] or {}).get(field, [])
        )
    global_items.extend(
        {"id": blocker["code"], "kind": "blocker", "reason": "live_gate_blocker"}
        for blocker in document["control"]["blockers"]
    )
    targets = {finding.get("target") for finding in document["control"]["findings"]}
    included = []
    for group in ("requirements", "decisions", "findings"):
        for record in document["working"][group]:
            reason = (
                "full_projection"
                if document["mode"] == "full"
                else (
                    "open_finding_target"
                    if record["id"] in targets
                    else "owned_test_path"
                )
            )
            included.append({"id": record["id"], "kind": group, "reason": reason})
    for group in ("files", "tests"):
        included.extend(
            {
                "id": path,
                "kind": group,
                "reason": "full_projection"
                if document["mode"] == "full"
                else "declared_path_allowed_by_policy",
            }
            for path in document["working"][group]
        )
    return {
        "context_hash": document["context_hash"],
        "mode": document["mode"],
        "base_policy": document["base_policy"],
        "policy": document["policy"],
        "included": included,
        "omitted": document["omitted"],
        "global": global_items,
        "expansions": document["expansions"],
    }
