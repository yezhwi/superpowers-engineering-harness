# Controlled candidate commits

**Status:** opt-in development implementation. Bounded anonymous-repository checks do not constitute final release/package qualification. See the [implementation design](superpowers/specs/2026-10-21-gate-before-commit-design.md). No command grants permission to commit or push this repository.

## Enroll before freeze

The operator authors the policy in `.harness/gate.yaml` before freezing the task contract:

```yaml
gate:
  candidate_commit:
    format: candidate-commit/v1
    capability_version: 1
    minimum_reader: 0.3.2
```

`current-task.yaml` Gate summaries are not enrollment authority. Prepare never inserts policy, changes scope or reseals alignment. Old strict Gate schema validators reject this new key; not every old nonvalidating CLI command is covered by that guarantee.

Continue the ordinary contract, scope, test-plan, Plan and phase workflow. This feature does not verify pending obligations, complete Plan items, waive reviews or add task states.

## Candidate workflow

Stage only intended task-owned changes yourself. Prepare does not stage/reset/clean files or rewrite/lock the user index.

```text
harness candidate prepare --path PATH [--path PATH ...] --json
harness candidate prove --candidate sha256:HEX --spec FILE --json
harness requirement verify REQ-ID --evidence .harness/evidence/candidate-proof/HASH.json
harness invariant verify INV-ID --evidence .harness/evidence/candidate-proof/HASH.json
harness interface verify INT-ID --evidence .harness/evidence/candidate-proof/HASH.json
harness plan reconcile P-ID --complete --evidence .harness/evidence/candidate-proof/HASH.json --surface PATH
harness transition VERIFYING
harness candidate review-record --candidate sha256:HEX --kind complexity|diagnosability|interface --manifest FILE --scope-attestation FILE --report FILE --json
harness transition REVIEWING
harness review outcome PASS --reason-code REVIEW_CLEAN
harness gate --candidate sha256:HEX --json
harness transition DONE
```

Identifiers and paths above are placeholders, not a runnable generated task. Run the native Plan begin/admission steps and supply all required evidence, reports and scope coverage. Repeat prove/review-record for required evidence types and all three review kinds. The manifest argument is the actual prepared record returned as `artifact_ref`. Scope attestations bind candidate ID, actual export fingerprint, kind and the complete typed review scope.

Prepare is legal in IMPLEMENTING. Prove remains available through GATING. Review recording starts in VERIFYING. Candidate Gate requires GATING and uses the original assessor/convergence policy; acceptance alone is not an alternative state transition implementation.

### Proof specifications

Specs are JSON validated by `candidate-proof-spec.schema.json`. Supported profiles:

- `pytest-junit-v1`: exact pytest node selectors and evidence type; actual collected/executed JUnit cases must satisfy the declared test-plan bindings, including parameter IDs.
- `python-module-build-v1`: actual `python -S -m build --no-isolation --wheel` with a supported local backend and declared writable outputs; not arbitrary build-system support.
- `python-script-v1`: one candidate-relative script and literal arguments; not an arbitrary shell command.

All specs declare interpreter, dependency file mappings, environment, writable paths and the supported input policy. The supported runtime is a native Darwin CPython image, not an interpreter-delegating shell script. Runtime receipts bind executable bytes, actual stdlib files, vendor LIBDIR native libraries, optional configuration/stdlib zip files, platform identity and the native inspector. Load paths outside the captured runtime roots refuse; OS shared-cache libraries remain trusted platform inputs, not a whole-OS filesystem-CAS guarantee. Existing bytecode caches are excluded from execution through private cache prefixes. Runtime bytes are rehashed after proof and at Gate/commit revalidation; only deterministic parsed loader commands may be cached by actual image/tool digests. Dependency mappings name actual source files and their execution-copy targets; a package entry point alone is not a complete dependency declaration. Unsupported closure/configuration must refuse, not silently omit inputs for speed. Inspect the packaged schema and supply the complete qualified manifest for the intended runtime/profile.

Execution uses a fresh copy outside Git repositories with sanitized Python/site/plugin/config state and read-only candidate inputs. This is cooperative finite-input execution, **not an OS sandbox or network-denial guarantee**. Do not run code that requires Git-sensitive, network, secret, plugin or undeclared dynamic inputs under these profiles.

Place specs/review inputs created after prepare in `.harness/.candidate-operation-inputs/<candidate-id-without-prefix>/`. Otherwise newly created untracked product files are drift. Message files may be external regular files; safe readers reject special files and symlinks.

## Separate commit authority

Only after actual Gate convergence (and the ordinary DONE transition when used):

```text
harness authorize commit
harness commit --candidate sha256:HEX --message-file FILE --json
harness candidate status --candidate sha256:HEX --json
harness candidate recover --operation sha256:HEX --json
```

Grant commit only when the operator intends the exact local commit. Push is separate and never implied. Supported effective Git configuration and actual identity are bound; hooks/signing/filters/conditional includes and other unsupported repository modes fail closed rather than being silently disabled.

Commit fixes its payload before durable intent, consumes authority before expected-old ref CAS and never rewrites the index. Ordinary pending mutators are blocked. Known same-task commit grant/revoke and explicit recovery are the only narrow exceptions.

- **Ref still parent:** explicit recovery needs live authority and unchanged inputs. After a consumed-grant crash, grant again; old consumed authorization is not a new permission.
- **Ref equals proposed:** finish the trace forward, without another CAS or new grant.
- **Foreign ref / unknown metadata:** refuse. Never reset, roll back, autostage or erase later user edits.

Use explicit candidate recovery for candidate intents. Legacy metadata recovery does not mutate Git. Same-message retries reuse the fixed operation; changed payloads refuse.

## JSON, failures and historical facts

Candidate-family operations require `--json`. Responses have exactly the 14 INT-010 fields in `candidate-command-result/v1`; use `candidate_id`, `operation_id`, `acceptance_id` and `artifact_ref`, not the old development scaffold's raw dictionaries. Artifact refs are repository-relative existing candidate evidence or operation records.

Exit codes: success **0**, supported refusal **1**, usage **2**, unexpected internal failure **70**. Missing authority also emits the existing `USER_AUTHORITY_REQUIRED` / `HALT_AND_WAIT` diagnostics. Errors never echo argument tokens, message content, protected bytes, environment values or raw Git diagnostics.

`REF_PUBLISHED_POSTCHECK_FAILED` means the ref may already be published: inspect the recorded operation and recover forward. Known operations retain true phase and `mutation_started`. If intent cannot be read unambiguously, `phase: UNKNOWN` and `mutation_started: null` express uncertainty, not a false no-mutation claim. Broken stdout/stderr never roll back durable state or trigger a second commit.

Status is read-only and creates no status artifact. Its envelope points to existing prepared/operation/trace facts. `TRACE_PUBLISHED` is historical publication, not a fresh proof for the current HEAD. Context exposes historical acceptance/commit separately from live HEAD relation, reports current readiness as `NOT_ASSESSED`, and never grants generic evidence reuse—even after a later commit with an identical tree.

## Limits

V1 supports qualified attached SHA-1 main worktrees and the three cooperative profiles only. Candidate mode refuses `gate.architecture.mode: required`: the existing architecture assessor reads the live worktree and has no candidate-export adapter. Do not disable required architecture checks to enable this feature; retain the ordinary architecture/Gate workflow instead. Unsupported hooks/configuration, index flags, linked/sparse/split worktrees, sequencer state, special files, escaping links, input drift, unknown schemas and foreign refs refuse. No arbitrary shell, automatic Git cleanup, post-commit Gate rerun, cross-HEAD evidence reuse, scheduler, background pruning, push or release is provided.
