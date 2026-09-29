"""Restricted byte-preserving projection of canonical Plan execution into Markdown."""

from __future__ import annotations

import re

_MAPPING_LINE = re.compile(r"^[ \t]*- \[( |x|X)\] (P-[0-9]+)(?:[ \t]+.*)?$")
_RESERVED_PREFIX = re.compile(r"^[ \t]*- \[")
_PLAN_ID = re.compile(r"P-[0-9]+")
_TERMINAL = frozenset({"COMPLETE", "SKIPPED", "SUPERSEDED"})
_NONTERMINAL = frozenset({"PENDING", "IN_PROGRESS", "BLOCKED"})


class PlanMarkdownError(ValueError):
    """Stable refusal raised for unsafe Markdown content or item mappings."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _without_line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\n", "\r")):
        return line[:-1]
    return line


def _required_marker(item_id: str, projection: dict[str, dict]) -> str:
    record = projection.get(item_id)
    status = "PENDING" if record is None else record.get("status")
    if status in _TERMINAL:
        return "x"
    if status in _NONTERMINAL:
        return " "
    raise PlanMarkdownError("PLAN_MARKDOWN_TARGET_INVALID")


def project_markdown_checkboxes(
    content: bytes,
    ordered_plan_ids: tuple[str, ...],
    projection: dict[str, dict],
) -> bytes:
    """Return content with only mapped checkbox-state bytes projected."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanMarkdownError("PLAN_MARKDOWN_TARGET_INVALID") from exc

    if len(set(ordered_plan_ids)) != len(ordered_plan_ids):
        raise PlanMarkdownError("PLAN_MARKDOWN_MAPPING_INVALID")

    expected = set(ordered_plan_ids)
    mappings: dict[str, tuple[int, int]] = {}
    lines = text.splitlines(keepends=True)

    for line_index, line in enumerate(lines):
        body = _without_line_ending(line)
        match = _MAPPING_LINE.fullmatch(body)
        if match is None:
            if _RESERVED_PREFIX.match(body) and _PLAN_ID.search(body):
                raise PlanMarkdownError("PLAN_MARKDOWN_TARGET_INVALID")
            continue
        item_id = match.group(2)
        if item_id not in expected or item_id in mappings:
            raise PlanMarkdownError("PLAN_MARKDOWN_MAPPING_INVALID")
        mappings[item_id] = (line_index, match.start(1))

    if set(mappings) != expected:
        raise PlanMarkdownError("PLAN_MARKDOWN_MAPPING_INVALID")

    projected = list(lines)
    for item_id in ordered_plan_ids:
        line_index, marker_index = mappings[item_id]
        line = projected[line_index]
        marker = _required_marker(item_id, projection)
        if line[marker_index] != marker:
            projected[line_index] = line[:marker_index] + marker + line[marker_index + 1 :]

    return "".join(projected).encode("utf-8")
