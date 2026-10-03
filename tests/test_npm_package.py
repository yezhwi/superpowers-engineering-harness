"""npm package must include declared release assets and exclude local runtime state."""

import json
from pathlib import Path
import subprocess


REPO = Path(__file__).resolve().parent.parent
NPM_ALWAYS_INCLUDED = {"package.json", "README.md", "README.zh-CN.md", "LICENSE"}
FORBIDDEN_PREFIXES = (".harness/", ".idea/", "src/", "tests/", "benchmarks/")


def test_npm_tarball_matches_explicit_release_manifest():
    package = json.loads((REPO / "package.json").read_text())
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    files = {entry["path"] for entry in json.loads(result.stdout)[0]["files"]}
    declared_files = {path for path in package["files"] if path != "skills"}

    assert files <= NPM_ALWAYS_INCLUDED | declared_files | {
        path for path in files if path.startswith("skills/")
    }
    assert {
        "CHANGELOG.md",
        "SKILL.md",
        "skills/engineering-harness/SKILL.md",
        "docs/Superpowers-Engineering-Harness-v0.3.0-Architecture-Scope-and-Drift-Design.md",
        "docs/superpowers/reports/v030-architecture-benchmark-template.md",
    } <= files
    assert not any(path.startswith(FORBIDDEN_PREFIXES) for path in files)
