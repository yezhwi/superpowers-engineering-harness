# v0.3.0 Architecture Benchmark Report

Status: PENDING

No measured improvement is claimed. Populate this report only from accepted persisted run artifacts. Generated fixtures are not measured Agent runs, and results do not prove external Agent generalization or provide Gate guarantees.

## Run Contract

- Validate `benchmarks/architecture` before comparison.
- Run `drift_detection` and `context_recovery` separately.
- Preserve identical fixture inputs and token budget across arms.
- Change only declared treatment for each experiment.
- At least three independent runs per fixture and arm.
- Accept runtime/provider token and tool-call measurements only; estimated usage is invalid.
- Record correctness and integrity before interpreting efficiency.

## Drift Detection

Treatment: Architecture Gate `off` baseline versus `required` adaptive.

| Metric | numerator | denominator | not_applicable | value |
|---|---:|---:|---:|---:|
| Drift recall | PENDING | PENDING | PENDING | INCONCLUSIVE |
| Diagnostic precision | PENDING | PENDING | PENDING | INCONCLUSIVE |
| False-positive rate | PENDING | PENDING | PENDING | INCONCLUSIVE |

### Declaration Quality

| Metric | numerator | denominator | not_applicable | value |
|---|---:|---:|---:|---:|
| Missed-impact proxy | PENDING | PENDING | PENDING | INCONCLUSIVE |

## Context Recovery

Treatment: identical required Architecture assessment and task facts; baseline omits Architecture projection, adaptive includes approved declared-plus-one-hop projection.

| Metric | numerator | denominator | not_applicable | value |
|---|---:|---:|---:|---:|
| Context factual recovery | PENDING | PENDING | PENDING | INCONCLUSIVE |

## Efficiency

Report run-level token and tool-call summaries for each arm only after correctness does not regress. Efficiency never changes correctness verdict.

| Experiment | Arm | Runs | Median tokens | p90 tokens | Tokens/success | Tool calls/success |
|---|---|---:|---:|---:|---:|---:|
| drift_detection | baseline | PENDING | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| drift_detection | adaptive | PENDING | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| context_recovery | baseline | PENDING | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| context_recovery | adaptive | PENDING | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |

## Limitations

- Fixture performance describes only accepted sample runs.
- Module text appearing in Context does not prove understanding.
- Lower token cost cannot offset correctness or integrity regression.
- Benchmark commands do not modify canonical Harness state.
