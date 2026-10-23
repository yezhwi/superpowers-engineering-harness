# v0.3.2 Context and Evidence Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver approved Context/evidence efficiency contract as v0.3.2 without weakening freshness, authorization, or Gate.

**Architecture:** Instrument existing Context operation, plan automatic events against one validated source in memory, and publish one transaction under continuous lock. Read-only evidence planning and audited test-scope reconciliation share one scope assessor used by public Gate; existing evidence reuse remains unchanged. Durable recovery is prerequisite for multi-artifact batch/audit publication, not a second state machine or Gate.

**Tech Stack:** Python >=3.11, existing PyYAML/jsonschema, pytest, Git, existing transaction/source_access/read_scope/telemetry_lock modules; no new runtime dependency.

**Spec:** `docs/2026-10-14-context-evidence-collection-efficiency-spec.md` v0.6, approved by user for implementation.

> **Historical checklist note:** The unchecked Task 1–8 boxes below preserve the design-time implementation plan; they are not a live list of unfinished v0.3.2 features and must not be bulk-marked complete without item-level receipts. See the canonical human-readable [delivery status](../reports/v032-context-efficiency.md#v032-delivery-status) for the qualified historical/current distinction.

## Global Constraints

- EF-INV-01–08 apply to every task; no compression of global must requirements, critical invariants, accepted decisions, open findings or typed blockers.
- `risk/profile/执行权限不随Context扩展改变；Q3不降级；USER_AUTHORITY_REQUIRED/HALT_AND_WAIT仍立即停止`.
- `不删RED、不修改旧evidence payload/HEAD，不把 attach或reuse当重新执行，不自动标verified/COMPLETE`.
- No persistent parsing cache, cross-HEAD evidence inheritance, production access, archived business-code restoration, guessed repository-wide dependency scanning, or timeout-based optimization claim.
- Stable N=0/1/10/50/100: full_context_builds<=2, source_loads<=3, gate_assessments<=3. Counter definitions are function-entry definitions in spec §5.1, including independent final validation.
- Candidate eligibility loss commits legal prefix, stops traversal, and completes generation; genuine errors before batch publication write zero new events. These are distinct compatibility cases.
- Profiling disabled by default. Enabled stdout remains Context only; prepublication output validation failure exits 2 with context_published=false; postpublication profile OSError exits 3 with exact `PROFILE_WRITE_FAILED_CONTEXT_PUBLISHED context_published=true`.
- Exclusive phase sum matches total_ms within <=1ms; total excludes external profile-file output. Progress contains fixed stage names/counts/elapsed only, on stderr.
- Scope Gate enforcement and transactional add-test activate together, after schema/seal/migration/recovery mechanism tests. Apply activates later. Legacy tasks without trustworthy baseline remain blocked, not silently migrated.
- Only affected tests (impact-related means tests affected by changed behavior, not only tests of impact module), never full suite. Record real RED/GREEN and covered_tests through Harness during execution; only Gate CONVERGED then DONE permits completion claim.
- No commit, tag, push, publish, deploy or decision acceptance without explicit authorization for new task. Preserve existing untracked user documents and planning history.

## Review Focus

1. Profile destination replaced by symlink/existing file between precheck and publication: fail without overwrite, Context publication fact remains accurate (Task 1).
2. Candidate disappears mid-prefix while later initial candidate remains eligible: stop now, leave later candidate to next command (Task 3).
3. Process dies between task/log or impact/audit writes: recover consistently without overwriting unmanaged edits (Tasks 2/5).
4. Current impact list is already reduced on legacy task: never bless it as original baseline; require explicit historical reconstruction (Task 5).
5. ACCEPTED decision selects unrelated option or contradicts constraints: no inferred retirement permission, no verified status mutation (Tasks 4/6).

## Execution Startup and Tracking

- [ ] Restore this plan and existing root planning history; append v0.3.2 entries without replacing past content.
- [ ] Use using-git-worktrees at execution time. Existing approved spec/evidence are untracked: preserve original bytes and explicitly make them available to isolated execution; do not accidentally omit them from worktree.
- [ ] Create new Harness task; recommend Q3/STRICT because changes affect authorization, public CLI contracts, concurrent publication and fail-closed Gate. Persist all seven risk dimensions through CLI, not inferred profile defaults.
- [ ] Run compact Context only after classification. Invoke task-contract for requirements/invariants/interface/observability contracts, then minimal-implementation, then executing-plans + test-driven-development. Current TASK-091 is DONE and its grants are not reusable.
- [ ] Record five delivery groups in task plan/impact before verification; record proof and reconcile each Plan Item immediately. Persist accepted implementation decisions through existing decision CLI only after user confirmation.
- [ ] If current Harness Guard requires authority, halt rather than changing frozen contract or auto-accepting decisions.

## File Map

| Module / files | Responsibility |
|---|---|
| New `src/harness/context/telemetry.py` | Invocation-local exclusive timing, entry counters, fixed progress, safe external JSON publication |
| `src/harness/cli.py`, `src/harness/controlplane.py` | Thin CLI parsing/output/error adapters; legacy evidence syntax compatibility |
| `src/harness/context/{store,integrity,source,freshness,escalation}.py`, `src/harness/quality_gate.py` | Real entry instrumentation, stable source seam, automatic batch integration |
| `src/harness/transaction.py`, new `src/harness/transaction_recovery.py` | Recoverable multi-file publication, ownership-limited rollback; journal lifecycle under existing lock |
| New `src/harness/evidence_plan.py` | Read-only declared-path diagnostics and minimum missing fresh coverage; no execution |
| New `src/harness/test_scope.py` | Baseline/audit replay, decision authorization, proposal planning and transactional scope publication |
| `src/harness/{alignment,blockers,task_replacement}.py`, `src/harness/context/read_scope.py` | Existing seal/Guard routing, authoritative scope sources, new-task scope origin |
| `src/harness/schemas/{context-profile,test-scope-baseline,test-scope-audit,test-scope-seal,impact-reconcile}.schema.json` | Explicit versioned payload contracts |
| `src/harness/schemas/decision.schema.json` | Optional structured authority on selected decision options, backward-compatible legacy decisions |
| `tests/test_context_{telemetry,batch}.py`, `tests/test_transaction_recovery.py`, `tests/test_evidence_plan.py`, `tests/test_test_scope.py`, `tests/test_impact_reconcile.py` | New acceptance/regression tests, alongside existing affected tests |
| New `benchmarks/context_efficiency.py`, `docs/superpowers/reports/v032-context-efficiency.md` | Anonymous seeded fixtures/reference comparison, actual measurements and limitations |
| New `docs/test-scope-migration.md`, READMEs, skills, manifests, CHANGELOG | Operator migration/compatibility and verified v0.3.2 release surface |

File names above are implementation choices, not previously approved spec requirements. Keep existing large adapters; avoid unrelated restructuring.

## Implementation Decisions Requiring Plan Approval

1. **Scope payloads:** use version 1 `test-scope-baseline.yaml`, `test-scope-audit.yaml`, `test-scope-seal.yaml`. Baseline has task_id, original sorted unique required_tests, original source hashes, authorization refs and created_at. Audit envelope holds append-only ordered entries: sequence, previous_hash, before/after scope sets and hashes, added/retired paths, decision selections, reason, affected binding hashes, timestamp and entry_hash. Seal records task_id, immutable baseline hash and authorized decision selections; extend existing Guard to validate it, without rewriting legacy alignment seal v1/v2.
2. **Authorization:** legacy decision prose cannot safely grant arbitrary retirement. Add optional `test_scope_authorization` object to decision option schema, with exact `baseline_tests`, `retire_tests`, `replacement_tests` mapping, authorized binding changes and exact source/contract hashes. Only current-task ACCEPTED user-selected option grants listed action. Free-text constraints remain global; unexpressible/conflicting constraints fail closed and need explicit revised decision. No keyword/NLP permission inference. Schema-valid old decisions remain valid but do not implicitly grant retirement.
3. **Migration:** add `harness impact reconcile --file proposal.yaml --migrate-baseline` for explicit authorized reconstruction. Proposal carries original source refs/hashes and historical authorized test set. Existing original lists must be reconstructed from trustworthy preserved task/contract/history, never inferred from reduced current impact. Separate migration audit and seal publication are one transaction. Ordinary apply cannot initialize baseline. New task creation seals the actual initial required_tests and task-origin seal in the same transaction; an empty baseline is permitted only when creation truly has no required_tests. Subsequent add-test publishes scope and audit in the same transaction. Existing tasks lacking origin remain typed-blocked.
4. **Crash recovery:** inspected `transaction.publish` catches Exception and rolls back files, but has no durable recovery journal and can overwrite user edits during rollback. Extend existing publication with durable before/after journal and ownership checks, recover under existing telemetry_lock before canonical reads. Unknown/interleaved edits produce typed invalid-state stop, never automatic destructive cleanup. Do not claim crash safety before process-kill tests pass.
5. **Profile location:** initially support repository-external destinations only, using no-overwrite atomic publication and no-follow path checks. Do not add an internal telemetry exclusion without separate capture tests. Profile flags apply to Context generation, not expand/explain/validate.

These choices complete spec implementation prerequisites; they do not accept runtime task migration or grant operations on TASK-1038001.

---

### Task 1: Opt-in Context telemetry and safe profile output

**Files:** create telemetry/profile schema/test_context_telemetry; modify CLI/controlplane, store/integrity/source/freshness, quality_gate entry instrumentation.

**Interfaces:** `ContextTelemetry.phase(name: str)` context manager; `increment(name: str) -> None`; `finish(outcome: str, context_published: bool) -> dict`; invocation-local activation with no-op default. CLI `cmd_context(..., profile_json: Path | None = None, progress: bool = False) -> int`.

- [ ] Write failing `test_exclusive_phases_and_entry_counters`: deterministic monotonic clock; nested phases pause parent, cumulative sum within 1ms; spies count real build_context/FileContextSource.load/assess_gate entries exactly. Include final validate.
- [ ] Write failing `test_default_context_output_unchanged`, `test_profile_precheck_fails_before_publish`, `test_profile_postpublish_failure_exits_three`, `test_profile_does_not_change_context_or_product_fingerprint`. Assert exact exit/stderr and legal stdout on postpublish error. Disabled profiling performs no destination checks.
- [ ] Write safety tests for existing target, symlink path/ancestor substitution, in-repo destination, permission failure, partial JSON cleanup, sensitive source strings absent, stdout write failure not treated as profile error.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_context_telemetry.py -q`; record expected RED behavior gaps, not import/setup failures.
- [ ] Implement fixed phase/counter allowlist and exclusive monotonic accumulation; timing includes command rendering/printing and lock release, excludes external JSON write. Atomic external JSON publication must never overwrite competing destination; ordinary `Path.replace` alone is insufficient. Context render/print precedes independent profile-output try/except.
- [ ] Implement SIGTERM flag-only handler and restore previous handler. At the lock-free completion boundary write exactly one profile: if cancellation flag is set, finish emits CANCELLED with actual context_published, never a second SUCCESS. Strong kill may leave no profile. Add subprocess cancellation tests before and after publication. stdout printing failure is not exit 3; when Context was published, stderr still includes context_published=true.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_context_telemetry.py tests/test_context_cli.py -q`. Verify default behavior and separate exit 3 branch. Checkpoint commit only if authorized.

### Task 2: Recoverable publication required by batches and scope audit

**Files:** transaction/recovery modules; tests/test_transaction.py, tests/test_transaction_recovery.py; store/escalation recovery entry.

**Interfaces:** `recover_pending_publications(harness_dir: Path) -> None`, called under telemetry_lock; existing `stage/publish` signatures preserved, optional durable mode for Context batch/scope operations. Journal records operation identity, target paths, before/after hashes and recoverable bytes, phase and committed marker; validates containment before use.

- [ ] Write failing `test_recovery_after_kill_between_members`: subprocess publishes task/log, kill at deterministic hook, fresh process recovers both old or both committed new bytes; budget equals log count. Parameterize impact/audit/seal and derived Context bundle.
- [ ] Write failing `test_rollback_preserves_user_edit`, `test_interrupt_restores_owned_members`, `test_recovery_rejects_symlink_and_invalid_journal`, `test_committed_recovery_idempotent`. Never remove user-written bytes or unknown staged operations.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_transaction_recovery.py -q`; capture RED.
- [ ] Store durable recovery journal outside `.staging`, at `.harness/.transactions/`, untouched by cleanup_stale_staging. Test cleanup followed by restart recovery; unknown/interleaved writes halt without destructive cleanup. Add durable journal with ordered flush/commit publication and ownership-limited recovery. Handle BaseException without declaring success; restart resolves uncommitted operation before canonical source load. Reuse existing transaction module, no alternative publication engine.
- [ ] Exclude recoverable staging/journal mechanics from authoritative product facts while retaining blocking recovery failures. Test source_access/capture directory rules; no blanket telemetry exclusion for scope audit.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_transaction.py tests/test_transaction_recovery.py tests/test_context_integrity.py -q`. Checkpoint only with authorization.

### Task 3: One-snapshot automatic expansion planning and publication

**Files:** escalation/integrity/store; tests/test_context_batch.py plus automatic/expansion/freshness/read_scope regressions.

**Interfaces:** private `plan_automatic_expansions(validated_source: AuthoritativeContext, current_context: dict) -> ExpansionBatch`; `publish_expansion_batch(harness_dir: Path, batch: ExpansionBatch, expected_sources: dict) -> dict`. Batch fields: task_id, original versions, original log tail digest, ordered events, budget_delta, final_policy. `_make_expansion_event(task: dict, context: dict, trigger: str, reason: str, automatic: dict | None) -> dict` shared with manual `_record_expansion`.

- [ ] Write parameterized failing `test_batch_entry_bounds` for N=0/1/10/50/100: build<=2/load<=3/Gate<=3, final independent validation included. Use real function-entry spies and valid anonymous fixtures.
- [ ] Write reference parity tests: full control/working/omitted/references/policy/events/budget/blockers equal except documented timestamps/hash/telemetry. Assert automatic source_hash override, risk history from/to, EXPANDED self-loop, manual expansion unchanged.
- [ ] Write `test_candidate_loss_commits_prefix_and_stops`: initial A/B/C, A makes B disappear but C remains eligible; first command succeeds with only A, later command handles C, no duplicate A. Assert no new candidate outside initial list. Reference first exit differs intentionally.
- [ ] Explicit EF-T05 tests: other-task historical decisions never enter current Control Core or trigger expansion; same-task historical RED is retained. Write dedup/basis-change/history tests and fault tests for pre/post publication edits, metadata unreadability, directory-member drift and symlink substitution; genuine prepublication errors leave zero new events.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_context_batch.py -q`; record RED.
- [ ] Extract private stable-load/projection seam from build_context without adding extra public entry counts. Retain validated AuthoritativeContext for planner; derive simulated state with original active_expansions/effective_policy/selector. Recheck candidate dict membership using automatic_candidates exactly, never an approximate predicate.
- [ ] Take initial candidate list once, validate all accepted prefix payloads in memory, then publish task/log in one durable transaction with pre/post capture checks. Continuous outer telemetry_lock covers first read through final validate/bundle publication. After nonempty batch, rebuild once with new canonical facts; empty batch writes no events and keeps initial build, but independent validate_context still runs.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_context_batch.py tests/test_context_automatic.py tests/test_context_expansion.py tests/test_context_freshness_property.py tests/test_context_read_scope.py -q`. Confirm final failure may retain legal batch but never claim fresh old Context. Checkpoint only if authorized.

### Task 4: Read-only evidence plan and reconcile dry-run

**Files:** evidence_plan/test_scope proposal loader; CLI/controlplane; proposal schema; tests/test_evidence_plan.py, tests/test_impact_reconcile.py.

**Interfaces:** `plan_evidence(harness_dir: Path) -> dict`; `plan_reconciliation(harness_dir: Path, proposal: dict) -> dict`. CLI `harness evidence plan --json`, `harness impact reconcile --file proposal.yaml --dry-run`. Existing run/attach/legacy evidence argument handling remains supported.

- [ ] Write failing fixture with 64 declared paths/18 missing targets; assert all 18 classified MISSING_DECLARED_TEST with REQ/INV/case/plan refs and external command count=0. Fixture only, no real TASK-1038001 modification.
- [ ] Add selector-resolution, UNBOUND_TEST_CASE, PLAN_ITEM_UNRECONCILED, HEAD mismatch/workspace stale, minimum NO_FRESH_COVERAGE and environment constraints tests. Coverage union uses existing validated fresh evidence semantics, never historical exit0 alone.
- [ ] Assert tree byte hashes unchanged by both read-only commands, including missing metadata case; source/schema errors fail closed. Do not call existing mutating impact scope initialization or decision-index migration from diagnostic path.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_evidence_plan.py tests/test_impact_reconcile.py -q`; record RED.
- [ ] Implement declared-path-only diagnostics using existing evidence/path binding and plan predicates; no external pytest collection/subprocess, no repo-wide scan. Surface authority/environment issues separately without test-pass claims.
- [ ] Add new evidence plan parsing before current argv normalization so plan is not treated as deprecated evidence run. Keep dry-run proposal validation reusable by future apply, but disable apply until Task 5 passes.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_evidence_plan.py tests/test_impact_reconcile.py tests/test_cli_evidence_reuse.py tests/test_impact_control_plane.py -q`. Checkpoint only if authorized.

### Task 5: Trusted test-scope origin, migration and Gate/add-test joint activation

**Files:** test_scope module, five scope/proposal schemas and decision schema; alignment/blockers/task_replacement/quality_gate/controlplane; Context source/freshness/read_scope; test_test_scope/impact authorization/verification/transaction recovery tests; migration doc.

**Interfaces:** `assess_test_scope_retirements(harness_dir: Path) -> list[GateBlocker]`; `add_required_test(harness_dir: Path, test: str) -> None`; `migrate_test_scope(harness_dir: Path, proposal: dict) -> dict`. Every call validates task identity, source bytes, seal, full audit replay and actual decision selections. Public Gate calls assessor for all profiles, including preflight.

- [ ] Write failing unaudited-shrink tests across direct Gate, generated Context Control Core and stage transition. Assert TEST_SCOPE_RETIREMENT_UNAUDITED; missing/damaged/rewritten audit or baseline gives TEST_SCOPE_AUDIT_INVALID; insufficient selected authority gives TEST_SCOPE_RETIREMENT_UNAUTHORIZED.
- [ ] Write failing add-then-hand-delete test: formal add records audit in same transaction; deletion cannot disappear through compatibility treatment. Test duplicate add idempotence and all historical increases retained.
- [ ] Write legacy migration tests: missing origin blocks, reduced current list cannot self-initialize, historical original 64-path source required, prefeature unchained additions remain distinguishable until authorized migration. Valid old seal v1/v2 loads but does not create trusted scope automatically.
- [ ] Write new-task origin and migration seal tests for FAST/STANDARD/STRICT; Guard detects baseline/selected decision changes. Explicit original-set approval is necessary; general add permission cannot retire.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_test_scope.py -q`; capture RED.
- [ ] Implement versioned schemas from approved plan choices and exact optional option-level authority. Replay validates sequence, previous hash, before/after sets, decision state/selection/constraints, affected bindings and must obligations. Purely synthesized hash chains are not claimed to defend against full-disk rewrite.
- [ ] Add baseline/audit/seal to authoritative capture and allowed read scopes; schema changes invalidate snapshots. Add blockers to existing recovery/authority routing so agent cannot autonomously approve missing authority.
- [ ] Implement authorized reconstruction CLI and new-task origin publication under existing Guard/lock, with source CAS. Failure restores only operation-owned bytes. Never auto-freeze/resume or migrate real legacy tasks as side effect of enabling feature.
- [ ] Wire common Gate assessor and transactional add-test together in this task, never as separately enabled commits. Before enabling, finish migration/recovery/old-reader compatibility tests and document minimum supported reader (v0.3.2).
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_test_scope.py tests/test_impact_control_plane.py tests/test_impact_authorization.py tests/test_impact_verification_gate.py tests/test_context_read_scope.py tests/test_transaction_recovery.py -q`. Update only impacted fixtures with explicit trusted origin, never disable Gate to restore GREEN. Checkpoint only if authorized.

### Task 6: Authorized transactional reconcile apply

**Files:** test_scope module; CLI/controlplane; tests/test_impact_reconcile.py; migration doc.

**Interfaces:** `apply_reconciliation(harness_dir: Path, proposal: dict) -> dict`. Input matches spec version/task_id/expected_impact_hash/retirements/bindings; output reports updated hashes, audit refs and Context regeneration required, never proof/verified status.

- [ ] Write failing rejection tests for unrelated selected option, only DEC ID, absent replacement, must case emptied, unknown owner/case, out-of-root selector, stale impact CAS, changed plan refs, conflicting constraints and sealed boundary drift.
- [ ] Write valid replacement/rebinding test: updates impact and all affected existing case/plan mappings in one durable transaction; preserves statement/priority/severity/status/evidence/findings/RED payloads. Appends audit with before/after hash, paths, decisions, reason and timestamp.
- [ ] Assert dry-run byte identity and zero execution; inject publish/edit/kill failures to test no unauthorized partial apply. Contract retirement stays on existing realignment path, not impact editor.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_impact_reconcile.py -q`; record RED.
- [ ] Enable apply only after Task 5 joint activation/permission tests pass. Share validation with dry-run and Gate, check all involved sources before and after one transaction. Source changes make Context stale without changing product evidence unnecessarily.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_impact_reconcile.py tests/test_test_scope.py tests/test_cli_alignment.py tests/test_evidence_freshness_and_path_binding.py -q`. Checkpoint only if authorized.

### Task 7: Repeatable benchmark and existing reuse regression

**Files:** benchmark generator/reference runner/report; test_context_batch; test_cli_evidence_reuse; skills/engineering-harness, collect-evidence, task-contract.

**Interfaces:** benchmark emits raw per-run samples and median/min/max, seed/environment/source identity, counters and semantic diff results. Reference uses preserved prechange algorithm from checkout c74ac4d4477469fdbeda80a2b470094d3134375f, isolated from new code; not a second production implementation.

- [ ] Extend reuse regressions to exact can_reuse_evidence predicate: default/GREEN valid reuse; HEAD/command/scope/both coverage/workspace/runtime/schema/subject/test mismatches rejected; RED/finding executes original command; current task directory isolation. Do not rewrite predicate or invent task_id record field.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_cli_evidence_reuse.py tests/test_evidence_freshness_and_path_binding.py -q`; expect existing valid behavior, not fabricated RED for already shipped reuse.
- [ ] Generate fresh identical cold fixtures for N=0/1/10/50/100, five runs per reference/new arm; separately five unchanged-source steady generation/validate runs. Record Python/OS/deps/HEAD/workspace/schema/CPU/artifact counts/policy/candidates. No user secrets or business environments.
- [ ] Run `PYTHONPATH=src python benchmarks/context_efficiency.py --seed 1038001 --repetitions 5 --output <outside-repository-report.json>` after runner exists. Reject failed/timeout runs as success samples; compare semantic facts as well as timings.
- [ ] Publish actual counters/times and approved compatibility exceptions in report; no p95 or 50%/10% pass criterion. Treat new legacy-scope blockers as deliberate tightening, not batch semantic regression.
- [ ] Profile decides §8.1 cache: if schema/YAML validation is not demonstrably significant, record cache deferred. If significant, stop for supplemental plan with full content/schema/projection/task/HEAD/workspace/member dependency keys and standalone validate independence; no speculative cache in this plan.
- [ ] Update skills to diagnose/reconcile first, generate final Context once metadata stable, save plan proof promptly, use existing reuse flag, keep related tests and mutually exclusive shared resources serial. Do not document unimplemented commands as shipped.

### Task 8: v0.3.2 packaging, final related verification and Gate

**Files:** pyproject.toml/package.json, README.md/README.zh-CN.md, CHANGELOG.md, tests/test_version_consistency.py/test_package_resources.py/test_npm_package.py, release report.

- [ ] Add failing version/resource assertions for 0.3.2 and new packaged schemas/docs; keep historical release entries unchanged. Run `PYTHONPATH=src python -m pytest tests/test_version_consistency.py tests/test_package_resources.py tests/test_npm_package.py -q` for RED before version bump.
- [ ] Set current versions to 0.3.2, document profile exit 3, prefix-success change, legacy task blocking, explicit migration, audited add/apply sequencing and no cross-HEAD proof reuse. Add new migration/spec docs to npm package file list if referenced by packaged skills; synchronize schema mirrors only according to existing package layout.
- [ ] Record impacted files/dependents/contracts/risks/required tests through Harness CLI, then transition VERIFYING. Run each affected test group from Tasks 1–7 as related evidence with root-relative covered_tests; run only newly required coverage when fresh evidence already exists.
- [ ] Run `python -m build` if available (otherwise record exact existing supported build command, no fabricated success), package/resource targeted tests, and `git diff --check`. Build proof must be Harness-recorded and fresh after final product edits.
- [ ] Invoke complexity-reviewer, diagnosability-review and requesting-code-review. No subagent tool available in current session: execute native checks but explicitly report missing independent review; do not claim self-review is independent. Persist actual review evidence/outcome, handle findings with reproduce-finding/safe-fix/TDD and related regressions.
- [ ] Refresh compact Context after control changes, run Gate freshness preflight, then legal review/GATING route. Only `DECISION: CONVERGED`, followed by `harness transition DONE`, permits completion report. USER_AUTHORITY_REQUIRED/HALT_AND_WAIT stops; no autonomous decision acceptance or full-suite fallback.
- [ ] Deliver source diff, related-test/build evidence, migration compatibility note and truthful benchmark report. Release tag/publication remain separate authorized operations.

## Acceptance Mapping / Plan Self-Review

| Spec tests | Owning tasks |
|---|---|
| EF-T01/02/03/04 | Task 3 + Task 7 reference/counters |
| EF-T05 | Task 3 historical decision/RED regression |
| EF-T06/07 | Task 2 recovery + Task 3 freshness/concurrency |
| EF-T08 | Task 1 timing/output/cancellation/security |
| EF-T09 | Task 4 declared missing-path fixture |
| EF-T10 | Task 6 authority/replacement/must obligation |
| EF-T11 | Tasks 4–6 Gate/add/audit/migration/apply joint safety |
| EF-T12 | Tasks 1/6/7 telemetry/control vs product freshness |
| EF-T13 | Task 7 existing exact reuse predicate |
| EF-T14 | Tasks 3/5/7 control parity and explicit tightening |

Self-review: all approved unconditional sections mapped; parse cache intentionally conditional; global constraints copied from contract; reference parity separates approved exit/failure-atomicity/scope-blocker changes. Durable transaction recovery, structured authority and trusted migration are explicit implementation decisions pending plan approval, not assertions about existing capability.

## Handoff

User approved native execution against spec v0.6, with review clarifications incorporated above. Proceed sequentially with task-local RED/GREEN and explicit external review gap. Approval covers implementation, not commit/push, production migration or release publication.

## v0.3.2 Proposed follow-up: evidence batching and artifact lifecycle

**Status: A GUIDANCE IMPLEMENTED / B MANUAL IMPLEMENTED AND HISTORICALLY ACCEPTED / C IMPLEMENTED AND HISTORICALLY ACCEPTED.** Follow-up A is a static/instructional change, not an automatic Core capability. Follow-up B is the bounded manual fixed-policy feature described below; its historical acceptance does not authorize real cleanup. Follow-up C was delivered by TASK-103 (`6f453d9`); its opt-in candidate domain does not weaken default Gate behavior, generic evidence freshness, task states or separate commit/push authorization.

### Follow-up A: Plan bounded related-test batches before execution

**Status: GUIDANCE IMPLEMENTED.** The completed entries below describe static Agent guidance, not runtime automation.

**Problem:** A combined related-test command reached the collector's fixed 1,800-second limit with exit 124. Partial output without reported test failures was not successful proof. Subsequent disjoint serial batches completed and the existing Gate unioned their fresh coverage. Waiting for the first timeout was avoidable execution-planning waste, not evidence that the collector deadline or Gate must be relaxed.

**Guidance scope:**

- [x] Guidance plans batches before launching a large or historically slow related scope and reuses the existing evidence collector and coverage-union behavior.
- [x] Guidance permits qualified historical duration information when available, preserving source/environment identity and uncertainty; without it, use conservative bounded groups rather than an unbounded trial run.
- [x] Guidance plans only missing fresh coverage and maps original repository-root targets/selectors to batches while preserving selector semantics and checking the final union for omissions.
- [x] Guidance runs batches serially by default, requires demonstrated isolation before parallel work, and retains each completed batch's immutable receipt and actual JUnit/output independently.
- [x] Guidance validates HEAD, workspace, runtime and command/coverage qualification for every batch, stops on drift, and reuses completed fresh coverage through existing rules.
- [x] Guidance checks execution budgets before starting and preserves failed, timed-out or cancelled batches as non-success records requiring diagnosis.
- [x] Guidance verifies exact required coverage, avoids repeating completed fresh batches, and forbids false-green unions, full-suite fallback, skipped obligations, cross-HEAD inheritance and automatic deadline extension.
- [ ] Automated scheduling/grouping and automatic manifest generation remain deferred pending separate design and verification.
- [ ] Runtime duration telemetry and any automatic duration policy remain deferred; no runtime collection or fixed timing guarantee is implemented.

**Delivery boundary:** Only guidance is implemented. This is not an automated scheduler, proof of Agent obedience, runtime duration telemetry, automatic manifest generation or performance proof. The existing collector, Gate, deadline and execution budgets are unchanged. A genuinely slow single target needs its own diagnosis, not silent omission; retain the original timeout receipt and never turn partial execution into a successful batch.

Historical TASK-095 acceptance covered 45 related tests: existing fixture-backed Guard/CLI tests plus new static guidance assertions, with an independent CLEAN review and packaged bytes matching the 3 guidance source files. Those results are historical and not fresh proof of this document candidate; they do not establish that all 45 checks were pure static assertions, Agent obedience, automatic scheduling, runtime duration behavior or speedup.

### Follow-up B: Define `.harness` inventory, retention and controlled cleanup

**Status: MANUAL IMPLEMENTED AND HISTORICALLY ACCEPTED.** TASK-099 accepted the user-approved current-plus-nine task-history policy and exact-plan manual interface at parent `999bfb94bef1cbe32067a5488c1203f843d9085f`; the accepted bytes were then committed exactly as `3b4fa2853b1990990df847d80461e7a5c454a175`. Its 362 related tests across four files, ten private package-acceptance scenarios, independent CLEAN/formal reviews and original Gate convergence are historical parent/candidate evidence, not a Gate or 362-test run on `3b4fa28`.

**Problem:** Evidence, task history, acceptance artifacts, build/install workspaces and retained publication objects accumulate. Growth needs lifecycle management, but evidence freshness is not a deletion policy. File count alone does not prove Context/Gate slowdown; measure category sizes, counts and relevant traversal costs before claiming a performance fix.

**Implemented candidate scope:**

- [x] `harness task prune` produces a deterministic read-only preview; execution requires `--apply --plan-id <digest>` and recomputes the plan under the existing publication lock and read-only pending-publication admission.
- [x] The fixed rule retains the current task ID plus the nine newest distinct trusted historical IDs by canonical UTC creation time and retains every archive version of those IDs. At most ten distinct IDs is a no-op.
- [x] Candidate admission is limited to recognizable direct-child whole archive packages with the actual task-new/recover member shape and scope artifacts. Unknown, malformed, ambiguous, symlinked, hard-linked, cross-device or unreadable groups are skipped whole.
- [x] Bounded structured scalar scanning covers actual canonical YAML/JSON in current and retained roots, including provenance references. Qualified normalized history paths protect live candidates; ambiguous potential candidate paths fail closed without repository-wide or candidate-graph scanning.
- [x] Apply revalidates plan facts and member identity using directory-relative no-follow operations, stops on the first unlink/rmdir failure, and reports actual removed entries and logical bytes without promising rollback or physical reclamation.
- [x] Anonymous related tests cover preview/apply authorization, fixed retention, all-version protection, unsafe-package skips, references, ambiguity, pending publication, partial failure and sanitized structured output. Historical package acceptance covered ten private scenarios.

**Delivery boundary:** This is a manual task-history mechanism, not authorization to clean this repository. No real root cleanup was performed. Shared retained publication objects, fixtures, probes, current/live facts, referenced history and user-owned files remain protected; unknown ownership is skipped. The feature adds no automatic or age-based pruning, configurable retention, persistent ownership registry, reachability graph, scheduler or whole-tree size guarantee. Release and any real cleanup remain separately authorized.

### Follow-up C: Gate before commit readiness

**Status: IMPLEMENTED AND HISTORICALLY ACCEPTED.** TASK-103 delivered DEC-043 / INT-010 in commit `6f453d9`. This is no longer a pending proposal. See the [operator guide](../../candidate-commit.md), [implementation design](../specs/2026-10-21-gate-before-commit-design.md) and [qualified delivery status](../reports/v032-context-efficiency.md#v032-delivery-status).

The opt-in workflow binds an immutable candidate, actual proof/runtime inputs and original Gate acceptance to a separately authorized local commit with expected-old ref CAS and explicit recovery. It does not introduce generic cross-HEAD evidence reuse, rewrite old receipt HEADs, auto-complete obligations or grant commit/push permission. Unsupported inputs refuse; architecture-required candidate mode remains unsupported. Release qualification and broader support require separate approval.

### Execution workflow corrections

**Status: REPOSITORY GUIDANCE UPDATED; LIGHTWEIGHT VERIFICATION ONLY.** The user approved direct skill/test/documentation work without creating a new Harness task after native task creation refused a pre-existing FIFO probe. TASK-103 remains its own historical DONE task; this correction claims no new Gate/DONE, independent review, installed-skill update or release qualification.

- Keep one implementation executor across checker repairs, wording edits and diagnosed retries; skill invocation is not agent/process delegation. Preserve explicitly selected per-task review or parallel execution rather than silently overriding it.
- Separate setup/checker failures, genuine product RED and authority/policy refusals. Retain invalid attempts, repair diagnosed oracles in the same executor, and establish a valid identified RED/GREEN pair. Existing budgets and user-authority stops remain binding.
- Decide changed paths, related selectors, required build/review/Gate work and stop conditions before execution. Surface workflow conflicts before expanding scope; do not manufacture RED or bypass native policy.
- Validate documentation facts/sequence by human review and interfaces, links and history mechanically. Ordinary prose variants must not force wording changes for a brittle oracle.
- Consolidate required closeout after content stabilizes; retain original logs and one concise record. Static regression/package checks do not prove model compliance or speedup. Core, state machine, Gate, authorization, collector and freshness remain unchanged.

### Follow-up sequencing and acceptance

1. Keep the implemented batching guidance within its instructional boundary; automation requires a separate design and approval.
2. For any future cleanup beyond the delivered fixed-policy manual mechanism, design and verify only separately approved scope; no broad storage subsystem or persistent scheduling cache is implied.
3. Record new related verification, package/build impact and review obligations for future candidates. Documentation and historical tests are not proof of new runtime behavior, and this sequencing is not a retroactive TASK-099 obligation.
4. Require fresh candidate acceptance through the then-applicable preflight/review/Gate path before describing broader storage cleanup or batching automation as delivered. Push, tag and publication authorization remain separate.
