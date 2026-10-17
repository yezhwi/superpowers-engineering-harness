# Safe publication and durable compensation — supplemental design draft

Status: **DESIGN APPROVED / IMPLEMENTATION PLAN PENDING REVIEW**.
Approval: user said “接受推荐” in current conversation, accepting recommended
platform, qualified byte-preservation, retention cost and durable-boundary choices.
No commit/merge/release authority. Earlier draft's independent builder-review hash
is preserved in ledger; only approval metadata changed here.
Date: 2026-10-15. Task: TASK-092, Q3/STRICT.
Primary findings: FND-002 (CONFIRMED), FND-004 (PROPOSED).
Required adjacent boundaries: FND-003 and FND-005 (both PROPOSED).
Original approved efficiency spec remains unchanged. No commit/release authority.

## 1. Purpose and evidence

FND-002 deterministic regression proves both existing publisher modes can destroy
an unmanaged edit between final byte check and unconditional replacement. Two RED
assertions are recorded in `FND-002-red-unit-test.json`. Adding another compare
merely moves that window. An advisory Harness lock does not constrain editors.

FND-004 independently proposes a crash window after publisher journal removal but
before outer freshness compensation. It still requires actual reproduction; this
shared design must not be described as an already validated fix.

Goal: preserve unmanaged bytes and recovery information, keep final validation
inside durable commit boundary, and prevent supported Harness readers/writers from
consuming incomplete publication. No new evidence cache or expanded scope authority.

## 2. Approved platform boundary — macOS-only amendment

User subsequently instructed “对 Linux 体验排除，只支持 macOS” and approved continued
execution of spec/docs/platform-refusal synchronization. Supported Decision DEC-003
records this platform amendment; it supersedes the earlier Linux/macOS support
choice, not scope authority, risk or other acceptance requirements. Earlier Linux
ABI analysis and unexecuted coverage remain historical, never passing evidence.

Initial backend now targets **local macOS filesystems only (macOS-only)** with atomic
exchange, atomic no-replace name move, no-follow descriptor-relative access, and
required file/directory synchronization. Use Python stdlib `ctypes` for narrow libc
calls; no new runtime dependency, guessed syscall numbers or shell implementation.

- macOS: `renameatx_np(RENAME_SWAP)` and `renameatx_np(RENAME_EXCL)`.
- Linux, Windows and every other OS: typed `PUBLICATION_UNSUPPORTED` before opening
  publication directories, loading a native ABI or creating capability probe files.
  Do not provision/run a Linux matrix; Linux is excluded from current support.
- Unavailable symbols/flags, EXDEV, unsupported filesystem semantics or required
  synchronization failure: typed fail-closed error. **Never fall back to ordinary
  replacing rename, copy/unlink, mtime comparison or advisory-lock-only safety.**
- Windows and unvalidated network/FUSE/remote/special filesystems are not silently
  supported. Do not assume symbol presence proves filesystem semantics. Capability
  validation uses private anonymous files on actual destination filesystem before
  canonical mutation; it is not a business/test/environment command executed by
  read-only diagnostics. Formal Windows support needs a separate backend design.

Design-time observation: libc exported renameatx_np; no native operation had yet
been run for that proposal. Subsequent macOS execution evidence lives in the task
ledger; this historical observation is not current filesystem certification.
macOS support still requires actual destination capability checks and native tests.

### Required honest guarantee

Atomic exchange is **not content compare-and-swap** and does not stop arbitrary
external in-place writes, renames, unlinks or directory moves. It can preserve both
namespace objects instead of discarding the displaced object. Post-operation
classification detects observed identity/content mismatch and halts.

The proposed guarantee is no publisher-caused destruction of displaced bytes:
retain displaced inodes and do not truncate/rewrite them. During a concurrent
namespace conflict, the latest unmanaged object may be retained at a reported
recovery location rather than its original canonical name. It must remain
recoverable; do not automatically select its business meaning or declare success.

**User accepted this qualification with recommended design.** If the invariant instead requires
canonical pathname always retain the unmanaged version at every instant, this
protocol is insufficient: portable rename/exchange provides no expected-inode CAS.
That stronger requirement needs all writers to honor an enforced exclusion model
or a broader storage/reader redesign. Do not silently claim either guarantee.

## 3. Scope and non-goals

Covered: existing/new/deleted regular canonical artifacts published in a bounded
Harness transaction; Context bundle, expansion task/log and scope impact/bindings/
audit/seal; forward publication, compensating rollback, restart recovery.

Not covered by implication: every existing `atomic_write`, task-directory
replacement, arbitrary external tools, cross-device transactions, user-secret or
business-file migration, physical disk firmware/power-loss certification. Audit
shared callers before shipping; any caller needing invariant must use safe API or
explicitly be blocked. No standalone-write safety claim from fixing batch publish.

No persistent cache, schema/permission relaxation, automatic Decision acceptance,
freeze/resume, risk downgrade, raw-byte telemetry, production TASK-1038001 change,
release or restart of cancelled N=100 benchmark.

## 4. Three storage roles

1. `.harness/.staging/`: disposable prepared input, never recovery authority.
2. `.harness/.transactions/`: durable active operation descriptor and private
   operation slots, outside staging. Journal v2 explicitly versioned, exact member
   set and pinned root/member-parent identity. V1 pending journals remain readable
   only through their existing conservative recovery path before new operations.
3. `.harness/.publication-retained/`: durable retained objects and terminal recovery
   manifest. Not canonical facts, not reuse cache and never read as test/Decision
   authority. Permission-limited storage contains actual canonical metadata bytes;
   no contents emitted in progress or errors.

Retained objects cannot share the active-journal enumeration such that every
successful operation permanently blocks the next. Unsupported/unknown active
journals still halt. Committed retention records do not imply pending recovery.

No automatic age/mtime cleanup. A displaced inode may still be open by an external
writer even when its bytes initially matched baseline. Retain all displaced objects,
not only initially detected mismatches. Cleanup requires a separately designed,
explicitly authorized operator action; not added by this supplement. Disk growth
and ENOSPC are real operational costs, not hidden behind a TTL.

Directory identities and final manifests must be journaled durably before deleting
active descriptor. Relocation into terminal retention is idempotent, preserves all
objects, and is itself a restart-tested handoff. Active descriptor disappears only
after terminal record and retained slots are durable. No unjournaled archive step.

## 5. Input and mutation boundary

Caller supplies exact ordered artifacts, explicit authorized deletions and captured
expected target map. The stage directory is not a wildcard source of authority.

- Reject extra/missing members, symlink parents/leaves, duplicate normalized paths,
  nonregular files, stage substitution and payload-byte drift before canonical work.
- Persist the exact payload identity/byte hashes and dependencies before first move.
- Pin verified root and member-parent directory descriptors. Use basename operations
  relative to those descriptors; never re-traverse a user-substituted ancestor.
- Revalidate named root/parent identity for acceptance. A renamed pinned directory
  remains the same object but operation cannot claim success for the new pathname.
  Restart cannot guess relocated roots by scanning disk; halt for explicit repair.
- All private operation slot names and journal transitions are fixed, no-follow,
  no-overwrite; unexpected objects are retained/blocked, not overwritten as cleanup.

Before first canonical mutation: all pure preparation/source/permission/capability
errors leave zero new canonical events. Once mutation starts, interrupted states
are pending—not a valid new Context or accepted audit—and must remain recoverable.

## 6. Per-member operations

### Existing target replacement

Durably prepare new inode in private slot, record intent. Atomically exchange it
with canonical basename. Both objects survive: canonical new candidate, private
slot containing **actually displaced** object, not merely a precheck byte copy.
Synchronize directories and classify identities/content against recorded input.
Mismatch enters durable abort/block route; no successful receipt or Context.
Retain the displaced object even when initially equal, including later writes
through an already-open external descriptor.

### New target

Atomically move candidate into absent canonical basename with no-replace semantics.
Concurrent creation returns conflict and cannot be overwritten. Compensation moves
the actually present object into a fresh private slot without replacing anything;
if it differs, retain and halt. A concurrent move can change where bytes reside,
not authorize deletion. Do not use check-then-unlink as rollback.

### Authorized deletion

Atomically move canonical object into absent retained slot, never unlink it as the
first destructive action. Classify actual displaced object, retain it. Conflicting
recreation of canonical path must be preserved; restoring uses no-replace when
canonical absent, otherwise halts instead of overwriting the recreation.

### Compensation

Every compensating exchange/move gets durable intent first and preserves both
objects. A crash at any step is replayable from recorded identities and slot
membership. Never rewrite a retained inode with old byte snapshots. If ambiguous,
retain all objects and active journal, return BLOCKED. No retry loop against a live
unmanaged writer and no claim that a precheck makes subsequent swap conditional.

## 7. Whole-operation state machine

Proposed states: PREPARED -> APPLYING -> VALIDATING -> COMMITTED, or
APPLYING/VALIDATING -> ABORTING -> ABORTED; unknown identities -> BLOCKED.
Journal transitions/slot identities must be durable before dependent mutation.

- Publish under existing continuous telemetry lock.
- Keep active journal through member changes **and all caller final freshness,
  replay and independent validation callbacks**.
- COMMITTED only after callbacks and expected-source/member/root checks pass and
  directories/data are synchronized.
- Any required post-publication outer check moves into this protected finalizer;
  a caller cannot start compensating writes after journal retirement.
- ABORTING recovery finishes conservatively using retained objects. Rollback
  completion is a durable state, not an exception-handler best effort.
- Active descriptor and terminal retention manifest identify enough before/new/
  displaced slot identities to distinguish death-before-op from death-after-op.
  Ambiguous identity/content is BLOCKED, never inferred from mtime alone.

This is a multi-file recoverable transaction, not atomic visibility to raw external
file readers. Supported Harness readers must participate in section8. No promise
to external tools reading canonical files without lock/protocol.

## 8. Gate, transition and final Context prerequisites

FND-003 and FND-005 are adjacent proposed findings and need separate RED tests.
They cannot be left as unsafe alternate entry points while claiming this protocol
accepted:

- Shared no-pending-publication check before Gate assessment and consequential
  transition reads/writes, under same lock. Read-only commands refuse pending state;
  do not silently repair. Explicit existing recovery-capable operations recover
  before canonical reads. Diagnostics execute no tests/business/environment probes.
- Final Context supplies captured exact target map and exact staged-member manifest,
  not publisher-adopted bytes at entry or recursive discovery of arbitrary files.
- Scope/expansion/final Context all use protected finalizer, no outer unjournaled
  compensation. Double validation semantics retained, with commit later—not deleted
  to make tests pass.

Scope grant, immutable origin, mappings and Gate checks remain independent of
filesystem capability. A successful storage probe confers no execution authority.

## 9. Failure reporting and compatibility

Keep existing public exit2/3 and publication/cancellation meanings; protocol must
not silently override FND-007 cancellation precedence or pretend it is fixed here.
Return stable typed failure codes and task/operation/publication status; no payload,
URLs, environment or business logs in diagnostics. Capability unsupported is
separate from ordinary source drift and ambiguous recovery.

V2 active journal is rejected by old reader, not reinterpreted as v1 or erased.
Never auto-upgrade a pending v1 journal, delete legal events/RED/audit, or manufacture
trusted scope during recovery. Version-marker details and rollback compatibility
must be settled in approved implementation plan before activation.

## 10. Verification and acceptance

Required deterministic matrix, not aggregate passing-test count:

1. Original FND-002 boundary injection for durable/non-durable old entry paths;
   new backend injection explicitly asserts writer actually ran at atomic boundary.
   A changed primitive cannot make test pass by bypassing its hook.
2. Operator in-place write and inode-replacing rename before/after exchange,
   compensation and finalizer, including held writable FD. Never truncate retained
   objects; conflict reports recoverable location and does not report success.
3. Kill at every forward, validation, abort, rollback and retention-handoff boundary;
   delete staging, restart, prove known recovery or conservative BLOCKED plus bytes.
4. New target race, concurrent deletion/recreation, unexpected stage member,
   symlink/parent substitution, root relocation, EXDEV/unsupported flags/ENOSPC/fsync
   failure. No unsafe fallback or inferred zero-loss guarantee on unsupported FS.
5. Gate/transition refuse PREPARED/APPLYING/ABORTING; supported commands cannot make
   recoverable operation unrecoverable by writing task metadata.
6. Exact selected scope authority, obligations, immutable RED, schema/reader and
   Context freshness/entry-count regressions remain valid. No 100-count benchmark
   restart; existing80 samples identify pre-supplement snapshot only.
7. Native macOS integration capability tests on claimed local filesystems;
   Linux/Windows/other OS tests prove fail-closed refusal, not native support.
   DEC-003 removes Linux matrix from acceptance, not any required test file or must
   obligation. No Linux environment operation or fabricated Linux pass.
8. Independent review of new protocol and new code, including crash matrices and
   retention lifetime. No finding closes merely from this design or a native call.

Before multi-finding fix pass proceeds, address supported fresh-proof routing for
FND-001 FIXED evidence after later test edits. Current impact admission refuses old
GREEN as workspace-stale. Do not hand-edit a receipt/status, disable Gate freshness
or pretend red/new test writes are control-only. This lifecycle workflow needs its
own diagnosis/approved bounded remedy, not a filesystem shortcut.

## 11. Alternatives and approval decisions

Rejected: one more compare; advisory lock as exclusive protection from arbitrary
editors; backup byte copy before replace; exchange followed by unconditional slot
cleanup; unjournaled rollback after return. All leave stated race/recovery gaps.

Broader alternative: generation storage with reader-indirection and enforced writer
model. Larger canonical-interface change; not selected for this supplement without
explicit approval. Cannot claim it solves arbitrary external namespace CAS for free.

User accepted these substantive choices; implementation plan still needs review:

- Original Linux/macOS initial-support choice is superseded by user-approved DEC-003:
  macOS-only capability-gated publication; Linux/Windows/other systems fail closed.
  Historical Linux references below do not imply current support.
- Byte-preserving retention may relocate unmanaged object on conflict; cannot promise
  canonical pathname always remains latest unmanaged object.
- Retain displaced inodes until separately authorized cleanup; accept disk cost.
- Expand durable commit boundary across finalizers and fix adjacent admission/stage
  gaps as acceptance prerequisites; do not treat FND-004/003/005 as confirmed yet.

## 12. Primary source references and limits

- Linux man-pages `rename(2)`: https://man7.org/linux/man-pages/man2/rename.2.html
  documents atomic exchange of two existing paths, separate no-replace semantics,
  mutually exclusive flags and filesystem support/errors. These are namespace
  guarantees, not content CAS or multi-file/power-loss guarantees.
- Apple XNU kernel implementation:
  https://github.com/apple-oss-distributions/xnu/blob/main/bsd/vfs/vfs_syscalls.c
  `renameatx_np` accepts SWAP/EXCL and rejects combining them. Kernel source is
  implementation reference, not proof of every filesystem or release behavior.
- Consulted source bytes retained locally in `/tmp/v032-publication-design-sources/`.
  Links to moving main are not pinned platform certification. Implementation plan
  must pin platform ABI/constants against supported release headers/documentation,
  verify runtime capabilities and test actual filesystem before claiming support.
