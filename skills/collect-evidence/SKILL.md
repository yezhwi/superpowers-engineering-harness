---
name: collect-evidence
description: "Use when entering VERIFYING or before GATING and fresh evidence is required. Decides which evidence types the task needs, then runs collect_evidence.py; MUST NOT judge pass/fail itself."
compatibility: Requires Python 3.11+, Git, and a matching superpowers-engineering-harness CLI installed separately.
---

# Collect Evidence Skill

You decide WHAT evidence the task requires. `collect_evidence.py` does the
measuring.

## Decide Required Types

From the task contract's Verification Plan + what the diff touched:

```text
task modifies backend API
→ required: build, unit_test, integration_test
```

Map each required verification in `.harness/requirements.yaml` /
`current-task.yaml` to an evidence type. If a required verification lacks a
matching type, that is a spec problem — surface it, do not silently skip.

## Plan and Reuse Before Execution

Run `harness evidence plan --json` before scheduling proof. It inspects declared targets, case/Plan links, and evidence gaps without running tests or collecting pytest. It is advice, not execution authority or a valid Context. Missing selectors or binding conflicts need explicit repair; never guess repository-wide coverage or widen to a full suite.

For eligible generic GREEN proof, use the shipped reuse flag rather than a new skip predicate:

```bash
harness evidence run --type unit_test --scope related \
  --covered-test tests/example.py --reuse-if-valid \
  --command "pytest tests/example.py"
```

Replace the example selector with an existing declared target. Collector delegates to `can_reuse_evidence`: command/type/scope, both coverage sets, HEAD, before/after workspace, runtime, schema, and subject/test constraints must match. RED and finding requests execute the original command again, even with the flag. No cross-HEAD inheritance or reuse from another task's evidence directory. Preserve immutable historical failure proof; distinguish reused proof from actual execution.

Run commands sharing databases, ports, workspaces, or other mutually exclusive resources serial. Reuse fresh related coverage; collect only missing/stale obligations, not a full-suite fallback. Persist actual Plan proof promptly, then regenerate final Context after legitimate metadata changes are stable. Neither reuse nor an exit-zero command declares requirements verified or task complete.

Before launching a large or known-slow scope, write a planned batch manifest with each exact command and its repository-root `--covered-test` selectors; preserve the original selectors across batches, select only missing fresh related coverage, and require the complete required-test union so no required test is skipped. Qualify duration history to the same source and environment; treat unknown duration conservatively. A roughly 50–70% available-deadline margin is illustrative, not a numeric mandate. Execute serial unless databases, ports, workspaces, and other resources are demonstrably disjoint.

Every executed batch must leave a genuine immutable receipt and JUnit that record or substantiate its command, exit code, runtime, current HEAD, before/after product-workspace fingerprints, and actual covered tests; collector process exit alone is not success. If a batch is failed, cancelled, timed out, or drifted, stop scheduling, diagnose before retry, and never blindly run until green; retain successful fresh batches without re-executing them, but reuse only through the existing `can_reuse_evidence` predicate. RED and finding requests still execute the actual command. Never reuse cross-HEAD proof or narrower coverage, and never widen to a full suite.

This is guidance only, not an automated scheduler or a claim of Agent obedience or measured performance. It preserves existing budget accounting and authority with no new limits, exemptions, or deadline extensions, and changes no collector, timeout, freshness, schema, CLI, or Gate behavior.

## Documentation Verification

Use engineering-harness's [documentation checks](../engineering-harness/SKILL.md#documentation-verification) and [failure triage](../engineering-harness/SKILL.md#verification-failure-triage) before treating a failed command as product RED. Keep the same executor for diagnosed checker/setup repairs; retain the original checker, baseline and failed execution, then establish a valid RED/GREEN pair with the corrected checker. Do not change prose merely to satisfy an ordinary-wording match. A budget refusal or user-authority halt still follows existing policy; this guidance grants no retries, exemptions or proof status. Consolidate required build/Gate work after content is stable, and revalidate affected inputs after later changes under existing freshness rules.

## Actual Test Execution

Freshness and command matching are necessary, not sufficient. Test and finding proof must include collector-captured `test_execution` from actual pytest calls. File/function coverage includes all collected parameterizations; filtered or skipped members require narrower explicit executed selectors. RED requires an assertion-style call failure for every declared target, exit 1 and no collection/setup/teardown/internal errors, not a checker `KeyError` or any arbitrary nonzero exit. Human review must still connect assertions to the product requirement.

The qualified command profile is one serial native pytest invocation preserving the private standalone reporter: optional literal environment assignments (`env` allowed), `cd ... &&` prefixes and transparent `sh/bash/zsh -c/-lc` wrappers. Compound sequences, pipelines, OR/background commands, redirection, substitutions and arbitrary program wrappers save measurements only; separate prerequisites and test commands instead of hiding earlier failures behind a final pytest status. The reporter does not prepend Harness source or count test-internal nested pytest as separate proof. Remote/Vitest selector parsing alone is not an execution provider. Unsupported/unreported commands and unqualified worker/transport adapters leave measurements, not qualified test proof. Preserve old receipts unchanged; recollect supported execution rather than inventing manifests or repairing receipts. `EVIDENCE_TEST_EXECUTION_INVALID` recovers through existing VERIFYING policy after diagnosis. Exit 0 from collection means stored only; exact test reuse additionally requires valid actual execution. This adds no budget exemption, sandbox, scheduler or state shortcut. Executable/module/plugin/conftest code remains trusted: basename syntax is not executable identity attestation. A custom same-named executable can swallow its own prerequisite failures; use known executables and collect prerequisites separately. Explicit worker/transport flags (`-n`, `--numprocesses`, `--dist`, `--tx`, `-d`) remain measurement-only; reporter also checks effective worker configuration from ini/environment. This does not qualify xdist.

## Execute

For each required type:

```bash
harness evidence --type unit_test --command "pytest"
```

(Inside the harness repo itself, the equivalent raw call is
`python scripts/collect_evidence.py --type ... --command ...`; elsewhere
always use the CLI.)

Generates `.harness/evidence/<type>.json` with command, exit_code, timestamp,
commit, stdout_tail, stderr_tail. Failing commands still produce evidence —
that is by design; never re-run until green to hide a failure.

For related unit tests, pass `--covered-test` as the repository-root path even
when the command `cd`s into a subproject. Harness canonicalizes pytest/Vitest
selectors (including `sh -lc 'cd ... && ...'`, `npx vitest run`, and
`npm run <script> --` when the package script is pytest or `vitest run`)
to that root-relative path:

```bash
harness evidence run --type unit_test --scope related \
  --covered-test backend/tests/foo.py \
  --command "sh -lc 'cd backend && pytest tests/foo.py'"
```

Missing files, paths outside the repository, invalid relative `cd`, and
selectors the command did not run fail with `COVERED_TEST_NOT_EXECUTED` or
`COVERED_TEST_PATH_INVALID`. When `--covered-test` is set, an `npm run`
script that cannot be resolved to pytest/`vitest run` fails with
`TEST_RUNNER_UNRESOLVED`. Build/lint `npm run` without covered tests is not
a missing test runner. Do not change cwd just to satisfy string matching.

## Hard Boundaries (不得违反)

1. **禁止自己写判定**："测试应该通过" / "看起来没问题" is not evidence.
   Only `collect_evidence.py` output counts.
2. **Fresh only against product workspace.** Evidence must bind current git
   HEAD and the product workspace fingerprint (product code, tests, and
   non-control-plane config). Writing `.harness/` verification, review, or
   task metadata does **not** stale product test/build evidence — do not
   re-run the same product tests after `harness requirement verify`,
   `harness invariant verify`, or review writes. Re-collect only when
   product files changed or Gate reports `EVIDENCE_WORKSPACE_STALE`.
3. Never hand-edit files under `.harness/evidence/`.
