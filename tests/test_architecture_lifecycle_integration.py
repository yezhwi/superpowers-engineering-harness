"""Architecture P0 lifecycle integration tests."""


def test_mode_off_gate_ignores_malformed_architecture_artifact(tmp_path):
    from harness.quality_gate import assess_gate
    from test_quality_gate import make_harness

    harness = make_harness(tmp_path)
    (harness / "architecture.yaml").write_text("malformed: [")

    assessment = assess_gate(harness, allow_preflight=True)

    assert assessment.status == "PASS"
    assert not any(
        blocker.code.startswith("ARCHITECTURE_") for blocker in assessment.blockers
    )


def test_required_support_only_change_passes_without_declared_modules(tmp_path):
    import yaml

    from harness.architecture import architecture_fingerprint, load_architecture_document
    from harness.architecture_gate import assess_architecture
    from test_architecture_gate import fixture

    root, harness, task, gate = fixture(tmp_path, declared=())
    architecture = yaml.safe_load((harness / "architecture.yaml").read_text())
    architecture["ownership"] = [
        {"id": "OWN-001", "pattern": "docs/**", "kind": "support", "modules": []}
    ]
    model = load_architecture_document(architecture)
    (harness / "architecture.yaml").write_text(yaml.safe_dump(architecture))
    seal_path = harness / "alignment-freeze.yaml"
    seal = yaml.safe_load(seal_path.read_text())
    seal["architecture_fingerprint"] = architecture_fingerprint(model)
    seal_path.write_text(yaml.safe_dump(seal))
    (root / "docs").mkdir()
    (root / "docs/note.md").write_text("support")

    assessment = assess_architecture(harness, task, gate, allow_preflight=False)

    assert assessment.blockers == ()
    assert assessment.declared_modules == ()
    assert assessment.relevant_modules == ()


def test_required_production_drift_is_repairable_but_contract_change_is_not(tmp_path):
    from harness.architecture_gate import assess_architecture
    from harness.blockers import GateBlocker, select_recovery
    from test_architecture_gate import fixture

    root, harness, task, gate = fixture(tmp_path, declared=())
    (root / "src/app.py").write_text("changed\n")

    assessment = assess_architecture(harness, task, gate, allow_preflight=False)
    drift = [b for b in assessment.blockers if b.code == "ARCHITECTURE_SCOPE_DRIFT"]

    assert len(drift) == 1
    assert select_recovery(drift) == "IMPLEMENTING"
    authority = GateBlocker(
        "CONTRACT_CHANGED",
        "implementation",
        "sealed contract changed",
        source="artifact:.harness/alignment-freeze.yaml",
    )
    assert select_recovery([authority]) is None
