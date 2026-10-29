"""Capture fresh child reports; unsupported or incomplete execution fails closed."""
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path

from .execution_proof import FIELDS, runs

LIMIT = 16 * 1024 * 1024
_CLEANUP_SECONDS = 1.0


def _stop_command(process):
    """Bounded cleanup of our own group, not a sandbox for escaped descendants."""
    def send(sig):
        with suppress(ProcessLookupError):
            if os.name == "posix":
                os.killpg(process.pid, sig)
            else:
                process.terminate()

    try:
        send(signal.SIGTERM)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=_CLEANUP_SECONDS)
    finally:
        # Shell exit does not imply its descendants exited or honored TERM.
        if os.name == "posix":
            send(signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=_CLEANUP_SECONDS)


def run_command(command, *, timeout, env=None):
    """Run trusted shell text; preserve primary failure after bounded cleanup."""
    process = subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, start_new_session=os.name == "posix",
    )
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            with suppress(OSError, subprocess.TimeoutExpired):
                _stop_command(process)
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        for stream in (process.stdout, process.stderr):
            with suppress(OSError):
                stream.close()


def _node(node, root, repository):
    if not isinstance(node, str):
        raise TypeError("invalid node")
    file, separator, suffix = node.partition("::")
    relative = (root / file).resolve().relative_to(repository).as_posix()
    return relative + (separator + suffix if separator else "")


def supported_command(command, depth=0):
    """Finite transparent profile; arbitrary trusted shell still runs as measurement."""
    if depth > 8 or any(value in command for value in ("$", "`", "\n", "\r")):
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
    except ValueError:
        return False
    # Consume only finite transparent prefixes, in their actual composition order.
    while words:
        if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*=.*", words[0]) or Path(words[0]).name == "env":
            words = words[1:]
        elif len(words) >= 3 and words[0] == "cd" and words[2] == "&&":
            words = words[3:]
        else:
            break
    if words and Path(words[0]).name in {"sh", "bash", "zsh"}:
        return (len(words) == 3 and words[1] in {"-c", "-lc"}
                and supported_command(words[2], depth + 1))
    if not words or any(word and all(char in ";&|()<>" for char in word) for word in words):
        return False
    if any(arg == "-d" or arg.startswith(("-n", "--numprocesses", "--dist", "--tx"))
           for arg in words[1:]):
        return False
    executable = Path(words[0]).name
    if executable in {"pytest", "py.test"}:
        return True
    if not re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)*)?", executable):
        return False
    args = words[1:]
    while args and args[0] in {"-B", "-u"}:
        args = args[1:]
    return len(args) >= 2 and args[:2] == ["-m", "pytest"]


def run(command, timeout, repository):
    repository = Path(repository).resolve()
    with tempfile.TemporaryDirectory(prefix="harness-pytest-report-") as temporary:
        nonce = uuid.uuid4().hex
        loader = Path(temporary) / "loader"
        reports = Path(temporary) / "reports"
        loader.mkdir(mode=0o700)
        reports.mkdir(mode=0o700)
        module = "_harness_pytest_" + nonce
        descriptor = os.open(loader / (module + ".py"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(Path(__file__).with_name("pytest_execution.py").read_bytes())
        environment = dict(os.environ)
        environment.pop("HARNESS_PYTEST_ACTIVE", None)  # A nested collector owns a fresh proof.
        previous = environment.get("HARNESS_PYTEST_PLUGIN_MODULE")
        plugins = [value for value in environment.get("PYTEST_PLUGINS", "").split(",") if value and value != previous]
        plugins.append(module)
        environment.update(PYTEST_PLUGINS=",".join(plugins),
                           HARNESS_PYTEST_PLUGIN_MODULE=module,
                           HARNESS_PYTEST_REPORT_DIR=str(reports),
                           HARNESS_PYTEST_REPORT_NONCE=nonce)
        # Add only a private, uniquely named reporter, never the Harness source
        # tree: installed-package tests must still import their actual subject.
        environment["PYTHONPATH"] = os.pathsep.join([str(loader), environment.get("PYTHONPATH", "")])
        result = run_command(command, timeout=timeout, env=environment)
        if not supported_command(command):
            return result, None
        observations = []
        try:
            for path in sorted(reports.iterdir()):
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
                        raise ValueError("invalid report file")
                    raw = stream.read(LIMIT + 1)
                    if len(raw) > LIMIT:
                        raise ValueError("oversized report")
                document = json.loads(raw)
                if not isinstance(document, dict) or set(document) != FIELDS | {"nonce", "root"} or document["nonce"] != nonce:
                    raise ValueError("invalid report")
                report_root = Path(document["root"])
                if not report_root.is_absolute():
                    raise ValueError("invalid report root")
                observed = {key: document[key] for key in FIELDS}
                for key in ("collected", "passed", "failed", "skipped", "assertion_failures"):
                    if not isinstance(observed[key], list):
                        raise TypeError("invalid report nodes")
                    observed[key] = sorted({_node(node, report_root, repository) for node in observed[key]})
                observations.append(observed)
            proof = {"schema": "pytest-execution/v1", "runs": observations}
            if runs({"test_execution": proof}) is None:
                raise ValueError("missing or invalid execution")
        except (OSError, ValueError, TypeError, KeyError):
            return result, None
        return result, proof
