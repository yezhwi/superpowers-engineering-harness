"""One-command Pi installer contracts."""

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import zipfile
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
if [ "${PI_TEST_PAUSE:-}" != "" ] && [ "$1" = list ]; then
  touch "$PI_TEST_PAUSE.entered"
  while [ ! -e "$PI_TEST_PAUSE.release" ]; do sleep 0.05; done
fi
if [ "${PI_TEST_PI_FAIL:-}" = "$1" ]; then exit 42; fi
case "$1" in
  list) cat "$PI_TEST_PI_LIST" ;;
  install)
    if [ "${PI_TEST_PI_NOOP:-no}" != yes ]; then
      awk -v source="$2" '{ print } /^User packages:/ { print "  " source }' \
        "$PI_TEST_PI_LIST" > "$PI_TEST_PI_LIST.next"
      mv "$PI_TEST_PI_LIST.next" "$PI_TEST_PI_LIST"
    fi ;;
  remove)
    [ "${PI_TEST_REMOVE_NOOP:-no}" = yes ] && exit 0
    awk -v source="$2" '
      /^User packages:/ { in_user = 1; print; next }
      /^[^[:space:]]/ { in_user = 0 }
      !(in_user && $1 == source) { print }
    ' "$PI_TEST_PI_LIST" > "$PI_TEST_PI_LIST.next"
    mv "$PI_TEST_PI_LIST.next" "$PI_TEST_PI_LIST" ;;
esac
""",
    )
    _executable(
        bin_dir / "python3",
        """#!/bin/sh
printf 'python3 %s\\n' "$*" >> "$PI_TEST_LOG"
if [ "$1" = -c ]; then
  case "$2" in
    *json.load*) printf '%s\\n' "${PI_TEST_LATEST:-9.9.9}"; exit 0 ;;
    *sys.version_info*) exit 0 ;;
  esac
  exec "$PI_TEST_REAL_PYTHON" "$@"
fi
if [ "$1" = -m ] && [ "$2" = venv ]; then
  target="$3"
  mkdir -p "$target/bin"
  cat > "$target/bin/python" <<'EOF'
#!/bin/sh
printf 'venv-python %s\\n' "$*" >> "$PI_TEST_LOG"
if [ "$1" = -c ]; then
  case "$2" in
    *schema_versions*) printf 'schema-resources-ok\\n' ;;
    *) printf '%s\\n' "$PI_TEST_TARGET" ;;
  esac
fi
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
        "PI_TEST_REAL_PYTHON": sys.executable,
        "HARNESS_INSTALL_ROOT": str(install_root),
        "HARNESS_BIN_DIR": str(home / ".local" / "bin"),
    }
    return home, install_root, pi_list, log, env


def _run(env, *args):
    return subprocess.run(
        [INSTALLER, *args], env=env, text=True, capture_output=True, check=False, timeout=30
    )


def _write_installed_cli(install_root: Path, version: str) -> None:
    python = install_root / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    _executable(python, f"""#!/bin/sh
if [ "$1" = -c ]; then
  case "$2" in
    *schema_versions*) printf 'schema-resources-ok\\n'; exit 0 ;;
  esac
fi
printf '%s\\n' '{version}'
""")
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
    assert launcher.resolve().is_relative_to(install_root / "versions")
    assert _public_help(home).returncode == 0


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


def _offline_console_wheel(directory: Path, version: str) -> Path:
    """Fixture distribution, not installed-Harness packaging acceptance."""
    name = "superpowers_engineering_harness"
    info = f"{name}-{version}.dist-info"
    wheel = directory / f"{name}-{version}-py3-none-any.whl"
    files = {
        "installer_smoke.py": (
            "import json, sys\n"
            "from importlib.metadata import version\n"
            "def main():\n"
            "    print(json.dumps({'version': version('superpowers-engineering-harness'), "
            "'prefix': sys.prefix}))\n"
        ),
        "harness/__init__.py": "",
        "harness/schema_resources.py": (
            "def schema_versions():\n"
            "    return {'task.schema.json': 'sha256:' + ('ab' * 32)}\n"
        ),
        f"{info}/METADATA": (
            "Metadata-Version: 2.1\nName: superpowers-engineering-harness\n"
            f"Version: {version}\n"
        ),
        f"{info}/WHEEL": "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{info}/entry_points.txt": "[console_scripts]\nharness = installer_smoke:main\n",
    }
    files[f"{info}/RECORD"] = "".join(f"{path},,\n" for path in files) + f"{info}/RECORD,,\n"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return wheel


@pytest.fixture
def real_pi_environment(pi_environment, tmp_path):
    """Real venv and pip-generated entry point; only remote acquisition is faked."""
    *_, env = pi_environment
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    for version in ("9.9.9", "0.2.10"):
        _offline_console_wheel(wheels, version)
    env["PI_TEST_WHEELS"] = str(wheels)
    env.pop("PYTHONPATH", None)
    _executable(
        tmp_path / "bin" / "python3",
        f"#!{sys.executable}\n" + textwrap.dedent('''\
            import os, pathlib, subprocess, sys
            with open(os.environ['PI_TEST_LOG'], 'a') as log:
                log.write('python3 ' + ' '.join(sys.argv[1:]) + '\\n')
            if sys.argv[1:3] != ['-m', 'venv']:
                os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
            target = pathlib.Path(sys.argv[3])
            subprocess.run([sys.executable, '-m', 'venv', str(target)], check=True)
            python = target / 'bin/python'
            version = os.environ['PI_TEST_TARGET']
            wheel = pathlib.Path(os.environ['PI_TEST_WHEELS']) / (
                f'superpowers_engineering_harness-{version}-py3-none-any.whl')
            subprocess.run([str(python), '-m', 'pip', 'install', '--no-index',
                            '--no-deps', str(wheel)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Keep interpreter and generated entry point untouched. Only replace
            # pip's module entry after the genuine offline wheel installation.
            pip_main = subprocess.check_output([str(python), '-c',
                'from pathlib import Path; import pip; '
                'print(Path(pip.__file__).with_name("__main__.py"))'], text=True).strip()
            pathlib.Path(pip_main).write_text('raise SystemExit(0)\\n')
            subprocess.run([str(target / 'bin/harness'), '--help'], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        '''),
    )
    # macOS kernel shebang limits are shorter than pytest's nested temp paths.
    # This fixture must be runnable BEFORE activation to isolate relocation.
    with tempfile.TemporaryDirectory(prefix="pi-", dir="/tmp") as short:
        home = Path(short).resolve() / "home"
        home.mkdir()
        root = home / ".local/share/superpowers-engineering-harness"
        env.update(HOME=str(home), HARNESS_INSTALL_ROOT=str(root),
                   HARNESS_BIN_DIR=str(home / ".local/bin"))
        yield home, root, pi_environment[2], pi_environment[3], env


def _public_help(home: Path):
    # Shell invocation turns missing shebang interpreters into an assertable
    # command failure, rather than a checker-side FileNotFoundError.
    return subprocess.run(
        ["bash", "-c", '"$1" --help', "check", str(home / ".local/bin/harness")],
        capture_output=True, text=True, check=False,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        cwd=home,
    )


def test_real_console_script_survives_installation(real_pi_environment):
    home, root, _, _, env = real_pi_environment
    result = _run(env)
    assert result.returncode == 0, result.stderr
    launched = _public_help(home)
    assert launched.returncode == 0, launched.stderr
    document = json.loads(launched.stdout)
    assert document["version"] == "9.9.9"
    assert Path(document["prefix"]).is_relative_to(root / "versions")


def test_real_upgrade_retains_previous_environment(real_pi_environment):
    home, _, _, _, env = real_pi_environment
    first = _run(env)
    assert first.returncode == 0, first.stderr
    old_launcher = (home / ".local/bin/harness").resolve()
    old_bytes = old_launcher.read_bytes()
    env["PI_TEST_TARGET"] = "0.2.10"
    upgraded = _run(env, "0.2.10")
    assert upgraded.returncode == 0, upgraded.stderr
    assert old_launcher.is_file(), "upgrade removed previous environment"
    assert old_launcher.read_bytes() == old_bytes
    launched = _public_help(home)
    assert launched.returncode == 0, launched.stderr
    assert json.loads(launched.stdout)["version"] == "0.2.10"
    assert old_launcher != (home / ".local/bin/harness").resolve()


def test_real_same_version_reuses_healthy_entry(real_pi_environment):
    home, _, _, log, env = real_pi_environment
    assert _run(env).returncode == 0
    launcher = (home / ".local/bin/harness").resolve()
    before = log.read_text().count("python3 -m venv")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _public_help(home).returncode == 0
    assert (home / ".local/bin/harness").resolve() == launcher
    assert log.read_text().count("python3 -m venv") == before


def _old_public_entry(environment):
    home, root, _, _, _ = environment
    _write_installed_cli(root, "0.2.9")
    launcher = home / ".local/bin/harness"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(root / "venv/bin/harness")
    return launcher, launcher.readlink(), (root / "venv/bin/harness").read_bytes()


def _assert_old_entry(environment, previous, result):
    launcher, target, data = previous
    assert result.returncode != 0
    assert "Installed Engineering Harness" not in result.stdout
    assert launcher.readlink() == target
    assert launcher.read_bytes() == data
    assert _public_help(environment[0]).returncode == 0


@pytest.mark.parametrize("fault", ["pip", "version", "missing", "help", "schema"])
def test_candidate_failure_keeps_previous_cli(pi_environment, tmp_path, fault):
    previous = _old_public_entry(pi_environment)
    shim = tmp_path / "bin/python3"
    content = shim.read_text()
    if fault == "pip":
        content = content.replace(
            'if [ "$1" = -c ]; then\n  case "$2" in',
            'if [ "$1" = -m ]; then exit 42; fi\nif [ "$1" = -c ]; then\n  case "$2" in',
        )
    elif fault == "version":
        content = content.replace('printf \'%s\\n\' "$PI_TEST_TARGET"', "printf '0.0.0\\n'")
    elif fault == "schema":
        content = content.replace("schema-resources-ok", "schema-resources-bad")
    elif fault == "missing":
        content = content.replace('chmod +x "$target/bin/python" "$target/bin/harness"',
                                  'chmod +x "$target/bin/python"; rm "$target/bin/harness"')
    else:
        content = content.replace('#!/bin/sh\nexit 0\nEOF', '#!/bin/sh\nexit 42\nEOF')
    assert content != shim.read_text()
    shim.write_text(content)
    result = _run(pi_environment[-1])
    _assert_old_entry(pi_environment, previous, result)
    assert "pi install" not in pi_environment[3].read_text()


@pytest.mark.parametrize("fault", ["install", "remove", "noop", "remove_noop"])
def test_skills_failure_is_reported_without_switching_cli(pi_environment, fault):
    previous = _old_public_entry(pi_environment)
    _, _, listing, _, env = pi_environment
    listing.write_text("User packages:\n  npm:superpowers-engineering-harness@0.2.9\n")
    if fault == "noop":
        env["PI_TEST_PI_NOOP"] = "yes"
    elif fault == "remove_noop":
        env["PI_TEST_REMOVE_NOOP"] = "yes"
    else:
        env["PI_TEST_PI_FAIL"] = fault
    result = _run(env)
    _assert_old_entry(pi_environment, previous, result)
    assert "CLI/skills" in result.stderr


def _activation_fault(tmp_path, fault):
    # Fault at actual stdlib activation boundary, without a production test hook.
    wrapper = tmp_path / "fault-python"
    _executable(wrapper, f"#!{sys.executable}\n" + textwrap.dedent('''\
        import os, pathlib, signal, subprocess, sys
        if sys.argv[1] != '-c' or 'os.replace' not in sys.argv[2]:
            delegate = str(pathlib.Path(__file__).parent / 'bin/python3')
            os.execv(delegate, [delegate, *sys.argv[1:]])
        original_replace = os.replace
        original_run = subprocess.run
        original_lstat = pathlib.Path.lstat
        inspecting = False
        def lstat(path, *args, **kwargs):
            if inspecting and path.name == 'harness':
                raise OSError('injected recovery inspection failure')
            return original_lstat(path, *args, **kwargs)
        pathlib.Path.lstat = lstat
        fault = os.environ['PI_TEST_ACTIVATION_FAULT']
        def replace(source, target):
            if fault == 'rollback' and pathlib.Path(source).name == 'previous':
                raise OSError('injected rollback failure')
            if fault == 'replace' and pathlib.Path(target).name == 'harness':
                raise OSError('injected activation failure')
            return original_replace(source, target)
        def run(*args, **kwargs):
            global inspecting
            if fault == 'external':
                launcher = pathlib.Path(args[0][0])
                launcher.unlink()
                launcher.write_text('unmanaged entry')
                raise subprocess.CalledProcessError(42, args[0])
            if fault == 'inspect':
                inspecting = True
                raise subprocess.CalledProcessError(42, args[0])
            if fault == 'signal':
                os.kill(os.getpid(), signal.SIGTERM)
            if fault in {'final', 'rollback'}:
                raise subprocess.CalledProcessError(42, args[0])
            return original_run(*args, **kwargs)
        os.replace = replace
        subprocess.run = run
        sys.argv = ['-c', *sys.argv[3:]]
        exec(compile(os.environ['PI_TEST_ACTIVATION_CODE'], '<installer>', 'exec'))
    '''))
    # Wrapper captures code through argv itself, not shared mutable environment.
    content = wrapper.read_text().replace(
        "sys.argv = ['-c', *sys.argv[3:]]", "code = sys.argv[2]\nsys.argv = ['-c', *sys.argv[3:]]").replace(
        "os.environ['PI_TEST_ACTIVATION_CODE']", "code")
    wrapper.write_text(content)
    return wrapper


@pytest.mark.parametrize("fault", ["replace", "final", "signal"])
def test_activation_failure_restores_previous_entry(pi_environment, tmp_path, fault):
    previous = _old_public_entry(pi_environment)
    env = pi_environment[-1]
    env.update(PYTHON_BIN=str(_activation_fault(tmp_path, fault)),
               PI_TEST_ACTIVATION_FAULT=fault)
    result = _run(env)
    _assert_old_entry(pi_environment, previous, result)
    assert "CLI/skills" in result.stderr
    env.pop("PYTHON_BIN")
    repaired = _run(env)
    assert repaired.returncode == 0, repaired.stderr
    assert _public_help(pi_environment[0]).returncode == 0


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_non_symlink_launcher_is_not_replaced(pi_environment, kind):
    home, _, _, log, env = pi_environment
    launcher = home / ".local/bin/harness"
    launcher.parent.mkdir(parents=True)
    if kind == "file":
        launcher.write_text("user executable")
    else:
        launcher.mkdir()
    result = _run(env)
    assert result.returncode != 0
    assert not launcher.is_symlink()
    assert "pi install" not in log.read_text()


def test_dangling_public_entry_can_be_repaired(pi_environment):
    home, _, _, _, env = pi_environment
    launcher = home / ".local/bin/harness"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to("missing/bin/harness")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _public_help(home).returncode == 0


def test_relative_paths_with_spaces_activate_absolute_entry(pi_environment, tmp_path):
    home, _, _, _, env = pi_environment
    env.update(HARNESS_INSTALL_ROOT="install root", HARNESS_BIN_DIR="public bin")
    result = subprocess.run([str(INSTALLER), "9.9.9"], env=env, cwd=tmp_path,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    launcher = tmp_path / "public bin/harness"
    assert launcher.readlink().is_absolute()
    assert subprocess.run([str(launcher), "--help"], check=False).returncode == 0
    assert not (home / ".local/bin/harness").exists()


def test_existing_lock_fails_without_mutations(pi_environment):
    _, root, _, log, env = pi_environment
    lock = root / ".install.lock"
    lock.mkdir(parents=True)
    (lock / "owner").write_text("unresolved previous installer")
    result = _run(env)
    assert result.returncode != 0
    assert "lock" in result.stderr.lower()
    assert (lock / "owner").read_text() == "unresolved previous installer"
    assert "pi install" not in log.read_text()
    assert "python3 -m venv" not in log.read_text()


def test_concurrent_installer_cannot_remove_owners_lock(pi_environment, tmp_path):
    home, root, _, _, env = pi_environment
    pause = tmp_path / "pause"
    env["PI_TEST_PAUSE"] = str(pause)
    with subprocess.Popen([str(INSTALLER)], env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as owner:
        try:
            deadline = time.monotonic() + 15
            while not Path(str(pause) + ".entered").exists():
                assert owner.poll() is None, "owner exited before contention boundary"
                assert time.monotonic() < deadline
                time.sleep(0.05)
            loser = _run(env)
            assert loser.returncode != 0
            assert (root / ".install.lock").is_dir()
        finally:
            Path(str(pause) + ".release").touch()
            stdout, stderr = owner.communicate(timeout=15)
        assert owner.returncode == 0, stdout + stderr
    assert not (root / ".install.lock").exists()
    assert _public_help(home).returncode == 0


def test_interruption_before_activation_allows_rerun(pi_environment, tmp_path):
    previous = _old_public_entry(pi_environment)
    env = pi_environment[-1]
    pause = tmp_path / "pause"
    env["PI_TEST_PAUSE"] = str(pause)
    with subprocess.Popen([str(INSTALLER)], env=env, text=True,
                          start_new_session=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as process:
        deadline = time.monotonic() + 15
        while not Path(str(pause) + ".entered").exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.05)
        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=15)
    result = subprocess.CompletedProcess([], process.returncode, stdout, stderr)
    _assert_old_entry(pi_environment, previous, result)
    env.pop("PI_TEST_PAUSE")
    rerun = _run(env)
    assert rerun.returncode == 0, rerun.stderr


@pytest.mark.parametrize("fault", ["rollback", "inspect"])
def test_failed_rollback_retains_recovery_link(pi_environment, tmp_path, fault):
    previous = _old_public_entry(pi_environment)
    home, _, _, _, env = pi_environment
    env.update(PYTHON_BIN=str(_activation_fault(tmp_path, fault)),
               PI_TEST_ACTIVATION_FAULT=fault)
    result = _run(env)
    assert result.returncode != 0
    backups = list((home / ".local/bin").glob(".harness-entry-*/previous"))
    assert len(backups) == 1, result.stderr
    assert backups[0].readlink() == previous[1]
    assert str(backups[0].parent) in result.stderr


def test_external_entry_is_not_overwritten_by_rollback(pi_environment, tmp_path):
    previous = _old_public_entry(pi_environment)
    home, _, _, _, env = pi_environment
    env.update(PYTHON_BIN=str(_activation_fault(tmp_path, "external")),
               PI_TEST_ACTIVATION_FAULT="external")
    result = _run(env)
    assert result.returncode != 0
    assert previous[0].read_text() == "unmanaged entry"
    backups = list((home / ".local/bin").glob(".harness-entry-*/previous"))
    assert len(backups) == 1
    assert backups[0].readlink() == previous[1]


def test_failed_first_activation_leaves_no_public_entry(pi_environment, tmp_path):
    home, _, _, _, env = pi_environment
    env.update(PYTHON_BIN=str(_activation_fault(tmp_path, "final")),
               PI_TEST_ACTIVATION_FAULT="final")
    result = _run(env)
    assert result.returncode != 0
    assert not os.path.lexists(home / ".local/bin/harness")


def test_missing_superpowers_after_noop_is_not_success(pi_environment):
    _, _, listing, _, env = pi_environment
    listing.write_text("User packages:\n  npm:superpowers-engineering-harness@9.9.9\n")
    env["PI_TEST_PI_NOOP"] = "yes"
    result = _run(env)
    assert result.returncode != 0
    assert "Installed Engineering Harness" not in result.stdout


def test_abrupt_death_keeps_lock_and_blocks_implicit_recovery(pi_environment, tmp_path):
    previous = _old_public_entry(pi_environment)
    _, root, _, log, env = pi_environment
    pause = tmp_path / "pause"
    env["PI_TEST_PAUSE"] = str(pause)
    with subprocess.Popen([str(INSTALLER)], env=env, text=True,
                          start_new_session=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as process:
        deadline = time.monotonic() + 15
        while not Path(str(pause) + ".entered").exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.05)
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate(timeout=15)
    _assert_old_entry(pi_environment, previous,
                      subprocess.CompletedProcess([], process.returncode, stdout, stderr))
    assert (root / ".install.lock").is_dir()
    assert list((root / "versions").iterdir())
    env.pop("PI_TEST_PAUSE")
    before = log.read_text().count("pi install")
    rerun = _run(env)
    assert rerun.returncode != 0
    assert "lock" in rerun.stderr.lower()
    assert log.read_text().count("pi install") == before


def test_real_console_script_with_space_in_install_path(real_pi_environment):
    home, root, _, _, env = real_pi_environment
    env["HARNESS_INSTALL_ROOT"] = str(root.parent / "install root")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    launched = _public_help(home)
    assert launched.returncode == 0, launched.stderr
    assert json.loads(launched.stdout)["version"] == "9.9.9"


def test_same_version_broken_shebang_is_repaired(pi_environment):
    home, root, _, log, env = pi_environment
    _write_installed_cli(root, "9.9.9")
    _executable(root / "venv/bin/harness", "#!/missing/old-venv/bin/python\n")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "python3 -m venv" in log.read_text()
    assert _public_help(home).returncode == 0
    assert (root / "venv/bin/harness").read_text() == "#!/missing/old-venv/bin/python\n"
