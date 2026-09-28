# v0.2.10 Plan Reconciliation P1A — Context Design

**Status:** Review incorporated; accepted for P1A implementation

**Authority:** Extends `docs/Superpowers-Engineering-Harness-v0.2.10-Implementation-Contract.md` section 7 for P1A only.

## 1. Goal

Make enabled Plan Reconciliation artifacts authoritative Context sources without copying full plan or execution bodies into derived Context.

P1A lets an Agent recover whether Plan Reconciliation is enabled, whether final reconciliation currently passes, and which canonical nonterminal item comes next. Persistent Harness state remains authoritative; conversation history and Markdown remain non-authoritative.

## 2. Scope

P1A includes:

- conditional Context loading of `.harness/plan.yaml` and `.harness/plan-execution.yaml`;
- compact summary projection in both compact and full Context modes;
- plan artifact references and freshness inputs;
- Context projection version and closed-schema migration;
- fail-closed malformed-artifact handling;
- source-scope and integrity regression coverage.

P1A excludes:

- `harness plan status` (P1B);
- Q3 task-level enforcement (P1C);
- full item/execution body projection;
- Markdown parsing or checkbox synchronization;
- automatic reconciliation or plan mutation;
- new blocker or evidence types.

## 3. Context Contract

Both compact and full modes project the same summary under `control`:

```yaml
plan_reconciliation:
  enabled: true
  mode: final
  next_plan_item: P-003
  final_status: blocked
```

Disabled tasks project only:

```yaml
plan_reconciliation:
  enabled: false
```

Rules:

- `enabled` is the effective switch. It is true only when persisted `plan_reconciliation.enabled` is true and the profile is STANDARD or STRICT. A missing configuration is disabled. FAST/Q1 projects `{enabled: false}` even when the task file contains `enabled: true`: that value is not a defined opt-in, and Gate does not evaluate plan artifacts for FAST.
- `mode` is present only when the projected `enabled` is true, and is `final` or `task_and_final`. It is copied from the persisted task configuration.
- `next_plan_item` is a `P-*` ID or `null`.
- `final_status` is `pass` or `blocked` and is present only when enabled.
- No plan item body, intent, references, surfaces, execution record, reason, or evidence payload is copied into Context.

## 4. Source Loading

`FileContextSource` first loads and validates `current-task.yaml`, then branches on effective enablement.

### Disabled path

For missing configuration, persisted `enabled: false`, or any FAST/Q1 task:

- do not open, parse, validate, hash, stat, or enumerate either plan artifact;
- keep the current Gate boundary: `_evaluate_gate` returns through `run_fast_gate` before Plan Reconciliation, so FAST does not read plan artifacts. An ad hoc `enabled: true` on FAST is not the opt-in left undefined by Implementation Contract section 4;
- do not add plan artifact references;
- do not let adjacent artifact creation, deletion, corruption, or content changes affect Context freshness;
- project `{enabled: false}`.

P1A does not change the persisted `enabled` check on `PLANNED → IMPLEMENTING`. The normal FAST path does not enter through that edge.

### Enabled path

For enabled STANDARD/STRICT tasks:

- load each canonical artifact conditionally before calling `assess_gate`;
- absent artifacts are authoritative absence, represented by a `null` reference and `null` named hash;
- present artifacts must pass YAML decoding, their registered JSON schema, and static canonical checks such as unique item IDs;
- malformed present artifacts raise `CONTEXT_SCHEMA_INVALID` from Context publication. `harness gate` continues to report the same schema failure as `InvalidHarnessState` with exit 2;
- semantic reconciliation outcomes (`PLAN_REQUIRED`, `PLAN_STALE`, `PLAN_ITEM_UNRECONCILED`, `PLAN_PROOF_MISSING`, `PLAN_PROTECTED_PATHS_MODIFIED`, and schema-valid `PLAN_DISPOSITION_INVALID`) remain typed Gate blockers and do not prevent Context publication;
- canonical references use `.harness/plan.yaml` and `.harness/plan-execution.yaml` bytes;
- fingerprint mismatch is not a Context schema error: Context remains publishable but blocked.

Plan loading reuses the P0 canonical loader/normalization seam. Before that loader enters Context dependency closure, all direct `Path.read_text` / `Path.is_file` plan and contract reads must move to audited `source_access`. The module then joins the explicit allowed dependency set, not the adapter exemption set. No broad source-scope exemption is added.

## 5. Authoritative Model and Projection

`AuthoritativeContext` gains optional normalized plan and execution fields. Missing enabled artifacts remain `None`; disabled and missing states remain distinguishable through task enablement and references.

A pure projection helper consumes:

- task Plan Reconciliation configuration;
- normalized plan and execution documents already loaded into `AuthoritativeContext`, when available;
- typed Gate blockers from the same Context assessment.

It never calls `validate_plan_reconciliation` or performs file I/O. It returns the summary only. `build_control_core` inserts that summary, and Context integrity independently recomputes and compares it from the same loaded documents.

### `next_plan_item`

Return `null` when:

- disabled;
- either artifact is absent;
- fingerprint is stale;
- all canonical items have terminal execution records.

Otherwise, traverse `plan.items` in canonical list order and return the first item whose execution record is absent or has `PENDING`, `IN_PROGRESS`, or `BLOCKED` status.

Terminal proof or disposition failures do not invent a next item. If all records are terminal but Gate reports `PLAN_PROOF_MISSING`, `PLAN_DISPOSITION_INVALID`, or `PLAN_PROTECTED_PATHS_MODIFIED`, `next_plan_item` remains `null`.

### `final_status`

For enabled tasks:

- `blocked` when the current Gate assessment contains any blocker whose code starts with `PLAN_`;
- `pass` otherwise.

This field reports the P0 final Plan Reconciliation check, including when `mode` is `task_and_final`. Q3 task-level enforcement is P1C and does not change this field. It does not mirror global Gate status and does not authorize state transitions.

## 6. Freshness and Integrity

Increment Context `PROJECTION_VERSION` from `2` to `3`.

The closed `generated_from` schema adds:

```yaml
plan_hash: sha256:... | null
plan_execution_hash: sha256:... | null
```

For enabled tasks, these values bind canonical artifact presence and bytes. For disabled tasks, both values are `null`, the generic `files` map contains neither plan artifact key, and adjacent artifacts are never inspected. For an enabled present artifact, each named hash equals its generic `files` entry and its `references` entry's `sha256`; for enabled absence, the named hash, generic `files` entry, and reference value are all `null`.

Freshness capture follows a conditional finite registry:

1. read canonical task metadata already required by Context bootstrap;
2. include plan artifact paths only when effective enablement is true (persisted `enabled: true` plus STANDARD/STRICT profile);
3. version present files and preserve `null` for absence;
4. authorize only those selected paths in version/read scope.

Consequences:

- enabled artifact creation, deletion, or content change makes an old Context stale;
- disabled artifact changes have no freshness effect;
- artifact mutation during generation fails with `CONTEXT_STALE` and publishes nothing;
- old projection-version documents fail closed under the new schema.

`references` includes `plan.yaml` and `plan-execution.yaml` only for enabled tasks, each as a canonical reference or `null`. Manifest source accounting gains a Plan Reconciliation entry showing loaded/absent state without exposing bodies.

## 7. Error Semantics

| Condition | Result |
|---|---|
| Disabled plus absent or malformed adjacent artifacts | Context valid; artifacts ignored |
| Enabled plus both artifacts absent | Context valid; blocked summary; both hashes `null` |
| Enabled plus one artifact absent | Context valid; blocked summary; missing hash `null` |
| Enabled plus malformed present artifact | `CONTEXT_SCHEMA_INVALID` |
| Enabled plus stale fingerprint | Context valid; blocked summary; `next_plan_item: null` |
| Enabled plus matching nonterminal item | Context valid; blocked summary; first nonterminal ID |
| Enabled plus terminal proof/disposition failure | Context valid; blocked summary; `next_plan_item: null` |
| Enabled plus reconciliation pass | Context valid; `final_status: pass`; next item `null` |
| Artifact changes during generation | `CONTEXT_STALE`; no publication |

No fallback to cached plan state is permitted.

## 8. Expected Implementation Surfaces

- `src/harness/context/source.py` — conditional authoritative loading and references.
- `src/harness/context/model.py` — optional authoritative plan fields and Control Core type.
- `src/harness/context/builder.py` — summary projection.
- `src/harness/context/freshness.py` — conditional source registry and projection version.
- `src/harness/context/integrity.py` — summary/reference/manifest equality checks.
- `src/harness/context/read_scope.py` — admit the same conditional plan paths selected by freshness capture. Do not add them to the unconditional root-file list.
- `src/harness/plan_reconciliation.py` — source-access-safe normalized loading and pure summary helper.
- `src/harness/context/dependency_closure.py` — add the module to the allowed closure only after direct I/O is removed; do not add an adapter exemption.
- `src/harness/schemas/context.schema.json` — closed summary and generated-from fields.
- Context/source/schema focused tests.

No new package or dependency is required.

## 9. Verification

Focused deterministic tests must cover:

1. enabled matching artifacts appear as canonical references and summary;
2. compact and full summaries are identical;
3. first canonical absent/nonterminal execution item is selected;
4. enabled missing artifacts produce blocked summary without Context failure;
5. stale fingerprint produces blocked status and null next item;
6. malformed enabled artifact fails closed;
7. disabled malformed artifacts remain unread and do not affect freshness, including FAST with an ad hoc persisted `enabled: true`;
8. enabled artifact content and presence changes invalidate saved Context;
9. artifact mutation during generation prevents publication;
10. projection version/schema migration rejects old projection;
11. semantic Plan blockers publish a blocked summary without rerunning reconciliation in the projection helper;
12. dependency closure permits the audited plan loader, rejects direct I/O, and adds no adapter exemption;
13. existing FAST Context lazy-import/source-scope regressions remain green.

Run focused related test files only; no full repository suite.

## 10. Follow-on Slices

P1B may reuse the pure summary helper for read-only `harness plan status`, but it must not make Context depend on CLI rendering.

P1C adds deterministic Q3 task-level enforcement separately. It must not change the P1A summary contract or introduce per-item top-level Harness states.
