"""Release metadata must describe one publishable version."""

import json
import re
from pathlib import Path

import tomllib


REPO = Path(__file__).resolve().parent.parent


def test_v025_release_metadata_is_publishable():
    expected = "0.2.5"
    assert tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"] == expected
    assert json.loads((REPO / "package.json").read_text())["version"] == expected
    assert f"# Superpowers Engineering Harness v{expected}" in (REPO / "README.md").read_text()
    changelog = (REPO / "CHANGELOG.md").read_text()
    assert f"## {expected}\n" in changelog
    assert f"## {expected} (unreleased)" not in changelog


def test_v025_release_notes_document_diagnosability():
    changelog = (REPO / "CHANGELOG.md").read_text()
    release = changelog.split("## 0.2.4", 1)[0]
    for phrase in ("Observability Contract", "DIAG Finding", "Q2/Q3", "non-goals"):
        assert phrase in release


def test_v025_release_notes_include_installation_and_boundaries():
    changelog = (REPO / "CHANGELOG.md").read_text()
    release = changelog.split("## 0.2.4", 1)[0]
    assert "git:github.com/yezhwi/superpowers-engineering-harness@v0.2.5" in release
    assert "diagnosability" in release.lower()
    for phrase in ("logger SDK", "OpenTelemetry", "automatic log insertion", "universal source scanning"):
        assert phrase in release


def test_python_npm_readme_and_changelog_versions_match():
    """Break caught: npm or documentation release version drifts from Python package."""
    python_version = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
    npm_version = json.loads((REPO / "package.json").read_text())["version"]
    readme = (REPO / "README.md").read_text()
    changelog = (REPO / "CHANGELOG.md").read_text()

    assert npm_version == python_version
    assert f"v{python_version}" in readme
    assert re.search(rf"^## {re.escape(python_version)}$", changelog, re.MULTILINE)
