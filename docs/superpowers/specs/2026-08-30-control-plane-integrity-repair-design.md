# Control-Plane Integrity Repair Design

## Goal
Repair every confirmed control-plane defect so Harness behavior, persisted artifacts, CLI contracts, Skills, and docs agree and fail closed.

## Scope
- DIAG Finding Gate proof policy
- Gate decision interface and stale Skill/docs contract
- FAST recursive boundary matching
- BLOCKED recovery routing
- replacement-task transaction and impact reset
- evidence-reference containment
- risk level/profile integrity
- CLI Harness-root resolution
- complexity-review transaction
- stale source-of-truth documentation and low-risk hardening

## Architecture

### Gate policy
`quality_gate.run_gate` validates risk consistency before selecting FAST or STANDARD/STRICT policy. FAST requires `level: Q1` and `profile: FAST`; Q2/Q3 always use non-FAST Gate policy.

Finding proof selection is category-specific. Ordinary Findings retain RED/GREEN/full-regression requirements. `category: diagnosability` never reads `regression_test`; terminal DIAG Findings validate canonical diagnosability-review compliance proof. DIAG Findings are excluded from ordinary confirmed-regression-test debt.

Gate configuration receives a JSON schema and validation before policy values affect decisions. `must_match_head` controls whether relevant evidence must match current HEAD. Evidence collection derives pytest-covered node IDs from executed command/output where available and rejects declared coverage that cannot identify execution. Commands run with bounded timeout; timeout is persisted as failed evidence.

### CLI and state transitions
CLI resolves one Harness root for every command. `status --harness-dir` passes through its parsed path. Other commands use repository-root Harness resolution rather than CWD-local `.harness`.

`harness gate` exposes decision in durable state and stdout. Its exit status means command execution only; Skills/docs inspect `DECISION: CONVERGED|CONTINUE|ESCALATED` and run `harness status`, never infer PASS from exit `0`. Generic `transition` rejects every departure from `BLOCKED`; `resume` is sole departure route.

### Artifact integrity
Evidence references are validated as relative single-file JSON names beneath `.harness/evidence`; absolute paths, parent traversal, and nested paths reject before reading.

Task replacement publishes archive and new task artifacts as one staged transaction. Archive includes `impact.yaml`; new task gets new template impact. Complexity reviews stage all findings and review evidence, then publish together.

### Risk boundaries
Boundary matching operates on full POSIX path segments. `**` matches zero or more directory segments; matching is anchored to repository-relative path. Q3 remains dominant over Q2.

### Module boundaries
Split `controlplane.py` command groups into focused modules: task lifecycle, findings, impact, gate orchestration, and common Harness-root/path helpers. CLI remains parser/dispatcher. Existing public command names remain compatible except documented behavior corrections.

### Documentation and packaging
Root Skill, sub-Skills, README variants, worked example, and module documentation name `src/harness` as source, CLI as task-control surface, correct state order, DIAG review timing, and Gate decision handling. Deprecated `harness converge` is removed from workflows.

Wheel isolation installs with no system-site packages. Repository ignores and removes tracked runtime `.harness` dogfood state. Package metadata documents CLI-only public API; it does not imply Python module API stability. All atomic writers use unique same-directory temporary files.

## Error handling
All malformed artifact state maps to deterministic invalid-state errors or typed blockers; no raw `KeyError`, accidental external read, or partial canonical publication. Existing user work remains untouched.

## Testing
Add focused failing tests first for every behavior above: DIAG Gate states, Gate decision contract, nested and anchored risk globs, blocked bypass, replacement impact isolation, evidence traversal, schema mismatch, subdirectory CLI behavior, and complexity write rollback. Run affected modules, then full `pytest -q`.

## Non-goals
- Redesigning risk dimensions or Finding lifecycle semantics.
- Adding remote security boundaries against users who can alter project source.
- Replacing persisted YAML/JSON artifact formats wholesale.
