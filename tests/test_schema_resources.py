"""Registered package resources are versioned independently of project files."""

import pytest
import test_context_builder

from harness.context.model import ContextBuildError
from harness.source_access import source_scope

harness = test_context_builder.harness


def test_schema_parser_and_manifest_use_same_registered_bytes():
    from harness.schema_resources import read_schema, schema_versions

    assert read_schema("decision.schema.json")["type"] == "object"
    assert schema_versions()["decision.schema.json"].startswith("sha256:")


@pytest.mark.parametrize(
    "name",
    [
        "../task.schema.json",
        "/tmp/schema.json",
        "unknown.json",
        "schemas/task.schema.json",
    ],
)
def test_unknown_or_noncanonical_resource_is_rejected(name):
    from harness.schema_resources import read_schema

    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        read_schema(name)


def test_schema_bytes_observed_in_source_scope(tmp_path):
    from harness.schema_resources import read_schema, schema_versions

    expected = schema_versions()["decision.schema.json"]
    with source_scope(tmp_path, allowed=[]) as observed:
        read_schema("decision.schema.json")
    assert observed.resource_snapshot() == {"decision.schema.json": expected}


def test_resource_change_stales_old_context(harness, monkeypatch):
    from harness import schema_resources
    from harness.context.integrity import build_context, validate_context

    document = build_context(harness)
    original = schema_resources._resource_bytes

    def changed(name):
        data = original(name)
        return data + b"\n" if name == "decision.schema.json" else data

    monkeypatch.setattr(schema_resources, "_resource_bytes", changed)
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        validate_context(harness, document)


def test_resource_change_before_scope_exit_is_stale(tmp_path, monkeypatch):
    from harness import schema_resources

    original = schema_resources._resource_bytes
    with (
        pytest.raises(ContextBuildError, match="CONTEXT_STALE"),
        source_scope(tmp_path, allowed=[]),
    ):
        schema_resources.read_schema("decision.schema.json")
        monkeypatch.setattr(
            schema_resources, "_resource_bytes", lambda name: original(name) + b"\n"
        )


def test_registered_resource_does_not_grant_neighbor_read_permission():
    from importlib import resources

    from harness.schema_resources import read_schema

    root = resources.files("harness")
    with (
        pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"),
        source_scope(root, allowed=[]),
    ):
        assert read_schema("decision.schema.json")["type"] == "object"
        (root / "decision.py").read_bytes()


def test_unknown_resource_error_cannot_be_swallowed(tmp_path):
    from harness.schema_resources import read_schema

    with (
        pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"),
        source_scope(tmp_path, allowed=[]),
    ):
        try:
            read_schema("unknown.json")
        except ContextBuildError:
            pass


def test_old_projection_document_requires_regeneration(harness):
    from harness.context.integrity import build_context, validate_context

    document = build_context(harness)
    document["generated_from"]["projection_version"] = 1
    document["generated_from"].pop("schema_resources")
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        validate_context(harness, document)


def test_resource_symlink_outside_schema_root_is_rejected(tmp_path, monkeypatch):
    from harness import schema_resources

    package = tmp_path / "package"
    schemas = package / "schemas"
    schemas.mkdir(parents=True)
    outside = tmp_path / "private.json"
    outside.write_text('{"type": "object"}')
    (schemas / "decision.schema.json").symlink_to(outside)
    monkeypatch.setattr(schema_resources.resources, "files", lambda name: package)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        schema_resources.read_schema("decision.schema.json")


def test_all_shipped_schemas_have_explicit_registry_entries():
    from importlib import resources

    from harness.schema_resources import SCHEMA_NAMES

    actual = {
        p.name
        for p in resources.files("harness").joinpath("schemas").iterdir()
        if p.name.endswith(".json")
    }
    assert actual == set(SCHEMA_NAMES)
