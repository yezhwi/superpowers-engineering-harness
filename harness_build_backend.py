"""PEP 517 wheel hook: build from fresh inputs, never a caller's build cache."""
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from setuptools import build_meta as _backend
from setuptools.build_meta import (
    build_editable,
    build_sdist,
    get_requires_for_build_editable,
    get_requires_for_build_sdist,
    get_requires_for_build_wheel,
    prepare_metadata_for_build_editable,
    prepare_metadata_for_build_wheel,
)

__all__ = [
    "build_editable",
    "build_sdist",
    "build_wheel",
    "get_requires_for_build_editable",
    "get_requires_for_build_sdist",
    "get_requires_for_build_wheel",
    "prepare_metadata_for_build_editable",
    "prepare_metadata_for_build_wheel",
]


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    source = Path.cwd()
    output = Path(wheel_directory).resolve()
    metadata = str(Path(metadata_directory).resolve()) if metadata_directory else None
    with tempfile.TemporaryDirectory(prefix="harness-clean-wheel-") as temporary:
        clean = Path(temporary)
        for name in ("pyproject.toml", "LICENSE", "README.md", "MANIFEST.in", "harness_build_backend.py"):
            if (source / name).is_file():
                shutil.copy2(source / name, clean / name)
        shutil.copytree(source / "src", clean / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
        try:
            os.chdir(clean)
            name = _backend.build_wheel(str(output), config_settings, metadata)
        finally:
            os.chdir(source)
        # Check the actual result, not build output or the stale local manifest.
        with zipfile.ZipFile(output / name) as archive:
            for member in archive.namelist():
                parts = member.split("/")
                if member.endswith("/"):
                    continue
                if len(parts) > 1 and parts[0].endswith(".dist-info") and ".." not in parts:
                    continue
                path = clean / "src" / member
                if not member.startswith("harness/") or not path.is_file() or archive.read(member) != path.read_bytes():
                    raise RuntimeError("WHEEL_SOURCE_MISMATCH")
        return name
