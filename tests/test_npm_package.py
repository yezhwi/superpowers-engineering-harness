"""npm package must exclude local Harness state and Python runtime."""

import json
from pathlib import Path
import subprocess


REPO = Path(__file__).resolve().parent.parent
ALLOWED = {"package.json", "README.md", "README.zh-CN.md", "LICENSE", "SKILL.md"}


def test_npm_tarball_contains_only_skill_package_files():
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    files = {entry["path"] for entry in json.loads(result.stdout)[0]["files"]}
    assert all(path in ALLOWED or path.startswith("skills/") for path in files)
    assert not any(
        path.startswith((".harness/", ".idea/", "src/", "docs/", "tests/"))
        for path in files
    )
