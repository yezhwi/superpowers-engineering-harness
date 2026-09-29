"""P2 restricted Plan Markdown projection tests."""

import pytest

from harness.plan_markdown import PlanMarkdownError, project_markdown_checkboxes


def _project(content: bytes, projection: dict[str, dict] | None = None) -> bytes:
    return project_markdown_checkboxes(
        content,
        ("P-001", "P-002", "P-003"),
        projection
        or {
            "P-001": {"status": "COMPLETE"},
            "P-002": {"status": "SKIPPED"},
            "P-003": {"status": "BLOCKED"},
        },
    )


def test_project_markdown_checkboxes_accepts_exact_mapping_grammar():
    content = (
        b"heading\n"
        b"- [ ] P-001 implement parser\n"
        b"\t- [X] P-002\tkeep suffix\n"
        b"  - [x] P-003 blocked item\n"
    )

    assert _project(content) == (
        b"heading\n"
        b"- [x] P-001 implement parser\n"
        b"\t- [x] P-002\tkeep suffix\n"
        b"  - [ ] P-003 blocked item\n"
    )


def test_project_markdown_checkboxes_preserves_non_state_bytes():
    content = b"  - [ ] P-001 suffix \xf0\x9f\x94\x92\r\n- [ ] P-002\n\t- [ ] P-003 end"

    result = _project(content)

    changed = [index for index, pair in enumerate(zip(content, result)) if pair[0] != pair[1]]
    assert changed == [5, 30]
    assert all(
        before == after
        for index, (before, after) in enumerate(zip(content, result))
        if index not in changed
    )


def test_project_markdown_checkboxes_ignores_plan_ids_in_ordinary_prose():
    content = (
        b"# P-001 heading\n"
        b"Paragraph mentions P-002.\n"
        b"- prose P-003\n"
        b"- [ ] P-001\n- [ ] P-002\n- [ ] P-003\n"
    )

    assert _project(content).startswith(
        b"# P-001 heading\nParagraph mentions P-002.\n- prose P-003\n"
    )


@pytest.mark.parametrize(
    "line",
    [
        b"- [ ]  P-001\n",
        b"- [] P-001\n",
        b"- [y] P-001\n",
        b" - [ ]P-001\n",
        b"- [ ] P-001suffix\n",
    ],
)
def test_project_markdown_checkboxes_rejects_malformed_reserved_candidate(line):
    with pytest.raises(PlanMarkdownError) as error:
        project_markdown_checkboxes(line, ("P-001",), {})

    assert error.value.code == "PLAN_MARKDOWN_TARGET_INVALID"


def test_project_markdown_checkboxes_rejects_duplicate_mapping():
    with pytest.raises(PlanMarkdownError) as error:
        project_markdown_checkboxes(
            b"- [ ] P-001\n- [x] P-001 duplicate\n", ("P-001",), {}
        )

    assert error.value.code == "PLAN_MARKDOWN_MAPPING_INVALID"


def test_project_markdown_checkboxes_rejects_unknown_mapping():
    with pytest.raises(PlanMarkdownError) as error:
        project_markdown_checkboxes(
            b"- [ ] P-001\n- [ ] P-999\n", ("P-001",), {}
        )

    assert error.value.code == "PLAN_MARKDOWN_MAPPING_INVALID"


def test_project_markdown_checkboxes_rejects_missing_mapping():
    with pytest.raises(PlanMarkdownError) as error:
        project_markdown_checkboxes(b"- [ ] P-001\n", ("P-001", "P-002"), {})

    assert error.value.code == "PLAN_MARKDOWN_MAPPING_INVALID"


def test_project_markdown_checkboxes_rejects_non_utf8_content():
    with pytest.raises(PlanMarkdownError) as error:
        project_markdown_checkboxes(b"- [ ] P-001\n\xff", ("P-001",), {})

    assert error.value.code == "PLAN_MARKDOWN_TARGET_INVALID"


@pytest.mark.parametrize(
    ("status", "marker"),
    [
        ("COMPLETE", b"x"),
        ("SKIPPED", b"x"),
        ("SUPERSEDED", b"x"),
        ("PENDING", b" "),
        ("IN_PROGRESS", b" "),
        ("BLOCKED", b" "),
    ],
)
def test_project_markdown_checkboxes_maps_closed_execution_statuses(status, marker):
    result = project_markdown_checkboxes(
        b"- [X] P-001\r\n", ("P-001",), {"P-001": {"status": status}}
    )

    assert result == b"- [" + marker + b"] P-001\r\n"


def test_project_markdown_checkboxes_treats_absent_projection_item_as_pending():
    assert project_markdown_checkboxes(
        b"- [x] P-001\n", ("P-001",), {}
    ) == b"- [ ] P-001\n"


def test_project_markdown_checkboxes_is_byte_identical_when_already_synchronized():
    content = b"- [x] P-001\n- [x] P-002\n- [ ] P-003\n"

    assert _project(content) == content


def test_project_markdown_checkboxes_counterexamples_change_only_mapping_state():
    prefixes = [b"", b" ", b"\t\t"]
    suffixes = [b"", b" words P-999", b"\tunicode \xe2\x9c\x93"]
    prose = b"P-001\n# P-002\nparagraph P-003\n"
    for prefix in prefixes:
        for suffix in suffixes:
            content = (
                prose
                + prefix
                + b"- [ ] P-001"
                + suffix
                + b"\r\n- [X] P-002\n- [x] P-003"
            )
            result = _project(content)
            assert len(result) == len(content)
            differing = [
                index
                for index, (before, after) in enumerate(zip(content, result))
                if before != after
            ]
            assert len(differing) == 3
            assert all(content[index] in b" Xx" and result[index] in b" x" for index in differing)
