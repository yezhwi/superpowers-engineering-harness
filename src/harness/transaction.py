"""Stage and publish Harness artifacts without partial canonical state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class StagedArtifact:
    relative_path: str
    content: bytes
    replace: bool = False


def stage(harness_dir: Path, artifacts: list[StagedArtifact], *, operation_id: str | None = None) -> Path:
    """Write complete artifact set outside canonical Harness paths."""
    stage_dir = harness_dir / ".staging" / (operation_id or uuid4().hex)
    for artifact in artifacts:
        target = stage_dir / artifact.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    return stage_dir


def publish(harness_dir: Path, stage_dir: Path, *, replace_paths: frozenset[str] = frozenset()) -> None:
    """Publish staged files or restore every touched canonical target."""
    sources = sorted(path for path in stage_dir.rglob("*") if path.is_file())
    targets = [(path, harness_dir / path.relative_to(stage_dir)) for path in sources]
    existing = {target: target.read_bytes() if target.exists() else None for _, target in targets}
    published: list[Path] = []
    succeeded = False
    try:
        for source, target in targets:
            if target.exists() and target.relative_to(harness_dir).as_posix() not in replace_paths:
                raise FileExistsError(f"canonical artifact exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            temp.write_bytes(source.read_bytes())
            temp.replace(target)
            published.append(target)
        succeeded = True
    except Exception:
        for target in reversed(published):
            previous = existing[target]
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(previous)
        raise
    finally:
        if succeeded:
            for path in sorted(stage_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            stage_dir.rmdir()


def cleanup_stale_staging(harness_dir: Path) -> None:
    root = harness_dir / ".staging"
    if not root.exists():
        return
    for stage_dir in root.iterdir():
        if stage_dir.is_dir():
            for path in sorted(stage_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            stage_dir.rmdir()
