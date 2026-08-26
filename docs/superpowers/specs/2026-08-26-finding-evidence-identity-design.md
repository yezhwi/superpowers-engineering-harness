# Finding Evidence Identity Design

## Goal

Fix CR-005: preserve RED, GREEN, and FULL finding evidence as distinct deterministic files.

## Filename API

`harness.collect_evidence.evidence_filename(evidence_type, *, finding_id=None, phase=None) -> str` is sole filename authority.

- Generic evidence: `<type-with-hyphens>.json`.
- Finding evidence: `<FND-ID>-<phase>-<type-with-hyphens>.json`.
- Phases: `red`, `green`, `full`.

Examples:

```text
unit-test.json
FND-001-red-unit-test.json
FND-001-green-unit-test.json
FND-001-full-unit-test.json
```

Same finding/phase/type overwrites deterministically. Different finding or phase never collide.

## CLI

Add `--phase {red,green,full}` to `harness evidence` and root collector wrapper.

- `--finding` requires `--phase`.
- `--phase` requires `--finding`.
- No phase is inferred from exit code.
- Existing generic evidence CLI remains compatible.

## Lifecycle and Gate

Finding YAML stores filename references written by caller/transition. RED, GREEN, and FULL refs resolve independently through existing proof validation. Historical RED retains self-consistent fingerprint semantics; GREEN/FULL require current workspace. No state-machine or generic evidence policy changes.

## Tests

1. filename API covers generic, red, green, full, and different finding identities;
2. real CLI collects same finding RED then GREEN with separate files, preserving both exit codes and subject/test identity;
3. invalid finding/phase argument combinations reject;
4. existing lifecycle/gate tests pass;
5. scripts remain thin wrappers and installed wheel exposes phase help.
