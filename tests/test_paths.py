from pathlib import Path

import pytest


def test_evidence_path_keeps_filename_inside_evidence_directory(tmp_path):
    from harness.paths import evidence_path

    assert evidence_path(tmp_path / ".harness", "unit-test") == (
        tmp_path / ".harness" / "evidence" / "unit-test.json"
    )


@pytest.mark.parametrize("reference", ["/tmp/proof.json", "../history/proof.json", "nested/proof.json"])
def test_evidence_path_rejects_reference_outside_canonical_directory(tmp_path, reference):
    from harness.paths import evidence_path

    with pytest.raises(ValueError, match="EVIDENCE_REFERENCE_INVALID"):
        evidence_path(tmp_path / ".harness", reference)
