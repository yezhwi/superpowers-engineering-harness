"""Static trusted-code checks; not a general Python sandbox."""

import pytest


@pytest.mark.parametrize(
    "code",
    [
        "path.read_text()",
        "read = path.read_bytes\nread()",
        "import builtins as b\nf = b.open\nf('x')",
        "from io import open as read\nread('x')",
        "from os import stat as inspect\ninspect('x')",
        "from os.path import exists as present\npresent('x')",
        "import pathlib as p\nP = p.Path\nP('x').is_file()",
        "f = open\nf('x')",
    ],
)
def test_direct_io_aliases_are_rejected(code):
    from source_boundary_checks import direct_io_lines

    assert direct_io_lines(code)


@pytest.mark.parametrize(
    "code",
    [
        "from harness import source_access\nsource_access.read_text(path)",
        "from harness import source_access as access\naccess.exists(path)",
        "from harness.source_access import read_bytes as read\nread(path)",
    ],
)
def test_controlled_import_aliases_are_allowed(code):
    from source_boundary_checks import direct_io_lines

    assert direct_io_lines(code) == []


@pytest.mark.parametrize(
    "code",
    [
        "from harness import source_access as access\ntry:\n    pass\nexcept Exception as access:\n    access.read_text()",
        "from harness import source_access as access\ndef read(access):\n    return access.read_bytes()",
        "from harness import source_access as access\nimport io as access\naccess.open('x')",
    ],
)
def test_controlled_module_alias_shadowing_is_rejected(code):
    from source_boundary_checks import direct_io_lines

    assert direct_io_lines(code)


def test_module_name_cannot_be_shadowed_to_evade_checks():
    from source_boundary_checks import direct_io_lines

    assert direct_io_lines(
        "from harness import source_access\nsource_access = path\nsource_access.read_bytes()"
    )
