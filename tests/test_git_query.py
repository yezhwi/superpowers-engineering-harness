"""Bounded Git-only content queries used by protected snapshots."""

import pytest

from harness.git_query import GitQueryError, _validate


def test_hash_object_accepts_single_repo_relative_path():
    _validate(("hash-object", "--", "notes/user.md"))


@pytest.mark.parametrize("args", [
    ("hash-object", "--", "../outside"),
    ("hash-object", "--", "/tmp/outside"),
    ("hash-object", "--", "notes/../../outside"),
    ("hash-object", "--", "-w"),
    ("hash-object", "-w", "--", "notes/user.md"),
    ("hash-object", "--", "a.md", "b.md"),
    ("hash-object", "--", "."),
])
def test_hash_object_rejects_unbounded_queries(args):
    with pytest.raises(GitQueryError, match="GIT_QUERY_INVALID"):
        _validate(args)
