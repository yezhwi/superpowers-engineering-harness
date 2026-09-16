---
name: collect-evidence
description: "Use when entering VERIFYING or before GATING and fresh evidence is required. Decides which evidence types the task needs, then runs collect_evidence.py; MUST NOT judge pass/fail itself."
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
`COVERED_TEST_PATH_INVALID`. An `npm run` script that cannot be resolved to
pytest/`vitest run` fails with `TEST_RUNNER_UNRESOLVED`. Do not change cwd
just to satisfy string matching.

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
