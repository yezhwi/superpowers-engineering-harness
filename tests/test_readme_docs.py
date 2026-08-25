"""README navigation and command contracts."""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_bilingual_readmes_link_and_document_core_commands():
    """Break caught: language mirror or documented core workflow disappears."""
    english = (REPO / "README.md").read_text()
    chinese = (REPO / "README.zh-CN.md").read_text()

    for command in (
        "harness init",
        "harness check minimal",
        "harness review complexity",
        "harness converge",
    ):
        assert command in english
        assert command in chinese
    assert "README.zh-CN.md" in english
    assert "README.md" in chinese


def test_workflow_makes_full_suite_advisory_after_focused_tests():
    workflow = (REPO / "SKILL.md").read_text()
    assert "exact regression + impact-related tests" in workflow
    assert "only when user wants final broad regression confidence" in workflow
    assert "Critical findings may use the same related proof only with explicit per-finding user approval" in workflow
