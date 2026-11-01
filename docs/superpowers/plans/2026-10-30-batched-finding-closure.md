# Batched Finding Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, one executor. Steps use checkbox syntax. No commits/push/releases; user-selected main workspace remains.

**Goal:** Native Finding closure validates multiple real related receipts and their coverage union without synthesizing execution or weakening Gate.

**Architecture:** New batch proofs use the existing base execution validator for every member, then compute related coverage union. finding_closure owns batch-only bounded reads and format selection; old single-proof transition/Gate retain their separate existing loaders and old closure validator. A new batch VERIFIED branch explicitly uses transaction.stage/publish rather than the current atomic_write.

**Tech Stack:** Python 3.11+, existing PyYAML/jsonschema, argparse, hashlib, source_access and native transaction owner. No new dependencies.

**Spec:** docs/superpowers/specs/2026-10-30-batched-finding-closure-design.md

## Global Constraints

- User selected A: repeated --evidence; no external aggregate-execution manifest.
- Multi-proof version1, 2–64 refs; each <=4MiB, combined <=16MiB, preparation and Gate reread identical. Exact cap allowed; excess/incomplete input rejects without truncation. Canonical duplicate refs reject.
- Every receipt must have actual successful related test execution and current HEAD/workspace; any invalid member fails whole closure.
- Legacy evidence string and new closure_evidence are mutually exclusive; old readers must reject the latter, not silently validate first receipt.
- Every new batch requires current nonempty required_tests union. Only severity == critical requires approval in existing finding.closure; major batch does not read or require closure. Old single evidence loader/validator/critical behavior unchanged; existing unenforced approval gap documented, not fixed here. No reproduction/closure/state shortcut.
- No source/evidence payload rewriting, new dependencies, destructive storage, full-suite fallback, commit, push or release.
- Native TASK117 contract/interface/scope/state admission precedes implementation; independent review still required. Current FIXED finding is not pre-closed.

## Review Focus

- Duplicate refs using alternate accepted spelling: normalize first, reject duplicates (Task1).
- Valid legacy evidence plus malformed batch metadata: refuse mixed format, never fallback (Tasks1/2).
- One passing complete receipt plus one invalid extra receipt: reject entire collection (Tasks1/2).
- New batch member missing scope, non-related/full/custom/build/review or mixed with related: reject before any coverage union; never call old early-return closure validator per member (Tasks1/2).
- Batch required_tests changes after VERIFIED/CLOSED or batch critical approval missing: Gate rechecks; legacy single branch unchanged (Task2).
- Source changes before publication: same-owner pinned inputs, reject without writes. Callback drift after apply: existing rollback/recovery reports partial side effects if externally blocked, never pretend unconditional zero mutation (Task2).

---

### Approved prerequisite: Native Q3 replanned continuation

**Files:** src/harness/plan_reconciliation.py; tests/test_plan_mutation.py, tests/test_plan_execution.py, tests/test_plan_mutation_cli.py.

- [x] User explicitly accepted necessary continuation prerequisite after native empty-history refusal. Write terminal-prefix/pending-suffix actual RED and negative histories in temporary roots.
- [x] Limit self-hosted bootstrap edits to private initialization guard and tests while task remains PLANNED; do not hand-edit state. Schema-valid replay, no active item, a real terminal prefix and pending suffix, same-task frozen Alignment with revisions required. Full seal/boundary caller validation unchanged.
- [x] Observe195related plan tests GREEN, then actual native PLANNED->IMPLEMENTING and P009BEGIN. Preserve empty initial flow, sync-fingerprint nonempty refusal, original journal and stale-proof rules. This approved bootstrap is not a claim implementation admission preceded its own prerequisite fix.
- [ ] Include prerequisite in fresh native evidence, independent review and final proof; no arbitrary nonempty-plan or unfrozen-contract acceptance.

### Task 1: Shared batch closure proof with bounded immutable receipt references

**Files:** Create src/harness/finding_closure.py, tests/test_finding_closure.py; modify src/harness/evidence_validator.py, src/harness/schemas/adversarial-finding.schema.json, tests/test_evidence_validator.py, tests/test_finding_schema.py.

**Interfaces:**
- `validate_finding_closure_batch(finding, records, impact, *, current_head, current_workspace) -> None` in evidence_validator: first reject each unsupported type/scope; call existing base validate_evidence per record, then nonempty required union and batch-only critical approval. Do not call validate_finding_closure_evidence per member.
- `prepare_closure_proof(root, finding, references, impact, *, current_head, current_workspace) -> dict` in finding_closure: returns exactly `proof` (the closure_evidence document), `sources` (canonical root-relative receipt path -> raw bytes), and `identities` (same path -> [device,inode]). Caller owns Finding/impact snapshots separately; no new task-state gate or current-task read. These are validation inputs, not synthetic execution records.
- `closure_proof_kind(finding) -> str`: returns `single` or `batch`; rejects both/neither/unknown batch version. Does not load legacy receipts or impose new limits on them.
- `validate_persisted_batch_closure(root, finding, impact, *, current_head, current_workspace) -> None`: batch only, same 2–64/4MiB/16MiB limits, verify persisted byte digests then fresh per-member execution/union/critical policy; recheck captured per-invocation source bytes/inode before return, without inventing cross-invocation persisted inode binding. Legacy callers retain their current loader and validate_finding_closure_evidence.
- `require_closure_sources(root, prepared) -> None`: reopens prepared batch sources and checks exact bytes+identity. Caller invokes before publication and in a NEW transaction.publish after_publish callback; receipt paths never enter write set.

- [ ] Record native incremental scope/contract/public CLI interface admission before code. Preserve original task/finding/proof and prior independent review record.
- [ ] Write meaningful RED: two actual qualified receipt fixtures each cover a disjoint current required selector; combined proof should succeed where existing single-record closure rejects partial coverage. Observe assertion failure, not absent-import-only RED.
- [ ] Add batch validation negatives: failed/stale/missing execution, wrong HEAD/workspace, unsupported type/scope, incomplete current required set, no required set, critical approval absent/foreign; ensure valid major union and correctly approved critical union.
- [ ] Implement strict batch type/scope checks and validate_evidence per member, then union; do not trust covered_tests alone or reuse old closure early-return semantics. Explicit non-related-only and related/full mixed tests must fail before union. Legacy closure function, direct transition Path.read_text, Gate source_access.read_text, non-related early return and optional critical flag behavior remain unchanged. Record existing critical gap as deferred, not an implicit bug fix.
- [ ] Implement canonical no-follow bounded loading/byte-digest capture; reject duplicate aliases, traversal, over-limit/truncated/invalid JSON, source swaps and arbitrary type inputs. Never deserialize raw source in error messages.
- [ ] Update BOTH VERIFIED and CLOSED schema conditionals: retain existing RED/GREEN/regression/time requirements and diagnosability compliance format, replace adversarial evidence-only requirement with mutually exclusive single evidence or closure_evidence. Test legacy acceptance, batch acceptance and both/neither/unknown version rejection at both states. Pinned old schema rejects pure new batch; new schema must additionally reject mixed documents that old additionalProperties:true would allow.
- [ ] Run bounded unit scope: python3 -B -m pytest -q -p no:cacheprovider tests/test_finding_closure.py tests/test_evidence_validator.py tests/test_finding_schema.py. Actual native evidence, absolute PYTHONPATH.

### Task 2: CLI transition and Gate consume identical proof, preserving atomicity

**Files:** Modify src/harness/cli.py, src/harness/controlplane.py, src/harness/quality_gate.py; tests/test_finding_transition.py, tests/test_finding_lifecycle.py, tests/test_quality_gate.py; Context tests only at actual affected seams.

**Interfaces:** CLI `finding transition FND-nnn VERIFIED --evidence A.json --evidence B.json`; existing direct Python `evidence=str` remains accepted, new sequence allowed only adversarial VERIFIED. No change to diagnostic Finding closure semantics.

- [ ] Write CLI RED: temp FIXED adversarial finding with independently qualified partial receipts closes VERIFIED only when repeated evidence covers all impact required selectors. Separate case missing second member must remain FIXED byte-for-byte.
- [ ] Parse repeated evidence, preserve zero/one argument behavior at other states; reject >1 on other states/diagnosability. Normalize at shared boundary, not multiple ad-hoc branches.
- [ ] Add new batch VERIFIED publication branch under existing owner: capture no-follow Finding/impact and batch receipt snapshots; stage only updated Finding. transaction.publish uses expected_sources={finding-relative-path: original-finding-bytes} and exact expected_artifacts; receipts/impact are not write-set entries. Recheck input bytes+inode and workspace before publish and in newly supplied after_publish callback, following finding_refresh's updated-Finding check pattern. Keep old single/other states on existing atomic_write; never claim it has a callback.
- [ ] Gate uses closure_proof_kind: legacy single stays existing loader+validator, batch uses validate_persisted_batch_closure. Test both VERIFIED/CLOSED for member missing/failed/stale, same-semantic changed raw JSON, altered digest, missing/unknown/mixed metadata and expanded required_tests; valid union accepted. Include exact cap and excess/partial-read cases at Gate, not only preparation.
- [ ] CLOSED with zero evidence arguments preserves persisted closure_evidence byte-for-byte apart from existing lifecycle fields; repeated 2+ evidence arguments reject. No new batch must be submitted for VERIFIED->CLOSED.
- [ ] Only severity == critical batch requires closure.mode == related, critical_related_approved is True, source == user, and nonempty approved_at; impose no additional approval-time freshness. Major batch does not read or require finding.closure. In new VERIFIED branch, existing --critical-related-approved writes approval into the in-memory candidate Finding BEFORE policy validation; original FIXED need not already contain closure, and nothing is persisted before validation/publication success. Test major success without closure, critical denial without approval, critical success via that flag when original has no closure, and Gate enforcement of the persisted fields. Approval is Finding-level, not digest-set-bound: valid replacement receipts do not need another approval when flags remain valid. Keep regression proving legacy critical single-without-closure remains accepted as current code permits; document deferred policy gap instead of silently turning historical findings red.
- [ ] Add transaction failure counterexamples: prepublish input drift leaves original Finding unchanged; callback source drift triggers normal rollback; externally occupied rollback target reports failure and retains objects instead of claiming no side effects. Rejected/aborted batch never rewrites source receipts.
- [ ] Verify Context schema/source traceability and installed resources support new Finding format; do not weaken schema/resource access to make it pass.
- [ ] Run related lifecycle/Gate/CLI/source-access tests in preplanned serial batches, no blanket suite. Preserve every failed receipt; source edits stale old proof.

### Task 3: Operator guidance, fresh evidence and independent review handoff

**Files:** Update relevant README command documentation, skills/reproduce-finding/SKILL.md, skills/collect-evidence/SKILL.md, tests/test_readme_docs.py and package tests only if command/resource contract requires.

- [ ] Document repeated evidence, partial-batch failure, per-member freshness/digest binding and current required-set coverage; CLOSED zero-argument preservation; new batch-only critical enforcement versus explicitly deferred legacy gap; existing finding.closure approval is Finding-level, not bound to receipt digests. Explain no synthesized execution, no automatic blanket approval and unchanged RED/GREEN/single-proof loaders.
- [ ] Native enroll final exact impacted files/tests. Build batch manifest with complete required selector union and conservative deadlines from same-source timing; run serial. Collect only real missing/stale proof, never edit old metadata fingerprints.
- [ ] Run offline supported-backend wheel/resource/isolation checks, focused lint and diff-check; install no dependencies and change no release pin/version.
- [ ] Independent reviewer inspects new batch validation/old-reader behavior/locking/critical approval. Report any product findings through native lifecycle, not self-certification.
- [ ] Only after valid new actual proof, use new native multi-receipt interface for FND001. Native transitions and current evidence association refresh are separate audited steps; preserve original RED and all historical receipts. Never mark overall task done without final native Gate CONVERGED and explicit DONE.

## Self-review

Design invariants1–8 map to Tasks1/2; all new loader/limit/critical rules explicitly batch-only. Legacy single loaders, early return and critical behavior pinned by compatibility tests. Both terminal schema blocks, CLOSED zero-argument retention, Gate cap checks, mixed scope and staged transaction callbacks have explicit tests. No-delete/no-real-storage/no-unreviewed acceptance map to all tasks and Task3. No new cache, separate manifest, alternate Gate or dependency. Existing task scope remains authoritative until native amendment; design files are not runtime execution permission. First implementation action after user document approval: native scope/contract/interface routing, not source edits.
