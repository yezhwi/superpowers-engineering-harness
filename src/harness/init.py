"""Harness initialization core (guide sections 8-13).

Non-destructive by construction: existing files are skipped, never
overwritten; directories created only when missing.
"""

from dataclasses import dataclass, field
from pathlib import Path

from harness import templates as templates_mod
from harness.templates import TemplateNotFoundError

REQUIRED_FILES = (
    "current-task.yaml",
    "requirements.yaml",
    "invariants.yaml",
    "gate.yaml",
    "impact.yaml",
    "observability.yaml",
)

REQUIRED_DIRS = (
    "findings",
    "evidence",
)


@dataclass
class InitResult:
    repo_root: Path
    harness_dir: Path
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


def _ensure_dir(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True)


def init_harness(repo_root: Path, templates: Path | None = None) -> InitResult:
    """Initialize .harness/ under repo_root. Idempotent and non-destructive.

    created/skipped record FILES only; missing directories are silently
    ensured. Raises TemplateNotFoundError if any required template is
    missing.
    """
    repo_root = Path(repo_root)
    templates = (
        Path(templates) if templates else templates_mod.templates_dir()
    )

    missing = [name for name in REQUIRED_FILES
               if not (templates / name).is_file()]
    if missing:
        raise TemplateNotFoundError(
            f"missing required templates in {templates}: {missing}"
        )

    harness_dir = repo_root / ".harness"
    result = InitResult(repo_root=repo_root, harness_dir=harness_dir)

    _ensure_dir(harness_dir)
    for dirname in REQUIRED_DIRS:
        _ensure_dir(harness_dir / dirname)

    for name in REQUIRED_FILES:
        target = harness_dir / name
        if target.exists():
            result.skipped.append(target)
            continue
        target.write_text(
            (templates / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        result.created.append(target)

    return result


def init_current_repository(cwd: Path | None = None) -> InitResult:
    """Resolve the git repository root from `cwd` (default: Path.cwd())
    and initialize .harness/ there (guide section 21)."""
    from harness.repository import find_git_root

    start = Path(cwd) if cwd else Path.cwd()
    return init_harness(find_git_root(start))
