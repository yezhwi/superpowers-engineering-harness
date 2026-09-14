"""Authoritative inputs retained independently of their Control Core projection."""

from dataclasses import dataclass, field
from typing import Protocol, TypedDict

from harness.quality_gate import GateAssessment
from harness.workspace import WorkspaceSnapshot


class ContextBuildError(ValueError):
    """Stable error category plus source detail; never a fallback Context."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class AuthoritativeContext:
    """Loaded inputs, not an atomic snapshot or proof of Context Integrity."""

    task: dict
    requirements: list[dict]
    invariants: list[dict]
    decisions: list[dict]
    findings: list[dict]
    interface_contracts: list[dict]
    impact: dict | None
    observability: dict | None
    evidence: list[dict]
    references: dict[str, dict | None]
    workspace: WorkspaceSnapshot
    gate: GateAssessment
    expansions: list[dict] = field(default_factory=list)


class ContextSource(Protocol):
    def load(self) -> AuthoritativeContext: ...


class ControlCore(TypedDict):
    task: dict
    requirements: list[dict]
    invariants: list[dict]
    decisions: list[dict]
    findings: list[dict]
    blockers: list[dict]
    scope: dict | None
    authorizations: dict | None
    constraints: dict
    contracts: dict
    observability: dict | None
    evidence: list[dict]
    gate: dict
