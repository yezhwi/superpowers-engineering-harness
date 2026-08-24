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
python scripts/collect_evidence.py \
  --type unit_test \
  --command "pytest"
```

Generates `.harness/evidence/<type>.json` with command, exit_code, timestamp,
commit, stdout_tail, stderr_tail. Failing commands still produce evidence —
that is by design; never re-run until green to hide a failure.

## Hard Boundaries (不得违反)

1. **禁止自己写判定**："测试应该通过" / "看起来没问题" is not evidence.
   Only `collect_evidence.py` output counts.
2. **Fresh only.** Evidence must bind current git HEAD. Stale evidence →
   re-collect before GATING (gate will reject stale otherwise).
3. Never hand-edit files under `.harness/evidence/`.
