# Stable Harness storage — development candidate

This is an opt-in source-development feature, not a released-version guarantee or
permission to operate an existing repository. TASK-117 implementation work does
**not** authorize this project's real activation, migration, or cleanup. Review
and final native Gate acceptance are separate from implementation progress.

## Supported boundary

Requires the reader capability `harness-storage-layout/v1`, supported macOS local
same-device filesystem operations, and canonical workspace-root `.harness`.
Package version alone does not attest the reader's actual loaded code. Each Git
worktree owns its store; Git common-dir is not the ownership boundary. Moving or
copying a workspace does not silently rebind its store.

Before applying an exact plan, an operator must explicitly inventory all CLI,
agent, CI, test, build, editor and other relevant writers. Each must be stopped
or upgraded to the capability. Maintenance JSON records this declaration, not a
process-list proof. Advisory locking cannot isolate arbitrary old tools,
editors, external writers, or their already-open file descriptors. No automatic
maintenance declaration, authority inference, or capability probe grants apply.

New private directories request `0700`, new files `0600`; original moved objects
keep inode and mode. There is no cross-device copy/delete fallback. Store
exclusion from product/Git/architecture discovery requires valid ownership;
unknown same-name data is refused, not silently hidden or adopted.

## Layout and task turnover

- `.harness/`: current generation, policy and task facts; ordinary regular-file
  publication retains its existing protocol.
- `.harness-store/store.yaml`: workspace/store ownership header.
- `.harness-store/operations/`: active directory coordinators. Ordinary admitted
  operations refuse pending/unknown coordination, including while `.harness` is
  temporarily absent. `init` is not a recovery mechanism.
- `.harness-store/history/`: canonical archive index, persistent task-ID
  reservations and qualified archive objects.
- `.harness-store/retained/roots/<operation>/previous`: the actual displaced
  generation. Bound new/recover creates fresh task documents and scope genesis,
  inherits explicit project policy/Decision/interface semantics, and does not
  copy history, retention or experiment trees into the next generation.
- `.harness-store/receipts/`: immutable operation facts, not task acceptance or
  deletion grants. Quarantine and aborted candidates remain retained data.

An old root stays intact, including any preexisting nested legacy data; the new
layout prevents future root nesting, not retroactive flattening. Original file
handles still reach the same displaced inode. That preserves object lifetime,
not a promise that unmanaged writers cannot change its contents.

## Read-only inspection and planning

```bash
harness storage inspect --json
harness storage migrate --kind ACTIVATE --dry-run --json
harness storage migrate --kind M1 --json
harness storage migrate --kind M2 --file /outside/workspace/request.json --dry-run --json
harness storage prune --dry-run --json
```

Omitting `--apply` never activates or migrates. Planning does not create the
store, Decisions, Context, journals or probes. Missing ownership, unsafe source
nodes, unsupported metadata, stale source identity, and incomplete inventories
are refusals, not empty successful plans.

ACTIVATE installs ownership and reader markers without fabricating an archive of
the current task. M1 moves explicitly inventoried canonical legacy history,
keeping original member/receipt bytes and inodes. M2 accepts explicitly selected
objects; it does not recursively adopt or recover nested fixture workspaces.

A request JSON object accepts only `sources`, `max_nodes`, and `max_bytes`. M2
`sources` is a list of mappings:

```json
{
  "sources": [{
    "source": ".harness/.publication-retained/selected-package",
    "role": "retained_root",
    "origin": {
      "workspace_id": "<actual 32-hex workspace ID>",
      "generation_id": "<explicit original 32-hex generation ID>",
      "original_workspace_root": "/original/absolute/workspace"
    },
    "logical_path": ".harness/.publication-retained/selected-package"
  }]
}
```

Placeholders are not executable values. Roles are `retained_root`, `history`, or
`experiment`; `history` additionally requires an explicit `alias`. Neither role
nor origin is inferred from a directory name. Whole retained/experiment packages
are opaque single moves, with `logical_bytes_complete: false`; only specifically
selected history trees are expanded. Overlapping or unclassified selections
refuse. Unregistered fixture-internal references remain unknown.

## Explicit apply and maintenance

**These commands move original live objects. Run only with separate operation
approval for the exact workspace and plan. They are examples, not authorization.**

Save plans and maintenance inputs outside the product workspace: adding an
untracked input inside it changes the product fingerprint and can stale the
plan. The JSON plan must be unchanged, `ready: true`, and backed by an ACCEPTED
Decision's exact selected user `storage_authorization`: task/workspace/store,
operation, plan digest and scope digest must all match. A hash, proposed option,
old grant or migration grant is not deletion authority.

```bash
harness storage migrate --apply --file /outside/workspace/plan.json \
  --decision DEC-nnn --maintenance-file /outside/workspace/maintenance.json --json
```

`--apply` excludes `--dry-run` and `--kind`; the accepted plan contains its kind.
Decision and maintenance flags are apply-only. Inputs are bounded, no-follow JSON;
duplicate keys, nonfinite values, symlinks and malformed input refuse safely.
The maintenance object contains exactly:

```json
{
  "version": 1,
  "workspace_id": "<actual workspace ID>",
  "operation": "ACTIVATE",
  "plan_digest": "sha256:<exact plan digest>",
  "participants_complete": true,
  "operator_confirmation": true,
  "participants": [{
    "name": "<inventoried participant>",
    "role": "agent",
    "disposition": "upgraded",
    "capabilities": ["harness-storage-layout/v1"]
  }]
}
```

Each participant role is `cli`, `agent`, `ci`, `test`, `build`, `editor`, or
`external_writer`; disposition is `stopped` or `upgraded`. Upgraded participants
must declare the capability. This is an explicit operator declaration, not proof
that arbitrary processes have stopped. Never manufacture it from empty `lsof`.

Same-operation, same-plan terminal apply returns its original receipt; a new
operation is not an idempotency retry. Do not substitute another plan after an
ambiguous failure.

## Failure and explicit recovery

A storage error does not mean no side effects. A matching readable coordinator
can report operation ID, phase, acknowledged action count and retained paths.
If output fails after COMMITTED, stderr reports that committed status when the
stream remains available; there is no rollback or new archive merely because
reporting failed. Both unavailable streams can prevent diagnostic delivery.

Inspect first, then explicitly recover the **original operation ID**:

```bash
harness storage inspect --json
harness storage recover <original-32-hex-operation-id>
```

Recovery finishes an acknowledged commit; before commit it can abort only under
proven identity/ownership, preserving candidate and failure inputs. Unknown
creations, occupied rollback targets and same-byte inode substitutions block;
there is no guessed adoption, automatic init/repair, overwrite or deletion.
Observed task IDs remain reserved after abort; old aliases are visible only for
committed complete archives.

## References and cleanup limits

Logical history references carry explicit workspace/generation/original-root
origin and bind selected alias/descriptor/member identity and bytes. Qualified
old absolute references use the registered original origin, not arbitrary path
string replacement. This does **not** keep raw old shell command paths working;
evidence payloads and recorded commands are not patched to imply replayability.
Unrelated history appends do not invalidate a selected dependency; changed or
missing selected objects do.

`task prune` previews canonical bound archives and current declared contract
references; it does not prove global reference closure. Bound `task prune
--apply` refuses. Existing unbound legacy pruning remains its separate policy.

Experiment manifests explicitly classify inputs/results/runtime/opaque objects
and bind source-task, tool/environment declarations, object identity/digest,
rebuild inputs and must-keep references. Unmanifested legacy experiments stay
unknown. Inputs/results/opaque remain retained. Qualified runtime rows can be
`runtime_review_only`, never a deletion grant: `candidates` is empty,
`deletion_authorized` is false, global reference closure is false and declared
rebuild identities are not measured replay proof. Live, dynamic, ambiguous or
unknown references block even runtime review. Scans are bounded, same-device and
no-follow; caps report incomplete, unsafe nodes stay unknown. Logical byte
counts are not guaranteed physical savings; quarantine is not reclaimed space.

**There is no store-backed archive/runtime/retained GC apply in this design.**
DONE, mtime, matching hashes, empty process reports, terminal receipts and
migration grants never authorize deletion. Actual production activation,
migration, and any future destructive cleanup require separate approval.
