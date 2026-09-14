"""Publish and read the latest complete, validated Context bundle."""

import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from harness import transaction
from harness.telemetry_lock import telemetry_lock

from .evidence import context_evidence
from .freshness import capture, digest, require_fresh
from .integrity import build_context, validate_context
from .model import ContextBuildError

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


def _restore(paths: dict[str, Path], before: dict[str, bytes | None]) -> None:
    for name, path in paths.items():
        previous = before[name]
        if previous is None:
            path.unlink(missing_ok=True)
        elif not path.exists() or path.read_bytes() != previous:
            transaction.atomic_write(path, previous)


def generate_context(harness_dir: Path, *, mode: str = "compact") -> dict:
    """Validate before stdout; restore prior bytes on any publication failure.

    Shared task-publication lock also serializes Context readers/writers and
    task replacement. Unmanaged product/control edits are detected by hashes.
    """
    harness_dir = harness_dir.absolute()
    with telemetry_lock(harness_dir):
        _require_task(harness_dir)
        paths = _paths(harness_dir)
        staging_root = harness_dir / ".staging"
        if staging_root.is_symlink():
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN", "Context staging cannot be a symlink"
            )
        from .escalation import apply_automatic_expansions

        document = build_context(harness_dir, mode=mode)
        document = apply_automatic_expansions(harness_dir, document)
        integrity = validate_context(harness_dir, document)
        evidence = context_evidence(document, integrity, datetime.now(UTC).isoformat())
        bundle = {
            "current.yaml": document,
            "manifest.yaml": _manifest(document),
            "evidence.yaml": evidence,
        }
        before = {
            name: path.read_bytes() if path.exists() else None
            for name, path in paths.items()
        }
        operation = f"context-{uuid4().hex}"
        staged = staging_root / operation
        try:
            transaction.stage(
                harness_dir,
                [
                    transaction.StagedArtifact(
                        f"context/{name}",
                        yaml.safe_dump(
                            value, sort_keys=False, allow_unicode=True
                        ).encode(),
                    )
                    for name, value in bundle.items()
                ],
                operation_id=operation,
            )
            require_fresh(document["generated_from"], capture(harness_dir))
            _paths(harness_dir)
            transaction.publish(
                harness_dir,
                staged,
                replace_paths=frozenset(f"context/{name}" for name in MEMBERS),
            )
            for name, path in paths.items():
                _equal(_read(path), bundle[name], name)
            require_fresh(document["generated_from"], capture(harness_dir))
        except BaseException:
            _paths(harness_dir)  # do not follow a concurrently substituted symlink
            _restore(paths, before)
            raise
        finally:
            shutil.rmtree(staged, ignore_errors=True)
        return document


def load_context(harness_dir: Path) -> tuple[dict, dict]:
    """Read-only validation of current + its companions; never regenerate."""
    harness_dir = harness_dir.absolute()
    with telemetry_lock(harness_dir):
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
