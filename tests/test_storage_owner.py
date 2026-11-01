"""Directory and ordinary participants use the same process-shared owner."""
import json
import os
import select
import subprocess
import sys

from storage_factory import ROOT, repository
from storage_journal_factory import OP, activation_plan


def test_owner_blocks_ordinary_reader_until_directory_descriptor_visible(tmp_path):
    from harness.storage import recover_operation

    repo = repository(tmp_path)
    value = activation_plan(repo)
    script = '''
import json, sys
from pathlib import Path
from harness.telemetry_lock import telemetry_lock
from harness.storage.journal import prepare_activation
from storage_journal_factory import authority
value=json.loads(sys.argv[1])
with telemetry_lock(Path.cwd()/'.harness'):
    prepare_activation(Path.cwd()/'.harness',value,authority(value))
    print('HELD',flush=True)
    sys.stdin.readline()
'''
    env = {**os.environ, 'PYTHONPATH': f'{ROOT}/src:{ROOT}/tests'}
    holder = subprocess.Popen([sys.executable, '-B', '-c', script, json.dumps(value)],
                              cwd=repo, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
    reader = None
    try:
        assert select.select([holder.stdout], [], [], 15)[0], 'holder did not acquire owner'
        assert holder.stdout.readline().strip() == 'HELD'
        # Signal when reader has reached the actual flock, not before import/setup.
        reader_script = '''
import fcntl
from pathlib import Path
from harness.transaction_recovery import publication_admission
original=fcntl.flock
def observed(fd, mode):
    if mode == fcntl.LOCK_EX:
        print('WAITING', flush=True)
    return original(fd,mode)
fcntl.flock=observed
try:
    with publication_admission(Path.cwd()/'.harness'):
        print('WRONG_ADMISSION',flush=True)
except OSError as error:
    print(str(error),flush=True)
'''
        reader = subprocess.Popen([sys.executable, '-B', '-c', reader_script], cwd=repo,
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert select.select([reader.stdout], [], [], 15)[0], 'reader did not reach owner'
        assert reader.stdout.readline().strip() == 'WAITING'
        assert not select.select([reader.stdout], [], [], 0.15)[0]
        holder.communicate('\n', timeout=15)
        output, error = reader.communicate(timeout=15)
        assert reader.returncode == 0, error
        assert 'WRONG_ADMISSION' not in output
        assert 'TRANSACTION_RECOVERY_REQUIRED' in output
        assert recover_operation(repo, OP)['status'] == 'ABORTED'
    finally:
        for process in (reader, holder):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


def test_legacy_custom_root_shares_workspace_owner_before_activation(tmp_path):
    from harness.telemetry_lock import telemetry_lock

    repo = repository(tmp_path)
    nested = repo / 'nested/.harness'
    nested.mkdir(parents=True)
    process = None
    script = '''
from pathlib import Path
from harness.telemetry_lock import telemetry_lock
print('WAITING',flush=True)
with telemetry_lock(Path.cwd()/'nested/.harness'):
    print('ENTERED',flush=True)
'''
    try:
        with telemetry_lock(repo / '.harness'):
            process = subprocess.Popen([sys.executable, '-B', '-c', script], cwd=repo,
                                       env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert select.select([process.stdout], [], [], 15)[0]
            assert process.stdout.readline().strip() == 'WAITING'
            assert not select.select([process.stdout], [], [], 0.2)[0], 'custom root acquired a second owner'
        output, error = process.communicate(timeout=15)
        assert process.returncode == 0, error
        assert output.strip() == 'ENTERED'
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
