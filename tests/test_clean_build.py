"""A dirty local build cache must not restore removed modules into a wheel."""
import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("member", ["harness/unexpected.py", "harness/__init__.py", "harness/old.dist-info/stale.py"])
def test_wheel_manifest_rejects_unknown_or_changed_payload(tmp_path, monkeypatch, member):
    spec = importlib.util.spec_from_file_location("local_build_backend", ROOT / "harness_build_backend.py")
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
    source = tmp_path / "source"
    package = source / "src/harness"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("CURRENT = True\n")
    output = tmp_path / "dist"
    output.mkdir()
    monkeypatch.chdir(source)

    def stale_backend(directory, *args):
        path = Path(directory) / "fixture-0-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(member, "STALE = True\n")
        return path.name

    monkeypatch.setattr(backend._backend, "build_wheel", stale_backend)
    with pytest.raises(RuntimeError, match="WHEEL_SOURCE_MISMATCH"):
        backend.build_wheel(output)
    assert Path.cwd() == source


def test_dirty_build_cache_is_not_packaged_or_deleted(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "LICENSE", "README.md", "MANIFEST.in", "harness_build_backend.py"):
        if (ROOT / name).is_file():
            shutil.copy2(ROOT / name, source / name)
    for path in (ROOT / "src/harness").rglob("*"):
        if path.is_file() and path.suffix in {".py", ".yaml", ".json"}:
            target = source / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    stale = source / "build/lib/harness/removed_module.py"
    stale.parent.mkdir(parents=True)
    stale.write_text("OLD_CACHE_MARKER = True\n")
    before = stale.stat().st_ino, stale.read_bytes()
    dist = tmp_path / "dist"
    result = subprocess.run([
        os.environ.get("HARNESS_BUILD_PYTHON", sys.executable), "-m", "pip", "wheel", str(source),
        "--no-index", "--no-deps", "--no-build-isolation", "--wheel-dir", str(dist),
    ], capture_output=True, text=True, timeout=90, check=False,
       env={k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}})
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(next(dist.glob("*.whl"))) as archive:
        assert "harness/removed_module.py" not in archive.namelist()
        for name in archive.namelist():
            if name.startswith("harness/") and not name.endswith("/"):
                assert archive.read(name) == (source / "src" / name).read_bytes()
    assert (stale.stat().st_ino, stale.read_bytes()) == before
