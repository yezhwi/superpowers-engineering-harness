"""Template locator (guide section 22): locate templates relative to this
repository, never a hard-coded absolute path."""

from pathlib import Path

TEMPLATES_DIRNAME = "templates"


def templates_dir() -> Path:
    """Return the repository's templates directory.

    Resolved from this file's location: src/harness/templates.py ->
    <repo>/templates. Raises TemplateNotFoundError when missing.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / TEMPLATES_DIRNAME
        if candidate.is_dir():
            return candidate
    raise TemplateNotFoundError(
        f"could not locate '{TEMPLATES_DIRNAME}/' above {here}"
    )


class TemplateNotFoundError(Exception):
    """Raised when the templates directory or a required template is missing."""
