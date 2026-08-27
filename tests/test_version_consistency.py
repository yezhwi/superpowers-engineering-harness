"""Release metadata must describe one publishable version."""

import json
import re
from pathlib import Path

import tomllib


REPO = Path(__file__).resolve().parent.parent


def test_python_npm_readme_and_changelog_versions_match():
    """Break caught: npm or documentation release version drifts from Python package."""
    python_version = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
    npm_version = json.loads((REPO / "package.json").read_text())["version"]
    readme = (REPO / "README.md").read_text()
    changelog = (REPO / "CHANGELOG.md").read_text()

    assert npm_version == python_version
    assert f"v{python_version}" in readme
    assert re.search(rf"^## {re.escape(python_version)}$", changelog, re.MULTILINE)
