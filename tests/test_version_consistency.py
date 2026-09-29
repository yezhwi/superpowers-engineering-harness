"""Release metadata must describe one publishable version."""

import json
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_current_release_metadata_is_publishable():
    expected = "0.2.10"
    assert (
        tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
        == expected
    )
    assert json.loads((REPO / "package.json").read_text())["version"] == expected
    assert (
        f"# Superpowers Engineering Harness v{expected}"
        in (REPO / "README.md").read_text()
    )
    changelog = (REPO / "CHANGELOG.md").read_text()
    assert f"## {expected}\n" in changelog
    assert f"## {expected} (unreleased)" not in changelog


def test_npm_and_python_package_metadata_describe_same_license_and_source():
    package = json.loads((REPO / "package.json").read_text())
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]

    assert package["license"] == project["license"] == "Apache-2.0"
    assert package["author"] == {"name": "Yezhiwei"}
    assert package["repository"] == {
        "type": "git",
        "url": "git+https://github.com/yezhwi/superpowers-engineering-harness.git",
    }
    assert package["homepage"] == (
        "https://github.com/yezhwi/superpowers-engineering-harness#readme"
    )
    assert package["bugs"] == {
        "url": "https://github.com/yezhwi/superpowers-engineering-harness/issues"
    }
    assert "Pi skills" in package["description"]
    assert "Harness CLI" in package["description"]
    assert (REPO / "LICENSE").read_text().startswith("Apache License\nVersion 2.0")


def test_v027_release_notes_document_diagnosability():
    changelog = (REPO / "CHANGELOG.md").read_text()
    release = changelog.split("## 0.2.4", 1)[0]
    for phrase in ("Observability Contract", "DIAG Finding", "Q2/Q3", "non-goals"):
        assert phrase in release


def test_v027_release_notes_include_installation_and_boundaries():
    changelog = (REPO / "CHANGELOG.md").read_text()
    release = changelog.split("## 0.2.5", 1)[0]
    assert "git:github.com/yezhwi/superpowers-engineering-harness@v0.2.7" in release
    assert "diagnosability" in release.lower()
    for phrase in (
        "logger SDK",
        "OpenTelemetry",
        "automatic log insertion",
        "universal source scanning",
    ):
        assert phrase in release


def test_python_npm_readme_and_changelog_versions_match():
    """Break caught: npm or documentation release version drifts from Python package."""
    python_version = tomllib.loads((REPO / "pyproject.toml").read_text())["project"][
        "version"
    ]
    npm_version = json.loads((REPO / "package.json").read_text())["version"]
    readme = (REPO / "README.md").read_text()
    changelog = (REPO / "CHANGELOG.md").read_text()

    assert npm_version == python_version
    assert f"v{python_version}" in readme
    assert re.search(rf"^## {re.escape(python_version)}$", changelog, re.MULTILINE)
