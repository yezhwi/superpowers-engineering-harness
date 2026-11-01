"""Stable Harness storage; no implicit activation or cleanup."""
from .layout import LayoutInspection, StorageError, admit_storage, inspect_layout
from .archive import ArchiveHandle, ReferenceOrigin, resolve_archive
from .migration import StorageRequest, apply_operation, plan_operation


def recover_operation(repo_root, operation_id):
    from .journal import recover_operation as recover

    return recover(repo_root, operation_id)

__all__ = ["ArchiveHandle", "ReferenceOrigin", "LayoutInspection", "StorageError",
           "StorageRequest", "apply_operation", "plan_operation",
           "admit_storage", "inspect_layout", "recover_operation", "resolve_archive"]
