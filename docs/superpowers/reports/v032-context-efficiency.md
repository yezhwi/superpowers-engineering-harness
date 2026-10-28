# v0.3.2 Context efficiency observations

Status: historical implementation-candidate measurements, **not acceptance by
themselves and not a release record**. User explicitly reduced benchmark scope to
completed samples and cancelled remaining N=100 work; cancellation is not unfinished
mandatory work. The original five-count matrix is incomplete. Later feature
acceptance is summarized separately below and does not rebind these measurements.

## Method and identity

Anonymous deterministic fixture seed `1038001`; N=0/1/10/50 outside-scope minor
finding candidates, LOCAL policy, Q1/FAST, no input evidence records. Each count has
five fresh-fixture cold repetitions per arm, plus separate five unchanged-source
steady generation/validation repetitions after one excluded warm-up. Arms run
serially. Input inventories and fixture HEAD are identical between arms.

Reference is isolated Git archive of `src/harness` at exact commit
`c74ac4d4477469fdbeda80a2b470094d3134375f`, not another reference implementation.
Archive SHA256: `4b24cdcf5c99b8e6c5ef25825ff3d0496d716f54eb01ae62137ee934c0dc855d`.
New arm is fixed external copy of uncommitted implementation, with per-file byte
hashes in raw report. Repository HEAD is same commit; HEAD alone does not identify
the new implementation. Measurements predate final version/docs packaging edits;
no claim that later package-build artifact was benchmarked.

Environment: CPython3.11.5, macOS26.4 x86_64,12 logical CPUs reported,
PyYAML6.0.3, jsonschema4.26.0. Same environment for both arms, no parallel test job.
CPU affinity, background system load and power state were not controlled. Long
wall/CPU discrepancy observed during cancelled N=100 work; no timings from that
incomplete work are used. Earlier persisted runs remain observational measurements,
not proof of immunity to scheduling or suspend effects.

Generator: `benchmarks/context_efficiency.py` in source checkout. Raw per-run
phases/counters, standalone validation, schemas, workspace/source identities,
artifact inventories and semantic facts retained outside repository:

- `/tmp/v032-context-efficiency-full-run1.json` (original incremental report).
- `/tmp/v032-context-efficiency-stopped-80-samples.json` (stopped wrapper/raw copy).
- Original JSON SHA256: `a87a6f58ef3bae156d5753d1c32d08611dab4ad41cb525614cf5d20623e66c1c`.

These are local retained artifacts, not publicly hosted evidence or permanent
archive guarantees. Generator can reproduce fixture/method from source, but
published npm skill package does not contain benchmark runner or raw samples.
No further samples are authorized by this report.

## Actual results

80 SUCCESS samples in8 complete groups, zero persisted failed/timeout samples in
these groups. Cancelled/in-flight N=100 work is excluded, not reported as success
or runtime failure. Values below are **min / median / max seconds** of generation
plus separate standalone validation, not process startup wall time.

| N | Mode | Archived reference | New snapshot |
|---|---|---|---|
| 0 | cold | 4.194 / 4.507 / 4.657 | 4.457 / 4.907 / 5.053 |
| 0 | steady | 4.235 / 4.349 / 4.439 | 4.834 / 4.923 / 5.063 |
| 1 | cold | 7.383 / 7.611 / 7.962 | 7.178 / 7.504 / 7.864 |
| 1 | steady | 4.061 / 4.126 / 4.160 | 4.531 / 4.680 / 4.881 |
| 10 | cold | 36.587 / 39.505 / 42.763 | 8.531 / 8.558 / 8.609 |
| 10 | steady | 5.341 / 5.376 / 5.496 | 5.751 / 5.812 / 5.942 |
| 50 | cold | 278.766 / 286.894 / 311.950 | 14.341 / 14.461 / 14.504 |
| 50 | steady | 8.814 / 8.861 / 8.924 | 9.403 / 9.486 / 9.655 |

Batch-heavy cold cases improve; N=0 and steady medians are slower. No universal
speedup, p95, absolute deadline or50%/10% performance acceptance threshold claimed.
Regression-test durations are not performance samples.

Every persisted new generation has full builds<=2, source loads<=3, Gate
assessments<=3 **including internal independent final validation**. Extra standalone
validation is measured/counted separately. N=50 cold reference counts101/102/102;
new2/3/3. Separate structural regression tests exercise N=100, but no N=100
benchmark observation is available under user-reduced scope.

## Semantic checks and limits

All persisted samples report completeness/accuracy/freshness/traceability true and
final expansion count=N. Both arms agree on normalized semantic facts for each
sample. Comparison preserves working/global facts, policy, blockers and expansion
audit facts, with explicit exceptions:

- Fixture is deliberately legacy so archived reader can load identical inputs.
  New `TEST_SCOPE_AUDIT_INVALID` is deliberate fail-closed tightening, removed
  only from duplicate semantic comparison blocker lists, never bypassed in Gate.
- Volatile timestamps/derived context/source hashes and anonymous absolute fixture
  roots are normalized. Original generated-from/schema/source identities remain in
  raw report. New absent scope reference keys are not treated as old-schema facts.
- This is not byte-identical schema equivalence, all-case authority proof, failure
  atomicity/recovery testing, or authorization for a real migration/retirement.
  Those mechanisms require their separate related regression/authority evidence.

## Cache and remaining acceptance

New N=50 schema+YAML exclusive generation share is38.2–38.7%, across all documents,
not evidence-specific work. Fixtures have zero evidence records; reusable hits,
evidence-specific cost and net benefit are unproven. Cache deferred; no persistent,
cross-command or cross-HEAD cache introduced. A future cache needs supplemental
plan and complete dependency identity keys plus independent standalone validation.
Existing exact `can_reuse_evidence` unchanged; RED/finding commands still execute.

Reduced samples do not imply Gate CONVERGED, task DONE, independent review PASS,
commit/merge/tag/publication authorization, or production task migration.

<a id="v032-delivery-status"></a>

## v0.3.2 delivery status

This is the canonical human-readable status summary, not a second runtime authority. Historical artifacts named below are repository-local acceptance records; they are not guaranteed to be present in a packaged or public archive. Current Core HEAD/workspace freshness rules are unchanged, and no historical receipt is relabeled as current-HEAD proof.

| Area | Status | Qualified task and revision | Evidence limits |
|---|---|---|---|
| Original Core context/evidence/scope/provenance/publication work | Historically accepted | TASK-094, source commit `51c705280fb34d565e402ed2202e6d9153bdf34d`; `.harness/acceptance-artifacts/task094-reference-rebind/delivery-summary.json` and `gate.log` | macOS native only; controlled exits/injected I/O are not real power loss or hardware faults; no N=100 benchmark, full-suite, or native/actor rerun. |
| A: bounded related-test batching guidance | Guidance implemented and historically accepted | TASK-095 at `51c7052`, then TASK-097 already-satisfied verification on `999bfb94bef1cbe32067a5488c1203f843d9085f`; corresponding `delivery-summary.json` files under `.harness/acceptance-artifacts/task095-final-plan/` and `task097-verification/` | Static guidance checks do not prove Agent obedience, automatic scheduling, runtime-duration policy, or speedup. |
| B: manual keep-ten task-history pruning | Implemented and historically accepted | TASK-099 accepted the eight-file candidate at parent `999bfb9`; exact accepted bytes committed as `3b4fa2853b1990990df847d80461e7a5c454a175`; `.harness/acceptance-artifacts/task099-final-validation-v3/delivery-summary.json`, `gate.log`, and `task099-commit/summary.json` | 362 related tests/four files, ten private package scenarios, CLEAN/formal reviews, and Gate convergence belong to the precommit candidate. They were not rerun on `3b4fa28`. No real cleanup occurred; shared retained data, fixtures, probes, unknown/user-owned data and live/referenced archives remain excluded, with no whole-`.harness` size bound. |
| Execution workflow corrections | Repository guidance updated; lightweight validation only | Root/engineering skill mirrors, collector guidance and related static regression tests; see [execution guidance](../../../skills/engineering-harness/SKILL.md#executor-continuity) | One continuing executor, diagnosed checker repairs, semantic-versus-interface checks and bounded closeout guidance. No new Harness Gate/DONE, independent review, Agent-behavior experiment, measured speedup or installed-skill update is claimed. Core safety rules remain unchanged. |
| Deferred | Not required for accepted scope | Automatic batching scheduler/manifests/runtime-duration policy; conditional parse cache | Cache has no evidence-specific benefit proof. These are not mandatory unfinished v0.3.2 features. |
| Excluded | Outside accepted scope | Broad GC/TTL, configurable retention, scheduler, Linux support/matrix | Not release blockers for the user-narrowed accepted scope. |
| Later proposals | Separate proposals | Control-plane Phase 0/1 and dependency-scoped freshness | Not original v0.3.2 acceptance failures or retroactive obligations. |
| Reviewed P1/P2 and advisory repairs | Implemented; task-level acceptance completed | TASK-104 / `8f19300`, TASK-105 / `e66a842`, TASK-106 / `3bfff30`; merged through PR #1 | 762 / 178 / 349 related tests respectively, builds, independent static reviews and native Gates at their qualified precommit candidates. Historical receipts do not become current-HEAD release proof. |
| Regression-oracle strengthening | Implemented; task-level acceptance completed | TASK-107 / `e4efdc8`, merged through PR #2 | 75 related tests and build; shell cwd/wrong-selector and committed cleanup/cancellation controls. Static review is not independent test execution. |
| Context single-call reuse | Implemented; task-level acceptance completed | TASK-108–109 / `7d54ebc`, merged through PR #3 | 328 related tests and build at committed HEAD. Successful Decision parsing/schema preparation reused only inside one Context call; reads, real validation and source/schema observation remain. Separate strict original-task replay below, not acceptance of the anonymous matrix. |
| Zero-only regression tolerance | Implemented; task-level acceptance completed | TASK-110 / `5cd3011` | 280 related tests and build refreshed after commit; nonzero legacy policy values fail closed, no automatic migration. Missing regression proof always blocks; no newly reproduced allowance bypass claimed. |
| New-task fixture inheritance | Implemented; task-level acceptance completed | TASK-111 / `60018cb` | 306 related tests and build refreshed after commit; only task new omits root behavior-fixtures, originals retained. Recover/escalate/default copying unchanged. Metadata copy-volume estimates are not copy timings or reclaimed-space promises. |
| Graph versus CLI semantics | Clarified; task-level acceptance completed | TASK-112 / `a9d5517` | 216 related tests and build refreshed after commit, independent static review and precommit Gate. Function docs, bilingual guide and regression controls only; executable AST, graph and guards unchanged. No confirmed runtime permission defect. |
| Release | Not established by this workflow | Source checkpoint `a9d5517c361417a85c3f2a761ec683fca77b42fc`, not an automatically updated HEAD claim | No version-level current-source release Gate, tag, publication, deployment, or system install is claimed. |

The 80-sample benchmark above remains observational and is not acceptance by itself. TASK-094 and TASK-099 acceptance were separate historical processes with the qualifications shown here. Historical rows are append-only qualifications, not current freshness assertions; the completed task-level work does not certify every proposed interface in the original design.

### Later strict original-task replay

TASK-109 compared isolated, complete baseline/candidate package pins using recovered TASK-107 input. Final strict command medians were **21.0835 → 20.1166 seconds**, about **4.586% lower**. Reads 456 and directly observed root-schema validation iterations 358 were unchanged; Decision parsing 378 → 44 and successful schema preparation 358 → 1. All six runs retained two source loads, two Gate assessments, one Context build, zero expansion candidates/events and 22 evidence records. This is a different source/input/method from the anonymous benchmark above; do not combine them, revive the earlier approximately 26% estimate, or claim universal improvement. Local task report: `context-followup-result.md`; strict summary: `context-original-replay-verified-summary.json`, within repository-local `.harness` storage when retained. No new measurements were run for this documentation update.

### Local evidence retention qualification

Historical `.harness/acceptance-artifacts/...` references above describe their original canonical locations. Task turnover may move original trees under nested `.harness/.publication-retained/task-replacement-…/previous/`; do not infer public download availability or continued existence from a report path. User-authorized local cleanup subsequently removed 48 older fixture launcher files (`applypatch`, `apply_patch`, `codex-execve-wrapper`) under old `private-codex-home/tmp/arg0/` trees, retaining the latest six and all other entries. Affected historical fixtures are no longer intact for byte-exact reruns. Original report/receipt records were not rewritten; successful historical checks are not recertified by preservation of those records. Local cleanup inventory/results are recorded separately when retained. No automatic retention, general garbage collection or guaranteed APFS reclaim amount follows from that one authorization.

### Proposed release verification — not execution authority

1. Finish this documentation-only task and obtain separate commit authorization. Pin the final source revision and retain task-qualified receipt identities; a source change invalidates release evidence freshness.
2. With explicit approval of the release-verification scope, collect fresh bounded related-test batches covering changed release surfaces. Include README/version/resource/package compatibility checks and actual wheel/npm payload/installed-CLI smoke checks in isolated temporary environments. Do not replace native proof with historical counts or silently run a repository-wide suite.
3. Check macOS/native-filesystem support, legacy scope and zero-only regression-policy migration guidance, root fixture path compatibility and unchanged pinned installer examples. Preserve limits: no Linux matrix, real power-loss, Agent-obedience or universal performance certification. Cancelled N=100 and deferred persistent evidence caching remain outside the accepted scope.
4. Obtain the required fresh independent release review and native version-scoped Gate using the agreed contract. Reaching task DONE or passing a package build alone is not version-level release readiness; if no applicable native release route exists, surface that gap rather than inventing a command or status.
5. Only after explicit separate tag/package publication authorization: select immutable artifacts, publish and verify registry/tag/install results. Documentation remains **development candidate** and installers stay pinned to v0.3.1 until that release is actually established. No tag, push, package install or publication is authorized by this proposal.
