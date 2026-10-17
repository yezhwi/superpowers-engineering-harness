# TASK-092 scope reconstruction authorization package — DRAFT

This package prepares authorization materials only. No Decision was proposed or
accepted, no scope baseline/audit/seal was published, and no migration was run.
The user's confirmation authorized preparation, not `approve_reconstruction`.

## Proposed choice

Approve `approve_reconstruction` in `decision-proposal.yaml` only after reviewing
source limitations below. Alternative: `request_original_records`; retain current
`TEST_SCOPE_AUDIT_INVALID` until original records are supplied.

Scope: isolated TASK-092 only. Original required set: empty. Approved historical
increase requested: all 10 paths below, captured as one cumulative snapshot.
Retirements: none. Binding changes: none. Risk/profile remains Q3/STRICT. No
execution/release, auto-freeze/resume, verified/COMPLETE, production migration,
commit or push permission follows from this package.

## Original-set evidence

`original-impact.yaml` copies actual template bytes, not a newly synthesized empty
manifest. SHA-256:

`ce4672fd8e6a8bc7da97ceb870cb91d0a224adbfa994b27b3c3f03b77301fd1c`

Both earlier TASK-092 Context records name this exact `impact.yaml` byte hash:

- `.superpowers/sdd/2026-10-14-v032-context-evidence-efficiency/context-checkpoint.yaml`
- `.superpowers/sdd/2026-10-14-v032-context-evidence-efficiency/context-resume.yaml`

Their file hashes are identical:
`da2c3f344a3e0ddbe6630a3c33dcac9d850ef6cc6aabce828985b11ad11d02ce`.
They represent one duplicated observation, **not two independent proofs**.
The template currently matches the recorded bytes; ledger also records empty
initial impact. Context is derived historical corroboration, not migration
permission or an immutable trusted origin. The operator must approve reconstruction.

Original ordered test-set hash:
`sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.

## Historical additions requested

`historical-impact.yaml` is an exact copy of current preactivation impact bytes.
It was captured **now**, not recovered from an original historical snapshot.
SHA-256:

`b2639457b89fe5b7faafdb18a0b8ab57647f8d3ac5e580d6d183e262588369ec`

Ordered test-set hash:
`sha256:5a8da2b4918c8dbb72b55b2c0ba5a02e45e079b0ef95cc2e2fb9387a605aec0f`.

| Path | Current file SHA-256 (inventory only) |
| --- | --- |
| tests/test_evidence_plan.py | 64cc562c9ff9d085c3c4eb71c992f20cb5165b06e47ed63e7f9eb854a36f9359 |
| tests/test_impact_reconcile.py | 20517ab77cd4bf6f4a2b4566614dfa4005a736db75383a18d123d1cf55e15914 |
| tests/test_test_scope.py | a5a160d339bf31ebb0f9302a5ba0c5fa9fa8267016195aedb1037623f1aa90d0 |
| tests/test_scope_migration.py | 59ab5e7d34d229c8c60af74344e8f5db1d827019be8df92189cbbc20e1a13d2f |
| tests/test_scope_creation.py | ba7afa9baf79dd237f9a43e353b1f53ac0cc9b249fad6b1ed0ee6f28b083fbf4 |
| tests/test_scope_init.py | 104632a0d7dbe2c746ff2387534b0a0f22f45f2e6ff162fc143aa537a719bc80 |
| tests/test_scope_seal.py | 3e0607c2f42b2857dafe8c01985956e975eec8dbbc889f715a42acb43269a55d |
| tests/test_scope_authority.py | 2220a18fd50217c4e4ac24d2f30810bfda07943691e883fbc00d722324baa26f |
| tests/test_scope_migration_cli.py | 250ef31058e34c22aa3abe76a89cfd557c86c77e081d601c7c8ddedce9cc9d7a |
| tests/test_scope_joint.py | 13e6e028016c4ba419fa2bfc93199df21df20622ff83821a0a08fe8fb75571ed |

Ledger checkpoints record these paths being added through the prefeature CLI,
including `test_scope_joint.py` before joint activation. Original intermediate
impact files and authenticated per-add receipts are unavailable in the inspected
finite source set. We therefore propose one explicit cumulative user attestation,
not invented intermediate timestamps or files. This cannot independently establish
historical chronology or prove no earlier path was lost. Current target file hashes
show present inventory only, not historic versions, business equivalence or evidence.

## Binding and freshness

Proposed expected current impact hash is the snapshot byte hash above. Frozen
Alignment contract hash:
`sha256:7cd0e78823cd3cad8befe5c71b3a47f6a27fe63652d096a758c0a643696ef518`.
Task currently IMPLEMENTING; task creation timestamp is null. No timestamp inferred.

Any impact/source/contract change requires rechecking and, where grant descriptors
change, renewed approval. No actual `decision_ref` or runnable migration proposal
is fabricated. After explicit option approval, persist through `harness decision`,
use actual allocated Decision ID, then verify migration freshness and Guard before
publication. Accepted MIGRATE would preserve original set and record the cumulative
increase as `HISTORICAL_ADD`; it would grant no future retirement or rebind.

## Verification boundaries

Preparation checks only declared source bytes, YAML/schema shapes, path inventory,
set hashes and equality. No pytest collection, target imports, repository-wide
coverage search, business/environment tests or production task reads. No Gate,
state transition, Decision acceptance or migration used to bypass missing origin.
Historical Context snapshots are preserved byte-for-byte.
