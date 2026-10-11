from pathlib import Path

import pytest


@pytest.mark.parametrize("reference, expected", [
    ("build", 1), ("build-2.json", 2), ("build-10", 10),
    ("fast-green-unit-test-3.json", 3), ("fast-red-unit-test", 1),
    ("FND-001-green-unit-test-4", 4),
    ("unit-test-abcdef123456", 1), ("unit-test-abcdef123456-10", 10),
    ("unit-test-000000000002", 1), ("unit-test-000000000002-2", 2),
    ("build-0", 1), ("build-1", 1), ("build-invalid", 1),
    ("build-2-extra", 1), ("build--2", 1), ("build-٢", 1),
])
def test_evidence_receipt_order(reference, expected):
    from harness.paths import evidence_receipt_order

    assert evidence_receipt_order(reference) == expected


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
