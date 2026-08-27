# Benchmark Corpus and AC Evidence Design

**Status:** Proposed P1-4. No implementation before user approves this document.

## Goal

Create versioned 50-fixture benchmark corpus and fail-closed AC16–20 evidence evaluation. Corpus existence is not performance evidence; missing external artifacts remain INCONCLUSIVE.

## Corpus

Create individual YAML fixtures:

```text
benchmarks/corpus/q0/  # 10
benchmarks/corpus/q1/  # 20
benchmarks/corpus/q2/  # 10
benchmarks/corpus/q3/  # 10
```

Every fixture requires:

```yaml
id: q1-01-error-mapper
level: Q1
expected_profile: FAST
scenario: error mapper null handling
risk_tags: [local_logic]
required_correctness: [gate_pass, regression_detected]
```

IDs match `<level>-<two-digit>-<slug>`. Level/profile pairs are Q0/no profile, Q1/FAST, Q2/STANDARD, Q3/STRICT. Q0 uses `expected_profile: null` and required correctness is empty. Scenario and every risk tag are nonempty strings.

Q1 covers error mapper, formatter, UI state, helper reuse, CLI config, validation bug, consumer omission. Q2 covers API/schema/event/cross-module/contract. Q3 covers permission, tenant isolation, migration, concurrency, security.

## Corpus validation

`harness benchmark corpus validate --corpus <dir>` validates all fixture shapes, IDs, directory-level consistency, exact distribution Q0 10/Q1 20/Q2 10/Q3 10, and duplicate IDs. It writes no report and executes no agents. Invalid corpus exits 2.

## Artifact comparison and AC evaluation

Extend comparator with `evaluate_acceptance(report, fixtures) -> dict`.

- AC16 Q1 tool calls: all 20 Q1 baseline/adaptive artifacts need numeric `tool_calls`; adaptive mean must be lower.
- AC17 Q1 tokens: all 20 Q1 artifacts need numeric `token_estimate`; adaptive mean must be lower.
- AC18 Q1 time: all 20 Q1 artifacts need numeric `elapsed_seconds`; adaptive mean must be lower.
- AC19 success rate: all 50 fixture correctness artifacts complete; adaptive successful-fixture count divided by 50 must be at least baseline count divided by 50.
- AC20 Q2/Q3 detection: all 20 Q2/Q3 artifacts complete required correctness vectors; adaptive required true-detection count must be at least baseline.

Any missing/malformed artifact, missing metric, null required correctness value, or incomplete fixture set yields that AC `INCONCLUSIVE`. Comparator never claims improvement for INCONCLUSIVE ACs.

## Invariants

- No external agent execution, network, metric inference, or fake artifact generation.
- Corpus validator does not claim correctness/performance.
- Existing fixture `benchmark run` and `benchmark compare` remain supported.
- Reports distinguish `PASS`, `FAIL`, and `INCONCLUSIVE` per AC.

## Verification

TDD proves corpus exact count/distribution/shape rejection, Q0 profile semantics, duplicate detection, complete synthetic artifacts yielding AC pass/fail, and one missing artifact/metric yielding INCONCLUSIVE.
