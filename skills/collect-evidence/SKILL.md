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
