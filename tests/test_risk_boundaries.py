import pytest

from harness.risk_boundaries import (
    RiskBoundaryPolicyError, business_paths, load_boundaries, matches_boundary,
    required_level,
)


def test_business_paths_excludes_docs_and_tests_only():
    assert business_paths(["docs/a.md", "tests/test_a.py", "README.md", "src/api/x.py"]) == ("src/api/x.py",)


def test_q3_boundary_wins_over_q2(tmp_path):
    policy = tmp_path / "risk-boundaries.yaml"
    policy.write_text("boundaries:\n  q2: [src/**]\n  q3: [auth/**]\n")
    assert required_level(["src/api.py", "auth/login.py"], load_boundaries(policy)) == "Q3"


@pytest.mark.parametrize("path", ["src/api.py", "src/a/b.py", "src/a/b/c.py"])
def test_recursive_boundary_matches_all_nested_source_paths(path):
    assert matches_boundary(path, "src/**")


def test_boundary_does_not_right_match_unrelated_prefix():
    assert not matches_boundary("src/auth/login.py", "auth/**")


def test_malformed_policy_fails_closed(tmp_path):
    path = tmp_path / "risk-boundaries.yaml"
    path.write_text("boundaries: {q2: nope}")
    with pytest.raises(RiskBoundaryPolicyError):
        load_boundaries(path)
