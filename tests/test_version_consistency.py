"""Release metadata must describe one publishable version."""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement

REPO = Path(__file__).resolve().parent.parent


def test_declared_backend_compatibility_matches_real_metadata_build(tmp_path):
    """Break caught: declaration admits a backend that rejects actual project metadata."""
    project = tmp_path / 'project'
    project.mkdir()
    for name in ('pyproject.toml', 'LICENSE'):
        shutil.copy2(REPO / name, project / name)
    shutil.copytree(REPO / 'src', project / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-info'))
    output = tmp_path / 'metadata'
    output.mkdir()
    script = '''
import importlib.metadata
print('HARNESS_BACKEND_VERSION=' + importlib.metadata.version('setuptools'), flush=True)
from setuptools.build_meta import prepare_metadata_for_build_wheel
print('HARNESS_DIST_INFO=' + prepare_metadata_for_build_wheel(__import__('sys').argv[1]), flush=True)
'''
    python = os.environ.get('HARNESS_PACKAGE_BACKEND_PYTHON', sys.executable)
    result = subprocess.run([python, '-I', '-c', script, str(output)], cwd=project,
                            capture_output=True, text=True, check=False, timeout=60)
    version = re.search(r'^HARNESS_BACKEND_VERSION=(\S+)$', result.stdout, re.MULTILINE)
    assert version, result.stdout + result.stderr  # Environment failures are not compatibility passes.
    configuration = tomllib.loads((project / 'pyproject.toml').read_text())
    requirement = next(Requirement(value) for value in configuration['build-system']['requires']
                       if Requirement(value).name == 'setuptools')
    admitted = requirement.specifier.contains(version.group(1), prereleases=True)
    assert result.returncode == 0 or not admitted, (
        f'Advertised backend setuptools=={version.group(1)} failed metadata generation:\n'
        + result.stdout + result.stderr
    )
    if result.returncode == 0:
        dist_info = re.search(r'^HARNESS_DIST_INFO=(\S+)$', result.stdout, re.MULTILINE)
        assert dist_info, result.stdout
        metadata = Parser().parsestr((output / dist_info.group(1) / 'METADATA').read_text())
        assert metadata['Name'] == 'superpowers-engineering-harness' and metadata['Version'] == '0.3.2'
        assert metadata['License-Expression'] == 'Apache-2.0'
    print(f'Backend setuptools=={version.group(1)} admitted={admitted} metadata_exit={result.returncode}')


def test_current_release_metadata_is_publishable():
    expected = "0.3.2"
    assert (
        tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
        == expected
    )
    assert json.loads((REPO / "package.json").read_text())["version"] == expected
    changelog = (REPO / "CHANGELOG.md").read_text()
    assert f"## {expected}\n" in changelog
    assert f"## {expected} (unreleased)" not in changelog


def test_v030_release_notes_cover_architecture_p0_p1_p2_without_claims():
    changelog = (REPO / "CHANGELOG.md").read_text()
    unreleased, remainder = changelog.split("## 0.3.0", 1)
    release = remainder.split("## 0.2.10", 1)[0]

    assert unreleased.split("## 0.3.2", 1)[0].strip() == "# Changelog\n\n## Unreleased"
    assert "## 0.3.2" in unreleased
    assert "## 0.3.1" in unreleased
    for phrase in (
        "Architecture Scope Gate P0",
        "four-layer Git attribution",
        "Alignment seal v2",
        "FAST/Q1 and mode off",
        "Architecture Context Projection P1",
        "Architecture Evaluation P2",
        "No measured benchmark improvement is claimed",
    ):
        assert phrase in release


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
    assert "docs/Superpowers-Engineering-Harness-v0.3.0-Architecture-Scope-and-Drift-Design.md" in package["files"]
    assert "docs/superpowers/reports/v030-architecture-benchmark-template.md" in package["files"]
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


def test_v032_release_notes_and_packaged_compatibility_docs():
    changelog = (REPO / "CHANGELOG.md").read_text()
    release = changelog.split("## 0.3.2\n", 1)[1].split("## 0.3.1", 1)[0]
    for phrase in (
        "exit 3", "prefix", "TEST_SCOPE_AUDIT_INVALID", "MIGRATE",
        "RETIRE", "REBIND", "cross-HEAD", "80", "N=100",
    ):
        assert phrase in release
    package = json.loads((REPO / "package.json").read_text())
    for name in (
        "docs/test-scope-migration.md",
        "docs/2026-10-14-context-evidence-collection-efficiency-spec.md",
        "docs/superpowers/reports/v032-context-efficiency.md",
    ):
        assert name in package["files"]
        assert (REPO / name).is_file()
    for name in ("README.md", "README.zh-CN.md"):
        text = (REPO / name).read_text()
        assert "docs/test-scope-migration.md" in text
        assert "docs/superpowers/reports/v032-context-efficiency.md" in text
        assert "PROFILE_WRITE_FAILED_CONTEXT_PUBLISHED" in text


def test_python_npm_and_changelog_versions_match():
    """Break caught: npm or changelog release version drifts from Python package."""
    python_version = tomllib.loads((REPO / "pyproject.toml").read_text())["project"][
        "version"
    ]
    npm_version = json.loads((REPO / "package.json").read_text())["version"]
    changelog = (REPO / "CHANGELOG.md").read_text()

    assert npm_version == python_version
    assert re.search(rf"^## {re.escape(python_version)}$", changelog, re.MULTILINE)
