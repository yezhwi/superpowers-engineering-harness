"""Architecture model, resolver, and fingerprint tests."""

from copy import deepcopy

import pytest

from harness.architecture import (
    ArchitectureError,
    architecture_fingerprint,
    load_architecture_document,
    resolve_ownership,
)


def architecture_document() -> dict:
    return {
        "version": 1,
        "modules": [
            {
                "id": "auth",
                "name": "Authentication",
                "responsibility": "Authenticate users.",
                "depends_on": ["session"],
                "evidence": [{"type": "source", "path": "src/auth/service.py"}],
            },
            {
                "id": "session",
                "name": "Session",
                "responsibility": "Manage sessions.",
                "depends_on": [],
                "evidence": [{"type": "config", "path": "config/session.yaml"}],
            },
            {
                "id": "payment",
                "name": "Payment",
                "responsibility": "Record payments.",
                "depends_on": [],
                "evidence": [
                    {"type": "documentation", "path": "docs/payment.md"}
                ],
            },
        ],
        "ownership": [
            {
                "id": "OWN-001",
                "pattern": "src/auth/**",
                "kind": "production",
                "modules": ["auth"],
            },
            {
                "id": "OWN-002",
                "pattern": "src/*/shared.py",
                "kind": "shared",
                "modules": ["auth", "payment"],
            },
            {
                "id": "OWN-003",
                "pattern": "tests/**",
                "kind": "support",
                "modules": [],
            },
            {
                "id": "OWN-004",
                "pattern": "src/future/**",
                "kind": "production",
                "modules": ["payment"],
                "allow_empty": True,
                "empty_reason": "Planned module.",
            },
        ],
    }


def test_load_architecture_document_returns_immutable_domain_model():
    model = load_architecture_document(architecture_document())

    assert model.version == 1
    assert tuple(module.id for module in model.modules) == ("auth", "session", "payment")
    assert model.ownership[0].allow_empty is False
    with pytest.raises((AttributeError, TypeError)):
        model.modules[0].name = "changed"


def test_raw_yaml_size_bound_accepts_one_mib_and_rejects_next_byte():
    document = architecture_document()

    load_architecture_document(document, source_size_bytes=1024 * 1024)
    with pytest.raises(ArchitectureError) as exc:
        load_architecture_document(document, source_size_bytes=1024 * 1024 + 1)
    assert exc.value.code == "ARCHITECTURE_SIZE_LIMIT"


def _module(index: int) -> dict:
    return {
        "id": f"m{index}",
        "name": f"Module {index}",
        "responsibility": "Own one concern.",
        "depends_on": [],
        "evidence": [{"type": "source", "path": f"src/m{index}.py"}],
    }


def _rule(index: int) -> dict:
    return {
        "id": f"OWN-{index + 1:03d}",
        "pattern": f"src/path-{index}.py",
        "kind": "production",
        "modules": ["auth"],
        "allow_empty": True,
        "empty_reason": "Reserved path.",
    }


@pytest.mark.parametrize(
    ("field", "limit", "factory"),
    [
        ("modules", 256, _module),
        ("ownership", 1024, _rule),
    ],
)
def test_collection_hard_bounds_accept_limit_and_reject_limit_plus_one(
    field, limit, factory
):
    document = architecture_document()
    document[field] = [factory(index) for index in range(limit)]
    if field == "modules":
        document["ownership"] = []

    load_architecture_document(document)
    document[field].append(factory(limit))
    with pytest.raises(ArchitectureError) as exc:
        load_architecture_document(document)
    assert exc.value.code == "ARCHITECTURE_SCHEMA_INVALID"


@pytest.mark.parametrize(
    ("field", "limit", "value"),
    [
        ("depends_on", 32, lambda index: f"d{index}"),
        (
            "evidence",
            16,
            lambda index: {"type": "source", "path": f"src/e{index}.py"},
        ),
    ],
)
def test_per_module_collection_bounds_accept_limit_and_reject_next(
    field, limit, value
):
    document = architecture_document()
    auth = document["modules"][0]
    auth[field] = [value(index) for index in range(limit)]
    if field == "depends_on":
        document["modules"].extend(
            {
                "id": value(index),
                "name": value(index),
                "responsibility": value(index),
                "depends_on": [],
                "evidence": [{"type": "source", "path": f"src/d{index}.py"}],
            }
            for index in range(limit)
        )

    load_architecture_document(document)
    auth[field].append(value(limit))
    if field == "depends_on":
        document["modules"].append(
            {
                "id": value(limit),
                "name": value(limit),
                "responsibility": value(limit),
                "depends_on": [],
                "evidence": [{"type": "source", "path": f"src/d{limit}.py"}],
            }
        )
    with pytest.raises(ArchitectureError) as exc:
        load_architecture_document(document)
    assert exc.value.code == "ARCHITECTURE_SCHEMA_INVALID"


@pytest.mark.parametrize(
    ("target", "field", "limit"),
    [
        ("module", "id", 64),
        ("module", "name", 128),
        ("module", "responsibility", 512),
        ("evidence", "path", 512),
        ("ownership", "pattern", 512),
        ("ownership", "empty_reason", 512),
    ],
)
def test_string_bounds_count_unicode_code_points(target, field, limit):
    document = architecture_document()
    if target == "module":
        record = document["modules"][0]
    elif target == "evidence":
        record = document["modules"][0]["evidence"][0]
    else:
        record = document["ownership"][3]
    if field == "id":
        old_id = record[field]
        record[field] = "a" * limit
        for module in document["modules"]:
            module["depends_on"] = [
                record[field] if value == old_id else value
                for value in module["depends_on"]
            ]
        for rule in document["ownership"]:
            rule["modules"] = [
                record[field] if value == old_id else value for value in rule["modules"]
            ]
    elif field in {"path", "pattern"}:
        record[field] = "a" * (limit - 2) + "/x"
    else:
        record[field] = "界" * limit

    load_architecture_document(document)
    record[field] += "x"
    with pytest.raises(ArchitectureError) as exc:
        load_architecture_document(document)
    assert exc.value.code == "ARCHITECTURE_SCHEMA_INVALID"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["modules"].append(deepcopy(d["modules"][0])),
        lambda d: d["ownership"].append(deepcopy(d["ownership"][0])),
        lambda d: d["modules"][0].update(depends_on=["session", "session"]),
        lambda d: d["modules"][0].update(depends_on=["missing"]),
        lambda d: d["modules"][0].update(depends_on=["auth"]),
        lambda d: d["modules"][0].update(evidence=[]),
        lambda d: d["ownership"][0].update(modules=[]),
        lambda d: d["ownership"][1].update(modules=["auth"]),
        lambda d: d["ownership"][2].update(modules=["auth"]),
        lambda d: d["ownership"][0].update(modules=["missing"]),
        lambda d: d["ownership"][3].pop("empty_reason"),
    ],
)
def test_semantically_invalid_models_fail_closed(mutate):
    document = architecture_document()
    mutate(document)

    with pytest.raises(ArchitectureError) as exc:
        load_architecture_document(document)
    assert exc.value.code in {
        "ARCHITECTURE_SCHEMA_INVALID",
        "ARCHITECTURE_MODEL_INVALID",
    }


def test_dependency_cycles_are_allowed_when_not_self_referential():
    document = architecture_document()
    document["modules"][1]["depends_on"] = ["auth"]

    model = load_architecture_document(document)

    assert model.modules[0].depends_on == ("session",)
    assert model.modules[1].depends_on == ("auth",)


@pytest.mark.parametrize(
    ("path", "expected_code"),
    [
        ("", "ARCHITECTURE_SCHEMA_INVALID"),
        ("/absolute.py", "ARCHITECTURE_PATH_INVALID"),
        ("../outside.py", "ARCHITECTURE_PATH_INVALID"),
        ("src/../outside.py", "ARCHITECTURE_PATH_INVALID"),
        ("src\\file.py", "ARCHITECTURE_PATH_INVALID"),
        ("src//file.py", "ARCHITECTURE_PATH_INVALID"),
        ("src/./file.py", "ARCHITECTURE_PATH_INVALID"),
    ],
)
def test_evidence_paths_must_be_canonical_repository_relative(path, expected_code):
    document = architecture_document()
    document["modules"][0]["evidence"][0]["path"] = path

    with pytest.raises(ArchitectureError) as exc:
        load_architecture_document(document)
    assert exc.value.code == expected_code


@pytest.mark.parametrize(
    "pattern",
    [
        "src/?/file.py",
        "src/[ab]/file.py",
        "src/{a,b}/file.py",
        "src/**/file.py",
        "src\\**",
        "src//**",
        "src/../**",
    ],
)
def test_ownership_pattern_grammar_rejects_unsupported_patterns(pattern):
    document = architecture_document()
    document["ownership"][0]["pattern"] = pattern

    with pytest.raises(ArchitectureError) as exc:
        load_architecture_document(document)
    assert exc.value.code == "ARCHITECTURE_PATTERN_INVALID"


def test_duplicate_semantic_ownership_rules_are_rejected_even_with_distinct_ids():
    document = architecture_document()
    duplicate = deepcopy(document["ownership"][0])
    duplicate["id"] = "OWN-999"
    document["ownership"].append(duplicate)

    with pytest.raises(ArchitectureError) as exc:
        load_architecture_document(document)
    assert exc.value.code == "ARCHITECTURE_MODEL_INVALID"


def test_resolver_prefers_exact_then_more_literal_then_more_segments():
    document = architecture_document()
    document["ownership"] = [
        {"id": "OWN-010", "pattern": "src/*/**", "kind": "production", "modules": ["session"]},
        {"id": "OWN-011", "pattern": "src/auth/**", "kind": "production", "modules": ["auth"]},
        {"id": "OWN-012", "pattern": "src/auth/service.py", "kind": "production", "modules": ["payment"]},
    ]
    model = load_architecture_document(document)

    exact = resolve_ownership(model, "src/auth/service.py")
    recursive = resolve_ownership(model, "src/auth/nested/file.py")

    assert (exact.status, exact.rule_id, exact.score) == ("resolved", "OWN-012", (1, 3, 3))
    assert (recursive.status, recursive.rule_id, recursive.score) == ("resolved", "OWN-011", (0, 2, 3))


def test_resolver_reports_unresolved_ambiguous_shared_and_support_results():
    document = architecture_document()
    document["ownership"] = [
        {"id": "OWN-010", "pattern": "src/*/shared.py", "kind": "shared", "modules": ["auth", "payment"]},
        {"id": "OWN-011", "pattern": "src/common/shared.py", "kind": "shared", "modules": ["auth", "payment"]},
        {"id": "OWN-012", "pattern": "src/*/shared.py", "kind": "shared", "modules": ["session", "payment"]},
        {"id": "OWN-013", "pattern": "tests/**", "kind": "support", "modules": []},
    ]
    model = load_architecture_document(document)

    ambiguous = resolve_ownership(model, "src/auth/shared.py")
    shared = resolve_ownership(model, "src/common/shared.py")
    support = resolve_ownership(model, "tests/unit/test_auth.py")
    unresolved = resolve_ownership(model, "docs/readme.md")

    assert ambiguous.status == "ambiguous"
    assert ambiguous.rule_ids == ("OWN-010", "OWN-012")
    assert shared.status == "resolved"
    assert shared.modules == ("auth", "payment") and shared.kind == "shared"
    assert support.status == "resolved" and support.modules == () and support.kind == "support"
    assert unresolved.status == "unresolved" and unresolved.rule_id is None


@pytest.mark.parametrize("path", ["", "/abs", "src/../x", "src\\x", "src//x"])
def test_resolver_rejects_noncanonical_input_path(path):
    model = load_architecture_document(architecture_document())
    with pytest.raises(ArchitectureError) as exc:
        resolve_ownership(model, path)
    assert exc.value.code == "ARCHITECTURE_PATH_INVALID"


def test_semantic_fingerprint_ignores_presentation_order_but_tracks_semantics():
    first = architecture_document()
    second = deepcopy(first)
    second["modules"] = list(reversed(second["modules"]))
    second["modules"][0]["evidence"] = list(reversed(second["modules"][0]["evidence"]))
    second["ownership"] = list(reversed(second["ownership"]))
    for rule in second["ownership"]:
        rule["modules"] = list(reversed(rule["modules"]))

    first_hash = architecture_fingerprint(load_architecture_document(first))
    second_hash = architecture_fingerprint(load_architecture_document(second))
    second["modules"][0]["responsibility"] += " Changed."
    changed_hash = architecture_fingerprint(load_architecture_document(second))

    assert first_hash == second_hash
    assert first_hash.startswith("sha256:") and len(first_hash) == 71
    assert changed_hash != first_hash
