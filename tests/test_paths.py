from pathlib import Path

import pytest


def test_evidence_path_keeps_filename_inside_evidence_directory(tmp_path):
    from harness.paths import evidence_path

    assert evidence_path(tmp_path / ".harness", "unit-test") == (
        tmp_path / ".harness" / "evidence" / "unit-test.json"
    )


def test_evidence_path_resolves_canonical_reference_forms(tmp_path):
    from harness.paths import evidence_path

    harness = tmp_path / ".harness"
    expected = harness / "evidence" / "unit-test.json"
    for reference in (
        "unit-test",
        "unit-test.json",
        ".harness/evidence/unit-test.json",
        str(expected.resolve()),
    ):
        assert evidence_path(harness, reference) == expected


@pytest.mark.parametrize(
    "reference", ["/tmp/proof.json", "../history/proof.json", "nested/proof.json"]
)
def test_evidence_path_rejects_noncanonical_reference(tmp_path, reference):
    from harness.paths import evidence_path

    harness = tmp_path / ".harness"
    (harness / "evidence").mkdir(parents=True)
    (harness / "evidence" / "fast-green-integration-test.json").write_text("{}")
    with pytest.raises(
        ValueError,
        match="EVIDENCE_REFERENCE_INVALID.*candidates: fast-green-integration-test",
    ):
        evidence_path(harness, reference)
