# Bilingual README Design

## Goal

Make Engineering Harness purpose, operating model, boundaries, installation, and v0.2 workflow understandable from repository landing page. Publish English default README and complete Simplified Chinese mirror.

## Information architecture

Both `README.md` and `README.zh-CN.md` use same structure:

1. One-sentence positioning: Harness is deterministic control plane around Superpowers workflows, not an agent replacement.
2. Problems solved: lost context, self-declared completion, stale/missing evidence, unreproduced findings, unbounded repair loops, and unnecessary implementation complexity.
3. Design model: Worker, Workflow, Controller, Truth; state, contract, evidence, gate, convergence.
4. Fit and boundaries: agentic feature/bug-fix delivery; not CI, security scanning, or human architecture decisions.
5. Full workflow including v0.2 Minimal Implementation Check PREVENT and Complexity Reviewer DETECT.
6. Five-minute quick start: install Superpowers, Harness skills, and CLI; initialize a project; begin a task.
7. Daily operations: status/recovery, core commands, impact analysis/full-suite authorization, finding lifecycle.
8. v0.2 controls: Decision Ladder, complexity taxonomy, HIGH-only blocking policy.
9. Links to design docs, development instructions, license.

Long worked bug example moves to a document under `docs/`; landing page retains short task example.

## Bilingual policy

`README.md` is English default. `README.zh-CN.md` is complete Simplified Chinese mirror. Both include reciprocal language links at top. CLI commands and file paths remain unchanged. README claims only implemented behavior; historical v0.1 design documents retain historical labels.

## Verification

Run a documentation link/command presence test that confirms both language links, `harness init`, `harness check minimal`, `harness review complexity`, and `harness converge` appear in both documents. Run full pytest suite after documentation changes.
