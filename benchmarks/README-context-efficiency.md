# Context efficiency benchmark

Run from repository root:

```bash
PYTHONPATH=src python3 benchmarks/context_efficiency.py --seed 1038001 --repetitions 5 --output /tmp/context-efficiency.json
```

Report must be outside repository. Default counts: 0/1/10/50/100. Each cold
repetition gets fresh identical anonymous fixture and separate Python worker.
Steady arm generates once (excluded warm-up), then performs five unchanged-source
generation/standalone-validation repetitions in same worker/fixture. Arms serial;
shared CPU/resources not parallelized. Background execution is possible; incremental
JSON and stdout progress expose completed arms, not assumed completion.

Reference package is actual Git archive of only `src/harness` at
`c74ac4d4477469fdbeda80a2b470094d3134375f`, in temporary external directory. New package
is fixed snapshot of current `src/harness` with per-file byte hashes. No second
production reference algorithm, user task metadata, secrets or business data copied.
Both arms use same anonymous template-derived input bytes, seed, fixed Git author/
commit timestamp/identity, and HEAD. Fixture is deliberately legacy Q1 with no
trusted scope origin, to remain readable by archived package; new typed
`TEST_SCOPE_AUDIT_INVALID` is retained in raw facts and explicitly normalized from
both duplicate Control Core blocker lists for comparison. No origin initialized
implicitly. Finding candidates have deterministic IDs/locations and minor severity.

Raw report includes Python/OS/dependency/CPU metadata, archive/new-source identities,
fixture byte inventories/HEAD, initial source identities/workspace/schema versions,
per-run generation and separate standalone-validation times, process wall time,
exclusive measured phases/counts, validation results, expansion count and semantic
facts. Common lightweight instrumentation applies to both packages; JSON-schema and
YAML parsing are measured, with no persistent cache. Counter bounds apply to
`generate_context` including its own independent final validation; extra standalone
validation is separately timed/counted, never hidden in those acceptance counts.

Semantic comparison preserves policy, working/global facts, fresh blockers and
audit entries; it removes volatile timestamps/derived snapshot/context hashes,
normalizes anonymous absolute fixture roots, removes absent new scope references,
and allows only explicitly listed legacy-origin tightening. Different runtime paths
are not treated as semantic drift. Original `generated_from` data/schema hashes
remain separately recorded for freshness inspection. This is not bitwise equality
of new/old schema snapshots or an acceptance proof for every dynamic candidate type.

Failed/timed-out runs remain failures. Summary uses successful samples only and
lists failure count. min/median/max only: no p95, fixed absolute deadline, 50% speedup
or N=0 10% threshold. A one-repetition smoke run is not five-repetition acceptance.
Benchmark exit 0 means complete sample semantic comparisons passed, not Harness
Gate PASS or task completion. Existing failure/recovery/reuse regression matrix
remains required independently. Final report review must verify requested repetition
counts, source identities, structural bounds and allowed semantic differences.
