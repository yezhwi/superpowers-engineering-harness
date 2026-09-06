# Bilingual README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mixed-language landing page with English README and complete Simplified Chinese mirror that explain Harness purpose, design, workflow, and usage.

**Architecture:** Both README files share fixed information architecture and reciprocal language links. README keeps short operational examples; long worked example moves to `docs/`.

**Tech Stack:** Markdown, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-readme-bilingual-design.md`

## Global Constraints

- `README.md` is English default; `README.zh-CN.md` is complete Simplified Chinese mirror.
- Document only existing commands and behavior.
- Keep CLI commands, file paths, and code blocks identical across languages.
- No changes to runtime code, schemas, state machine, or gate.

---

### Task 1: Add bilingual README contract test

**Files:**
- Create: `tests/test_readme_docs.py`

**Interfaces:**
- Produces documentation guard for both README files and implemented core commands.

- [ ] **Step 1: Write failing documentation behavior test**

```python
def test_bilingual_readmes_link_to_each_other_and_document_core_commands():
    english = (REPO / "README.md").read_text()
    chinese = (REPO / "README.zh-CN.md").read_text()
    for command in ("harness init", "harness check minimal", "harness review complexity", "harness converge"):
        assert command in english
        assert command in chinese
    assert "README.zh-CN.md" in english
    assert "README.md" in chinese
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_readme_docs.py -q`

Expected: FAIL because Chinese README does not exist.

- [ ] **Step 3: Commit test**

```bash
git add tests/test_readme_docs.py
git commit -m "test: require bilingual readme links"
```

### Task 2: Rewrite English README and add Chinese mirror

**Files:**
- Modify: `README.md`
- Create: `README.zh-CN.md`
- Create: `docs/worked-example.md`

**Interfaces:**
- Both README files expose positioning, problems, design model, scope, workflow, quick start, operations, v0.2, docs, development, license.

- [ ] **Step 1: Replace English README content**

Write concise English sections in spec order. Add top language link:

```markdown
[简体中文](README.zh-CN.md)
```

Keep short task prompt and link long bug walkthrough to `docs/worked-example.md`.

- [ ] **Step 2: Create Chinese mirror**

Translate every English section. Add top link:

```markdown
[English](README.md)
```

Keep commands and paths byte-for-byte identical.

- [ ] **Step 3: Move worked example**

Move existing full retry/refund walkthrough to `docs/worked-example.md`; link both README files to it.

- [ ] **Step 4: Run contract test GREEN**

Run: `python -m pytest tests/test_readme_docs.py -q`

Expected: PASS.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md README.zh-CN.md docs/worked-example.md
git commit -m "docs: add bilingual harness readmes"
```

### Task 3: Full documentation verification

**Files:**
- Modify only if verification exposes factual documentation defect.

- [ ] **Step 1: Verify documented commands exist**

Run:

```bash
harness --help
harness check --help
harness review --help
```

Expected: help includes documented subcommands.

- [ ] **Step 2: Run full regression**

Run: `python -m pytest tests/ -q`

Expected: PASS.

- [ ] **Step 3: Review language parity**

Check every English section has Chinese counterpart; commands and paths match; no v0.1-only claims present as v0.2 behavior.

- [ ] **Step 4: Commit verification-only fixes if needed**

```bash
git add README.md README.zh-CN.md docs/worked-example.md tests/test_readme_docs.py
git commit -m "docs: align bilingual readmes"
```

## Plan self-review

- Spec coverage: Tasks 1–3 cover bilingual links, information architecture, moved example, existing-command accuracy, and full regression.
- Placeholder scan: no TBD/TODO.
- Type consistency: both files and every command use exact repository paths and CLI names.
