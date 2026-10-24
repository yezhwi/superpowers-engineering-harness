"""Ordinary paraphrases must not break structural skill checks."""
from pathlib import Path

import pytest
import test_agent_guidance_contract as checks

ROOT = Path(__file__).resolve().parents[1]


def guidance_copy(tmp_path, monkeypatch):
    for name in ("SKILL.md", "skills/engineering-harness/SKILL.md", "skills/collect-evidence/SKILL.md"):
        text = (ROOT / name).read_text()
        for old, new in (("before launching", "before starting"),
                         ("planned batch manifest", "batch execution plan"),
                         ("collector process exit alone", "collector return code alone"),
                         ("Setup/checker failure", "Invalid setup or checker"),
                         ("Product regression", "Product failure"),
                         ("Authority/policy refusal", "Permission or budget refusal")):
            text = text.replace(old, new)
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    monkeypatch.setattr(checks, "ROOT", tmp_path)


@pytest.mark.parametrize("case", ["batch", "collection", "triage"])
def test_equivalent_prose_is_not_an_interface_regression(tmp_path, monkeypatch, case):
    guidance_copy(tmp_path, monkeypatch)
    if case == "batch":
        checks.test_evidence_scheduling_preplans_complete_bounded_batches("SKILL.md")
    elif case == "collection":
        checks.test_collection_batch_proof_is_genuine_qualified_and_fail_stop()
    else:
        checks.test_failure_triage_covers_setup_product_and_authority_without_new_states("SKILL.md")


def test_missing_real_selector_interface_still_fails(tmp_path, monkeypatch):
    guidance_copy(tmp_path, monkeypatch)
    path = tmp_path / "SKILL.md"
    path.write_text(path.read_text().replace("--covered-test", "REMOVED_SELECTOR"))
    with pytest.raises(AssertionError):
        checks.test_evidence_scheduling_preplans_complete_bounded_batches("SKILL.md")
