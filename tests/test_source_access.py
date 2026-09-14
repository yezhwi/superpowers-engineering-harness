"""Guard behavior in isolation; integration with Gate is a separate step."""

# Keep exception assertions separate from the scopes whose exit they test.
# ruff: noqa: SIM117

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest


def test_declared_member_pattern_allows_missing_file_not_other_names(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import exists, source_scope

    directory = tmp_path / "evidence"
    directory.mkdir()
    with source_scope(tmp_path, allowed=[], member_rules=[(directory, "*.json")]):
        assert not exists(directory / "missing.json")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(tmp_path, allowed=[], member_rules=[(directory, "*.json")]):
            exists(directory / "unexpected.yaml")


def test_unknown_read_is_rejected(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    root = tmp_path / ".harness"
    root.mkdir()
    file = root / "unknown.yaml"
    file.write_text("secret")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(root, allowed=[]):
            file.read_text()


def test_swallowed_violation_still_fails_scope(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    root = tmp_path / ".harness"
    root.mkdir()
    file = root / "unknown"
    file.write_text("secret")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN") as error:
        with source_scope(root, allowed=[]):
            try:
                file.read_bytes()
            except Exception:  # noqa: BLE001, S110 -- simulate Gate swallowing a loader error
                pass
    assert "secret" not in str(error.value)
    assert file.read_text() == "secret"  # scope restored on failure


def test_declared_read_and_missing_probe(tmp_path):
    from harness.source_access import exists, read_bytes, source_scope

    file = tmp_path / ".harness" / "optional"
    file.parent.mkdir()
    with source_scope(file.parent, allowed=[file]):
        assert not exists(file)
    file.write_bytes(b"declared")
    with source_scope(file.parent, allowed=[file]):
        assert read_bytes(file) == b"declared"


def test_unknown_exists_is_rejected(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import exists, source_scope

    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(tmp_path, allowed=[]):
            exists(tmp_path / "absent")


def test_nested_scope_cannot_expand_parent_authority(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    file = tmp_path / "unknown"
    file.write_text("value")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(tmp_path, allowed=[]):
            with source_scope(tmp_path, allowed=[file]):
                file.read_text()


def test_external_symlink_cannot_escape_guard(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    root = tmp_path / ".harness"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("private")
    link = root / "link"
    link.symlink_to(outside)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(root, allowed=[link]):
            link.read_text()


def test_catching_nested_scope_error_does_not_clear_outer_violation(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    file = tmp_path / "declared"
    file.write_text("value")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(tmp_path, allowed=[file]):
            try:
                with source_scope(tmp_path, allowed=[]):
                    file.read_text()
            except ContextBuildError:
                pass


@pytest.mark.parametrize("method", ["builtin", "bytes", "fd"])
def test_other_open_routes_cannot_bypass_guard(tmp_path, method):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    file = tmp_path / "unknown"
    file.write_text("value")
    with file.open("rb") as prior:
        with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
            with source_scope(tmp_path, allowed=[]):
                if method == "builtin":
                    with open(file) as stream:
                        stream.read()
                elif method == "bytes":
                    file.read_bytes()
                else:
                    with open(prior.fileno(), closefd=False) as stream:
                        stream.read()


def test_parallel_scope_permissions_are_isolated(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    file = tmp_path / "shared"
    file.write_text("value")
    barrier = Barrier(2)

    def read(allowed):
        try:
            with source_scope(tmp_path, allowed=[file] if allowed else []):
                barrier.wait(timeout=5)
                return file.read_text()
        except ContextBuildError:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        yes, no = pool.submit(read, True), pool.submit(read, False)
        assert yes.result(timeout=10) == "value"
        assert no.result(timeout=10) == "denied"
