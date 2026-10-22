# Gate-accepted candidates and controlled commits

Status: TASK-103 implementation design, DEC-043 / INT-010. Implementation and bounded anonymous-repository tests exist; final independent review, package qualification and task Gate remain pending. This document does not claim release qualification or authorize committing this repository.

## Boundary

An operator explicitly enrolls `gate.candidate_commit` before contract freeze:

```yaml
gate:
  candidate_commit:
    format: candidate-commit/v1
    capability_version: 1
    minimum_reader: 0.3.2
```

Preparation requires that policy; it never adds policy, stages files or reseals alignment. Package/minimum-reader version stays 0.3.2. Old strict Gate schema readers reject the new key; there is no claim that all old nonvalidating commands reject it.

Default Gate, ordinary Git, generic evidence freshness/reuse, task states and the read-only Git query allowlist remain unchanged. Candidate receipts cannot become generic fresh evidence merely because HEAD or tree contents match.

## Identity and execution domain

The domain-separated candidate ID binds the task identity/type, stable risk/scope/Git baseline, parent/full ref, repository/common-directory identities, actual supported Git configuration, selected stage-0 entries/deletions, index bytes/identity, tracked/untracked/protected inputs and finite semantic specification sources. Operational state, grant values, verification status, Plan progress and future proof/review/acceptance objects are not immutable candidate identity.

The user index is the staging interface. An owned temporary index creates the candidate tree; the user index is neither rewritten nor locked by this feature. Unsupported index flags, special files, escaping links, Git modes/configuration or repository states refuse. Effective configuration is inspected and bound, not silently replaced by disabled hooks/signing or ignored system configuration.

Proof executes in a fresh writable copy outside Git repositories, never in a retained export under the source repository. Inputs are read-only; generated paths must be declared. The three profiles are `pytest-junit-v1`, `python-module-build-v1` and `python-script-v1`. They bind interpreter/tool/dependency bytes, exact argv, declared environment, generated outputs and before/after input hashes. Python uses `-S`, sanitized dependency paths and disabled ambient pytest plugin discovery. Actual collected/executed JUnit node IDs, including parameter IDs, establish test-plan coverage; selectors alone do not.

Runtime qualification requires a native Darwin CPython image whose reported actual executable matches the declared resolved image. Runtime manifests hash actual stdlib files, vendor LIBDIR native libraries, optional interpreter/stdlib-zip configuration and native inspector bytes. Native load commands/rpaths must resolve within captured runtime roots; `/usr/lib` and `/System/Library` shared-cache libraries remain trusted platform inputs, identified by recorded platform identity. Private bytecode prefixes avoid unbound ambient `.pyc` execution. Proof completion and Gate/commit revalidation reread runtime bytes/membership, not stat-only caches. Parsed native load commands alone may be cached by actual image and inspector digests.

This is a cooperative finite-input execution contract. It is not a whole-OS filesystem CAS, OS sandbox, network blocker, hidden-dependency detector, arbitrary build runner or defense against arbitrary same-UID changes.

## Native verification and Gate

`CandidateAssessmentView` is an explicit in-memory adapter selected by the task-bound `.candidate-active.json` pointer. It changes evidence-domain lookup/freshness only. It does not verify pending requirements/invariants/interfaces, complete Plan items, waive review/type/coverage checks or remove native blockers.

Native verification stores complete `.harness/evidence/candidate-proof/<hash>.json` references. Plan transitions retain native replay and terminal-proof rules; candidate proof receipts carry candidate/tree/export identity rather than fabricated generic commit/workspace fields. Complexity, diagnosability and interface reports are validated and recorded in the candidate review namespace before review admission.

| Command | Live phase |
| --- | --- |
| prepare | IMPLEMENTING |
| prove | IMPLEMENTING, VERIFYING, REVIEWING, GATING |
| review-record | VERIFYING, REVIEWING, GATING |
| candidate Gate | GATING |
| commit | CONVERGED, DONE |
| status | known candidate; read-only |
| recover | known operation and its recovery protocol |

The finite Gate source capture binds actual final specification/control documents, member sets, namespaced evidence, tool code and Git policy. Architecture-required candidate mode is unsupported in v1: its existing assessor consumes the live worktree, not the immutable export. Policy admission refuses that combination; it never turns architecture off or treats an unadapted live assessment as candidate proof. Ordinary architecture-required Gate behavior is unchanged. Gate revalidates preparation and proof inputs around the original assessor. Only its PASS with no blockers permits acceptance. The candidate path reuses the original convergence persistence/policy: PASS reaches CONVERGED; a blocked assessment takes the existing typed recovery/convergence route. It does not implement a second state machine. Ordinary CONVERGED → DONE admission remains required.

## Commit and recovery

A separately granted, live user commit authorization is required. Push is never implied. Before durable PREPARED, the operation fixes message bytes, identities/timestamps, parent/tree/full ref, proposed commit OID, accepted-source hashes and grant receipt. Private, no-follow, inode-preserving, fsynced metadata publication reuses the existing transaction journal.

Grant consumption and `REF_CAS_STARTED` are published together before the fixed expected-old `update-ref` CAS. Git owns its ref lock. Metadata publication and Git ref publication are distinct commit points, not a fabricated cross-filesystem transaction.

Recovery compares actual ref with recorded parent/proposed:

- **Parent:** revalidate all bound inputs and require a live independent grant. If a previous attempt consumed its grant before crashing, the operator must grant again; a historical consumed receipt is not permission for another ref attempt.
- **Proposed:** finish the captured trace forward, without another CAS or new grant. Later user edits do not erase historical acceptance.
- **Foreign ref or unknown metadata:** refuse; never roll back/reset user state.

A failure after ref publication reports `REF_PUBLISHED_POSTCHECK_FAILED`, retaining true mutation/operation identity. Same-message retries are idempotent; changed payloads refuse. Terminal operations and the active pointer archive with the originating task. Shared admission blocks ordinary mutators during pending operations; only narrowly validated same-task commit grant/revoke and explicit recovery exceptions apply.

## Public result and delivery

All candidate-family commands require `--json`. INT-010 defines exactly 14 fields: `schema`, `ok`, `command`, `task_id`, `candidate_id`, `operation_id`, `acceptance_id`, `parent_commit`, `proposed_commit`, `phase`, `mutation_started`, `reason_code`, `message`, `artifact_ref`. The schema is `candidate-command-result/v1`; inapplicable IDs are null. Artifact references are restricted to candidate evidence or known operation records.

Success exits 0, supported refusal 1, usage 2 and unexpected internal failure 70. Authority refusal retains native `POLICY: USER_AUTHORITY_REQUIRED` / `DIRECTIVE: HALT_AND_WAIT` diagnostics. Argument errors and unexpected exception details never echo tokens, absolute paths, message bytes or Git stderr.

Result correlation runs under the same reentrant task lock as the action. Console delivery occurs after releasing that lock. Unreadable/ambiguous intent is `phase: UNKNOWN`, `mutation_started: null`, not a false assertion of no side effects. Known after-ref outcomes retain their recorded phase and `mutation_started: true`. Broken stdout/stderr do not retry mutation or replace the primary durable result.

## Context and qualification limits

Context versions only the explicit pointer and finite immediate candidate namespaces. It rejects symlink namespaces and uses no-follow/nonblocking regular reads for candidate files. Historical metadata validation is shared with recovery; Context checks known commit tree/parent through existing allowed read-only queries.

`control.candidate` separates historical acceptance/commit records from current HEAD relation. Current readiness is explicitly `NOT_ASSESSED`; generic evidence reuse is false, including a later HEAD with an identical tree. Status is read-only and points to existing records rather than creating a new status artifact.

Anonymous STRICT tests exercise real proofs/builds, native obligation/Plan verification, review admission, original Gate convergence/blocking, DONE, separate commit grant, fixed ref CAS, recovery and task archival. Fault cases cover process death, post-ref publication failure, internal exit 70, broken pipes, metadata corruption and special files. These bounded tests do not replace final source-frozen required tests, independent review, private installed-package qualification or the real task's formal Gate.

Operator instructions: [Controlled candidate commits](../../candidate-commit.md).
