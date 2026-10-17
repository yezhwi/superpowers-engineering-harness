"""Anonymous, archived-reference Context benchmark. No performance pass threshold."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from functools import wraps
from pathlib import Path

import yaml

REFERENCE = 'c74ac4d4477469fdbeda80a2b470094d3134375f'
COUNTS = (0, 1, 10, 50, 100)
REPO = Path(__file__).resolve().parents[1]


def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False))


def git(root, *args):
    env = {**os.environ, 'GIT_AUTHOR_DATE': '2026-01-01T00:00:00+00:00',
           'GIT_COMMITTER_DATE': '2026-01-01T00:00:00+00:00'}
    return subprocess.run(['git', '-C', str(root), *args], env=env, capture_output=True, check=True).stdout.decode().strip()


def make_fixture(root, templates, *, seed, count):
    root.mkdir(parents=True)
    git(root, 'init', '-q')
    git(root, '-c', 'user.name=Anonymous', '-c', 'user.email=benchmark@example.invalid',
        'commit', '--allow-empty', '-qm', f'anonymous seed {seed}')
    h = root / '.harness'
    h.mkdir()
    for name in ('current-task.yaml', 'gate.yaml', 'requirements.yaml', 'invariants.yaml', 'impact.yaml', 'observability.yaml'):
        shutil.copyfile(templates / name, h / name)
    task = yaml.safe_load((h / 'current-task.yaml').read_bytes())
    task['task'].update(id='TASK-001', title='Anonymous Context fixture', description=f'seed {seed}')
    task['state'] = 'CLASSIFIED'
    task['risk'] = {'level': 'Q1', 'profile': 'FAST',
                    'dimensions': {key: 'low' if key == 'scope' else 'none' for key in
                                   ('scope', 'contract', 'data', 'authorization', 'security', 'concurrency', 'deployment')},
                    'escalation_history': [], 'user_changes': {'paths': [], 'fingerprint': sha(b'')}}
    task['scope'] = {'owned_paths': ['src/local.py'], 'protected_user_paths': []}
    task['git']['base_commit'] = git(root, 'rev-parse', 'HEAD')
    dump(h / 'current-task.yaml', task)
    dump(h / 'requirements.yaml', {'requirements': []})
    dump(h / 'invariants.yaml', {'invariants': [{'id': 'INV-001', 'statement': 'Anonymous invariant',
          'category': 'correctness', 'severity': 'minor', 'status': 'pending'}]})
    dump(h / 'decisions/index.yaml', {'decisions': []})
    for i in range(count):
        dump(h / f'findings/FND-{i+1:03}.yaml', {'id': f'FND-{i+1:03}', 'category': 'adversarial',
             'kind': 'invariant_violation', 'target': 'INV-001', 'scenario': 'Anonymous outside-scope candidate',
             'severity': 'minor', 'status': 'PROPOSED', 'location': {'file': f'src/outside-{i:03}.py'}})


def fixture_identity(root):
    files = {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in sorted((root / '.harness').rglob('*')) if p.is_file()}
    return json.dumps({'files': files, 'finding_count': len(list((root / '.harness/findings').glob('*.yaml'))),
                       'head': git(root, 'rev-parse', 'HEAD')}, sort_keys=True)


def check_output(path, repo):
    if path.resolve().is_relative_to(repo.resolve()):
        raise ValueError('benchmark report must be outside repository')


def summarize(samples):
    values = [s['wall_ms'] for s in samples if s['status'] == 'SUCCESS']
    return {'successful': len(values), 'failed': len(samples) - len(values),
            'min_ms': min(values) if values else None, 'median_ms': statistics.median(values) if values else None,
            'max_ms': max(values) if values else None}


def normalized(value):
    if isinstance(value, str):
        return value.replace(str(Path.cwd().resolve()), '<fixture>')
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items() if key not in
                {'timestamp', 'generated_at', 'context_hash', 'generated_from'}}
    return value


def semantics(document):
    facts = normalized({key: document[key] for key in ('control', 'working', 'omitted', 'references', 'policy', 'expansions')})
    # Explicit legacy-origin tightening: anonymous fixture is intentionally legacy.
    gate = facts['control']['gate']
    gate['blocked_by'] = [b for b in gate['blocked_by'] if b['code'] != 'TEST_SCOPE_AUDIT_INVALID']
    facts['control']['blockers'] = [b for b in facts['control']['blockers'] if b['code'] != 'TEST_SCOPE_AUDIT_INVALID']
    for name in ('test-scope-baseline.yaml', 'test-scope-audit.yaml', 'test-scope-seal.yaml'):
        facts['references'].pop(name, None)
    return facts


class Measurements:
    """Same lightweight invocation-local instrumentation for both isolated arms."""
    def __init__(self):
        self.counts = {}
        self.phases = {}
        self.stack = []

    def reset(self):
        self.counts.clear()
        self.phases.clear()

    def wrap(self, function, name):
        @wraps(function)
        def measured(*args, **kwargs):
            self.counts[name] = self.counts.get(name, 0) + 1
            frame = [time.perf_counter(), 0.0]
            self.stack.append(frame)
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - frame[0]
                self.stack.pop()
                self.phases[name] = self.phases.get(name, 0.0) + (elapsed - frame[1]) * 1000
                if self.stack:
                    self.stack[-1][1] += elapsed
        return measured

    def install(self):
        from harness import quality_gate, transaction
        from harness.context import (
            builder,
            escalation,
            freshness,
            integrity,
            selector,
            source,
            store,
        )
        modules = (quality_gate, transaction, builder, escalation, freshness, integrity, selector, source, store)
        functions = [(integrity.build_context, 'full_context_builds'), (quality_gate.assess_gate, 'gate_assessments'),
                     (freshness.capture, 'capture'), (integrity.validate_context, 'integrity_validate'),
                     (transaction.publish, 'publish')]
        for original, name in functions:
            wrapped = self.wrap(original, name)
            for module in modules:
                for key, value in list(vars(module).items()):
                    if value is original:
                        setattr(module, key, wrapped)
        source.FileContextSource.load = self.wrap(source.FileContextSource.load, 'source_loads')
        import jsonschema
        original_validate = jsonschema.validate
        wrapped_validate = self.wrap(original_validate, 'schema_validate')
        for module in tuple(sys.modules.values()):
            if module is not None and getattr(module, '__name__', '').startswith('harness'):
                for key, value in list(vars(module).items()):
                    if value is original_validate:
                        setattr(module, key, wrapped_validate)
        jsonschema.validate = wrapped_validate
        yaml.safe_load = self.wrap(yaml.safe_load, 'yaml_parse')


def worker(iterations, steady):
    from harness.context import integrity
    from harness.context.freshness import capture, schema_versions
    from harness.context.store import generate_context
    h = Path('.harness')
    timer = Measurements()
    timer.install()
    initial = capture(h)
    if steady:
        generate_context(h)  # Explicit warm-up, excluded from samples.
    samples = []
    for _ in range(iterations):
        timer.reset()
        started = time.perf_counter()
        try:
            doc = generate_context(h)
            generation_ms = (time.perf_counter() - started) * 1000
            counters, phases = dict(timer.counts), dict(timer.phases)
            timer.reset()
            validation_started = time.perf_counter()
            checks = integrity.validate_context(h, doc)
            validation_ms = (time.perf_counter() - validation_started) * 1000
            samples.append({'status': 'SUCCESS', 'wall_ms': (time.perf_counter()-started)*1000,
                            'generation_ms': generation_ms, 'standalone_validation_ms': validation_ms,
                            'counters': counters, 'exclusive_phases_ms': phases,
                            'unattributed_generation_ms': generation_ms - sum(phases.values()),
                            'standalone_validation_counters': dict(timer.counts), 'integrity': checks,
                            'semantic_facts': semantics(doc), 'generated_from': doc['generated_from'],
                            'expansion_count': len(doc['expansions'])})
        except Exception as exc:  # noqa: BLE001 - failed measurements must remain visible, never successful samples.
            samples.append({'status': 'FAILED', 'wall_ms': (time.perf_counter()-started)*1000,
                            'error_type': type(exc).__name__, 'error': str(exc)})
            break  # Failed fixture is never reused as a later success sample.
    return {'samples': samples, 'initial_source_identity': initial,
            'schemas': schema_versions(), 'cpu_count': os.cpu_count()}


def run_arm(package, fixture, *, repetitions, steady, timeout):
    env = {**os.environ, 'PYTHONPATH': str(package / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
    started = time.perf_counter()
    try:
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker',
                                  '--repetitions', str(repetitions), *(['--steady'] if steady else [])],
                                 cwd=fixture, env=env, capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'samples': [{'status': 'TIMEOUT', 'wall_ms': (time.perf_counter()-started)*1000}]}
    if process.returncode != 0:
        return {'samples': [{'status': 'FAILED', 'wall_ms': (time.perf_counter()-started)*1000,
                             'stderr': process.stderr, 'exit_code': process.returncode}]}
    result = json.loads(process.stdout)
    result['process_wall_ms'] = (time.perf_counter()-started)*1000
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=1038001)
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--counts', type=int, nargs='+', default=list(COUNTS))
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--steady', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.repetitions, args.steady)))
        return 0
    if args.output is None or args.repetitions < 1 or any(n < 0 for n in args.counts):
        parser.error('output and positive repetitions/nonnegative counts required')
    check_output(args.output, REPO)
    report = {'seed': args.seed, 'reference_commit': REFERENCE, 'requested_repetitions': args.repetitions,
              'environment': {'python': platform.python_version(), 'implementation': platform.python_implementation(),
                              'os': platform.platform(), 'machine': platform.machine(), 'cpu_count': os.cpu_count(),
                              'dependencies': {name: importlib.metadata.version(name) for name in ('PyYAML', 'jsonschema')}},
              'compatibility_exceptions': ['Legacy fixture adds TEST_SCOPE_AUDIT_INVALID in new arm; retained separately in generated facts.'],
              'groups': [], 'acceptance': 'No timing threshold or p95 claim; incomplete/failed runs are not success samples.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='anonymous-context-benchmark-') as temporary:
        root = Path(temporary)
        reference = root / 'reference'
        reference.mkdir()
        archive = subprocess.run(['git', '-C', str(REPO), 'archive', REFERENCE, 'src/harness'], capture_output=True, check=True).stdout
        report['reference_archive_hash'] = sha(archive)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(reference, filter='data')
        new_package = root / 'new'
        shutil.copytree(REPO / 'src/harness', new_package / 'src/harness', ignore=shutil.ignore_patterns('__pycache__'))
        report['new_source_identity'] = {p.relative_to(new_package).as_posix(): sha(p.read_bytes())
                                         for p in sorted((new_package / 'src/harness').rglob('*')) if p.is_file()}
        report['new_repository_head'] = git(REPO, 'rev-parse', 'HEAD')
        templates = reference / 'src/harness/templates'
        for count in args.counts:
            for mode in ('cold', 'steady'):
                group = {'candidate_count': count, 'mode': mode, 'arms': {}}
                for arm, package in (('reference', reference), ('new', new_package)):
                    runs = []
                    identities = []
                    for rep in range(args.repetitions if mode == 'cold' else 1):
                        fixture = root / f'fixture-{count}-{mode}-{arm}-{rep}'
                        make_fixture(fixture, templates, seed=args.seed, count=count)
                        identities.append(json.loads(fixture_identity(fixture)))
                        runs.append(run_arm(package, fixture, repetitions=1 if mode == 'cold' else args.repetitions,
                                            steady=mode == 'steady', timeout=args.timeout))
                    samples = [sample for run in runs for sample in run['samples']]
                    group['arms'][arm] = {'runs': runs, 'summary': summarize(samples), 'fixture_identities': identities}
                    report['groups'] = [*report['groups'], group] if arm == 'reference' else report['groups']
                    args.output.write_text(json.dumps(report, indent=2))
                    print(f'{count} {mode} {arm}: {group["arms"][arm]["summary"]}', flush=True)
                left = [s['semantic_facts'] for run in group['arms']['reference']['runs'] for s in run['samples'] if s['status']=='SUCCESS']
                right = [s['semantic_facts'] for run in group['arms']['new']['runs'] for s in run['samples'] if s['status']=='SUCCESS']
                group['semantic_equal'] = len(left)==len(right)==args.repetitions and all(a==b for a,b in zip(left,right,strict=True))
                args.output.write_text(json.dumps(report, indent=2))
    return 0 if all(g.get('semantic_equal') for g in report['groups']) else 2


if __name__ == '__main__':
    raise SystemExit(main())
