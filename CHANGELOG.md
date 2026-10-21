# Changelog

## Unreleased

## 0.3.2

Development candidate; metadata and implementation only. Formal review/Gate acceptance, tag, publication, and deployment remain pending and separately authorized.

### Planned follow-up

- Add manual `harness task prune`: preview is read-only by default, while `--apply --plan-id <digest>` revalidates the exact plan under publication admission before deleting recognized task-history packages. The fixed policy retains the current task plus nine newest distinct historical task IDs and every version of retained IDs; unknown, unsafe, referenced, shared-retained, fixture and user-owned data remain protected.
- The command is not automatic cleanup or a whole-`.harness` size bound. It adds no TTL, scheduler, configurable policy, persistent registry, implicit recovery or atomic rollback promise; partial failures report only actual removals and logical bytes. See [Follow-up B](docs/superpowers/plans/2026-10-14-v032-context-evidence-efficiency.md#follow-up-b-define-harness-inventory-retention-and-controlled-cleanup).
- Follow-up C records a [Gate before commit readiness design](docs/superpowers/plans/2026-10-14-v032-context-evidence-efficiency.md#follow-up-c-gate-before-commit-readiness). It is not implemented: Core behavior, evidence freshness, task state and commit/push authorization remain unchanged.

### Added

- Agent guidance now calls for proactive bounded batching of long-running related verification, immutable receipts per batch, and reuse of only fresh successful coverage. This is instructional guidance using the existing collector, Gate, deadline and budgets—not an automated scheduler, proof of Agent obedience or a measured speedup—and makes no Core behavior change.
- Opt-in Context timing/profile output and ordered batch expansion with bounded full builds/source loads/Gate assessments. A candidate losing eligibility commits its legal prefix and stops; genuine prepublication errors publish no new events. Empty expansion still independently validates.
- Read-only `harness evidence plan --json` and `harness impact reconcile --file proposal.yaml --dry-run`; neither executes tests, initializes missing provenance, nor grants execution authority.
- Task-bound initial test-scope baseline, append-only audit and seal, transactional additions, explicit selected-authority reconstruction, and atomic authorized reconciliation. Gate enforcement and transactional add activate together; apply requires both mechanisms and operation-specific authority. Alignment v3 binds immutable origin; Context projection v5 includes scope sources.
- Inode-preserving v2 publication/recovery outside staging; final independent validation runs before durable commit, not in an unjournaled outer rollback. Admitted Gate/transitions hold shared lock before reading canonical facts and refuse pending recovery without implicit repair.

- Add a shared remediation registry and read-only `harness explain <CODE>`. Known Plan mutation, Gate preflight, implementation-admission and related-evidence failures include operator guidance; related-test coverage errors show a full example rather than requiring another `--help` call.
- Add `harness check admission` to aggregate independent implementation-entry defects and explicit `harness plan sync-fingerprint` for empty execution records only. Execution history cannot be rebound. Printed `Next:` guidance never executes a recovery command.
- Suggest near-match subcommands and unknown long options. Option suggestions are limited to the selected command, exclude ambiguous/low-confidence matches and arguments after `--`, and preserve invalid-usage exit code 2 without automatic correction.

### Fixed

- Admit `harness check minimal` before canonical reads and retain the publication owner through validation and output rendering.
- Validate Test Plan targets against the Harness repository rather than the caller's working directory; a same-named test in another checkout cannot satisfy a missing target.
- Declare publication-recovery, test-scope provenance and profile-publication adapters in the finite Context dependency closure.
- Restore legacy test fixtures to trusted scope/alignment setup without weakening `TEST_SCOPE_AUDIT_INVALID`. Isolated wheel checks remove inherited Python source paths and verify that imports resolve inside the installed environment.

### Development validation

- Implementation commit `520f0c7`: 2,975 tests passed across all 141 test files, with four file-level workers and no test failures, errors or skips. One scope-migration file exceeded its concurrent 600-second limit and passed all 80 cases on an isolated rerun; this is not a single uninterrupted suite run.
- A wheel built from that commit installed as version `0.3.2` in a fresh venv outside the checkout. All 16 CLI acceptance scenarios passed, including scoped suggestions, Plan/evidence/admission guidance, unchanged Harness file contents and rejection before the supplied evidence command executes.
- These checks are development verification, not formal review/Gate acceptance, publication authorization, or completion of the separately pending behavioral/benchmark validation below.

### Compatibility and boundaries

- Source builds require `setuptools>=77.0.3` for PEP 639 SPDX license metadata, correcting the incompatible `>=68` declaration. Apache-2.0 SPDX metadata and Python `>=3.11` runtime requirement remain unchanged; this is a build-time floor, not release approval.
- User-narrowed macOS-only support: native `renameatx_np` exchange/no-replace plus destination capability validation. Linux, Windows and other OS publication backends fail closed with `PUBLICATION_UNSUPPORTED`; no Linux support/matrix or implicit network/FUSE/remote-filesystem guarantee. Symbol presence/probe success is not universal filesystem or power-loss certification.
- Qualified preservation, not content CAS or permanent canonical freshness: unmanaged inodes may relocate to retained recovery storage. All stages, displaced objects, probes and terminal data remain indefinitely; disk growth/`ENOSPC` is accepted. New private directories/files request `0700`/`0600`; displaced objects keep inode/mode. No pruning command, automatic cleanup, standalone-write or task-directory-swap safety upgrade.

- Missing/untrusted legacy scope fails closed with `TEST_SCOPE_AUDIT_INVALID`; current required tests never self-certify historical scope. Explicit MIGRATE reconstructs provenance only, never RETIRE or REBIND. Retire/rebind require exact selected user authority, frozen contract and preserved obligations. Old readers reject `gate.test_scope.minimum_reader: 0.3.2`; do not roll back by deleting legal audit/events/proof.
- Profile writes occur once outside lock. Prepublication failure remains exit 2; postpublication profile-write OSError is exit 3 with `PROFILE_WRITE_FAILED_CONTEXT_PUBLISHED context_published=true`. Context is already published: inspect/validate it instead of retrying blindly. Stdout failure is not classified as profile exit 3.
- Existing `can_reuse_evidence` is unchanged; no cross-HEAD inheritance, persistent parse cache, automatic freeze/resume, risk downgrade, or verified/COMPLETE status from diagnostics. RED/finding commands execute again.
- User-reduced anonymous benchmark: 80 completed samples for N=0/1/10/50, five cold and five steady samples per arm/count. N=100 remaining measurements cancelled by user; no full-matrix acceptance claim. Batch-heavy cold samples improve, but N=0 and steady medians regress. See [actual report](docs/superpowers/reports/v032-context-efficiency.md); no p95 or universal speedup claim. Cache deferred: aggregate parse timings do not establish evidence-specific payoff.
- Skills now diagnose first, preserve exact grants and reuse boundaries, serialize shared resources, persist actual Plan proof promptly and refresh final Context after stable metadata. Independent agent behavioral validation remains pending.

Migration details: [test-scope migration](docs/test-scope-migration.md). Historical release entries below are unchanged.

## 0.3.1

### Fixed

- Add controlled `harness align revise --reason` with revision audit and atomic seal removal; require freeze/check before re-entry.
- Archive and clear prior-task plan artifacts during task replacement/recovery. Classification initializes no plan for Q1, empty v1 execution for Q2, and empty replayable v2 execution for Q3.
- Reject incomplete contracts at `SPECIFYING -> PLANNED`; automated binding diagnostics identify the requirement/invariant and case. Task Contract writes alignment before freeze/check and PLANNED admission.
- Build protected v2 path contributions and aggregate from a single scan using Context-safe Git queries. Publish classification task/plan artifacts and telemetry within one rollback boundary.
- Preserve historical protection for unadopted user paths; reject stale v1 adoption with `USER_CHANGE_BASELINE_STALE` rather than replacing the baseline with current bytes.
- Keep evidence receipts immutable, allocating the next unused numeric suffix on collection or reuse miss. Collector, FAST gate and automated proof share receipt ordering, including all-numeric related identity digests.
- Fold equivalent coverage masks before automated-proof candidate limits while retaining ambiguity checks for distinct minimum covers. Missing-proof diagnostics identify case selectors and preserve surface references during proof refresh.
- Reject invalid covered case IDs before command execution. Align required diagnosability guidance with VERIFYING before REVIEWING, while preserving CLI acceptance of both review states.

### Compatibility and verification

- Only exact successful generic or task GREEN receipts may be reused. RED and finding proofs always rerun. Task phase receipts include `phase` metadata; old GREEN receipts without it are not reused and receive a new immutable receipt.
- Legacy v1 raw-byte fingerprint behavior remains unchanged. v2 path contributions now use Git binary diffs or Git content object IDs. Existing v2 baselines are not automatically rewritten or rebased; snapshots from the earlier digest format may fail protection checks, which remain fail-closed.
- Verification runs only regression and impact-related tests; full-suite execution remains forbidden. Release notes do not publish packages or create Git tags.

## 0.3.0

- Add Architecture Scope Gate P0: operator-authored canonical Architecture YAML, deterministic ownership resolution, bounded models, and stable fingerprints.
- Add typed four-layer Git attribution across committed, staged, worktree, and untracked changes while excluding `.harness` control-plane state.
- Add Alignment seal v2 with explicit Architecture mode, fingerprint, and declared module scope; retain controlled legacy v1 compatibility only for off-mode phase entry.
- Add atomic Architecture publication and scope commands, trusted task-replacement mode preservation, stable repairable blockers, and state-aware preflight guidance.
- Preserve source isolation: FAST/Q1 and mode off do not read Architecture artifacts or schemas and do not execute Architecture resolver or Git collection.
- Add Architecture Context Projection P1 for Q2/Q3 required mode: shared Gate assessment, deterministic declared-plus-one-hop module summaries, body-free `harness architecture summary`, conditional freshness, finite read scope, and projection version 4.
- Keep required-missing Architecture as blocker data, reject malformed present sources and capture races, and preserve read-only restart/validate/explain behavior without adding another Gate or cache authority.
- Add Architecture Evaluation P2: independent Drift Detection and Context Recovery corpora, strict one-treatment comparisons, three-run completeness, exact correctness and declaration-quality metrics, and runtime token/tool-call reporting.
- No measured benchmark improvement is claimed; repository report template remains `PENDING` until accepted external run artifacts are supplied.

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-pi.sh | bash -s -- v0.3.0
```

## 0.2.10

- Add deterministic Plan Reconciliation for STANDARD/Q2 and STRICT/Q3 tasks: canonical Plan artifacts, semantic fingerprints, final proof checks, typed blockers, recovery policy, and Q3 replayable task-level execution without fabricated history.
- Add authoritative Plan Context and read-only status projections. `harness plan status` preserves default output compatibility; `--verbose` adds body-free item status and proof health.
- Add explicit one-way `harness plan sync-markdown`, bounded Q3 `harness plan reconcile P-* --auto`, and a body-free Plan section in existing `harness gate preflight`. Markdown remains non-authoritative; automatic reconciliation creates only ordinary `COMPLETE` requests through the existing locked mutation path.
- Preserve FAST/Q1 no-read isolation and STANDARD/Q2 final-only execution while hardening malformed proof sources, Alignment guards, blocker fingerprints, convergence routing, and FAST Context helper loading.
- Add one-command AGY global installer. It resolves latest stable release by default, accepts an explicit tag, updates Harness-owned skills under `~/.gemini/antigravity-cli/skills/`, and preserves unrelated skills. Project initialization remains explicit through `harness init` in each Git repository.
- Add one-command Pi bootstrap installer. It resolves npm `latest` or accepts an explicit version, validates matching npm/Git artifacts, installs missing Superpowers, reconciles legacy or stale Harness packages, and installs the matching Python CLI in an isolated user environment.
- Archive and clear stale `alignment.yaml` during task replacement/recovery so prior-task Alignment cannot block a replacement task.
- Release this version as Git tag v0.2.10.

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-pi.sh | bash -s -- v0.2.10
```

## 0.2.9

- Add pre-implementation Alignment artifacts, closure checks, frozen contract hashes, and STANDARD/STRICT entry guards. Contract change and declared API, permission, or persistence boundary drift fail closed with auditable diagnostic Findings.
- Add opt-in Alignment Context Layer 0 references, typed impact contract boundaries with legacy generic compatibility, and deterministic persisted-record drift, question, and rework benchmark metrics.
- Alignment control remains deterministic: no LLM semantic judgment, source-text inference, external telemetry claim, tag, publish, or push.

### Install

```bash
pi install git:github.com/yezhwi/superpowers-engineering-harness@v0.2.9
```

## 0.2.8

- Add validated derived Context: compact/full projection, task-bound expansion, source freshness, and fail-closed Integrity checks. Context Evidence records generated context, not agent consumption, and does not become product Gate evidence.
- Add task-bound cumulative host usage reporting with validated token and agent counters. Local telemetry updates preserve reported usage; missing host measurements remain null.
- Extend Benchmark artifacts with usage and multi-run statistics, including `tokens_per_success`, median/P90 token reporting, and agent tool/search/file-read counters. Missing data remains `INCONCLUSIVE`; estimated usage is low-confidence; known correctness or integrity failures override efficiency claims.
- Add controlled source-access, schema-resource, workspace, and telemetry-lock boundaries with regression coverage.
- Resolve `npm run <script> --` Vitest selectors from the package script at the command cwd; unresolvable or non-Vitest scripts fail closed with `TEST_RUNNER_UNRESOLVED`.
- Compare diagnosability/complexity/interface review file scope as a set, and list actual-only vs expected-only paths on `DIAGNOSABILITY_SCOPE_MISMATCH`.
- Split review scope into path `files` and `contract_refs`. `DEC-*` labels are rejected in `review_scope.files`, compared as refs, and migrated out of old artifacts instead of being treated as paths.
- Reject `harness task classify` below the path-required risk in `.harness/risk-boundaries.yaml` without persisting task state; print `RISK_ESCALATION_REQUIRED` and the classify command to rerun.
- Derive `harness status` Build/Unit/Integration summary from the same live evidence projection as the Evidence list, including the selected record path.
- Scope compact Layer 0 to the current task's ACCEPTED decisions. Unreferenced historical decisions are omitted as `different_task_not_referenced` and do not trigger `DECISION_OUTSIDE_SCOPE`; explicit `supersedes`/`superseded_by` cross-task ids stay Layer 2 refs.
- Record optional `execution_environment` on collected evidence for `kubectl exec` (namespace/workload/cwd/container when present). Unparseable kubectl commands store `transport: unknown` without changing result semantics.
- Add `harness task verify-existing` for already-implemented work: records `verification_mode: existing_implementation` from CLASSIFIED/PLANNED with GREEN evidence, without RED, fake findings, or tracker writes. FAST Gate skips RED only with that mode plus a valid persisted verification record.
- Keep `TEST_RUNNER_UNRESOLVED` for unbound test selectors only; `npm run` build/lint evidence is not treated as a missing test runner. Persist `contract_refs` on complexity and interface review evidence so Gate matches typed scope.
- Rebuild a missing decision index from existing members during `harness init`. Context freshness versions `decisions/index.yaml` and member names, not historical bodies, and selected bodies must match index id/task_id/sha256.
- Document that `TEST_RUNNER_UNRESOLVED` applies only when binding covered tests. Context load migrates a missing decision index from existing members.
- Forbid full-suite test execution and authorization. Harness accepts only `related` test evidence, even when user or repository instructions request a full suite.
- Store related test evidence as append-only command/covered-test identity records. Gate unions fresh related coverage, so newly required tests can run independently.
- Run Gate freshness preflight before `VERIFYING → REVIEWING`; stale required evidence blocks review entry. STANDARD/STRICT plans reject missing declared test target files before implementation.

### Install

```bash
pi install git:github.com/yezhwi/superpowers-engineering-harness@v0.2.8
```

## 0.2.7

- Close Decision and Interface Contract correctness gaps: task-scoped Gate participation, explicit cross-task Interface reuse, validated active Decision references, safe supersession acceptance, and canonical Decision/Interface IDs.
- Separate product workspace fingerprint from control-plane fingerprint: requirement/invariant verification, review outcomes, and other `.harness/` metadata writes no longer mark product test/build evidence `EVIDENCE_WORKSPACE_STALE`. Product code, tests, and non-control-plane config changes still stale evidence. Gate still fail-closes on tampered evidence payload, invalid bindings, and invalid control-plane schema, without reporting control-plane self-updates as product-test stale.
- Canonicalize covered tests to repository-root paths. Subproject cwd pytest/Vitest selectors (including `sh -lc 'cd ... && ...'`) bind to test-plan paths such as `backend/tests/foo.py`. Collection still rejects missing files, repo-escaping paths, invalid relative cwd, and selectors the command did not execute (`COVERED_TEST_NOT_EXECUTED`, `COVERED_TEST_PATH_INVALID`). Legacy cwd-relative covered tests remain accepted until the next collection.

- Add explicit task-owned and protected-user scopes, preventing unrelated dirty paths from entering review.
- Add DIAG proposal publication, Finding-aware `resume-review`, unified evidence references, and evidence run/attach modes.
- Add Gate preflight, independent quality/release-readiness results, MR draft-only output, and complexity audit decisions.
- Add persisted Decision Records, Decision CLI, active-decision status summaries, and Gate blockers for unresolved or inconsistent decision state.
- Add external Interface Contracts, public-interface impact classification, Q1 escalation guard, fresh interface verification, and deterministic interface Gate blockers.
- Make `harness gate` sole product Gate authority; disable direct standalone quality-gate evaluation and typedly reject open Findings before `review outcome PASS`.
- Restrict `covered_tests` claims to test evidence, require explicit Finding categories, and reject category-less legacy artifacts with `MIGRATION_REQUIRED`.
- Remove obsolete aggregate `finding.schema.json`; canonical validation uses adversarial, diagnosability, complexity, and interface schemas.

### Install

```bash
pi install git:github.com/yezhwi/superpowers-engineering-harness@v0.2.7
```

## 0.2.6

- Harden diagnosability review control-plane integrity: task-type propagation, centralized fail-closed review readiness, and proposed DIAG Finding linkage validation.
- Stage review evidence and proposed Findings before publish; rollback canonical artifacts on publish failure.
- Add shared complete-lifecycle test fixtures and cross-layer fail-closed regression scenarios.

### User impact

Diagnosability review artifacts now reject Contract mismatches, unsupported `not_applicable` checks, and out-of-scope or unlinked DIAG Findings before canonical persistence. This release does not add a logger SDK, OpenTelemetry, automatic log insertion, or universal source scanning.

### Install

Pin this release from Git:

```bash
pi install git:github.com/yezhwi/superpowers-engineering-harness@v0.2.6
```

## 0.2.5

- Add Production Diagnosability Observability Contract for Q2/Q3 tasks, including applicability, business keys, failure boundaries, and bugfix observability-gap analysis.
- Add scope-bound diagnosability review evidence, DIAG Finding static-compliance lifecycle, and Q2/Q3 Gate enforcement for critical and major diagnosability findings.
- Keep logger frameworks, OpenTelemetry, automatic log insertion, and universal source scanning as explicit non-goals.

### User impact

Production failures in declared Q2/Q3 paths now retain a reviewed diagnostic contract: business keys, failure boundaries, and context needed to distinguish caller, dependency, and local failures. Critical and major DIAG Findings block completion; low-value logging remains advisory.

### Install

Pin this release from Git:

```bash
pi install git:github.com/yezhwi/superpowers-engineering-harness@v0.2.5
```

### Boundaries

This release does not provide a logger SDK, OpenTelemetry integration, APM, automatic log insertion, or universal source scanning. Harness persists and gates diagnostic intent and review proof; agents judge business semantics and logging quality.

## 0.2.4

- Add Test Plan Gate for STANDARD and STRICT `PLANNED → IMPLEMENTING` transitions.
- Add structured `test_plan` strategies, cases, executable bindings, and Test Case-to-Evidence traceability.
- Require fresh Evidence coverage for automated case bindings and typed recovery for missing plans, bindings, and proof.
- Preserve Q1/FAST Light Gate behavior and existing Requirement/Invariant Evidence fields.

## 0.2.3

- Add explicit rule-based Q1/Q2/Q3 task classification with FAST, STANDARD, and STRICT profiles.
- Add FAST Light Gate with task-level RED/GREEN regression proof and protection for user changes present at classification.
- Add independent per-task authorization records for commit, full suite, push, MR, merge, and deploy actions.
- Add same-task Evidence reuse with exact runtime/proof identity.
- Add Soft evidence budgets, local telemetry, and fixture benchmarks with validation/comparison and INCONCLUSIVE evidence handling.
- Add FAST risk-boundary revalidation and required repository verification.
- Keep remote telemetry, external-agent execution, and unrecorded external metric claims unavailable.

## 0.2.2

- Add typed Gate blockers and `harness resume` reason-driven recovery.
- Add structured `harness review outcome` routing for pass, verification gaps, and defects.
- Project current Evidence freshness in read-only `harness status`.
- Calculate complexity review scope from task Git baseline, committed, staged, unstaged, and relevant untracked changes.
- Derive recovery target from typed blocker code; add controlled review reason codes and release version consistency coverage.
- Make `harness gate` sole Gate evaluation and convergence authority; deprecate `harness converge`.

## 0.2.1

- Package runtime modules, schemas, and templates inside installed distributions.
- Add wheel-isolation coverage for execution outside source checkout.
- Add audited `harness task recover` for replacing stale active tasks.
