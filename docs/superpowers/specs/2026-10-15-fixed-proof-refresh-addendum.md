# FIXED proof refresh — bounded remedy proposal

Status: APPROVED by user's “确认” following proposal. Not implemented.
Approval includes bounded command and anonymous-fixture bootstrap ordering only;
no lifecycle bypass, acceptance, commit or release authority.
Parent: approved publication-ownership-recovery design and implementation plan.

## Observed prerequisite restriction

Isolated anonymous fixture follows supported CLI PROPOSED -> REPRODUCING ->
CONFIRMED -> FIXING -> FIXED. After product-file edit, original GREEN validation
correctly rejects EVIDENCE_WORKSPACE_STALE. A newly collected same-finding/test/HEAD
GREEN validates against current workspace. CLI cannot bind it: FIXED -> FIXED is
forbidden and finding refresh-proof is absent. Finding and old RED/GREEN hashes
unchanged. This is workflow diagnosis, not adversarial bug confirmation or real
TASK092 defect proof; fixture uses synthetic custom records from existing tests.

Script/log: `.superpowers/sdd/2026-10-15-publication-ownership-recovery/diagnose-proof-refresh.py`
and `proof-refresh-diagnosis.log` (exit0). No product code or actual task changed.

## Proposed command and limits

`harness finding refresh-proof ID --evidence RECEIPT`

Initially support adversarial findings in FIXED only, sufficient for actual FND001.
Reject other categories/states rather than silently change closure semantics.

- Load/validate schema and unchanged registered regression test, finding id, task,
  original RED and historical GREEN references. Do not require historical GREEN
  workspace to equal current; it remains historical, never reused as current proof.
- New receipt must independently pass existing evidence validator: success, exact
  same finding/test/current HEAD and workspace, before==after fingerprint. No
  changes to can_reuse_evidence or Gate active-proof freshness.
- Keep status FIXED, test, confirmed_at, original RED and fix identity unchanged.
  No VERIFIED/CLOSED/COMPLETE, task transition or obligation verification.
- Append optional structured regression_test.green_evidence_history entry recording
  old/new reference and refresh timestamp; update active green_evidence pointer
  atomically with history. Never overwrite receipt bytes. Repeating same reference
  is byte-idempotent; missing/failed/wrong-finding/test/HEAD/workspace proof rejects
  with zero canonical changes. Define/validate optional history schema explicitly.
- Hold existing shared lock and require no pending publication before reading.
  Revalidate input bytes and active source versions. Publish using approved safe
  transactional engine; do not add another check-then-replace control write while
  FND002 is open.
- Command is proof maintenance, not authority to bypass scope/Alignment/Gate,
  downgrade risk or issue acceptance. Read-only commands remain read-only.

## Approved bootstrap ordering amendment

A safe refresh writer depends on planned publisher, while current scope-admission
Guard rejects stale active proof before enrolling new tests. Do not defeat either
check to break this cycle.

Allow Tasks1–3 to develop/test against anonymous fixtures, with immutable measured
receipts where supported, before actual TASK092 new-file scope enrollment. Record
this explicitly as deferred enrollment, not fulfilled required-scope verification.
Do not apply runtime schema/scope changes to actual task, issue a Gate success or
claim completed task compliance during bootstrap.

Then add/test refresh command against anonymous fixtures with safe engine, collect
new actual FND001 GREEN, refresh via supported command, and enroll actual affected
sources/tests through impact CLI before any actual acceptance/closure or Tasks4–6.
Capability unsupported on actual filesystem means stop; do not bootstrap via unsafe
fallback. Pending actual journal is separately recovered/blocked, never erased.

If deferred enrollment is unacceptable, do not implement this ordering: stop for an
explicit alternative control-plane repair decision. General implementation approval
is not treated as permission to silently bypass current Guard.

## Tests and evidence

New failing tests cover FIXED proof rebind, append history with immutable old bytes,
idempotence, all wrong proof/state/category variants, concurrent source edit,
pending journal and crash at control publication. Existing lifecycle transition
matrix remains unchanged; this is not FIXED -> FIXED lifecycle transition.

No FND001 VERIFIED/CLOSED from refresh. Fresh related closure and independent review
remain mandatory. Addendum approved; product/runtime changes remain subject to planned TDD and guards. No
commit/release/production TASK1038001 or benchmark restart authority.
