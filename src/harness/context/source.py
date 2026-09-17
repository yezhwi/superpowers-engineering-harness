"""Read canonical Harness sources without status fallback or repository scans."""

import hashlib
from pathlib import Path

import yaml

from harness import (
    decision,
    diagnosability,
    interface_contract,
    quality_gate,
    source_access,
    workspace,
)
from harness.evidence_validator import EvidenceStatus, project_evidence
from harness.repository import RepositoryNotFoundError, find_git_root

from .model import AuthoritativeContext, ContextBuildError

ARTIFACT_PATTERNS = {
    "decisions": "DEC-*.yaml",
    "findings": "*.yaml",
    "interface-contracts": "*.yaml",
    "evidence": "*.json",
}


class FileContextSource:
    """Load from repository-root CWD, as normalized by the existing CLI.

    Gate currently reads workspace facts from CWD. Reject a mismatched root
    rather than changing process CWD or pairing one task with another workspace.
    Hashes here are object references, not a complete freshness manifest.
    """

    def __init__(self, harness_dir: Path):
        self.harness_dir = harness_dir.absolute()
        self.repo_root = self.harness_dir.parent.resolve()
        self.references: dict[str, dict | None] = {}

    def _checked_path(self, name: str) -> Path:
        path = self.harness_dir / name
        if not path.resolve().is_relative_to(self.repo_root):
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN", f"outside repository: {name}"
            )
        return path

    def _reference(self, name: str, *, content: bytes | None = None) -> dict:
        path = self._checked_path(name)
        reference = {
            "ref": path.relative_to(self.harness_dir.parent).as_posix(),
            "sha256": "sha256:"
            + hashlib.sha256(
                content if content is not None else source_access.read_bytes(path)
            ).hexdigest(),
        }
        self.references[name] = reference
        return reference

    def _document(
        self, name: str, schema: str | None = None, *, optional: bool = False
    ):
        path = self._checked_path(name)
        try:
            content = source_access.read_bytes(path)
            self._reference(name, content=content)
            document = yaml.safe_load(content.decode("utf-8"))
        except FileNotFoundError as exc:
            if optional:
                self.references[name] = None
                return None
            raise ContextBuildError("INVALID_HARNESS_STATE", f"missing {name}") from exc
        except (OSError, ValueError, yaml.YAMLError) as exc:
            if isinstance(exc, ContextBuildError):
                raise
            raise ContextBuildError(
                "CONTEXT_SCHEMA_INVALID", f"cannot load {name}"
            ) from exc
        if not isinstance(document, dict):
            raise ContextBuildError(
                "CONTEXT_SCHEMA_INVALID", f"{name} is not a mapping"
            )
        if schema:
            try:
                quality_gate.validate_schema(document, schema, path)
            except quality_gate.InvalidHarnessState as exc:
                raise ContextBuildError("CONTEXT_SCHEMA_INVALID", str(exc)) from exc
        return document

    def _artifact_paths(self, directory: str, pattern: str) -> list[Path]:
        path = self.harness_dir / directory
        if not path.resolve().is_relative_to(self.repo_root):
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN", f"outside repository: {directory}"
            )
        if source_access.exists(path) and not source_access.is_dir(path):
            raise ContextBuildError(
                "CONTEXT_SCHEMA_INVALID", f"not a directory: {directory}"
            )
        if source_access.is_symlink(path) and not source_access.exists(path):
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN", f"broken directory: {directory}"
            )
        return list(source_access.members(path, pattern))

    def _records(self, directory: str, loader) -> list[dict]:
        # Existing loaders return records in sorted canonical filename order.
        names = self._artifact_paths(directory, ARTIFACT_PATTERNS[directory])
        for path in names:
            self._reference(f"{directory}/{path.name}")
        try:
            records = loader()
        except (ValueError, OSError, quality_gate.InvalidHarnessState) as exc:
            raise ContextBuildError(
                "CONTEXT_SCHEMA_INVALID", f"{directory}: {exc}"
            ) from exc
        self._unique(records, directory)
        if [path.stem for path in names] != [record["id"] for record in records]:
            raise ContextBuildError(
                "CONTEXT_SCHEMA_INVALID", f"noncanonical artifacts in {directory}"
            )
        return records

    @staticmethod
    def _unique(records: list[dict], source: str) -> None:
        ids = [record["id"] for record in records]
        if len(ids) != len(set(ids)):
            raise ContextBuildError(
                "CONTEXT_SCHEMA_INVALID", f"duplicate ids in {source}"
            )

    def load(self) -> AuthoritativeContext:
        try:
            root = find_git_root(Path.cwd())
        except RepositoryNotFoundError as exc:
            raise ContextBuildError("INVALID_HARNESS_STATE", str(exc)) from exc
        if root.resolve() != self.repo_root or Path.cwd().resolve() != self.repo_root:
            raise ContextBuildError(
                "INVALID_HARNESS_STATE", "Context source requires repository-root CWD"
            )
        self.references = {}
        task = self._document("current-task.yaml", "task.schema.json")
        if not task["task"].get("id") or not isinstance(task.get("risk"), dict):
            raise ContextBuildError(
                "INVALID_HARNESS_STATE",
                "classified task required; run task classify first",
            )
        fast = task["risk"]["profile"] == "FAST"
        requirements = self._document(
            "requirements.yaml", "requirement.schema.json", optional=fast
        )
        invariants = self._document(
            "invariants.yaml", "invariant.schema.json", optional=fast
        )
        requirements = (requirements or {}).get("requirements", [])
        invariants = (invariants or {}).get("invariants", [])
        self._unique(requirements, "requirements.yaml")
        self._unique(invariants, "invariants.yaml")
        self._artifact_paths("decisions", ARTIFACT_PATTERNS["decisions"])
        try:
            decision_metadata = decision.load_decision_index(self.harness_dir)
        except decision.DecisionError as exc:
            raise ContextBuildError("CONTEXT_SCHEMA_INVALID", str(exc)) from exc
        if source_access.exists(self.harness_dir / "decisions/index.yaml"):
            self._reference("decisions/index.yaml")
        else:
            self.references["decisions/index.yaml"] = None
        task_id = task["task"]["id"]
        def load_decision_body(decision_id: str) -> dict:
            self._reference(f"decisions/{decision_id}.yaml")
            return decision.load_decision(self.harness_dir, decision_id)

        decisions = [
            load_decision_body(record["id"])
            for record in decision_metadata
            if record["task_id"] == task_id
        ]
        known = {record["id"] for record in decision_metadata}
        referenced = {
            value
            for record in decisions
            for value in (record.get("supersedes"), record.get("superseded_by"))
            if isinstance(value, str) and value
        }
        missing = referenced - known
        if missing:
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN",
                f"missing declaration: decisions/{min(missing)}.yaml",
            )
        decisions.extend(
            load_decision_body(decision_id)
            for decision_id in sorted(referenced - {record["id"] for record in decisions})
        )
        findings = self._records(
            "findings",
            lambda: quality_gate.load_findings(self.harness_dir / "findings"),
        )
        interfaces = self._records(
            "interface-contracts",
            lambda: interface_contract.load_interface_contracts(self.harness_dir),
        )
        impact = self._document("impact.yaml", optional=True)
        if impact is not None:
            value = impact.get("impact")
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("contracts", []), list)
                or not all(
                    isinstance(path, str) and path
                    for path in value.get("contracts", [])
                )
            ):
                raise ContextBuildError(
                    "CONTEXT_SCHEMA_INVALID", "invalid impact contracts"
                )
        contract_refs = {
            ref
            for interface in interfaces
            for ref in interface.get("decision_refs", [])
            if isinstance(ref, str)
        }
        contract_refs.update(
            value.split(":", 1)[0]
            for value in (impact or {}).get("impact", {}).get("contracts", [])
            if isinstance(value, str) and value.startswith("DEC-") and ":" in value
        )
        missing = contract_refs - known
        if missing:
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN",
                f"missing declaration: decisions/{min(missing)}.yaml",
            )
        loaded = {record["id"] for record in decisions}
        decisions.extend(
            load_decision_body(decision_id)
            for decision_id in sorted(contract_refs - loaded)
        )
        observability = self._document("observability.yaml", optional=True)
        if observability is not None:
            try:
                diagnosability.validate_contract(
                    observability, task_type=task["task"].get("type")
                )
            except ValueError as exc:
                raise ContextBuildError("CONTEXT_SCHEMA_INVALID", str(exc)) from exc
        self._document("gate.yaml", "gate.schema.json")
        try:
            current = workspace.snapshot(self.repo_root)
            evidence = []
            for path in self._artifact_paths("evidence", ARTIFACT_PATTERNS["evidence"]):
                reference = self._reference(f"evidence/{path.name}")
                projection = project_evidence(path, current.head, current.fingerprint)
                if projection.status in {
                    EvidenceStatus.INVALID,
                    EvidenceStatus.MISSING,
                }:
                    raise ContextBuildError(
                        "CONTEXT_SCHEMA_INVALID", f"{path.name}: {projection.code}"
                    )
                record = projection.record
                evidence.append(
                    {
                        **reference,
                        "type": record["type"],
                        "exit_code": record["exit_code"],
                        "covered_tests": record.get("covered_tests", []),
                        "status": projection.status.value,
                        "code": projection.code,
                        "expected_fingerprint": projection.expected_fingerprint,
                        "current_fingerprint": projection.current_fingerprint,
                    }
                )
            gate = quality_gate.assess_gate(
                self.harness_dir, head=current.head, allow_preflight=True
            )
        except (
            OSError,
            workspace.WorkspaceError,
            quality_gate.InvalidHarnessState,
        ) as exc:
            raise ContextBuildError("INVALID_HARNESS_STATE", str(exc)) from exc
        from .escalation import active_expansions

        expansions = active_expansions(
            task, self._document("context/expansions.yaml", optional=True)
        )
        return AuthoritativeContext(
            expansions=expansions,
            task=task,
            requirements=requirements,
            invariants=invariants,
            decisions=decisions,
            decision_metadata=decision_metadata,
            findings=findings,
            interface_contracts=interfaces,
            impact=impact,
            observability=observability,
            evidence=evidence,
            references=self.references.copy(),
            workspace=current,
            gate=gate,
        )
