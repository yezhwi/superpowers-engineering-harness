# v0.2.10 Plan Reconciliation P2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete v0.2.10 with safe Markdown checkbox projection, bounded Q3 mechanical COMPLETE automation, opt-in verbose Plan reporting, and Plan-aware existing Gate preflight.

**Architecture:** Add three focused modules: `plan_markdown.py` for restricted byte-preserving projection, `plan_automation.py` for exact bounded proof selection and shared mechanical surfaces, and `plan_reporting.py` for body-free item/preflight views. Existing `plan_reconciliation.py` remains canonical assessment and mutation orchestration; automatic requests resolve inside its existing lock and then pass through the ordinary mutation path. Gate computes one `PlanAssessment`, reuses it for blockers and preflight rendering, and keeps FAST/Q1 before all Plan reads.

**Tech Stack:** Python 3.11, argparse, dataclasses, itertools, pathlib, PyYAML, jsonschema, pytest, existing Harness telemetry lock and atomic transaction utilities.

**Spec:** `docs/superpowers/specs/2026-09-29-v0210-plan-reconciliation-p2-design.md`

## Global Constraints

- Canonical truth remains `.harness/plan.yaml` and `.harness/plan-execution.yaml`; Markdown is one-way projection only.
- `--auto` is Q3/STRICT `task_and_final`, current-item, COMPLETE-only automation. It cannot create reasons, Decisions, SKIPPED, or SUPERSEDED.
- Exact proof search accepts at most 16 eligible evidence candidates and 16 coverage atoms; 17 returns `PLAN_AUTO_LIMIT_EXCEEDED`.
- Zero coverage atoms for a non-empty test branch return `PLAN_PROOF_MISSING`.
- Manual coverage uses bare `TC-*`; automated coverage uses existing `record_covers_test` and `command_covers_test`.
- Reuse the P0 filtered mechanical surface set and protected-path behavior exactly.
- Default `harness plan status` text and JSON stay byte-for-byte compatible.
- Existing `harness gate preflight` `READY:` and blocker lines stay in the same content and order; Plan output appends afterward.
- Reports omit journal, receipt, evidence, reason, Decision, Requirement, Invariant, and test-case bodies.
- Reuse `telemetry_lock` and `transaction.atomic_write`; add no lock, persistent index, evidence type, top-level state, or canonical artifact.
- FAST/Q1 and disabled paths reject or return before Plan, Markdown, or auto-evidence reads.
- Work directly on `main`. Every commit requires explicit user authorization.
- Run focused related test files only. Never run unrestricted `pytest`.

## Review Focus

- A Markdown line containing `P-001` in ordinary prose must not become a mapping; a malformed reserved checkbox candidate must reject with zero writes. Task 1 pins both.
- Exact cover ties caused by duplicate or overlapping evidence must reject rather than depend on filesystem order. Task 3 pins canonical sorting and equal-cardinality ambiguity.
- Protected initial-user surfaces must be filtered while their aggregate fingerprint is unchanged and must retain `PLAN_PROTECTED_PATHS_MODIFIED` after divergence. Task 3 pins both branches.
- SKIPPED and SUPERSEDED remain `proof_health: not_applicable` even when their Plan definitions declare tests or surfaces. Task 5 pins disposition-before-proof precedence.
- Gate preflight must not evaluate Plan twice or duplicate a PLAN blocker while adding its appended section. Task 6 pins call count, object identity, and output ordering.

---

### Task 0: Freeze implementation contract and canonical P2 Plan

**Files:**
- Modify: `docs/Superpowers-Engineering-Harness-v0.2.10-Implementation-Contract.md`
- Create: `tests/test_plan_markdown.py`
- Create: `tests/test_plan_automation.py`
- Create: `tests/test_plan_reporting.py`
- Create through Harness workflow: `.harness/impact.yaml`, `.harness/minimal-implementation-TASK-063.yaml`, `.harness/plan.yaml`, `.harness/plan-execution.yaml`
- Verify: `.harness/requirements.yaml`, `.harness/invariants.yaml`, `.harness/alignment.yaml`, `.harness/observability.yaml`, `.harness/interface-contracts/INT-007.yaml`

**Interfaces:**
- Consumes: approved P2 design and TASK-063 Task Contract.
- Produces: minimal implementation record, impact declaration, authoritative delivery slices, test-path scaffolds, and empty Q3 execution v2 required for `PLANNED -> IMPLEMENTING`.

- [ ] **Step 1: Update contract status and P2 authority**

Change the contract header to state P0/P1A/P1B/P1C implemented and P2 designed. Replace the three-bullet P2 delivery summary with links and concise boundaries from the approved P2 spec. Do not copy the full design or change P0/P1 semantics.

- [ ] **Step 2: Record Minimal Implementation and impact**

Use the Harness Minimal Implementation workflow to record three new pure modules plus narrow orchestration edits as the lowest Decision Ladder option. Declare changed public CLI, Plan mutation, Gate preflight, Context dependency closure, tests, docs, and package surfaces in `.harness/impact.yaml`; include explicit non-impacts for Context schema, canonical artifact inventory, Q2 semantics, and FAST reads.

- [ ] **Step 3: Validate Task Contract artifacts**

Run schema validation for task, requirements, invariants, Alignment, Observability, INT-007, Minimal Implementation, and impact. Run `harness align check`.

Expected: all schemas valid and `ALIGNMENT_READY`.

- [ ] **Step 4: Create canonical Plan Items**

Write ordered Plan Items for:

1. restricted Markdown projection core;
2. Markdown CLI/locking integration;
3. exact auto-proof and shared mechanical surfaces;
4. auto mutation/CLI integration;
5. verbose status projection;
6. Gate preflight single-assessment integration;
7. benchmarks/package acceptance.

Each item maps to exact `REQ-*`, `INV-*`, `TC-*`, and declared surfaces from Alignment. Initialize execution v2 with sequence zero, empty transitions, and empty projection. Do not synthesize implementation history.

- [ ] **Step 5: Create test-path scaffolds without behavior**

Create the three new test modules with module docstrings only so frozen Task Contract paths exist for implementation entry. Do not import nonexistent production modules, add placeholder passing tests, or add production code. Each owning task adds its first behavioral test and observes RED before implementation.

- [ ] **Step 6: Run implementation-entry preflight**

Run schema checks, `harness plan status --json`, and the currently impacted existing tests. Then run `harness transition IMPLEMENTING`. Expected: transition succeeds only with fresh empty replay-valid v2 and resolved Test Plan paths.

- [ ] **Step 7: Request authorization, then commit Task 0 only**

```bash
git add docs/Superpowers-Engineering-Harness-v0.2.10-Implementation-Contract.md tests/test_plan_markdown.py tests/test_plan_automation.py tests/test_plan_reporting.py
git commit -m "chore: prepare plan reconciliation P2 execution"
```

Harness artifacts remain governed by repository policy. Do not stage `.gitignore` or unrelated user files.

---

### Task 1: Restricted Markdown projection core

**Files:**
- Create: `src/harness/plan_markdown.py`
- Modify: `tests/test_plan_markdown.py`

**Interfaces:**
- Produces: `PlanMarkdownError(code: str)`, `project_markdown_checkboxes(content: bytes, ordered_plan_ids: tuple[str, ...], projection: dict[str, dict]) -> bytes`.
- Consumes: trusted replay/v1 projection supplied by caller; no filesystem or Harness reads in the pure function.

- [ ] **Step 1: Write RED grammar and byte-preservation tests**

Add named tests including `test_project_markdown_checkboxes_accepts_exact_mapping_grammar` and `test_project_markdown_checkboxes_preserves_non_state_bytes`. Pin exact accepted regex, ordinary prose exclusion, malformed reserved candidates, missing/duplicate/unknown IDs, LF/CRLF, indentation/suffix preservation, uppercase `X` normalization, terminal/nonterminal state mapping, non-UTF-8 rejection, and byte-identical no-op.

- [ ] **Step 2: Run RED tests**

```bash
pytest tests/test_plan_markdown.py -q
```

Expected: tests are collected and fail on import or missing behavior because module does not exist.

- [ ] **Step 3: Implement pure projection**

Use line-preserving byte/UTF-8 processing. A malformed reserved candidate is optional indentation plus `- [`, containing a `P-[0-9]+` token before EOL, while failing the accepted mapping regex. Validate complete one-to-one mapping before creating output bytes.

- [ ] **Step 4: Add counterexample/property tests**

Generate non-mapping prose and suffix text containing Plan IDs. Assert only the one state character changes and every other byte position remains equal. Pin unknown valid `P-*` mappings separately from malformed candidates.

- [ ] **Step 5: Run focused core tests**

```bash
pytest tests/test_plan_markdown.py -q
```

Expected: PASS.

- [ ] **Step 6: Request authorization, then commit Task 1 only**

```bash
git add src/harness/plan_markdown.py tests/test_plan_markdown.py
git commit -m "feat: add restricted plan markdown projection"
```

---

### Task 2: Locked Markdown synchronization command

**Files:**
- Modify: `src/harness/plan_markdown.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Modify: `tests/test_plan_markdown.py`
- Modify: `tests/test_plan_mutation_cli.py`

**Interfaces:**
- Produces: `sync_plan_markdown(harness_dir: Path, repo_root: Path, task: dict, target: str) -> bool`.
- Consumes: `effective_plan_reconciliation`, `load_plan_artifacts`, `assess_plan_reconciliation_documents`, existing `telemetry_lock`, `transaction.atomic_write`, and Task 1 projection.

- [ ] **Step 1: Write RED parser and policy-isolation tests**

Add `test_plan_sync_markdown_parser_accepts_one_explicit_path`. Pin required repository-relative target, rejection of extra arguments, FAST/Q1 and disabled refusal before malformed Plan/Markdown reads, and unchanged behavior for existing Plan subcommands.

- [ ] **Step 2: Run parser RED test**

```bash
pytest tests/test_plan_mutation_cli.py::test_plan_sync_markdown_parser_accepts_one_explicit_path -q
```

Expected: test is collected and fails because parser rejects unknown command.

- [ ] **Step 3: Add CLI and control-plane dispatch**

Add `harness plan sync-markdown <path>`. Map command-domain errors to exit 1 stable code and malformed canonical Harness sources to exit 2 `INVALID_HARNESS_STATE:` with empty stdout. Success prints only updated/unchanged token.

- [ ] **Step 4: Write RED filesystem safety tests**

Pin absolute path, `..`, repository escape, symlink, directory, missing/non-regular target, protected `risk.user_changes.paths`, stale Plan, missing Plan, Q3 v1, replay-invalid v2, and malformed target zero-write behavior.

- [ ] **Step 5: Implement locked synchronization**

Reject ineffective profile before target or Plan reads. Under existing lock, reload Plan and target, snapshot workspace once for assessment, require non-null trusted projection, project complete output, and use `atomic_write` only when bytes differ.

- [ ] **Step 6: Add race/failure tests**

Inject atomic publication failure and run concurrent writers with different valid starting checkbox bytes. Assert no partial/temp output and final bytes equal one complete trusted projection. Assert exact no-op does not call `atomic_write`.

- [ ] **Step 7: Run focused Markdown/CLI regressions**

```bash
pytest tests/test_plan_markdown.py tests/test_plan_mutation_cli.py tests/test_plan_status_cli.py -k 'markdown or parser or status' -q
```

Expected: PASS; default status remains read-only and unchanged.

- [ ] **Step 8: Request authorization, then commit Task 2 only**

```bash
git add src/harness/plan_markdown.py src/harness/cli.py src/harness/controlplane.py tests/test_plan_markdown.py tests/test_plan_mutation_cli.py
git commit -m "feat: add locked markdown plan synchronization"
```

---

### Task 3: Exact automatic proof selection and mechanical surfaces

**Files:**
- Create: `src/harness/plan_automation.py`
- Modify: `src/harness/plan_reconciliation.py`
- Modify: `src/harness/context/dependency_closure.py`
- Modify: `tests/test_plan_automation.py`
- Modify: `tests/test_task_contract.py`
- Modify: `tests/test_context_dependency_closure.py`

**Interfaces:**
- Produces:
  - `PlanAutomationError(code: str)`
  - `ProofAtom(kind: str, value: str)`
  - `EvidenceCandidate(ref: str, coverage: int)`
  - `AutoProofSelection(evidence_refs: tuple[str, ...], surface_refs: tuple[str, ...])`
  - `select_unique_minimum_cover(required_mask: int, candidates: tuple[EvidenceCandidate, ...]) -> tuple[str, ...]`
  - `mechanical_surface_facts(task: dict, plan: dict, *, repo_root: Path | None = None) -> MechanicalSurfaceFacts`
  - `derive_auto_proof(harness_dir: Path, task: dict, plan: dict, item: dict, *, head: str, workspace: str) -> AutoProofSelection`
- Consumes: existing evidence projection, `record_covers_test`, `command_covers_test`, qualified case loading, changed paths, protected fingerprint rules, and audited `source_access` scopes for every evidence directory member and file read.
- Dependency rule: add `plan_automation` to `context.dependency_closure.ALLOWED`, never to `ADAPTERS`. Keep `plan_markdown` and `plan_reporting` outside the quality-gate dependency closure; they remain CLI/control-plane projection modules.

- [ ] **Step 1: Write RED exact-cover tests**

Add named tests including `test_select_unique_minimum_cover_rejects_equal_minimum_tie` and `test_select_unique_minimum_cover_enforces_closed_limits`. Pin sorted candidate order, unique one-file and multi-file covers, omission of redundant evidence, equal-minimum ambiguity, no cover, zero atoms, 16/17 candidates, 16/17 atoms, duplicate coverage, and deterministic repeat output.

- [ ] **Step 2: Run selector RED tests**

```bash
pytest tests/test_plan_automation.py -q
```

Expected: tests are collected and fail on import or missing behavior.

- [ ] **Step 3: Implement bounded exact selector**

Enumerate `itertools.combinations` by cardinality over canonically sorted candidates. At first covering cardinality, retain one result, continue only that cardinality, and reject immediately on a second distinct cover. Never enumerate above 16 candidates.

- [ ] **Step 4: Write RED evidence-index tests**

Pin canonical evidence-directory-only enumeration; fresh successful eligibility; stale/failed/wrong-HEAD/wrong-workspace exclusion; malformed present evidence fail-closed; manual bare-case atoms; automated node and command atoms; and no body output.

- [ ] **Step 5: Implement request-local evidence indexing through source access**

Enumerate canonical evidence members through an audited `source_access` directory scope and read each member through that scope exactly once. Do not use direct `Path.iterdir`, `glob`, `read_text`, or `open` for evidence sources. Build qualified test-case index and integer coverage masks once. Return only sorted refs selected by the exact algorithm.

- [ ] **Step 6: Register trusted dependency closure**

Add `plan_automation` to `ALLOWED`, not `ADAPTERS`. Add a closure test proving `quality_gate -> plan_reconciliation -> plan_automation` is accepted and that evidence reads are recognized as `source_access`-guarded. Add negative tests for direct unguarded evidence directory/file reads. Assert `plan_markdown` and `plan_reporting` are not imported by `quality_gate` or `plan_reconciliation`.

- [ ] **Step 7: Extract shared mechanical surface facts with characterization tests**

Move existing P0 changed/protected calculation behind `mechanical_surface_facts(...)`. Before changing P0 callers, pin unchanged fingerprint filtering, changed aggregate fingerprint, intersecting protected item, docs/tests path eligibility, and existing blocker ordering.

- [ ] **Step 8: Use shared facts in P0 and auto derivation**

P0 output must remain byte/tuple equivalent. Auto selects sorted declared/usable intersection; no path returns `PLAN_PROOF_MISSING`; protected divergence remains visible for existing mutation validation to return `PLAN_PROTECTED_PATHS_MODIFIED`.

- [ ] **Step 9: Run focused proof regressions**

```bash
pytest tests/test_plan_automation.py tests/test_task_contract.py tests/test_plan_mutation.py tests/test_context_dependency_closure.py -q
```

Expected: PASS with unchanged P0 blocker precedence and trusted closure.

- [ ] **Step 10: Request authorization, then commit Task 3 only**

```bash
git add src/harness/plan_automation.py src/harness/plan_reconciliation.py src/harness/context/dependency_closure.py tests/test_plan_automation.py tests/test_task_contract.py tests/test_context_dependency_closure.py
git commit -m "feat: derive bounded automatic plan proof"
```

---

### Task 4: Automatic COMPLETE mutation and CLI integration

**Files:**
- Modify: `src/harness/plan_reconciliation.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Modify: `tests/test_plan_automation.py`
- Modify: `tests/test_plan_mutation.py`
- Modify: `tests/test_plan_mutation_cli.py`

**Interfaces:**
- Extends: `PlanMutationRequest` with `auto: bool = False`; auto is orchestration input only and is never persisted.
- Consumes: Task 3 `derive_auto_proof(...)`; existing locked `mutate_plan_execution(...)`.
- Produces: `harness plan reconcile P-001 --auto` with ordinary canonical `RECONCILE` transition payload.

- [ ] **Step 1: Write RED parser matrix tests**

Add `test_plan_reconcile_auto_parser_accepts_closed_auto_shape`. Pin `--auto` acceptance and mutual exclusion with all disposition, reason, Decision, replacement, evidence, and surface options. Pin begin/block/resume/refresh/upgrade rejection of `--auto`.

- [ ] **Step 2: Run parser RED test**

```bash
pytest tests/test_plan_mutation_cli.py::test_plan_reconcile_auto_parser_accepts_closed_auto_shape -q
```

Expected: test is collected and fails because `--auto` is unknown.

- [ ] **Step 3: Write RED mutation-policy tests**

Pin Q3-only authorization before evidence reads, current active item/order, tests/surfaces/dual branches, semantic-disposition impossibility, stale writer, workspace race, exact retry, and inferred-proof revalidation.

- [ ] **Step 4: Resolve auto proof inside existing lock**

After existing policy check and locked artifact reload/replay, resolve auto proof against the current item and first workspace snapshot. Replace the orchestration request with an explicit COMPLETE request, then execute the unchanged lifecycle/proof/candidate-schema/atomic-write path. Avoid nested locking and alternate publication.

- [ ] **Step 5: Add explicit/auto payload equivalence tests**

For identical derived refs, compare canonical final transition and projection bytes from explicit and automatic requests. `auto` must not appear in YAML, receipts, status, Context, or output.

- [ ] **Step 6: Complete CLI error mapping**

Map `PLAN_AUTO_PROOF_AMBIGUOUS` and `PLAN_AUTO_LIMIT_EXCEEDED` to exit 1 stable stderr codes; malformed evidence remains exit 2 invalid state. Success and exact retry retain existing minimal tokens.

- [ ] **Step 7: Run focused mutation/CLI tests**

```bash
pytest tests/test_plan_automation.py tests/test_plan_mutation.py tests/test_plan_mutation_cli.py tests/test_task_contract.py -k 'auto or mutation or plan' -q
```

Expected: PASS.

- [ ] **Step 8: Request authorization, then commit Task 4 only**

```bash
git add src/harness/plan_reconciliation.py src/harness/cli.py src/harness/controlplane.py tests/test_plan_automation.py tests/test_plan_mutation.py tests/test_plan_mutation_cli.py
git commit -m "feat: add automatic complete reconciliation"
```

---

### Task 5: Body-free verbose Plan status

**Files:**
- Create: `src/harness/plan_reporting.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Modify: `tests/test_plan_reporting.py`
- Modify: `tests/test_plan_status_cli.py`

**Interfaces:**
- Produces:
  - `plan_item_reports(plan: dict | None, assessment: PlanAssessment) -> tuple[dict, ...]`
  - `with_verbose_items(report: dict, plan: dict | None, assessment: PlanAssessment) -> dict`
- Consumes: one already-loaded Plan and `PlanAssessment`; no filesystem or evidence reads.

- [ ] **Step 1: Snapshot default status output**

Add exact byte assertions for current enabled/disabled text and JSON before adding flags. These are compatibility locks, not new expected formatting.

- [ ] **Step 2: Write RED verbose parser/report tests**

Pin `--verbose`, `--json --verbose`, canonical item order, proof branch values, nullable untrusted status, independent final status, and exact closed item keys.

- [ ] **Step 3: Run RED report tests**

```bash
pytest tests/test_plan_reporting.py -q
```

Expected: tests are collected and fail because projection module/behavior is absent.

- [ ] **Step 4: Implement pure item projection**

Map proof health in this exact order: untrusted; nonterminal/SKIPPED/SUPERSEDED/no-branch not applicable; COMPLETE proof missing; COMPLETE disposition/protected invalid; COMPLETE valid. Preserve blocker rows even for not-applicable health.

- [ ] **Step 5: Add body-leak counterexamples**

Seed journal actions/sequences, receipts, evidence output, Decision IDs/body, reasons, and Requirement/Invariant statements with sentinel strings. Assert none appear in text or JSON.

- [ ] **Step 6: Add CLI rendering without changing default path**

Default branch must continue calling existing renderer with existing report shape. Only verbose branch attaches and renders `items`.

- [ ] **Step 7: Run focused report/status regressions**

```bash
pytest tests/test_plan_reporting.py tests/test_plan_status_cli.py tests/test_task_contract.py -q
```

Expected: PASS; default snapshots unchanged.

- [ ] **Step 8: Request authorization, then commit Task 5 only**

```bash
git add src/harness/plan_reporting.py src/harness/cli.py src/harness/controlplane.py tests/test_plan_reporting.py tests/test_plan_status_cli.py
git commit -m "feat: add verbose plan reconciliation status"
```

---

### Task 6: Single-assessment Gate preflight Plan section

**Files:**
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/plan_reporting.py`
- Modify: `src/harness/context/model.py` only if internal typing requires it
- Modify: `tests/test_plan_reporting.py`
- Modify: `tests/test_quality_gate.py`
- Modify: `tests/test_control_plane.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Extends: internal `GateAssessment` by appending `plan_assessment: PlanAssessment | None = None` as the final dataclass field. Default preserves all existing four-positional-argument constructors and serialized Gate artifacts.
- Produces: `gate_plan_preview(task: dict, plan: dict | None, assessment: PlanAssessment) -> tuple[str, ...]` in `plan_reporting`, invoked only from CLI/control-plane preflight rendering.
- Consumes: same PlanAssessment whose `.blockers` are appended to Gate blockers. `quality_gate` must not import `plan_reporting`; `controlplane` passes the carried assessment to the renderer.

- [ ] **Step 1: Write RED single-assessment tests**

Spy on Plan artifact load and assessment calls. Pin exactly one load/assessment per Gate evaluation and object identity between blocker source and renderer input. Assert no call to legacy wrapper in addition to assessment.

- [ ] **Step 2: Write RED output-order and constructor-compatibility tests**

Snapshot current `READY:` and blocked preflight lines. Pin enabled Plan section appended after all existing lines, disabled omission, unavailable progress for untrusted execution, item-sourced blocker rendering, and no duplicate PLAN code. In `tests/test_control_plane.py`, retain and exercise four-positional-argument `GateAssessment(...)` construction.

- [ ] **Step 3: Run RED Gate tests**

```bash
pytest tests/test_plan_reporting.py tests/test_quality_gate.py tests/test_control_plane.py -q
```

Expected: new single-assessment/preview tests are collected and fail before implementation; existing constructor tests still collect.

- [ ] **Step 4: Carry assessment through GateAssessment**

Append `plan_assessment: PlanAssessment | None = None` as the final field. Compute assessment once in the existing effective-enabled branch. Extend blockers from `assessment.blockers`; attach assessment internally. FAST must still return before this branch.

- [ ] **Step 5: Render appended body-free section**

Reuse Plan reporting summary; do not reload artifacts. Preserve exact existing lines and append only after them. Do not render command suggestions as authorization.

- [ ] **Step 6: Add FAST/Q2/Context regressions**

Pin FAST malformed adjacent Plan/evidence no-read, Q2 v1 preview, Q2 auto refusal, Context schema/output unchanged, and Plan blocker order unchanged.

- [ ] **Step 7: Run focused Gate/report/Context tests**

```bash
pytest tests/test_plan_reporting.py tests/test_quality_gate.py tests/test_control_plane.py tests/test_cli.py tests/test_context_builder.py tests/test_context_integrity.py -q
```

Expected: PASS, including existing four-positional-argument constructors and `READY:` output.

- [ ] **Step 8: Request authorization, then commit Task 6 only**

```bash
git add src/harness/quality_gate.py src/harness/controlplane.py src/harness/plan_reporting.py src/harness/context/model.py tests/test_plan_reporting.py tests/test_quality_gate.py tests/test_control_plane.py tests/test_cli.py
git commit -m "feat: append plan status to gate preflight"
```

Stage `context/model.py` only if changed.

---

### Task 7: Benchmarks, packaging, and focused acceptance

**Files:**
- Modify: benchmark fixtures or tests under existing benchmark conventions
- Modify: `tests/test_benchmark_cli.py`
- Modify: `tests/test_schema_resources.py`
- Modify: P2 tests only for confirmed acceptance gaps

**Interfaces:**
- Consumes: Tasks 1-6 public commands and pure seams.
- Produces: deterministic benchmark coverage, package-resource proof, and final impact-only evidence.

- [ ] **Step 1: Add RED benchmark fixtures**

Add `test_plan_reconciliation_p2_benchmark_corpus`. Use existing corpus format to cover omission, stale fingerprint, fake COMPLETE, replay-invalid recovery, equal-minimum proof ambiguity, and trusted Context/status recovery. Fixtures must not claim unseen Agent behavior.

- [ ] **Step 2: Run benchmark RED test**

```bash
pytest tests/test_benchmark_cli.py::test_plan_reconciliation_p2_benchmark_corpus -q
```

Expected: test is collected and fails on fixture validation/report behavior until corpus support is complete.

- [ ] **Step 3: Add minimal benchmark integration**

Reuse existing benchmark result vocabulary. Do not create a P2-only benchmark engine or persistent report artifact.

- [ ] **Step 4: Verify trusted dependency closure and package tests**

Keep Task 3's `plan_automation` allow-list registration. Assert `plan_automation` is reviewed code, not an adapter, and its evidence reads remain guarded by `source_access`. Assert `plan_markdown` and `plan_reporting` remain outside the `quality_gate`/`plan_reconciliation` import closure. Verify installed imports without broad repository scans.

- [ ] **Step 5: Run complete impact-only acceptance set**

List every impacted test file explicitly, including:

```bash
pytest \
  tests/test_plan_markdown.py \
  tests/test_plan_automation.py \
  tests/test_plan_reporting.py \
  tests/test_plan_execution.py \
  tests/test_plan_mutation.py \
  tests/test_plan_mutation_cli.py \
  tests/test_plan_status_cli.py \
  tests/test_task_contract.py \
  tests/test_quality_gate.py \
  tests/test_control_plane.py \
  tests/test_cli.py \
  tests/test_context_builder.py \
  tests/test_context_integrity.py \
  tests/test_context_dependency_closure.py \
  tests/test_benchmark_cli.py \
  tests/test_schema_resources.py \
  -q
```

Do not run unrestricted `pytest`.

- [ ] **Step 6: Build and install wheel in isolated environment**

Build with a temporary environment containing PyPA `build`, install the wheel into a fresh venv, then smoke:

```bash
harness plan sync-markdown --help
harness plan reconcile --help
harness plan status --help
harness gate preflight
```

Use a temporary fixture repository for commands requiring Harness state.

- [ ] **Step 7: Run complexity, diagnosability, interface, and code reviews**

Focus review on parser ambiguity, exact-cover bounds, protected surfaces, auto/mutation seam equivalence, default-output compatibility, single assessment, body isolation, and FAST no-read behavior. Address only confirmed findings with TDD and fresh focused evidence.

- [ ] **Step 8: Reconcile Plan Items and enter Gate legally**

Use P1C commands in canonical item order. Attach item-owned final-workspace evidence, refresh every stale COMPLETE receipt, verify Requirements/Invariants/INT-007, then transition through VERIFYING and REVIEWING. Run `harness gate`; only `DECISION: CONVERGED` permits `CONVERGED -> DONE`.

- [ ] **Step 9: Request authorization, then commit Task 7 artifacts only if tracked**

Do not bump package version, update release README/CHANGELOG, tag, push, or publish in this task. Those remain a separate release task after P2 convergence.

---

## Plan self-review

- Spec coverage: every design section maps to Tasks 0-7; no Markdown import, semantic auto disposition, persistent cache, or new preview command appears.
- Type consistency: Task 3 returns proof facts; Task 4 alone translates them into `PlanMutationRequest`; Task 5/6 consume one `PlanAssessment` and do not load sources.
- Review Focus: all five high-risk input classes have named RED tests in their owning task.
- TDD: every product-code task starts with RED tests and a focused failing command.
- Commit discipline: each commit is separately authorized and stages only named files.
- Verification scope: every command names related files; unrestricted full-suite execution is absent.
- Proportion: interfaces and decisions are pinned; function bodies are left to implementation except exact algorithm order required by the spec.
