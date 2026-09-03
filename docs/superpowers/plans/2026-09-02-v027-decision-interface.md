# v0.2.7 Decision Records and Interface-first Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persisted user decisions and external-interface contracts, with deterministic CLI, status, risk, review, Gate, and legacy-compatible behavior.

**Architecture:** Add small `decision` and `interface_contract` domain modules responsible for schema validation and artifact lifecycle. Keep CLI parsing and command routing in existing `cli.py` and `controlplane.py`; Gate and status consume read-only projections. New directories are optional and therefore legacy Harness state remains valid.

**Tech Stack:** Python 3.11, PyYAML, jsonschema, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-v027-decision-interface-design.md`

## Global Constraints

- Keep v0.2.7 package version and existing Q1/Q2/Q3 state machine.
- Fail closed only for persisted, Harness-known decision and public-interface facts.
- Never overwrite accepted decision selection; supersession preserves audit history.
- Do not require language interfaces or contracts for private helpers.
- Reuse existing transaction publication, evidence validation, finding lifecycle, and diagnosability contract.
- Preserve projects missing `.harness/decisions/` and `.harness/interface-contracts/`.
- Run focused tests by default. Full suite requires `harness authorize full-suite` for TASK-042.
- Do not commit without `harness authorize commit` for TASK-042.

---

### Task 1: Decision artifact domain and schema

**Files:**
- Create: `src/harness/decision.py`
- Create: `src/harness/schemas/decision.schema.json`
- Modify: `src/harness/init.py`
- Modify: `tests/test_init.py`
- Create: `tests/test_decision.py`

**Interfaces:**
- Produces `propose(harness_dir: Path, document: dict) -> dict`, `accept(harness_dir: Path, decision_id: str, option: str, source: str) -> dict`, `reject(...) -> dict`, `supersede(...) -> tuple[dict, dict]`, `load_decisions(harness_dir: Path) -> list[dict]`, and `active_decisions(...) -> list[dict]`.
- Consumes `task_id` from current task and schema validation through `quality_gate.validate_schema` or shared equivalent.
- Persists `.harness/decisions/DEC-nnn.yaml`; allocation is deterministic from existing IDs.

- [ ] **Step 1: Write failing decision lifecycle tests**

```python
def test_accept_persists_selected_recommendation(tmp_path):
    setup_harness(tmp_path, task_id="TASK-042")
    decision_id = propose(tmp_path, proposal(topic="cache", recommendation="redis"))["id"]
    accepted = accept(tmp_path, decision_id, "redis", "accepted_recommendation")
    assert accepted["status"] == "ACCEPTED"
    assert accepted["selected"] == {"option": "redis", "source": "accepted_recommendation", "decided_by": "user"}


def test_supersede_retains_accepted_original(tmp_path):
    original = accepted_decision(tmp_path)
    old, replacement = supersede(tmp_path, original["id"], proposal(topic="cache", recommendation="local"))
    assert old["status"] == "SUPERSEDED"
    assert old["superseded_by"] == replacement["id"]
    assert replacement["supersedes"] == old["id"]
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_decision.py -q`

Expected: FAIL with missing `harness.decision` module.

- [ ] **Step 3: Add schema and minimal domain implementation**

```python
def active_decisions(harness_dir: Path) -> list[dict]:
    return [record for record in load_decisions(harness_dir)
            if record["status"] == "ACCEPTED" and record["superseded_by"] is None]


def accept(harness_dir: Path, decision_id: str, option: str, source: str) -> dict:
    record = load_decision(harness_dir, decision_id)
    if record["status"] != "PROPOSED" or option not in {item["id"] for item in record["options"]}:
        raise DecisionError("DECISION_ACCEPT_INVALID")
    if (option == record["recommendation"]["option"]) != (source == "accepted_recommendation"):
        raise DecisionError("DECISION_SELECTION_SOURCE_INVALID")
    record.update(status="ACCEPTED", selected={"option": option, "source": source, "decided_by": "user"})
    validate_and_publish(harness_dir, record)
    return record
```

Create decision directory during init, validate every persisted record, use atomic publication for supersede pair, and return stable domain errors.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_decision.py tests/test_init.py -q`

Expected: PASS.

- [ ] **Step 5: Commit when authorized**

```bash
git add src/harness/decision.py src/harness/schemas/decision.schema.json src/harness/init.py tests/test_decision.py tests/test_init.py
git commit -m "feat: persist harness decision records"
```

### Task 2: Decision CLI, status, and decision-aware Gate

**Files:**
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/harness_status.py`
- Modify: `src/harness/quality_gate.py`
- Create: `tests/test_cli_decision.py`
- Create: `tests/test_decision_gate.py`
- Modify: `tests/test_status_projection.py`

**Interfaces:**
- Produces `harness decision propose|accept|reject|supersede|list|show`.
- Produces Gate blockers `DECISION_UNRESOLVED`, `DECISION_CONFLICT`, `DECISION_REFERENCE_INVALID`, `DECISION_SUPERSEDE_INVALID`.
- Status renders count plus active `ID topic = selected-option` summaries without full historical text.

- [ ] **Step 1: Write failing CLI/Gate tests**

```python
def test_proposed_decision_blocks_gate_preflight(tmp_path):
    setup_gating_task(tmp_path)
    run_cli(tmp_path, "decision", "propose", *proposal_args())
    result = run_cli(tmp_path, "gate", "preflight")
    assert result.returncode == 1
    assert "DECISION_UNRESOLVED" in result.stdout


def test_status_renders_active_decision_summary(tmp_path):
    accepted_decision(tmp_path, topic="pagination", option="cursor")
    result = run_cli(tmp_path, "status")
    assert "DEC-001 pagination = cursor" in result.stdout
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_cli_decision.py tests/test_decision_gate.py tests/test_status_projection.py -q`

Expected: FAIL because `decision` parser and Gate projection do not exist.

- [ ] **Step 3: Route commands and Gate checks**

```python
p_decision = sub.add_parser("decision", help="manage persisted user decisions")
decision_sub = p_decision.add_subparsers(dest="decision_command")
# define propose, accept, reject, supersede, list, and show arguments

for decision in load_decisions(harness_dir):
    if decision["status"] == "PROPOSED":
        block("DECISION_UNRESOLVED", f"{decision['id']} is still PROPOSED")
    validate_decision_references(decision, decisions, block)
```

Use decision-domain error codes at CLI boundary. Keep Gate checks read-only and preserve no-decision legacy behavior.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_decision.py tests/test_cli_decision.py tests/test_decision_gate.py tests/test_status_projection.py -q`

Expected: PASS.

- [ ] **Step 5: Commit when authorized**

```bash
git add src/harness/cli.py src/harness/controlplane.py src/harness/harness_status.py src/harness/quality_gate.py tests/test_cli_decision.py tests/test_decision_gate.py tests/test_status_projection.py
git commit -m "feat: enforce persisted decisions in gate"
```

### Task 3: Interface-contract artifact domain and CLI

**Files:**
- Create: `src/harness/interface_contract.py`
- Create: `src/harness/schemas/interface-contract.schema.json`
- Modify: `src/harness/init.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Create: `tests/test_interface_contract.py`
- Create: `tests/test_cli_interface.py`

**Interfaces:**
- Produces `declare`, `verify`, `approve_breaking`, `load_interface_contracts`, and `declared_external_interfaces`.
- Persists `.harness/interface-contracts/INT-nnn.yaml`.
- Contract requires external visibility, consumer list, input/output/error semantics, compatibility classification, and evidence references.

- [ ] **Step 1: Write failing contract tests**

```python
def test_declared_external_interface_requires_contract_fields(tmp_path):
    with pytest.raises(InterfaceContractError, match="INTERFACE_CONTRACT_INVALID"):
        declare(tmp_path, {"name": "users", "visibility": "external"})


def test_breaking_interface_requires_explicit_approval(tmp_path):
    contract = declare(tmp_path, valid_contract(compatibility="breaking"))
    assert contract["breaking_change_approved"] is False
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_interface_contract.py tests/test_cli_interface.py -q`

Expected: FAIL with missing interface-contract module and CLI command.

- [ ] **Step 3: Implement schema-backed contract lifecycle**

```python
def declare(harness_dir: Path, document: dict) -> dict:
    document = {**document, "id": next_id(harness_dir), "task_id": current_task_id(harness_dir),
                "status": "DECLARED", "breaking_change_approved": False}
    validate_schema(document, "interface-contract.schema.json", artifact_path(harness_dir, document["id"]))
    publish_artifact(harness_dir, "interface-contracts", document)
    return document
```

`verify` accepts only current-task evidence references; `approve_breaking` writes user reason and timestamp. Reject nonexternal contract declarations rather than using this artifact for private helpers.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_interface_contract.py tests/test_cli_interface.py tests/test_init.py -q`

Expected: PASS.

- [ ] **Step 5: Commit when authorized**

```bash
git add src/harness/interface_contract.py src/harness/schemas/interface-contract.schema.json src/harness/init.py src/harness/cli.py src/harness/controlplane.py tests/test_interface_contract.py tests/test_cli_interface.py tests/test_init.py
git commit -m "feat: add interface-first contract artifacts"
```

### Task 4: Public-interface impact and Q1 escalation

**Files:**
- Modify: `src/harness/templates/impact.yaml`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/risk.py`
- Modify: `tests/test_impact_control_plane.py`
- Modify: `tests/test_risk.py`

**Interfaces:**
- Adds `impact.interfaces: list[dict]` with `id`, `kind`, `visibility`, `consumers`, `compatibility`, `affected_contracts`, and `contract_id`.
- Adds `harness impact add-interface`.
- Emits `PUBLIC_INTERFACE_RISK_ESCALATION_REQUIRED` for Q1 external declaration.

- [ ] **Step 1: Write failing impact/risk tests**

```python
def test_q1_public_interface_requires_escalation(tmp_path):
    setup_fast_task(tmp_path)
    result = run_cli(tmp_path, "impact", "add-interface", "INT-001", "--visibility", "external")
    assert result.returncode == 1
    assert "PUBLIC_INTERFACE_RISK_ESCALATION_REQUIRED" in result.stderr


def test_q2_impact_persists_consumers_and_compatibility(tmp_path):
    setup_standard_task(tmp_path)
    run_cli(tmp_path, "impact", "add-interface", "INT-001", "--visibility", "external", "--consumer", "sdk", "--compatibility", "compatible")
    assert load_impact(tmp_path)["impact"]["interfaces"][0]["consumers"] == ["sdk"]
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_impact_control_plane.py tests/test_risk.py -q`

Expected: FAIL because impact lacks interface declaration and Q1 guard.

- [ ] **Step 3: Extend impact parser and control plane**

```python
if task["risk"]["profile"] == "FAST" and visibility == "external":
    print("PUBLIC_INTERFACE_RISK_ESCALATION_REQUIRED", file=sys.stderr)
    return 1
impact.setdefault("interfaces", []).append(interface_entry)
```

Add defaults to template and legacy loader. Require explicit `harness task escalate` rather than escalating automatically.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_impact_control_plane.py tests/test_risk.py -q`

Expected: PASS.

- [ ] **Step 5: Commit when authorized**

```bash
git add src/harness/templates/impact.yaml src/harness/controlplane.py src/harness/risk.py tests/test_impact_control_plane.py tests/test_risk.py
git commit -m "feat: classify public interface impact"
```

### Task 5: Interface Gate, review finding, and status integration

**Files:**
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/harness_status.py`
- Create: `src/harness/interface_review.py`
- Create: `src/harness/schemas/interface-review.schema.json`
- Create: `src/harness/schemas/interface-finding.schema.json`
- Modify: `src/harness/quality_gate.py:finding_schema_name`
- Modify: `src/harness/controlplane.py:cmd_finding_transition`
- Create: `tests/test_interface_gate.py`
- Create: `tests/test_interface_review.py`

**Interfaces:**
- Produces `INTERFACE_CONTRACT_MISSING`, `INTERFACE_COMPATIBILITY_UNDECLARED`, `INTERFACE_VERIFICATION_MISSING`, `INTERFACE_BREAKING_CHANGE_UNAPPROVED`.
- Supports `harness review interface --file review.yaml [--base REF]` and `category: interface` findings through existing finding lifecycle.
- Status reports public change count and compatibility summaries.

- [ ] **Step 1: Write failing Gate tests**

```python
@pytest.mark.parametrize("code, contract", [
    ("INTERFACE_CONTRACT_MISSING", None),
    ("INTERFACE_COMPATIBILITY_UNDECLARED", contract_without_compatibility()),
    ("INTERFACE_VERIFICATION_MISSING", valid_contract()),
])
def test_declared_external_interface_blocks_missing_obligation(tmp_path, code, contract):
    setup_gating_task_with_external_impact(tmp_path, contract)
    assert code in run_cli(tmp_path, "gate", "preflight").stdout


def test_interface_review_publishes_bound_finding(tmp_path):
    setup_reviewing_task_with_external_contract(tmp_path)
    review = write_interface_review(tmp_path, proposals=[interface_proposal("INT-001")])
    result = run_cli(tmp_path, "review", "interface", "--file", str(review))
    assert result.returncode == 0
    assert load_findings(tmp_path / ".harness" / "findings")[0]["category"] == "interface"


def test_private_only_task_has_no_interface_blocker(tmp_path):
    setup_gating_task(tmp_path)
    assert "INTERFACE_" not in run_cli(tmp_path, "gate", "preflight").stdout
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_interface_gate.py tests/test_interface_review.py tests/test_status_projection.py -q`

Expected: FAIL because Gate ignores interface impact.

- [ ] **Step 3: Add deterministic projections and checks**

```python
for declared in external_impact_interfaces(impact):
    contract = contracts_by_id.get(declared["contract_id"])
    if contract is None:
        block("INTERFACE_CONTRACT_MISSING", f"{declared['id']} has no contract")
    elif not contract["compatibility"]["classification"]:
        block("INTERFACE_COMPATIBILITY_UNDECLARED", f"{declared['id']} lacks compatibility")
    elif contract["compatibility"]["classification"] == "breaking" and not contract["breaking_change_approved"]:
        block("INTERFACE_BREAKING_CHANGE_UNAPPROVED", f"{declared['id']} is unapproved breaking change")
```

Add `review interface` parser and control-plane command. `interface_review.py` validates `interface-review.schema.json`, verifies task/HEAD/base binding and declared contract IDs, then atomically publishes review evidence and validated proposals. Create `interface-finding.schema.json` with normal Finding lifecycle fields plus `category: interface`; route it in `finding_schema_name`. Validate interface evidence using existing evidence resolver and freshness rules. Map interface review defects into existing finding lifecycle without a second state machine.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_interface_contract.py tests/test_interface_gate.py tests/test_interface_review.py tests/test_status_projection.py -q`

Expected: PASS.

- [ ] **Step 5: Commit when authorized**

```bash
git add src/harness/cli.py src/harness/controlplane.py src/harness/quality_gate.py src/harness/harness_status.py src/harness/interface_review.py src/harness/schemas/interface-review.schema.json src/harness/schemas/interface-finding.schema.json tests/test_interface_gate.py tests/test_interface_review.py tests/test_status_projection.py
git commit -m "feat: gate external interface contracts"
```

### Task 6: Skill and release documentation

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_readme_docs.py`

**Interfaces:**
- Session Startup includes active decision summary.
- Decision question protocol requires facts, options, recommendation, reason, trade-offs, impact, user confirmation, and persisted record.
- Q1 public interface detection routes to explicit escalation.

- [ ] **Step 1: Write failing documentation assertions**

```python
def test_docs_describe_decision_and_interface_contract_commands():
    readme = (REPO / "README.md").read_text()
    skill = (REPO / "SKILL.md").read_text()
    assert "harness decision propose" in readme
    assert "Interface-first" in readme
    assert "active accepted decisions" in skill
    assert "Recommendation" in skill
```

- [ ] **Step 2: Run RED test**

Run: `pytest tests/test_readme_docs.py -q`

Expected: FAIL because public docs and Skill do not describe new workflow.

- [ ] **Step 3: Document exact workflow**

Document decision CLI examples, accepted-decision resume behavior, interface contract scope, stable blockers, Q1 escalation, and legacy compatibility. State that recommendation uses observable facts and does not replace user confirmation.

- [ ] **Step 4: Run GREEN test**

Run: `pytest tests/test_readme_docs.py -q`

Expected: PASS.

- [ ] **Step 5: Commit when authorized**

```bash
git add SKILL.md README.md README.zh-CN.md CHANGELOG.md tests/test_readme_docs.py
git commit -m "docs: describe decision and interface contracts"
```

### Task 7: Focused regression and Harness verification

**Files:**
- Modify: `.harness/impact.yaml` through CLI commands
- Modify: `.harness/requirements.yaml` and `.harness/invariants.yaml` only through verification commands
- Create: `.harness/evidence/*.json` through `harness evidence`

**Interfaces:**
- Uses all feature suites as related proof for REQ-001 through REQ-006 and INV-001 through INV-005.
- Produces fresh evidence bound to current HEAD and workspace.

- [ ] **Step 1: Record changed paths and related tests**

```bash
harness impact add-change src/harness/decision.py
harness impact add-change src/harness/interface_contract.py
harness impact add-change src/harness/controlplane.py
harness impact add-change src/harness/quality_gate.py
harness impact add-test tests/test_decision.py
harness impact add-test tests/test_interface_gate.py
```

- [ ] **Step 2: Run focused regression suite**

```bash
pytest tests/test_decision.py tests/test_cli_decision.py tests/test_decision_gate.py tests/test_interface_contract.py tests/test_cli_interface.py tests/test_interface_gate.py tests/test_interface_review.py tests/test_impact_control_plane.py tests/test_risk.py tests/test_status_projection.py tests/test_init.py tests/test_readme_docs.py -q
```

Expected: PASS.

- [ ] **Step 3: Collect fresh related evidence**

```bash
harness evidence --type unit_test --scope related --command "pytest tests/test_decision.py tests/test_cli_decision.py tests/test_decision_gate.py tests/test_interface_contract.py tests/test_cli_interface.py tests/test_interface_gate.py tests/test_interface_review.py tests/test_impact_control_plane.py tests/test_risk.py tests/test_status_projection.py tests/test_init.py tests/test_readme_docs.py -q"
harness evidence --type build --scope related --command "python -m pip wheel --no-deps --no-build-isolation . --wheel-dir /tmp/TASK-042-wheel"
```

- [ ] **Step 4: Verify requirements and invariants with evidence**

```bash
harness requirement verify REQ-001 --evidence <unit-evidence-id>
harness requirement verify REQ-002 --evidence <unit-evidence-id>
harness requirement verify REQ-003 --evidence <unit-evidence-id>
harness requirement verify REQ-004 --evidence <unit-evidence-id>
harness requirement verify REQ-005 --evidence <unit-evidence-id>
harness requirement verify REQ-006 --evidence <unit-evidence-id>
harness invariant verify INV-001 --evidence <unit-evidence-id>
harness invariant verify INV-002 --evidence <unit-evidence-id>
harness invariant verify INV-003 --evidence <unit-evidence-id>
harness invariant verify INV-004 --evidence <unit-evidence-id>
harness invariant verify INV-005 --evidence <unit-evidence-id>
```

- [ ] **Step 5: Run complexity, interface, diagnosability, and Gate workflow**

```bash
harness transition VERIFYING
harness review complexity --file /tmp/TASK-042-complexity.yaml
harness transition REVIEWING
harness review interface --file /tmp/TASK-042-interface-review.yaml
harness review diagnosability --file /tmp/TASK-042-diagnosability.yaml
harness review outcome PASS --reason-code REVIEW_CLEAN
harness gate
```

Expected: Gate persists `DECISION: CONVERGED`; only then run `harness transition DONE`.
