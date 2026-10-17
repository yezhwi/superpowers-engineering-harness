# Test-scope origin and migration (v0.3.2 implementation contract)

Status: Gate/add and selected-authority reconcile apply implemented; formal task
acceptance and independent review pending. Minimum supported
reader after activation: **v0.3.2**. No production migration authorized.

Implemented so far: private replay/publication/reconstruction, replacement-task
origin creation, transactional fresh initialization/identity binding, Alignment v3
origin protection and canonical source enrollment (Context projection v5).
Selected-source historical addition provenance is implemented: optional
`historical_sources` on MIGRATE authorization and proposal must match exactly
(including ordered path/byte hash/test-set hash), with every source in selected
Decision scope. Snapshots must strictly increase; live canonical files and repeat
sources cannot serve as history. Baseline preserves original set; one immutable
`HISTORICAL_ADD` prefix entry per approved snapshot retains all increases. Current
extras alone, chronology guesses and a general add grant confer no migration
permission. Reconstruction still grants no retirement; loss of any original or
historical item remains blocked. Changed source bytes revoke origin trust.
RETIRE/REBIND replay and explicit `impact migrate-scope --file` are implemented.
Replay validates one exact selected grant per event (multiple grants require
separate ordered events), constraints, impact-before authorization, artifact scope,
changed REQ/INV cases, mapping continuity and current final mappings. RETIRE adds
only explicitly approved replacements; REBIND cannot shrink or expand required
scope. All linked current plan IDs must be authorized; retired references cannot
remain in any case or plan surface. Required obligations retain statically valid
mapping, but never gain verified/evidence status through replay.
Common Gate/Control Core, verification/review/Gate/completion stage entry and
transactional `impact add-test` are now activated together. Missing/invalid origin
blocks every profile; scope blockers require user authority, never automatic resume.
CLI add refuses missing provenance before legacy task-scope initialization, and
publishes impact/audit/seal in one recoverable transaction. Reconcile apply is
available only with trusted origin and operation-specific selected authority.
MIGRATE authority never permits RETIRE/REBIND. CLI reconstruction may successfully publish trusted history and
still report BLOCKED for unaudited removals; it never retires those paths or resumes
task state.

## Authoritative artifacts

All artifacts below are task-bound, schema-versioned canonical sources. They are
included in Context capture/read scope, not excluded as derived telemetry.

- `test-scope-baseline.yaml`, version 1: actual initial authorized `required_tests`,
  task ID, origin (`new_task` or `authorized_reconstruction`), timestamp, exact
  source hashes. Reconstruction records original historical impact bytes/path,
  original-set hash and selected user decision. Current reduced scope is never
  automatically promoted to original scope.
- `test-scope-audit.yaml`, version 1: ordered append-only entries. Each contains
  sequence, previous entry/baseline hash, timestamp, operation, exact before/after
  sets, artifact before/after hashes, decision references and selected-option
  hashes, reason, affected owner/case bindings and plan references. Entry digest
  excludes only its own digest. Every formal addition enters the chain.
- `test-scope-seal.yaml`, version 1: baseline raw-byte hash and audit head/hash;
  bound task/origin facts and migration decision bytes. Publication updates audit
  and seal together. Missing/truncated/rewritten members fail closed.
- Alignment freeze version 3 extends version 2 with immutable baseline and origin
  authority facts. Audit head is mutable and **not** frozen into Alignment.
  Version 1/2 remains readable but never manufactures trusted scope. Explicit
  reconstruction may introduce its independently decision-bound scope seal;
  it never auto-freezes or upgrades existing Alignment.
- Activated origins add `gate.test_scope.minimum_reader: 0.3.2` in same publication.
  Existing v0.3.1 Gate schema rejects this unknown property. This compatibility
  tripwire is not a security claim against modified/downgraded readers.

Baseline order is preserved for provenance; comparisons use unique exact test
identifiers. Duplicate or noncanonical references are invalid. No path globbing,
collection, module import, business execution or environment access establishes
scope authority. Missing retired historical paths do not require restoration.

## Creation

Task creation records **actual initial** `required_tests`, including nonempty
custom-template sets. Task and baseline/audit/seal become visible in one existing
transaction/replacement publication. Empty baseline only when actual set empty.
Existing unmanaged metadata is not silently blessed as new-task provenance.

Fresh initialization with an unassigned task ID needs an explicit identity-bind
transition preserving its initial-set/source proof. ID reassignment cannot move
another task's origin. Replacement/recovery archives previous scope artifacts
alongside previous task/impact, then creates a distinct task-bound origin.

## Selected-option authority

`decision.options[].test_scope_authorization` is optional structured authority;
only **actually selected**, ACCEPTED, same-task, user-selected option is usable.
Authorization identifies exact operation, impact source hash, frozen contract,
original source/set for migration, retired paths/reasons/replacements, affected
before/after case bindings and plan references. Grant is bounded to declared
metadata surfaces and preserves obligations/risk/evidence/authorization fields.

For a current-task, actually selected ACCEPTED RETIRE/REBIND option, Context
captures exact canonical `plan.yaml` as a scope-guard source, including FAST.
Enrollment precedes the first reconciliation and remains through replay; absence
is versioned too. This does not enable ordinary Plan projection, reconciliation
or execution, and does not enroll `plan-execution.yaml`. Replay still verifies
all actual Plan links against selected authority; malformed or unapproved links
remain blocked, and a changed captured Plan makes the prior view stale. Without
such a selection or another explicit source declaration, ad-hoc FAST Plan files
remain outside Context inputs. MIGRATE alone adds no implicit Plan-guard source.

Scope and constraints are checked, not inferred from an ID or recommendation.
Supported constraint codes: `PRESERVE_OBLIGATIONS`, `PRESERVE_RISK`,
`NO_EXECUTION`, `NO_RELEASE`; unsupported/ambiguous prose fails closed. General add authority grants no
retirement. Existence of replacement path grants no business equivalence. Grant
must account for every affected reference; still-in-scope must obligations retain
executable mapping. Later fresh test evidence remains necessary.

## Replay and blockers

Public assessor runs for FAST/STANDARD/STRICT, including preflight. Shared Gate,
Context Control Core and stage-entry checks use same replay. No initializer is
called by assessor or read-only planners.

- Missing/untrusted baseline, bad seal/schema/hash/task/sequence/source or
  truncated/rewritten audit: `TEST_SCOPE_AUDIT_INVALID`.
- Current scope loses replayed authorized path without matching retirement:
  `TEST_SCOPE_RETIREMENT_UNAUDITED`.
- Actual selected decision, constraints, source/contract or mapping insufficient:
  `TEST_SCOPE_RETIREMENT_UNAUTHORIZED`.

All three require human authority; autonomous recovery cannot approve them.
Sealed boundary drift retains original `USER_AUTHORITY_REQUIRED/HALT_AND_WAIT`
flow. Repair operation may address only its explicitly authorized scope defect;
other Guard blockers still stop. No automatic freeze/resume/verified/COMPLETE.

Historical prefeature unchained additions remain distinguishable from postfeature
formal additions until explicit reconstruction incorporates their provenance.
Missing origin stays blocked; compatibility never turns present subset into
trusted baseline. Subsequent formal add updates impact, audit and seal together,
including idempotent duplicate handling; add-then-hand-delete must remain blocked.

## Explicit reconstruction

`harness impact migrate-scope --file migration.yaml` verifies task/source CAS,
traceable original impact/source bytes, exact approved original set and selected
migration grant. Original 64-path source cannot be replaced with current 46-path
subset. Historical additions need declared provenance. Missing/reduced current
paths are not silently retired by reconstructing baseline; distinct selected
retirement authority and obligation checks remain necessary.

After trusted reconstruction reports unaudited missing paths, submit a distinct
exact selected RETIRE grant through `harness impact reconcile --file proposal.yaml`
(or inspect it with `--dry-run`). Preparation replays immutable origin and the
complete audit before evaluating the proposed projection; it never promotes current
46 to original 64. Event before-set is replayed 64, while artifact-before hashes
bind actual current reduced bytes. Selected retirements/replacements must explain
entire difference, preserve previous binding continuity and validate all projected
must mappings and plan references. Only the resulting validated candidate can
discharge its `TEST_SCOPE_RETIREMENT_UNAUDITED` blocker. Other Guard blockers,
invalid origin/audit/authority/CAS and unrelated mapping drift still stop. Empty
proposals, REBIND, ordinary reads and add-test cannot acknowledge missing scope.
Baseline bytes and existing audit entries remain unchanged; publication appends
one authorized event, without restoring missing historical files or resuming task.

Lock protects canonical read/plan/publication. V2 durable publication retains
actually displaced inodes under a journal outside staging. Both independent final
freshness/replay checks run inside the active operation before commit; no outer
unjournaled compensation. Unknown/interleaved bytes or symlinks halt recovery,
retaining journal and unmanaged data. Failed prepublication writes zero new
canonical scope entries. No read-only diagnostics initialize/reconstruct origin.

## Publication platform and retained-data operations

Current candidate is macOS-only. Local filesystems must provide validated atomic
exchange/no-replace, no-follow descriptor access and required synchronization.
Linux, Windows and other OS publication backends return `PUBLICATION_UNSUPPORTED`
before opening directories or creating probes; Linux is excluded from acceptance.
Network/FUSE/remote/special filesystem support and power-loss certification are
not inferred from symbol presence or capability success. No unsafe rename fallback.

This is inode/byte preservation, not content CAS or a permanent canonical-path
freshness guarantee. Conflicting unmanaged objects may be relocated into reported
retained storage. An editor holding their FD can continue writing; advisory locks
only coordinate supported Harness operations. No implied safety upgrade for
standalone atomic writes, task-directory swaps or arbitrary external readers.

- `.harness/.staging/` holds retained prepared input, never recovery authority.
- `.harness/.transactions/` holds active descriptors. Unknown/unresolved entries
  block admitted Gate/transition fact use; read-only admission never auto-recovers.
- `.harness/.publication-retained/` holds displaced objects, probes, frames and
  terminal recovery data. Terminal retention does not itself mean pending work.
- New private directories request `0700`, new files `0600`; displaced objects keep
  original inode/mode, and existing directories are not retroactively hardened.
  Retained bytes may be sensitive metadata: never treat storage as public logs or
  evidence/Decision authority. Indefinite growth can cause `ENOSPC`; no pruning command
  or automatic age-based cleanup exists. Cleanup needs separately designed explicit
  authority; deleting descriptors/retained objects is not a supported repair.

## Activation and rollback

Joint Gate/add-test and apply mechanisms have related creation/migration/replay,
process-death recovery, authorization and old-reader tests. Migrating all existing
tasks first is not required; their missing origins stay blocked.

`harness impact reconcile --file proposal.yaml --dry-run` uses same pure
preparation/replay permission checks as apply; it writes no authoritative bytes and
runs no tests/business/environment commands. Without `--dry-run`, CLI publishes
existing case test mappings, approved plan surfaces, impact and append-only audit/seal
as one durable bundle, with pre/post freshness, publication-entry CAS and final
replay. No-op returns empty updated hashes/audit refs. Invalid grants cannot be
accepted by supplying only a DEC ID or a replacement filename. One exact selected
grant per operation is supported; ambiguous or multi-grant union is rejected.

Apply preserves task/requirement/invariant status, statements, priority/severity,
evidence and findings. Updating plan surfaces never updates execution disposition
or proof receipts; existing Plan Gate may therefore correctly require fresh proof.
Real TASK-092 has MIGRATE-only DEC-002, not retirement authority; no real retirement
was performed when enabling CLI. Public interface availability is not permission
to mutate any particular task.

Do not roll back reader to v0.3.1 and bypass scope blockers. Retain versioned
baseline/audit/seal, decisions, historical RED and immutable evidence. Restoring
program files alone is not authorization to erase metadata. Full-disk rewrite
of all sources/seals is outside existing seal threat model; hash chains prove
consistency, not unforgeable user consent.
