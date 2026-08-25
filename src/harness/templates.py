"""Template locator (guide section 22): locate templates relative to this
repository, never a hard-coded absolute path."""

from importlib import resources


def templates_dir():
    """Return templates bundled with installed ``harness`` package."""
    directory = resources.files("harness").joinpath("templates")
    if directory.is_dir():
        return directory
    raise TemplateNotFoundError("package templates/ directory is unavailable")


class TemplateNotFoundError(Exception):
    """Raised when the templates directory or a required template is missing."""
