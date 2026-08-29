"""Diagnosability Gate policy tests."""

from harness.diagnosability import gate_blockers


def test_q3_blocks_unassessed_contract(tmp_path):
    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "observability.yaml").write_text(
        "version: 1\nrequired: false\napplicability:\n  reasons: [not_assessed]\n  inspected_paths: ['.']\n"
    )
    blockers = gate_blockers(
        harness,
        {"risk": {"level": "Q3", "profile": "STRICT"}},
        head="head", workspace="sha256:" + "a" * 64,
    )
    assert [blocker.code for blocker in blockers] == ["OBSERVABILITY_CONTRACT_INVALID"]
