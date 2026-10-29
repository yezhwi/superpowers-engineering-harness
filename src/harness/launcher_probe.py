"""One explicitly requested, unsandboxed local execution with bounded I/O."""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from pathlib import Path

DEADLINE_SECONDS = 10.0
TERM_GRACE_SECONDS = 1.0
CLEANUP_SECONDS = 1.0
STREAM_LIMIT = 65536


def _posix() -> bool:
    return os.name == 'posix'


def _termination_reason(*, timed_out: bool, output_limit: bool) -> str | None:
    if output_limit:
        return 'OUTPUT_LIMIT'
    if timed_out:
        return 'TIMED_OUT'
    return None


def _stop_group(process: subprocess.Popen) -> bool:
    """Best effort for our new group, never a process-tree sandbox guarantee."""
    try:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            # Darwin may report EPERM for a group whose root just became a
            # zombie. Reap it before deciding whether a group remains.
            pass
        try:
            process.wait(timeout=TERM_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=CLEANUP_SECONDS)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def probe_launcher(launcher: Path, *, cwd: Path) -> dict:
    report = {
        'status': 'UNSUPPORTED_PLATFORM', 'primary_status': None,
        'path': str(launcher), 'cwd': str(cwd), 'environment_policy': 'INHERITED',
        'spawn_attempts': 0, 'exit_code': None, 'errno': None,
        'stdout': '', 'stderr': '', 'stdout_truncated': False, 'stderr_truncated': False,
    }
    if not _posix():
        return report
    if not launcher.is_absolute() or not cwd.is_absolute():
        raise ValueError('probe paths must be absolute')
    started = time.monotonic()
    report['spawn_attempts'] = 1
    try:
        process = subprocess.Popen(
            [str(launcher), '--help'], cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
            start_new_session=True, bufsize=0,
        )
    except OSError as exc:
        return {**report, 'status': 'SPAWN_ERROR', 'errno': exc.errno}
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    reason = None
    cleanup_ok = True
    try:
        with selectors.DefaultSelector() as selector:
            for name in buffers:
                stream = getattr(process, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            deadline = started + DEADLINE_SECONDS
            while True:
                remaining = max(0, deadline - time.monotonic())
                output_limit = False
                for key, _ in selector.select(min(0.05, remaining)):
                    name = key.data
                    try:
                        data = os.read(key.fd, min(65536, STREAM_LIMIT - len(buffers[name]) + 1))
                    except BlockingIOError:
                        continue
                    if not data:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    available = STREAM_LIMIT - len(buffers[name])
                    buffers[name].extend(data[:available])
                    if len(data) > available:
                        output_limit = True
                        report[name + '_truncated'] = True
                reason = _termination_reason(timed_out=time.monotonic() >= deadline,
                                             output_limit=output_limit)
                if reason is not None:
                    break  # latch before cleanup; cleanup output cannot change cause
                if process.poll() is not None and not selector.get_map():
                    reason = 'SUCCEEDED' if process.returncode == 0 else 'NONZERO_EXIT'
                    break
    except OSError as exc:
        reason = 'CLEANUP_ERROR'
        report['errno'] = exc.errno
    except Exception:  # noqa: BLE001 - contain monitor faults after a real spawn
        reason = 'CLEANUP_ERROR'
    except BaseException:
        _stop_group(process)
        raise
    finally:
        if reason not in {'SUCCEEDED', 'NONZERO_EXIT', None}:
            cleanup_ok = _stop_group(process)
        for name in buffers:
            try:
                getattr(process, name).close()
            except OSError:
                cleanup_ok = False
        report['exit_code'] = process.poll()
        for name, content in buffers.items():
            report[name] = content.decode('utf-8', errors='replace')
    report['primary_status'] = reason
    report['status'] = reason if cleanup_ok else 'CLEANUP_ERROR'
    return report
