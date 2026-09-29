"""Cross-command P2 CLI contract tests."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_gate_preview_command_is_not_introduced(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "gate", "preview"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid choice: 'preview'" in result.stderr
