from test_cli_decision import cli, setup


def test_interface_declare_persists_external_contract(tmp_path):
    """Break caught: external interface can be declared without durable contract."""
    setup(tmp_path)

    result = cli(
        tmp_path,
        "interface",
        "declare",
        "--name",
        "decision-api",
        "--kind",
        "cli",
        "--consumer",
        "agent-worker",
        "--input",
        "command arguments",
        "--output",
        "machine-readable result",
        "--error",
        "stable error code",
        "--compatibility",
        "compatible",
        "--rationale",
        "additive command",
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".harness" / "interface-contracts" / "INT-001.yaml").is_file()
