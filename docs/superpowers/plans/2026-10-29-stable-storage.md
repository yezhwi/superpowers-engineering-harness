# Stable Harness Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline implementation task-by-task. Fresh independent review follows final integrated verification. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved stable-store design: stop future history-copy/nesting growth, provide inode-preserving migration mechanisms and read-only reclamation candidates, without activating or cleaning this repository's real data.

**Architecture:** Keep `.harness/` as current-task entry and use explicitly owned `.harness-store/` for stable archives and retained roots. One storage module hides layout, origin-qualified references and coordination; existing single-root regular-file publication remains unchanged in meaning. Activation and directory turnover have explicit recoverable coordination, never implicit startup repair.

**Tech Stack:** Python >=3.11, current PyYAML/jsonschema/pytest, Git and existing native macOS publication primitives; no new dependencies.

**Spec:** `/tmp/harness-storage-diagnosis/lifecycle-design.md` v0.2, SHA256 `853805d5ad0858cbfff12973fe669013399b6fd07ba515f00876c8b01e49945a`. §15 overrides ambiguities in earlier sections. User approved complete design including operational/legacy-path/prune limitations. No real activation/migration/deletion authorized.

## Global Constraints

- macOS本地受支持同设备文件系统；每个Git工作区独立store，不绑定Git common-dir，不跨worktree共享。
- 目录0700、新文件0600；已有对象mode不擅改。路径操作descriptor-relative/no-follow/no-replace，禁止跨设备copy+delete替代。
- 旧树内实验.harness是普通历史输入，不自动recover。
- 不以mtime、DONE、lsof无匹配或内容hash相同单独批准删除。
- 迁移不是回收：move不会凭空释放空间。
- D1–D4不包含store-backed destructive prune、retained/runtime GC apply、真实4.2GiB迁移、注册表发布或新依赖。
- Maintain old reader/writer qualification exactly: old Gate rejection is testable; arbitrary old writer isolation is NOT promised. Activation/migration need separately selected operation-specific user Decision and participant-maintenance attestation.
- Keep current decision/interface policy inheritance; do not silently narrow global constraints or change Gate/risk/test proof requirements.
- Existing user documents/plans and TASK-116 acceptance remain untouched. No commits/push/tag/release without separate explicit authority. Prior main preference is retained for handoff; confirm branch/head at execution entry, do not create/switch worktree implicitly.
- Only related verification, serial batches with exact selectors and qualified real evidence. Stale/failed/cancelled receipts stay historical. No cross-HEAD reuse.

## Review Focus

1. Bootstrap dies before store/header/binding exists: reject unknown objects without stranding admission or claiming user data; tests Tasks1/2/4.
2. Alias same bytes but replaced inode, or identical name in another generation: never substitute a different archive; unrelated index append must not invalidate all Context; tests Tasks3/6.
3. Candidate root installed but archive index not committed, or commit durable but receipt retirement fails: preserve correct authoritative generation and reserve observed IDs; tests Tasks2/5.
4. Pending coordination while `.harness` is absent, including init/status/evidence and custom harness-dir entries: no eager facts/init/recovery; tests Tasks1/4/5.
5. Migration/prune plan or Decision from legacy layout, another workspace, wrong selected option or operation cannot authorize new objects; tests Tasks4/6/7.

## Execution Entry and Durable Records

This document is a plan, not a command authorization for the current runtime. Execution starts only after user reviews the plan. Do not turn plan approval into maintenance/activation/deletion authority.

- [ ] Recheck HEAD and workspace; original baseline is dc4cd9d. If another session changed source, review that change before selecting an implementation baseline.
- [ ] Establish a new classified Harness implementation task with native CLI, not reuse DONE TASK-116. Capability involves recovery/concurrency and persistent identity: Q3/STRICT contract, native scope/Plan/decisions and non-sentinel Observability Contract. Bootstrap constraints or unrelated active task require user decision, never state edits.
- [ ] Copy approved design plus final plan into new `docs/superpowers/specs/2026-10-29-stable-storage-design.md` and `docs/superpowers/plans/2026-10-29-stable-storage.md` only after task/ownership admission; no overwrite of existing user files. Preserve approval text and substantive design bytes. This plan's /tmp paths then resolve to canonical doc copies.
- [ ] Use one ignored executor ledger under `.superpowers/sdd/2026-10-29-stable-storage/`; record changed paths, exact regression batches, formal build/review/Gate obligations and stop conditions before implementation. No additional root task_plan/findings/progress overwrite.
- [ ] No real `.harness-store/` at repository root; all bound-layout/activation/apply/new-task experiments run in temporary Git fixture repositories. Normal Harness development-task changes remain separate from forbidden real store activation/migration/deletion.

## File Map and Shared Types

Create package `src/harness/storage/` with `__init__.py` (small public Interface), `layout.py` (classification/identity/secure traversal), `journal.py` (directory coordination), `archive.py` (index/origin resolution), `migration.py` (plans/grants/activation), `experiments.py` (classification/dry-run). Keep command rendering in `cli.py`/`controlplane.py`; no second generic task engine or caching layer.

Create schemas:
- `storage-layout.schema.json`: discriminated owned header/binding and capability identities.
- `storage-history.schema.json`: archive descriptor, origin-qualified index and append-only ID reservations.
- `storage-operation.schema.json`: activation/turnover/M1/M2 plan, coordinator/frame, selected grant and terminal receipt variants.
- `storage-experiment.schema.json`: explicit inputs/results/runtime/opaque manifests and dry-run result.

Private types are frozen dataclasses; stored documents are schema-validated JSON/YAML dictionaries. Identity always device+inode with role/path; object descriptors also pin required bytes/digests, not content ownership by hash alone.

Public Interface (only export these functions and their result/error types):
- `inspect_layout(repo_root: Path) -> LayoutInspection` — `.mode` is `legacy|bound|blocked`, `.code` optional stable error, `.identity` validated header/binding identity or None; no writes/probes.
- `admit_storage(harness_root: Path) -> ContextManager[StorageSession]` — same canonical `.harness` telemetry owner; refuses current ordinary/coordination pending and unsupported layout before canonical facts.
- `resolve_archive(session: StorageSession, reference: str, origin: ReferenceOrigin) -> ArchiveHandle` — one origin-qualified archive/member with identity/digest/version token; never an arbitrary Path escape or entire-store grant.
- `plan_operation(repo_root: Path, request: StorageRequest) -> dict` — kinds `ACTIVATE|M1|M2`, immutable candidate/report data; no writes. Empty/bounded-incomplete scans never imply ready.
- `apply_operation(repo_root: Path, plan: dict, decision_id: str, maintenance: dict) -> dict` — exact selected accepted user grant and operation-specific maintenance qualification; no GC/delete kind.
- `recover_operation(repo_root: Path, operation_id: str) -> dict` — explicit recorded-object recovery only; cannot admit unknown object by matching bytes.

`StorageError.code` maps the approved STORE_* identifiers. Missing/unsupported capability/version/layout is refusal, not guessed legacy. Classes/inner helper fields may evolve only if public semantics and serialized contracts remain unchanged.

---

### Task 1: Layout Identity, Secure Reads and Pre-Fact Admission (D1, V1/V6/V7)

**Files:** Create storage/layout.py, storage/__init__.py, storage-layout.schema.json, tests/test_storage_layout.py, tests/test_storage_admission.py. Modify transaction_recovery.py, init.py, cli.py, controlplane.py, harness_status.py, schema_resources.py and affected source-boundary tests.

**Interfaces:** Produces LayoutInspection, StorageError and read-only/admission Interface above. StorageSession carries pinned repo/store/root identity plus generation and owner key; no mutation permission for arbitrary paths. Pending inspection initially recognizes schema-valid coordination records and blocks them; activation adapter comes Task2/4.

- [ ] Write tests `test_absent_store_keeps_legacy_without_creating_paths`, `test_unowned_name_is_never_claimed_or_hidden`, `test_bound_header_and_binding_require_exact_workspace_store_identity`, `test_same_named_user_symlink_and_directory_refuse`, `test_worktrees_are_not_bound_to_common_git_directory`. Assert actual tree bytes/identities unchanged and per-root binding refusal; schema errors must not fall back to legacy.
- [ ] Write parametrized pre-fact tests for ordinary init/status/evidence/Gate/Context/task new/recover/identity/prune and exposed `--harness-dir`: unknown active coordinator rejects before first canonical read, including absent current root. Legacy custom paths with no store remain legacy; bound layout only supports canonical repo-root `.harness`, other apparent bound paths refuse rather than acquire another owner. Read-only inspection may report pending, never recover it.
- [ ] Run exact tests against current implementation and keep valid RED showing wrong branch/side effect; if imports initially absent, first resolve test setup, do not label ImportError as product proof.
- [ ] Implement finite layout validation and descriptor-relative snapshots. Extend existing admission seam instead of suspending source guards. Add no production store/probe creation on read paths. Same stable telemetry owner identity through missing/replaced root; do not recursively call an admission wrapper from itself.
- [ ] Run new files and affected `test_publication_admission.py`, `test_cli_init.py`, `test_source_access.py` in bounded serial subsets. Expected new regressions GREEN and unchanged legacy refusals; serialize actual owner interleavings, not only sequential mocks.

### Task 2: Directory Coordinator and Activation Bootstrap Recovery (D1, V4/V7/V8)

**Files:** Create storage/journal.py, storage-operation.schema.json, tests/test_storage_journal.py, tests/test_storage_kill_recovery.py. Modify transaction_recovery.py dispatch and narrowly reuse publication_fs.py primitives without broadening their path authority.

**Interfaces:** Internal `prepare_activation(harness_root, plan, authority) -> DirectoryOperation`, `prepare_turnover(session, descriptor) -> DirectoryOperation`; operation `.advance(action)`, `.commit()`, `.abort()` validate finite state, intent, identity and frames; public recover_operation delegates here. Only operation-owned private writer runs while its coordination descriptor is active.

- [ ] Specify schemas for plan/descriptor/frame/receipt with explicit kind/version, source/target identities, operation/store/workspace IDs, old/candidate generations, manifest digests, selected authority snapshot, durable intent/ack and previous hash. Never accept a regular-file journal version as directory protocol.
- [ ] Write real process-kill tests at prepare/intent/create-before-identity-ack/move/sync/ack/commit-pointer/terminal/retirement. Before identity ack, unknown created object must remain BLOCKED and preserved. Cases `test_root_absence_never_authorizes_init`, `test_committed_operation_finishes_never_aborts`, `test_unknown_inode_with_identical_bytes_is_not_owned`, `test_regular_and_directory_operations_cannot_overlap` catch dangerous shortcuts.
- [ ] Run exact RED tests. Implement activation bootstrap as approved §15.1: versioned kind in existing `.harness/.transactions` before creating store; no root turnover during activation. Nonactivation coordinator lives in stable store/operations. Never invoke ordinary generic recover on nested old fixture journals.
- [ ] Implement no-replace directory moves, held parent FDs, immutable chained frames, exact legal transitions and bounded fd cleanup. Ambiguous crash layouts fail closed; do not promise automatic repair for unrecorded object identity.
- [ ] Exercise owner lock concurrency, directory substitution/symlink/unsupported platform/cross-device refusals and primary-vs-cleanup exception paths. All new raises need actual negative tests.
- [ ] Run storage journal/kills plus existing publication_fs/journal/transaction_recovery safety tests in planned batches; no edits to real recovery state.

### Task 3: Origin-Qualified Single History and Controlled Context References (D1, V3/V5)

**Files:** Create storage/archive.py, storage-history.schema.json, tests/test_storage_archive.py, tests/test_storage_context.py. Modify task_identity.py, paths.py (only relevant history references), source_access.py, context/freshness.py, context/read_scope.py, context/source.py, context/integrity.py, context schema and resource registry.

**Interfaces:** Produces ReferenceOrigin `(workspace_id, generation_id, original_workspace_root)`, ArchiveHandle with origin/alias record/object/descriptor/member identity+digest token and context-managed secure byte read. Internal `prepare_archive_overlay(session, operation_id, source_snapshot) -> dict`, `commit_archive_overlay(operation)` share Task2 authority, no standalone public task-state mutation.

- [ ] Write tests `test_same_archive_name_in_two_generations_is_ambiguous_without_origin`, `test_all_legacy_history_ref_forms_resolve_only_in_owner_generation`, `test_absolute_old_workspace_reference_requires_explicit_mapping`, `test_equal_bytes_new_inode_invalidates_context`, `test_unrelated_index_append_preserves_selected_reference`, `test_missing_selected_entry_or_member_fails_closed`.
- [ ] Add task-ID tests for original archive names and documents, accepted decisions, leading-zero aliases, aborted candidate reservations, index/document disagreement. Rejected/aborted turnover must not silently release observed IDs.
- [ ] Watch RED. Implement immutable archive IDs and source snapshot descriptors; deduplicate only with matching generation+object identities+member digest AND original accepted receipt, never merely task ID/name/hash. Keep same-ID different snapshots separate; pending overlay invisible to accepted history.
- [ ] Add scoped source adapter for selected entries/member identity. Actually read/observe index bytes each time but bind semantic selected entries for saved freshness; do not grant read access to entire store or fake mutable source hashes. Add Context projection/version/schema/resources simultaneously; preserve legacy Context behavior.
- [ ] Run new archive/context files plus task_identity, artifact/source boundary, Context integrity/freshness/read_scope and paths consumers. Assert historical receipt bytes unchanged and unrelated index growth does not stale product evidence.

### Task 4: Exact Grants, Activation/M1 Planning and Explicit Migration (D3, V1/V6/V8)

**Files:** Create storage/migration.py, tests/test_storage_activation.py, tests/test_storage_migration.py, tests/test_storage_cli.py. Modify decision.schema.json/decision.py, gate.schema.json, cli.py/controlplane.py, workspace.py/git_query.py, architecture path consumers and tool_identity/preflight capability reporting as required.

**Interfaces:** Implements plan_operation/apply_operation and CLI: `storage inspect --json`; `storage migrate --kind ACTIVATE|M1|M2 --dry-run --json [--file proposal.yaml]`; `storage migrate --apply --file plan.json --decision DEC-nnn --maintenance-file declaration.json`; `storage recover OPERATION_ID`. `--apply` and `--dry-run` mutually exclusive; missing explicit mode means dry-run, never apply. GC delete/apply absent.

- [ ] Extend existing selected Decision options with optional schema-closed `storage_authorization`: version1/task_id/workspace_id/store_id-or-null/operation/plan_digest/scope_digest. Require current-task ACCEPTED non-superseded selected option and `decided_by=user`. Binding plan digest excludes later grant snapshot to avoid circular hashes; operation records capture actual grant content hash. No auto-accept/propose from command text. Maintenance declaration lists named participants/capabilities, stop/upgrade attestation, workspace/operation and explicit operator confirmation; does not impersonate global process proof.
- [ ] Add rejection tests for unselected option, proposed/superseded/wrong task/wrong store/other kind/stale scope, old history-prune grant and migration-to-delete grant. A plan ID/hash alone never grants apply. Source/caller errors stay distinct from authority refusal.
- [ ] Add dry-run tests asserting zero canonical/store/staging/context writes/probes, incomplete-budget scan reports nonready, actual user same-name store is refused. Real apply tests only temp Git fixtures with explicit test user grants.
- [ ] Watch RED; implement M1 moves of existing canonical history original directories to stable archives without copy/hash merging, preserve old alias origin. Leave old retained-root history copies untouched. Stage root/header/binding and all required migration membership under Task2 coordination; abort and commit match §15.3/15.4, no first-task completed archive fabricated.
- [ ] Add capability identity `harness-storage-layout/v1` in owned header/binding and closed Gate marker. Unknown required capability refuses. Test archived v0.3.2 Gate schema rejects marker without executing old binary on real store; no package/tag/version release claim. Record exact reader/schema identities, not trust semver alone.
- [ ] Make product/architecture/Git exclusion conditional on valid owned binding, shared across consumers; no unconditional ignore of user `.harness-store`. Store dependency changes affect control Context not arbitrary product tests. Include namespace ownership observations before exclusion.
- [ ] Run activation/migration/CLI plus related decision, workspace/Git, architecture workspace, preflight/tool identity, schema resource and legacy init tests in bounded batches.

### Task 5: Bound New/Recover Turnover Without History Copying (D2, V2/V4/V5)

**Files:** Modify task_replacement.py and controlplane.py task_new/task_recover; create tests/test_storage_turnover.py, tests/test_storage_turnover_recovery.py. Extend existing task_replacement/task_new/task_recovery tests.

**Interfaces:** Bound path uses `replace_bound_task(session, prepared_task, archive_snapshot, operation_kind) -> TurnoverResult` implemented privately in storage/journal.py/archive.py as needed. Legacy path unchanged until explicit activation. Result reports committed fact and retained paths independent of warning-sink failure.

- [ ] Add tests for alternating 20 task new/recover operations: prior archive inode remains fixed, existing history collection never copied, stable top-level retained-root depth bounded, old held-FD write remains at recorded previous object. Tests create explicit fixture layout, not real project activation.
- [ ] Add real kill tests through PREPARED/ARCHIVE_READY/OLD_ROOT_RETAINED/NEW_ROOT_INSTALLED/VALIDATED/COMMITTED. Current root absent blocks all normal entrypoints; candidate rollback preserves candidate and provisional archive privately; accepted aliases return to original view; seen-ID reservations remain. If externally replaced root/index/target appears, stop and preserve instead of overwriting.
- [ ] Watch RED. Implement candidate root from required templates/policies/explicit existing inherited decisions/interfaces only, no history/store/experimental tree copy. Generate source snapshot once, pin before/after identity/bytes; concurrent external writes cause refusal/retention, not adoption. Old root no-replace moves to stable roots; new root installs via no-replace and validates binding/scope genesis/schema before commit.
- [ ] Reuse regular-file publisher only within each root/private candidate when admission permits; no generalized cross-root member paths. Normal bound task route inherits postactivation compatible-participant policy; observed incompatible writer invalidates qualification, arbitrary writer isolation is not promised.
- [ ] Run 20-cycle tests, all turnover kill variants and legacy task recovery/new/replacement consumers. Verify warning/teardown failures cannot falsely roll back committed facts or lose retained objects.

### Task 6: M2 Explicit Object Relocation and Read-Only History Prune Integration (D3, V5/V7/V8)

**Files:** Extend storage/migration.py/archive.py, task_prune.py, task_identity.py; create tests/test_storage_legacy_references.py and tests/test_storage_prune.py.

**Interfaces:** M2 plan request requires explicit source origin/object paths and target roles, never infer from directory names. Bound prune returns read-only history candidate/reference report; destructive legacy prune at bound layout returns refusal. Existing old-layout pruning remains scoped to its existing rules.

- [ ] Write cases for moved containing replacement package retains its origin-qualified aliases; same-name references from another generation never fallback; copied old stage inode mismatch stays unknown. Preserve nested fixture symlinks/FIFO as opaque archive objects, never treat internal .harness pending as active root authority.
- [ ] Write dry-run/negative apply cases: overlong descriptor-relative paths, cross-device, unknown source role, referenced/runtime object mixed with unclassified input, pending current root, reused old plan, alias target changed, rollback target occupied. Internal directory subtree is not recursively expanded unless that exact move is requested and qualified; root-package move is not fixture recovery.
- [ ] Watch RED; implement explicit M2 moves only with existing exact grant+maintenance+coordinator, holding identity from plan through acknowledgement. Keep original receipt bytes and record origin/current location in migration receipts; no patching command strings for apparent replay.
- [ ] Adapt task_identity/history resolution and prune preview to canonical index+legacy-compatible references. Explicitly refuse `task prune --apply` on bound layout; legacy grant/plan cannot be redirected. No recursive deletion API added.
- [ ] Run M2/reference/prune tests plus existing identity/prune CLI tests and source-boundary tests. Unknown/malformed input is reported and preserved, not excluded from size and silently treated safe.

### Task 7: Experiment Manifests and Reclamation Dry-Run Only (D4, V7/V9)

**Files:** Create storage/experiments.py, storage-experiment.schema.json, tests/test_storage_experiments.py. Extend storage CLI/control rendering and read-only storage prune preview.

**Interfaces:** Internal `classify_candidates(session, manifests: tuple[dict, ...], limits: dict) -> dict`, consumed by `storage prune --dry-run --json`. Public command has no destructive apply flag; reject attempted apply before opening candidate objects. Legacy unmanifested experiments are unknown, not auto-adopted.

- [ ] Write tests proving manifest runtime is not recognized from name `venv`, DONE, lsof result or equal binary hashes; inputs/results stay retained; missing rebuild identity or dynamic/ambiguous/live reference blocks candidate. Proposed/foreign migration grant cannot be used as delete authority.
- [ ] Write bounded scan cases with 55-level tree, no-follow symlink, FIFO never read, multi-hardlink/device changes and total limits. Assert report says incomplete on cap, logical sizes not guaranteed physical savings; nested candidate rows must not be summed twice.
- [ ] Watch RED, implement schema-bound inputs/results/runtime/opaque ownership and finite reference report. Current authority/pending/unknown descriptors always preserve. Terminal transaction diagnostics are metadata qualifications only unless all required protocol/member/identity checks pass; still not deletion permission.
- [ ] Add tests `test_quarantine_is_not_reported_as_freed_bytes`, `test_empty_lsof_output_never_qualifies_cleanup`, `test_read_only_candidate_command_does_not_update_task_or_context`. No hidden auto-init, auto-index repair, recovery, quarantine move or unlink.
- [ ] Run experiment/CLI/prune-related suites; all data synthetic fixture-generated, not the real6binary tools or4.2GiB tree.

### Task 8: Joint Admission, Docs, Packaging and Final Acceptance (V1–V10)

**Files:** Update README.md/README.zh-CN.md/docs/architecture.md and approved docs copies, relevant skills/engineering-harness/SKILL.md/SKILL.md mirror, task-contract/collect-evidence/quality-gate guidance only where new CLI affects workflow. Modify package.json resource allowlist/pyproject data inclusion only if new resources require it. Add tests/test_storage_lifecycle_integration.py and extend package/schema/source boundary tests.

**Interfaces:** Joint activation only after D1/D2/D3 and consumers work together; direct internal Python test adapters are not external execution grants. CLI identity exports storage capability, not false old-writer security promise.

- [ ] Test full temp-repo path: legacy inspect → exact explicit fixture activation → archive read → bound task cycles → injected process death → ordinary admission refusal → explicit recovery → origin reference/Context validation → read-only pruning. Prove no index/ID/freshness gap between feature parts.
- [ ] Test all command entrypoints (including help parsing does not execute migration) and unsupported old Gate marker; store present without valid binding never silently returns legacy success. Re-run concurrent owner tests, selected-entry source guard and final per-item evidence coverage.
- [ ] Update documentation with minimum capability, compatible-writer/maintenance assumption, logical-not-shell-path compatibility, no real cleanup, direct old prune restriction, partial outcome diagnostics and separately authorized production migration steps. Human review checks prose meaning; do not change ordinary wording only to satisfy a checker.
- [ ] Build local offline wheel using already available supported backend, output outside product tree; verify new schemas/package data and installed-isolation related tests. No pip dependency install, registry publish or installer pin/release change without separate permission.
- [ ] Final fresh independent review on exact commit/workspace inventory: focus only new-code fail-open, root identity, crash windows, privilege expansion, reference origins and unsupported promises. Reproduce important proposals before fixes, preserve failed attempts, do bounded RED→GREEN and rerun affected consumers. Document declined/unreproducible platform scenarios honestly.
- [ ] Native Harness acceptance: bind all must/critical/major obligations to real fresh evidence, native Q3 Plan journal per item, complexity and diagnosability review, Context final integrity check, legal REVIEWING/review outcome/GATING, then only Gate DECISION may grant CONVERGED/DONE. Do not author Q2 v1 workaround or reuse TASK-116 proof for this new task.
- [ ] Final report separates implementation acceptance from real activation/migration/GC execution. Explicitly report `.harness-store` at actual project root still absent, no live data moved/deleted, no commits/push/releases by agent unless separately authorized.

## Preplanned Verification Batches

Execution must record manifest with exact commands/selectors after tests exist and qualify durations to same source/runtime. Use absolute `PYTHONPATH=<repo>/src:<repo>/tests`, serial, no bare pytest/full suite. Each invocation must return actual test_execution; setup/import failure is not product RED.

A layout/admission + narrowly split publication-admission consumers; B directory journal+kill tests; C archive/identity/Context references; D activation/migration/decision; E turnover20cycles and kill variants; F legacy references/prune/experiments; G product workspace/Git/architecture/preflight; H source scopes/schema/package/build; I final lifecycle native CLI. Split parametrized crash matrices by explicit selectors before a deadline, preserving full required-test union. No background batch blindly retries or continues after failure/HEAD drift.

Legacy affected files to include as their seams change: test_publication_admission.py, test_transaction_recovery.py, test_publication_fs.py, test_publication_journal.py, test_task_replacement.py, test_task_new.py, test_cli_task_recovery.py, test_task_identity.py, test_decision.py, test_context_integrity.py, test_context_read_scope.py, test_workspace.py, test_workspace_source_access.py, test_git_source_access.py, test_architecture_workspace.py, test_schema_resources.py, test_package_resources.py and installed-isolation tests. Locate existing prune tests by current repository inventory rather than assume nonexistent test_task_prune.py. Do not declare unexecuted groups passed.

## Self-Review Coverage Matrix

- G1/V2 growth:Task5; strict source origin/dedup:Task3/5; existinghistoryM1 ownership:Task4; nestedfixtureM2 qualification:Task6.
- G2 inode/heldFD/bytes:Tasks2/4/5/6; no content-only substitution:Tasks2/3/5/7.
- G3 permission separation/non-destructive scope:Tasks4/6/7/8; realproductionapply never scheduled.
- G4 all requested failure classes:Tasks1/2/3/4/5/6/7; closed schemas/error consumers:Tasks1/4/8.
- G5 Gate/source/Context/freshness:Tasks1/3/4/8; legacy compatibility:Tasks1/4/5/6/8.
- Design§15.1 bootstrap:Task2/4;15.2 tokenfreshness:Task3;15.3 commit/abort:Task2/5;15.4 actualhistorymove:Task4;15.5 snapshotidentity:Task3/5;15.6 originrefs:Task3/6;15.7 maintenance:Task4/5;15.8 prune restriction:Task6/7.
- Task4 requires Task1 admission, Task2 coordinator and Task3 archive Interface; Task5 requires bound activation fixture fromTask4; Tasks6/7 share resolver/grant shapes, no independent competing plan identity format; Task8 activates/docs/tests whole composed behavior.

## Decisions and Stop Conditions

Author decisions for implementation (not new user requirements): split storage into six cohesive files; use capability ID rather than invent release tag; exact existing selected Decision extension rather than a parallel authorization framework; retain main preference and native execution recommendation. Wrong choices cost integration maintenance, not permission to skip safeguards. Source/version drift requires re-review, not automatic rebase/receipt editing.

No auto commits despite generic skill templates. Real activation, data relocation, cleanup, irreversible actions, new dependencies, security-sensitive scope expansion, unrelated active task takeover, user directory conflict or inability to preserve original inode stop execution and require explicit authority. Implementation plan approval is not any of those grants.

## Handoff

Recommended execution: **Native inline**, one executor across tightly coupled storage/identity/recovery seams, one fresh independent final review. This session has no dedicated implementer-subagent tool; native Pi CLI fresh read-only review is available. User must review this plan before implementation. Real migration/deletion remains prohibited even if implementation approved.
