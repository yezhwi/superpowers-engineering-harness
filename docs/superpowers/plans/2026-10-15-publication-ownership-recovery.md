# Publication Ownership and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent publisher-caused destruction of unmanaged objects and keep final validation/compensation inside recoverable publication.

**Architecture:** Narrow native filesystem backend preserves displaced inodes using atomic exchange/no-replace operations. Durable versioned operation records cover forward mutation, finalizer, rollback and terminal retention handoff. Shared reader admission refuses incomplete transactions; no unsafe fallback and no claim of content CAS.

**Tech Stack:** Python >=3.11, stdlib ctypes/os, pytest; existing telemetry_lock, source_access and evidence CLI. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-15-publication-ownership-recovery-design.md`, user accepted recommendation in current conversation. Original efficiency spec and task contract remain in force.

## Global Constraints

- User-approved DEC-003 supersedes original Linux/macOS target: macOS-only local filesystems with runtime-validated exchange/no-replace/no-follow/synchronization support. Linux/Windows/other OS fail closed before directory open, ABI load or probe creation. No Linux environment preparation or matrix. Historical Linux analysis/receipts remain unchanged.
- Retain all displaced inodes; no automatic age/mtime cleanup. Conflict may relocate unmanaged bytes to reported recovery location; no canonical-path-always-fresh or immutable external-history guarantee.
- No product authority from capability checks. Read-only diagnostics perform no native mutation probes, tests or business execution.
- Keep journals outside disposable staging; no unjournaled compensation, slot overwrite or inode truncation.
- Scope grants, immutable origin, freshness, Gate, cancellation/exit semantics and required independent validation unchanged.
- Finding lifecycle requires real RED before CONFIRMED/FIXING, same reproduction GREEN before FIXED, fresh closure proof before VERIFIED/CLOSED. FND003/004/005 remain PROPOSED until reproduced.
- Serial affected tests only. Preserve historical failed receipts. Never restart cancelled N=100 benchmark; existing80 samples describe earlier source snapshot.
- Existing isolated worktree/Native execution retained. No commit, merge, push, release, production TASK-1038001 operation, new dependency or automatic pruning authority.
- Approval covers supplemental design, not a shortcut through stale FND001 proof. New workflow/schema behavior needs bounded justification and approval if outside approved design.

## Review Focus

1. Writer holds writable FD across exchange and writes after initial classification: retained inode survives; no immutable byte-history claim (Task2).
2. Operator renames ancestor/root after directory pinning: no redirected write to substituted tree, no successful pathname claim; ambiguous restart BLOCKED (Task2).
3. Death after terminal record creation but before active record retirement: idempotent handoff, never lose object or block forever on valid terminal retention (Task2).
4. Backend symbol present but exchange/fsync unsupported on actual filesystem: fail before first canonical mutation, no fallback or success claim (Task1).
5. Raw reader enters during validation/rollback, or final Context contains extra staged member: supported reader refuses, exact manifest rejects extra member (Tasks3/4).

## File Map

Create `src/harness/publication_fs.py`: native ABI adapter, pinned directory access and private capability checks; no journal/business decisions.

Create `src/harness/publication_journal.py`: v2 records, retained slots, operation recovery and terminal retention. Keep v1 reader in `transaction_recovery.py`; route by explicit version, never reinterpret v2 as v1.

Modify `transaction.py`: exact input and safe protocol orchestration; keep standalone atomic_write separate and explicitly not upgraded by implication.

Modify `transaction_recovery.py`: lock-aware no-pending admission, v1 conservative recovery and v2 dispatch. No automatic mutation in read-only admission.

Modify `context/{store,escalation}.py`, `_scope_replay.py`: captured target maps, exact payload manifests, finalizers before commit; remove outer unsafe rollback.

Modify `quality_gate.py`, `controlplane.py`: common pending admission before canonical facts/transition, continuous lock.

Tests: existing transaction/recovery, scope apply/joint, Context integrity/batch/CLI and Gate/transition tests; add `test_publication_fs.py`, `test_publication_journal.py`, `test_publication_admission.py`.

Docs: supplemental design approval status, migration/support/retention notes, CHANGELOG; no release-version bump.

## Execution Prerequisites

- [ ] Read approved original and supplemental specs, current TASK092 contracts, all finding records and actual RED receipts. Revalidate worktree/branch and authority; save inventory, never enroll runtime transaction storage as product impact.
- [ ] Diagnose FND001 FIXED proof refresh restriction using temporary task fixture: current implementation allows FIXED -> VERIFIED only, but related metadata admission validates workspace-fresh GREEN. Do not mutate actual finding by hand or downgrade validation. Produce deterministic workflow reproduction and bounded remedy proposal if no supported route exists; obtain approval before adding lifecycle CLI/schema behavior. Exact FND002 reproduction collection already works; this prerequisite blocks actual new required-test enrollment, not read-only design work.
- [ ] After supported freshness route exists, refresh FND001 by running its registered selector with new immutable receipt, then supported proof update; enroll actual new test/source files via impact CLI. Do not overwrite RED/GREEN history or mark FND001 closed to escape stale proof.
- [ ] Before changing shared publisher/recovery seams, execute baseline FND003/004/005 reproduction steps listed in Tasks4/5 on existing source, saving independent exact receipts and lifecycle transitions. This prevents fixing an adjacent seam before its required RED exists. Any finding not reproduced stays PROPOSED/REPRODUCING or evidenced REJECTED, never retrospectively confirmed by another finding's GREEN.

### Task 1: Native atomic operations with honest capability boundary

**Files:** Create `src/harness/publication_fs.py`, `tests/test_publication_fs.py`.

**Interfaces:**
- `open_directory(path: Path) -> int`: no-follow descriptor, caller owns close.
- `exchange(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str) -> None`.
- `move_noreplace(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str) -> None`.
- `sync_directory(dir_fd: int) -> None`.
- `check_capabilities(private_dir_fd: int) -> None`: anonymous private files only, no canonical targets.
- `PublicationUnsupported(OSError)`: stable `PUBLICATION_UNSUPPORTED` code; preserve errno for diagnostics without content.

- [ ] Add failing tests `test_exchange_retains_both_objects`, `test_noreplace_preserves_concurrent_creation`, `test_unsupported_never_falls_back`, `test_fsync_failure_prevents_capability_success`. Assert exact byte pairs/inodes and zero canonical changes; absent libc symbol and kernel/filesystem refusal are distinct injected cases.
- [ ] Run `PYTHONPATH=src python3 -m pytest tests/test_publication_fs.py -q`; record actual RED, not import-only failure as finding confirmation.
- [ ] Implement functions using errno-aware libc calls; pin Darwin renameatx_np signatures/flag constants against release ABI headers. Original Linux adapter/ABI work is historical and superseded by DEC-003; remove enabled Linux branch during Task6 platform amendment. Persist Darwin citation/release in module comments; no hardcoded syscall numbers. Existing/new paths use mutually exclusive flags; restrict names to a single safe basename.
- [ ] Run same file serially; real local macOS filesystem tests pass, injected failure tests refuse. Linux is unsupported per DEC-003; no native Linux matrix or symbol-existence certification.
- [ ] Inspect diff for silent os.replace/copy/unlink fallback and content logs; save task checkpoint without committing.

### Task 2: Recoverable inode-preserving forward and abort protocol

**Files:** Create `src/harness/publication_journal.py`, `tests/test_publication_journal.py`; modify `transaction_recovery.py`, `tests/test_transaction_recovery.py`.

**Interfaces:**
- Immutable `Member(path: str, expected: bytes | None, payload: bytes | None)`; payload None means explicitly authorized deletion, not an absent staged file.
- `prepare(root: Path, members: tuple[Member, ...]) -> Operation` under telemetry_lock; copies candidate bytes into owned private slots and persists manifest before canonical mutation.
- `Operation.apply() -> None`, `Operation.commit() -> None`, `Operation.abort() -> None`; methods require continuous held lock and journal each atomic step before execution. Context-manager/close machinery releases all pinned FDs without unlinking retained objects.
- `recover(root: Path, operation_dir: Path) -> None`; known interrupted operation resumes conservative abort; unknown/ambiguous operation raises TRANSACTION_RECOVERY_BLOCKED and retains all slots.
- `transaction_recovery.require_no_pending_publications(root: Path) -> None`: read-only, lock required, unknown active records also block.

- [ ] Write failure tests for replacement, new creation, delete/recreate, held writable FD, writer rename/in-place mutation at each native operation, parent/root substitution and restart with renamed root. In `test_held_fd_write_survives_terminal_handoff`, preserve actual displaced inode then write via preopened FD after commit; retained object reflects write, no automatic purge.
- [ ] Write subprocess death matrix `test_kill_recovers_every_operation_boundary` for before/after native move, journal persistence, APPLYING/VALIDATING/ABORTING and terminal handoff. Remove staging, restart, assert known restoration or BLOCKED plus recoverable bytes. Test v1 valid/corrupt/unknown versions separately.
- [ ] Run new journal tests and existing recovery tests serially for RED. These new mechanics tests do not confirm FND004 until its caller scenario is reproduced in Task4.
- [ ] Implement explicit v2 record: version, operation id, state, root/parent `(st_dev, st_ino)`, exact members, expected/payload hashes, original/candidate/displaced identities, durable next-step intent and completed-step records. Persist candidate inode/content before exposing path. Reject duplicate/malformed/path-escaping members and recovery-storage targets, including `.publication-retained`.
- [ ] Implement PREPARED -> APPLYING -> VALIDATING -> COMMITTED or ABORTING -> ABORTED; ambiguous object identity/content -> BLOCKED. Each intent identifies source/destination slots and expected inode identities so restart distinguishes no-op/executed step; never infer identity solely from byte equality. Apply existing replacement by exchange, new by no-replace, deletion by no-replace move into private slot. Never truncate displaced inode. Compensation itself uses prejournaled exchange/no-replace; unknown objects are retained, not overwritten or retried indefinitely.
- [ ] Implement durable terminal handoff to `.publication-retained/<operation-id>/`: terminal manifest and every retained slot synchronized before active descriptor retirement; restart recognizes half-complete handoff idempotently. Fail on destination collision, no overwrite. Retain all displaced inodes even baseline-equal. Failure allocating/syncing retention blocks with active record, not data deletion.
- [ ] Route explicit v1/v2 versions, reject mixed/unknown overlapping active operations. Preserve conservative v1 behavior without claiming old rollback race fixed; v1 recovery must complete or block before v2 begins. Existing standalone atomic_write remains outside new guarantee.
- [ ] Run `PYTHONPATH=src python3 -m pytest tests/test_publication_journal.py tests/test_transaction_recovery.py -q`; inspect every kill case and any skips; save evidence/checkpoint, no commit.

### Task 3: Exact safe publisher and FND002 GREEN

**Files:** Modify `transaction.py`, `tests/test_transaction.py`, `tests/test_transaction_recovery.py`.

**Interfaces:**
- Keep `stage(...)` and `publish(...)` compatibility; add `expected_artifacts: tuple[StagedArtifact, ...] | None = None` to publish. Explicit manifest is required for new safe callers; legacy call entry snapshots exact staged names/bytes once and never silently expands them later.
- Existing `expected_sources` requires exact union of payload/deletion names; missing/extra keys fail before canonical mutation. New safe call sites pass both maps, not adopt current bytes at publisher entry.
- `after_publish` remains finalizer executed while operation active and before commit. `publish` owns reentrant telemetry_lock throughout; legacy `durable=False` is accepted for call compatibility but no longer permits nonrecoverable replacing writes. All batch publication uses journal; document compatibility/disk cost.

- [ ] Expand boundary injection regression to wrap real `publication_fs.exchange`, assert hook ran, inspect retained object on conflict and assert non-success. Keep original Path.replace test as historical proof; don't make it GREEN by changing primitive so hook never runs. Test old durable=False/True entries against same preservation contract.
- [ ] Add `test_publish_rejects_extra_stage_member`, `test_expected_sources_requires_exact_members`, stage payload substitution, callback death/failure, missing target plus concurrent creation. Assert no canonical event on genuine pre-mutation error and retained unknown objects after mutation conflict.
- [ ] Run exact affected selectors for RED; retain original FND002 receipt. Enter FND002 FIXING through CLI only after contract/minimal check recorded.
- [ ] Delegate forward/commit/abort to Task2, validate exact stage set/bytes without following symlinks, delete only operation-owned unchanged disposable stage entries. Required capability check precedes first canonical mutation. No rmtree over unknown stages and no publisher rollback using byte-copy atomic_write.
- [ ] Run `PYTHONPATH=src python3 -m pytest tests/test_transaction.py tests/test_transaction_recovery.py tests/test_publication_journal.py tests/test_publication_fs.py -q` serially. Collect finding-tagged GREEN of registered test path, proving actual native-boundary injection. If existing path must be split, preserve same registered reproduction selector plus strengthened matrix; no unproved retarget.
- [ ] Transition FND002 FIXED only on valid immutable GREEN; save code-only diff self-review/checkpoint, no close/commit.

### Task 4: Finalizer boundary and exact Context/scope bundles

**Files:** Modify `context/store.py`, `context/escalation.py`, `_scope_replay.py`; tests `test_context_integrity.py`, `test_context_batch.py`, `test_reconcile_apply.py`, `test_scope_joint.py`.

**Interfaces:** Safe callers supply `expected_artifacts=tuple(StagedArtifact(...))` and captured `expected_sources` to Task3 publish. Both independent final checks run inside one finalizer, before operation.commit; no dependent validation or canonical writes after publish returns.

- [ ] Reproduce FND004 on current outer check path in subprocess: publication commits, outer second check raises, kill after first compensating canonical write; destroy staging, restart, assert partial state has no recovery authority. Record real RED and only then CONFIRMED/FIXING. If scenario fails to reproduce, record why and disposition through lifecycle; no design-based confirmation.
- [ ] Reproduce FND005: edit target after captured before map but before publish entry; inject unexpected valid-looking staged member. Assert refusal/no adoption and zero events prepublication; record real RED/lifecycle separately.
- [ ] Write `test_all_final_checks_run_before_commit` for three callers; force second check failure/kill and assert active journal still exists and byte-preserving abort/restart. Preserve both check counts, not one check to remove race symptoms.
- [ ] Move both checks into finalizer; remove post-return restore loops and `_restore` if no remaining legitimate caller. Capture final Context before-map from verified source moment, pass exact names `context/current.yaml`, `context/manifest.yaml`, `context/evidence.yaml`; expansion exact task/log pair and scope exact prepared payloads. Ensure payload exceptions don't clean unknown stage bytes.
- [ ] Run `PYTHONPATH=src python3 -m pytest tests/test_context_integrity.py tests/test_context_batch.py tests/test_reconcile_apply.py tests/test_scope_joint.py -q` serially. Collect separate same-reproduction GREEN receipts before respective FIXED transitions; closure/review stays pending.
- [ ] Run existing structural count matrix N=0/1/10/50/100 unit tests only, no benchmark timings/sampling. Preserve full builds<=2/source loads<=3/Gate assessments<=3 including independent validation. Save checkpoint, no commit.

### Task 5: Pending-state admission before Gate and transition

**Files:** Modify `quality_gate.py`, `controlplane.py`, `transaction_recovery.py`; create `tests/test_publication_admission.py`; extend `tests/test_quality_gate.py`, `tests/test_finding_transition.py` only where affected.

**Interfaces:** `require_no_pending_publications` from Task2 must run under same reentrant telemetry lock as first canonical read and assessment/transition completion. Existing recovery-capable commands explicitly recover first; read-only assessment/diagnostics only refuse.

- [ ] Reproduce FND003 with partial task/log/scope publication, then actual supported Gate/transition command. Assert pending refusal before reading/changing task, retained bytes/journal unchanged; show actual RED before confirmation/fix.
- [ ] Add admission matrix for PREPARED/APPLYING/VALIDATING/ABORTING/BLOCKED, unknown versions, committed retention-only directory, and gap between check and command read. Use subprocess synchronization to show shared lock prevents supported interleaving. Diagnostics must neither repair journals nor probe platform capabilities.
- [ ] Implement common lock/admission boundary at public Gate and consequential transition entry, including task load (not after it). Use no-pending guard rather than suppressing findings/authority blockers. Audit direct assessor helpers; establish which are pure internal functions and ensure supported callers own continuous lock. Unknown state is refusal, not implicit valid task.
- [ ] Run `PYTHONPATH=src python3 -m pytest tests/test_publication_admission.py tests/test_quality_gate.py tests/test_finding_transition.py -q` serially. Collect exact FND003 GREEN before FIXED. Check recovery command still works, read-only refusal changes no canonical bytes. Save checkpoint, no commit.

### Task 6: Support docs, current evidence and independent acceptance

**Files:** Modify `CHANGELOG.md`, `docs/test-scope-migration.md`, `README.md`, `README.zh-CN.md`; DEC-003 additionally narrows `src/harness/publication_fs.py`, `tests/test_publication_fs.py`, and doc contracts in existing `tests/test_readme_docs.py`. npm package tests/allowlist only if new approved public docs require inclusion; update ledger and contracts through CLI.

**Platform amendment sequence (approved continuation, Native serial):**
- [ ] Add parameterized `test_unsupported_platform_refuses_before_native_access` for Linux/linux2/Windows/FreeBSD and directory/exchange/no-replace/probe entry paths. Real pinned FDs and bytes; trap ABI load, assert typed refusal, unchanged inode/bytes/member set. Run exact selector first: Linux cases must RED, not import error.
- [ ] Narrow `_native` and `open_directory` to Darwin only; no new abstraction, fallback or package-wide install restriction. Run full native boundary/probe tests: PASS on local macOS plus unsupported-OS refusal. This changes publication support, not every pure/read-only Python helper.
- [ ] Add operator-doc contract tests below, observe missing support/retention documentation RED, then update four public docs. Retain all required43 test files and historical evidence; no RETIRE/REBIND. Recollect fresh16 FIXED proofs after last product edit, not historical Task5 outputs.

- [ ] Add doc tests for unsupported platform refusal, qualified pathname guarantee, retained data/disk costs, private permissions and no pruning command; absence of universal Windows/network support claims. Run relevant tests RED, then document exact behavior and run GREEN.
- [ ] Audit all transaction.publish callers from Task3 signature, standalone atomic_write, task_replacement and after-return writes. If any unconverted call is within claimed invariant, convert with its own RED/GREEN or explicitly block it; never broaden claim to standalone operations without tests/approval.
- [ ] Run affected tests serially in bounded groups with immutable receipts; inspect command exit codes, not collector exit alone. Refresh current FND001 proof via approved route after final product edit; reverify current closure obligations, scope and Architecture consumers. No full-suite launch and no N=100 benchmark restart.
- [ ] Run native macOS filesystem integration matrix. DEC-003 explicitly excludes Linux support/acceptance and Linux environment operations; mocked OS refusal is not Linux execution. macOS capability refusal, network/special filesystem limits, qualified inode preservation and other acceptance gates remain. Build only in previously authorized isolated environment; never global install.
- [ ] Fresh independent code review of whole working diff/untracked files plus supplement, explicit new-code-only race/compensation review. Design builder-review is not implementation approval. Findings enter PROPOSED and require lifecycle evidence; remaining FND006/007/008 not solved by this plan.
- [ ] Use evidence-backed VERIFIED/CLOSED transitions per finding and legal REVIEWING/GATING route only when required proof fresh. Full original task still needs all outstanding findings/behavioral gaps resolved, actual CONVERGED and legal DONE. Stop before any commit/merge/release; seek separate authority.

## Self-review and handoff

Spec coverage: platform/guarantee sections2-3 -> Task1/global constraints; storage/input sections4-5 -> Tasks2-3; member/state sections6-7 -> Tasks2/4; admission/Context section8 -> Tasks4-5; reporting/compatibility section9 -> Tasks1/2/6; verification/approval sections10-12 -> all tasks/Task6. Every Review Focus item has owning test above. Types/interfaces consistent: Member and Operation belong only to publication_journal; filesystem backend knows no journal/task authority; safe callers use one publish entry.

Implementation sequencing: prerequisite diagnosis/approved fresh-proof route and baseline adjacent-finding REDs ->1->2->3->4->5->6. No separate parallel writers in shared worktree; subprocess race tests are intentional serial tests. Approval recorded for design, not yet execution of this new plan. Existing execution method Native preserved; ask user to review this plan before product implementation.
