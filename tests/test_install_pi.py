"""One-command Pi installer contracts."""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-pi.sh"


def _executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def pi_environment(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    pi_list = tmp_path / "pi-list.txt"
    pi_list.write_text("User packages:\n")

    _executable(
        bin_dir / "curl",
        """#!/bin/sh
printf 'curl %s\\n' "$*" >> "$PI_TEST_LOG"
case "$*" in
  *superpowers-engineering-harness/latest*)
    printf '{"version":"%s"}' "${PI_TEST_LATEST:-9.9.9}" ;;
  *superpowers-engineering-harness/*)
    [ "${PI_TEST_NPM_EXISTS:-yes}" = yes ] || exit 22
    printf '{"version":"%s"}' "${PI_TEST_TARGET:-9.9.9}" ;;
esac
""",
    )
    _executable(
        bin_dir / "git",
        """#!/bin/sh
printf 'git %s\\n' "$*" >> "$PI_TEST_LOG"
[ "${PI_TEST_GIT_EXISTS:-yes}" = yes ]
""",
    )
    _executable(
        bin_dir / "pi",
        """#!/bin/sh
printf 'pi %s\\n' "$*" >> "$PI_TEST_LOG"
if [ "$1" = list ]; then cat "$PI_TEST_PI_LIST"; fi
""",
    )
    _executable(
        bin_dir / "python3",
        """#!/bin/sh
printf 'python3 %s\\n' "$*" >> "$PI_TEST_LOG"
if [ "$1" = -c ]; then
  case "$2" in
    *json.load*) printf '%s\\n' "${PI_TEST_LATEST:-9.9.9}" ;;
    *sys.version_info*) exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = -m ] && [ "$2" = venv ]; then
  target="$3"
  mkdir -p "$target/bin"
  cat > "$target/bin/python" <<'EOF'
#!/bin/sh
printf 'venv-python %s\\n' "$*" >> "$PI_TEST_LOG"
if [ "$1" = -c ]; then printf '%s\\n' "$PI_TEST_TARGET"; fi
EOF
  cat > "$target/bin/harness" <<'EOF'
#!/bin/sh
exit 0
EOF
  chmod +x "$target/bin/python" "$target/bin/harness"
fi
""",
    )

    install_root = home / ".local" / "share" / "superpowers-engineering-harness"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PI_TEST_LOG": str(log),
        "PI_TEST_PI_LIST": str(pi_list),
        "PI_TEST_TARGET": "9.9.9",
        "HARNESS_INSTALL_ROOT": str(install_root),
        "HARNESS_BIN_DIR": str(home / ".local" / "bin"),
    }
    return home, install_root, pi_list, log, env


def _run(env, *args):
    return subprocess.run(
        [INSTALLER, *args], env=env, text=True, capture_output=True, check=False
    )


def _write_installed_cli(install_root: Path, version: str) -> None:
    python = install_root / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    _executable(python, f"#!/bin/sh\nprintf '%s\\n' '{version}'\n")
    _executable(python.parent / "harness", "#!/bin/sh\nexit 0\n")


def test_default_latest_installs_missing_superpowers_pinned_skills_and_cli(pi_environment):
    home, install_root, _, log, env = pi_environment

    result = _run(env)

    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert "superpowers-engineering-harness/latest" in calls
    assert "git ls-remote --exit-code --tags" in calls
    assert "refs/tags/v9.9.9" in calls
    assert "pi install git:github.com/obra/superpowers" in calls
    assert "pi install npm:superpowers-engineering-harness@9.9.9" in calls
    assert (
        "superpowers-engineering-harness.git@v9.9.9" in calls
    )
    launcher = home / ".local" / "bin" / "harness"
    assert launcher.is_symlink()
    assert launcher.resolve() == install_root / "venv" / "bin" / "harness"


def test_installer_runs_when_script_arrives_on_standard_input(pi_environment):
    _, _, _, _, env = pi_environment

    result = subprocess.run(
        ["bash"],
        input=INSTALLER.read_text(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_explicit_version_accepts_optional_v_without_latest_lookup(pi_environment):
    _, _, _, log, env = pi_environment
    env["PI_TEST_TARGET"] = "0.2.10"

    result = _run(env, "v0.2.10")

    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert "/latest" not in calls
    assert "superpowers-engineering-harness/0.2.10" in calls
    assert "refs/tags/v0.2.10" in calls
    assert "npm:superpowers-engineering-harness@0.2.10" in calls


def test_exact_existing_packages_and_cli_are_idempotent(pi_environment):
    _, install_root, pi_list, log, env = pi_environment
    pi_list.write_text(
        "User packages:\n"
        "  git:github.com/obra/superpowers\n"
        "    /tmp/superpowers\n"
        "  npm:superpowers-engineering-harness@9.9.9\n"
        "    /tmp/harness\n"
    )
    _write_installed_cli(install_root, "9.9.9")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    mutations = [
        line
        for line in log.read_text().splitlines()
        if line.startswith(("pi install", "pi remove", "python3 -m venv"))
    ]
    assert mutations == []


def test_matching_metadata_without_harness_executable_repairs_cli(pi_environment):
    home, install_root, pi_list, log, env = pi_environment
    pi_list.write_text(
        "User packages:\n"
        "  git:github.com/obra/superpowers\n"
        "    /tmp/superpowers\n"
        "  npm:superpowers-engineering-harness@9.9.9\n"
        "    /tmp/harness\n"
    )
    python = install_root / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    _executable(python, "#!/bin/sh\nprintf '%s\\n' '9.9.9'\n")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "python3 -m venv" in log.read_text()
    assert (home / ".local" / "bin" / "harness").resolve().is_file()


def test_project_local_packages_do_not_replace_missing_user_packages(pi_environment):
    _, _, pi_list, log, env = pi_environment
    pi_list.write_text(
        "User packages:\n"
        "  npm:unrelated-package\n"
        "    /tmp/unrelated\n"
        "Project packages:\n"
        "  git:github.com/obra/superpowers\n"
        "    /tmp/project-superpowers\n"
        "  npm:superpowers-engineering-harness@0.2.9\n"
        "    /tmp/project-harness\n"
    )
    env["PI_TEST_TARGET"] = "0.2.10"

    result = _run(env, "0.2.10")

    assert result.returncode == 0, result.stderr
    lines = log.read_text().splitlines()
    assert "pi install git:github.com/obra/superpowers" in lines
    assert "pi install npm:superpowers-engineering-harness@0.2.10" in lines
    assert "pi remove npm:superpowers-engineering-harness@0.2.9" not in lines


def test_upgrade_installs_new_harness_before_removing_old_source(pi_environment):
    _, _, pi_list, log, env = pi_environment
    pi_list.write_text(
        "User packages:\n"
        "  git:github.com/obra/superpowers@v6.4.2\n"
        "    /tmp/superpowers\n"
        "  npm:superpowers-engineering-harness@0.2.9\n"
        "    /tmp/harness\n"
        "  git:github.com/yezhwi/superpowers-engineering-harness@v0.2.9\n"
        "    /tmp/legacy-harness\n"
        "  npm:unrelated-package\n"
        "    /tmp/unrelated\n"
    )
    env["PI_TEST_TARGET"] = "0.2.10"

    result = _run(env, "0.2.10")

    assert result.returncode == 0, result.stderr
    lines = log.read_text().splitlines()
    install = lines.index("pi install npm:superpowers-engineering-harness@0.2.10")
    remove = lines.index("pi remove npm:superpowers-engineering-harness@0.2.9")
    legacy_remove = lines.index(
        "pi remove git:github.com/yezhwi/superpowers-engineering-harness@v0.2.9"
    )
    assert install < remove
    assert install < legacy_remove
    assert "pi install git:github.com/obra/superpowers" not in lines
    assert not any("unrelated-package" in line and "remove" in line for line in lines)


@pytest.mark.parametrize("version", ["", "latest", "1", "1.2", "v1.2", "1.2.3.4", "../1.2.3"])
def test_invalid_explicit_version_fails_before_external_mutation(pi_environment, version):
    _, _, _, log, env = pi_environment
    args = [version] if version else ["", "extra"]

    result = _run(env, *args)

    assert result.returncode != 0
    calls = log.read_text() if log.exists() else ""
    assert "pi install" not in calls
    assert "pi remove" not in calls
    assert "python3 -m venv" not in calls


@pytest.mark.parametrize(
    ("variable", "message"),
    [("PI_TEST_NPM_EXISTS", "npm"), ("PI_TEST_GIT_EXISTS", "Git tag")],
)
def test_missing_release_artifact_fails_before_mutation(pi_environment, variable, message):
    _, _, _, log, env = pi_environment
    env["PI_TEST_TARGET"] = "0.2.10"
    env[variable] = "no"

    result = _run(env, "0.2.10")

    assert result.returncode != 0
    assert message in result.stderr
    calls = log.read_text()
    assert "pi install" not in calls
    assert "pi remove" not in calls
    assert "python3 -m venv" not in calls


def test_installer_manifest_is_json_serializable_for_fixture_sanity(pi_environment):
    _, _, _, _, env = pi_environment
    assert json.dumps({"target": env["PI_TEST_TARGET"]})
