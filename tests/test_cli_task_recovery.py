"""CLI contract for audited stale-task recovery."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parent.parent


def run_cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def make_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert run_cli(tmp_path, "init").returncode == 0
    return tmp_path


def set_task_state(repo: Path, state: str, task_id: str = "TASK-004") -> None:
    path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["task"]["id"] = task_id
    task["state"] = state
    path.write_text(yaml.safe_dump(task, sort_keys=False))


def test_task_recover_requires_reason(tmp_path):
    repo = make_repo(tmp_path)

    result = run_cli(repo, "task", "recover", "TASK-005")

    assert result.returncode == 2
    assert "--reason" in result.stderr


def test_task_recover_rejects_invalid_id(tmp_path):
    repo = make_repo(tmp_path)
    before = (repo / ".harness/current-task.yaml").read_text()

    result = run_cli(repo, "task", "recover", "bad", "--reason", "stale")

    assert result.returncode == 2
    assert "INVALID TASK ID" in result.stderr
    assert (repo / ".harness/current-task.yaml").read_text() == before


def test_task_recover_rejects_terminal_task_without_mutation(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "DONE")
    before = (repo / ".harness/current-task.yaml").read_text()

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "stale")

    assert result.returncode == 1
    assert "requires active task" in result.stderr
    assert (repo / ".harness/current-task.yaml").read_text() == before
    assert not list((repo / ".harness/history").glob("TASK-004-*"))


def test_task_recover_archives_artifacts_and_creates_fresh_task(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    findings = repo / ".harness/findings"
    evidence = repo / ".harness/evidence"
    (findings / "FND-001.yaml").write_text("id: FND-001\n")
    (evidence / "unit.json").write_text("{}")

    result = run_cli(
        repo,
        "task",
        "recover",
        "TASK-005",
        "--title",
        "Wheel isolation",
        "--reason",
        "stale task",
    )

    assert result.returncode == 0, result.stderr
    archive = next((repo / ".harness/history").glob("TASK-004-*"))
    audit = yaml.safe_load((archive / "recovery.yaml").read_text())
    assert audit["previous_state"] == "IMPLEMENTING"
    assert audit["reason"] == "stale task"
    assert audit["replacement_task_id"] == "TASK-005"
    assert (archive / "findings/FND-001.yaml").is_file()
    assert (archive / "evidence/unit.json").is_file()
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert task["task"]["id"] == "TASK-005"
    assert task["task"]["title"] == "Wheel isolation"
    assert task["state"] == "CREATED"
    assert list(findings.iterdir()) == []
    assert list(evidence.iterdir()) == []


def test_task_recover_archives_and_removes_plan_artifacts(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    harness = repo / ".harness"
    (harness / "plan.yaml").write_text("version: 1\nitems: []\n")
    (harness / "plan-execution.yaml").write_text(
        "version: 2\nplan:\n  path: .harness/plan.yaml\n  fingerprint: sha256:" + "0" * 64 + "\nsequence: 0\ntransitions: []\nitems: {}\n"
    )

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "stale")

    assert result.returncode == 0, result.stderr
    archive = next((harness / "history").glob("TASK-004-*"))
    assert (archive / "plan.yaml").is_file()
    assert (archive / "plan-execution.yaml").is_file()
    assert not (harness / "plan.yaml").exists()
    assert not (harness / "plan-execution.yaml").exists()


def test_task_recover_preserves_required_mode_and_architecture_artifact(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    harness = repo / ".harness"
    seal = {
        "version": 2,
        "task_id": "TASK-004",
        "contract_hash": "sha256:" + "0" * 64,
        "architecture_mode": "required",
        "architecture_fingerprint": "sha256:" + "1" * 64,
        "declared_modules": ["app"],
        "decision_selections": {},
        "boundary_refs": {"interface": [], "permission": [], "persistence": []},
        "frozen_at": "2026-10-01T00:00:00Z",
    }
    (harness / "alignment-freeze.yaml").write_text(yaml.safe_dump(seal, sort_keys=False))
    architecture = harness / "architecture.yaml"
    architecture.write_text("version: 1\n")
    before = architecture.read_bytes()

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "stale")

    assert result.returncode == 0, result.stderr
    gate = yaml.safe_load((harness / "gate.yaml").read_text())
    assert gate["gate"]["architecture"]["mode"] == "required"
    assert architecture.read_bytes() == before
    archive = next((harness / "history").glob("TASK-004-*"))
    assert (archive / "alignment-freeze.yaml").is_file()


def test_task_recover_malformed_seal_is_atomic(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    harness = repo / ".harness"
    (harness / "alignment-freeze.yaml").write_text("version: 2\n")
    before = {path.relative_to(harness).as_posix(): path.read_bytes() for path in harness.rglob("*") if path.is_file()}

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "stale")

    assert result.returncode == 2
    assert {path.relative_to(harness).as_posix(): path.read_bytes() for path in harness.rglob("*") if path.is_file()} == before


def test_task_recover_archives_and_clears_stale_alignment(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    alignment = repo / ".harness/alignment.yaml"
    alignment.write_text("version: 1\ntask_id: TASK-004\n")

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "stale")

    assert result.returncode == 0, result.stderr
    archive = next((repo / ".harness/history").glob("TASK-004-*"))
    assert (archive / "alignment.yaml").is_file()
    assert not alignment.exists()


def test_resume_routes_typed_evidence_blocker_to_verifying(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "BLOCKED")
    path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["gate"] = {
        "status": "BLOCKED",
        "blocked_by": [
            {
                "code": "EVIDENCE_WORKSPACE_STALE",
                "category": "verification",
                "message": "unit-test evidence stale",
                "source": "unit_test",
                "finding_id": None,
                "recover_to": "VERIFYING",
            }
        ],
    }
    path.write_text(yaml.safe_dump(task))

    result = run_cli(repo, "resume")

    assert result.returncode == 0, result.stderr
    assert "BLOCKED -> VERIFYING" in result.stdout
    assert yaml.safe_load(path.read_text())["state"] == "VERIFYING"


@pytest.mark.parametrize(
    ("code", "category", "target"),
    [
        ("DIAGNOSABILITY_REVIEW_MISSING", "verification", "VERIFYING"),
        ("OBSERVABILITY_CONTRACT_INVALID", "implementation", "IMPLEMENTING"),
    ],
)
def test_resume_routes_diagnosability_blocker(code, category, target, tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "BLOCKED")
    path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["gate"] = {
        "status": "BLOCKED",
        "blocked_by": [
            {
                "code": code,
                "category": category,
                "message": "diagnosability blocked",
                "recover_to": "tampered",
            }
        ],
    }
    path.write_text(yaml.safe_dump(task))

    result = run_cli(repo, "resume")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(path.read_text())["state"] == target


def test_resume_ignores_tampered_persisted_recovery_target(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "BLOCKED")
    path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["gate"] = {
        "status": "BLOCKED",
        "blocked_by": [
            {
                "code": "EVIDENCE_MISSING",
                "category": "verification",
                "message": "missing build evidence",
                "source": "build",
                "requirement_id": None,
                "invariant_id": None,
                "finding_id": None,
                "recover_to": "IMPLEMENTING",
            }
        ],
    }
    path.write_text(yaml.safe_dump(task))

    result = run_cli(repo, "resume")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(path.read_text())["state"] == "VERIFYING"


@pytest.mark.parametrize(
    "target", ["IMPLEMENTING", "VERIFYING", "REPRODUCING", "ESCALATED"]
)
def test_transition_cannot_bypass_resume_for_blocked_recovery(tmp_path, target):
    repo = make_repo(tmp_path)
    bound = run_cli(repo, "task", "migrate-id", "TASK-004")
    assert bound.returncode == 0, bound.stdout + bound.stderr
    set_task_state(repo, "BLOCKED")

    result = run_cli(repo, "transition", target)

    assert result.returncode == 1
    assert "RESUME_REQUIRED" in result.stderr


def test_task_recover_records_current_git_head_as_complexity_baseline(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "restart")

    assert result.returncode == 0, result.stderr
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert task["git"]["head"] == head
    assert task["git"]["base_commit"] == head
    assert task["git"]["head_at_start"] == head
    assert task["git"]["base_ref"]


def test_task_new_without_git_head_fails_without_mutation(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "DONE")
    task_path = repo / ".harness/current-task.yaml"
    before = task_path.read_bytes()

    result = run_cli(repo, "task", "new", "TASK-005")

    assert result.returncode == 2
    assert "TASK_GIT_BASELINE_REQUIRED" in result.stderr
    assert task_path.read_bytes() == before
    history = repo / ".harness/history"
    assert not history.exists() or not list(history.iterdir())


def test_task_new_records_current_git_head_as_complexity_baseline(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "DONE")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    result = run_cli(repo, "task", "new", "TASK-005")

    assert result.returncode == 0, result.stderr
    assert (
        yaml.safe_load((repo / ".harness/current-task.yaml").read_text())["git"][
            "base_commit"
        ]
        == head
    )


def test_task_new_still_rejects_active_task(tmp_path):
    repo = make_repo(tmp_path)

    result = run_cli(repo, "task", "new", "TASK-005")

    assert result.returncode == 1
    assert "DONE or ESCALATED" in result.stderr
@pytest.mark.parametrize('gate_defect', [False, True], ids=['commit-and-archive', 'native-gate-block'])
def test_task_lifecycle_preserves_or_blocks_candidate_operation_facts(tmp_path, gate_defect):
    _exercise_candidate_workflow(tmp_path, gate_defect)


def _exercise_candidate_workflow(tmp_path, gate_defect=False, *, faults=False):
    """Real STRICT operator workflow; no planted verified/CONVERGED/DONE facts."""
    import importlib.util
    import json
    import os
    from harness.candidate_assessment import POLICY
    from harness.plan_execution import semantic_plan_fingerprint

    repo = tmp_path / 'operator-repository'
    repo.mkdir()
    home = tmp_path / 'home'
    home.mkdir()
    env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
           'PYTHONPATH': str(REPO / 'src')}
    events = []
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=repo, env=env, text=True).strip()
    def cli(*args, exit_code=0):
        result = subprocess.run([sys.executable, '-m', 'harness.cli', *args], cwd=repo,
                                env=env, capture_output=True, text=True, timeout=60)
        events.append({'argv': list(args), 'exit': result.returncode,
                       'stdout': result.stdout, 'stderr': result.stderr})
        (tmp_path / 'operator-actions.json').write_text(json.dumps(events, indent=2))
        assert result.returncode == exit_code, f'{args}: {result.stdout}\n{result.stderr}'
        if args[0] in {'candidate', 'commit', 'gate'}:
            from jsonschema import validate
            from harness.schema_resources import read_schema
            validate(json.loads(result.stdout), read_schema('candidate-command-result.schema.json'))
        return result
    def put(name, value):
        path = repo / '.harness' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value, sort_keys=False))
    def dependencies(names, site_packages=None):
        files = []
        for name in names:
            if site_packages is None:
                spec = importlib.util.find_spec(name)
                assert spec is not None and spec.origin is not None
                origin = Path(spec.origin).resolve()
            else:
                origin = site_packages / name / '__init__.py'
                assert origin.is_file()
            base = origin.parent.parent if origin.name == '__init__.py' else origin.parent
            package = origin.parent if origin.name == '__init__.py' else origin
            paths = [package] if package.is_file() else package.rglob('*')
            for path in paths:
                if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts:
                    files.append({'source': str(path), 'target': path.relative_to(base).as_posix()})
            for directory in base.glob('*.dist-info'):
                if directory.name.split('-')[0].lower().replace('-', '_') != name.lower().replace('-', '_'):
                    continue
                for path in directory.rglob('*'):
                    if path.is_file() and not path.is_symlink():
                        files.append({'source': str(path), 'target': path.relative_to(base).as_posix()})
        return files

    git('init', '-q', '-b', 'main')
    git('config', 'user.name', 'Fixture Operator')
    git('config', 'user.email', 'operator@example.com')
    (repo / 'calc.py').write_text('def add(a, b):\n    return 0\n')
    (repo / 'tests').mkdir()
    (repo / 'tests/test_calc.py').write_text('from calc import add\ndef test_add():\n    assert add(2, 2) == 4\n')
    (repo / 'pyproject.toml').write_text('[build-system]\nrequires = []\nbuild-backend = "backend"\nbackend-path = ["."]\n')
    (repo / 'backend.py').write_text(
        'from pathlib import Path\nfrom zipfile import ZipFile\n'
        'def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):\n'
        '    name = "fixture_calc-1.0-py3-none-any.whl"\n'
        '    with ZipFile(Path(wheel_directory) / name, "w") as wheel:\n'
        '        wheel.writestr("calc.py", Path("calc.py").read_text())\n'
        '        wheel.writestr("fixture_calc-1.0.dist-info/METADATA", "Metadata-Version: 2.1\\nName: fixture-calc\\nVersion: 1.0\\n")\n'
        '        wheel.writestr("fixture_calc-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\\nGenerator: fixture\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n")\n'
        '        wheel.writestr("fixture_calc-1.0.dist-info/RECORD", "")\n'
        '    return name\n')
    git('add', '.')
    git('commit', '-qm', 'incomplete calculation baseline')
    baseline = git('rev-parse', 'HEAD')
    cli('init')
    cli('task', 'migrate-id', 'TASK-1')
    cli('task', 'classify', '--level', 'Q3', *[part for key in
        ('scope', 'contract', 'data', 'authorization', 'security', 'concurrency', 'deployment')
        for part in ('--' + key, 'high')])
    cli('transition', 'SPECIFYING')
    files = ['calc.py', 'tests/test_calc.py', 'backend.py', 'pyproject.toml']
    for name in files:
        cli('impact', 'adopt-path', name)
    cli('impact', 'add-change', 'calc.py')
    cli('impact', 'add-dependent', 'tests/test_calc.py')
    case = {'id': 'TC-001', 'type': 'happy_path', 'strategy': 'unit',
            'description': 'sum behavior', 'tests': ['tests/test_calc.py::test_add']}
    put('requirements.yaml', {'requirements': [{'id': 'REQ-001', 'statement': 'add returns the sum',
        'priority': 'must', 'status': 'pending', 'evidence': [], 'test_plan': {'strategies': ['unit'], 'cases': [case]}}]})
    put('invariants.yaml', {'invariants': [{'id': 'INV-001', 'statement': 'sum assertion holds',
        'category': 'correctness', 'severity': 'critical', 'status': 'pending', 'verification': [],
        'test_plan': {'strategies': ['unit'], 'cases': [{**case, 'id': 'TC-101', 'type': 'invariant'}]}}]})
    gate = yaml.safe_load((repo / '.harness/gate.yaml').read_text())
    gate['gate']['candidate_commit'] = POLICY
    put('gate.yaml', gate)
    put('observability.yaml', {'version': 1, 'required': True,
        'applicability': {'reasons': ['calculation CLI rejects invalid operands'], 'inspected_paths': files},
        'business_keys': ['request_id'], 'critical_events': ['calculation_completed', 'calculation_rejected'],
        'state_transitions': [{'business_key': 'request_id', 'from': 'input', 'to': 'output', 'trigger': 'sum'}],
        'external_dependencies': [{'name': 'Python interpreter', 'operations': ['calculate'], 'required_context': ['request_id']}],
        'failure_boundaries': ['invalid operands'],
        'sensitive_data': {'policy': 'Never emit operand secrets', 'prohibited': ['credentials']}})
    cli('interface', 'declare', '--name', 'calculation API', '--kind', 'cli', '--consumer', 'fixture',
        '--input', 'two integers', '--output', 'sum', '--error', 'typed rejection',
        '--compatibility', 'compatible', '--rationale', 'new calculation')
    cli('impact', 'add-interface', 'calculation API', '--kind', 'cli', '--consumer', 'fixture',
        '--compatibility', 'compatible', '--contract-id', 'INT-001')
    put('alignment.yaml', {'version': 1, 'task_id': 'TASK-1', 'goal': {'summary': 'Implement sum'},
        'scope': {'in': ['calculation and tests'], 'out': ['deployment']}, 'non_goals': ['network services'],
        'boundaries': ['local pure calculation'], 'constraints': ['preserve caller input'],
        'assumptions': ['integer inputs'], 'acceptance_criteria': [{'id': 'AC-001', 'description': 'correct sum', 'requirement_ids': ['REQ-001']}],
        'implementation_surfaces': [{'id': 'SURFACE-001', 'acceptance_criteria': ['AC-001'], 'paths': files, 'seam': 'calculation function'}],
        'verification': [{'id': 'VER-001', 'acceptance_criteria': ['AC-001'], 'method': 'execute bound pytest assertion', 'expected_evidence': 'passing test_add'}],
        'decision_ids': [], 'interface_contract_ids': ['INT-001'], 'open_questions': [], 'open_decisions': [], 'open_loops': [],
        'freeze': {'frozen': False, 'frozen_at': None, 'contract_hash': None}})
    plan = {'version': 1, 'items': [{'id': 'P-001', 'intent': 'implement sum', 'requirement_refs': ['REQ-001'],
        'invariant_refs': ['INV-001'], 'test_case_refs': ['REQ-001/TC-001', 'INV-001/TC-101'], 'surfaces': ['calc.py']}]}
    put('plan.yaml', plan)
    put('plan-execution.yaml', {'version': 2, 'plan': {'path': '.harness/plan.yaml', 'fingerprint': semantic_plan_fingerprint(plan)},
                              'items': {}, 'sequence': 0, 'transitions': []})
    cli('align', 'freeze')
    cli('impact', 'add-test', 'tests/test_calc.py')
    cli('transition', 'PLANNED')
    checks = {name: {'checked': False, 'result': 'skipped'} for name in
              ('existence', 'reuse', 'stdlib', 'native', 'existing_dependency', 'minimum_local_implementation')}
    checks['existence'] = {'checked': True, 'result': 'required'}
    checks['reuse'] = {'checked': True, 'result': 'found', 'candidate': 'existing calc.add function'}
    put('minimal-fixture.yaml', {'version': 1, 'task': 'TASK-1', 'checks': checks,
                               'decision': {'approach': 'reuse', 'rationale': 'Implement existing calculation seam'}})
    cli('check', 'minimal', '--file', '.harness/minimal-fixture.yaml')
    cli('transition', 'IMPLEMENTING')
    cli('plan', 'begin', 'P-001')
    command = f'{sys.executable} -m pytest -q tests/test_calc.py'
    cli('evidence', 'run', '--type', 'unit_test', '--phase', 'red', '--scope', 'related',
        '--covered-test', 'tests/test_calc.py', '--command', command)
    reds = [json.loads(path.read_text()) for path in (repo / '.harness/evidence').glob('*.json')]
    assert any(record.get('exit_code') == 1 for record in reds)
    (repo / 'calc.py').write_text('def add(a, b):\n    return a + b\n')
    git('add', 'calc.py')
    prepared = json.loads(cli('candidate', 'prepare', '--path', 'calc.py', '--json').stdout)
    candidate = prepared['candidate_id']
    index = (repo / '.git/index').read_bytes()
    def profile(name, **options):
        return {'schema': 'candidate-proof-spec/v1', 'profile': name, 'interpreter': sys.executable,
            'dependencies': [], 'environment': {'SOURCE_DATE_EPOCH': '0'}, 'writable_paths': ['.candidate-output'],
            'input_policy': {'git': 'forbidden', 'hooks': 'forbidden', 'network': 'forbidden',
                             'secrets': 'forbidden', 'dynamic_dependencies': 'forbidden'}, **options}
    inputs = repo / '.harness/.candidate-operation-inputs' / candidate[7:]
    inputs.mkdir(parents=True)
    unit = inputs / 'unit.json'
    unit.write_text(json.dumps(profile('pytest-junit-v1', selectors=['tests/test_calc.py::test_add'], evidence_type='unit_test',
        dependencies=dependencies(['pytest', '_pytest', 'pluggy', 'iniconfig', 'packaging', 'pygments', 'py']))))
    proof = json.loads(cli('candidate', 'prove', '--candidate', candidate, '--spec', str(unit), '--json').stdout)
    build = inputs / 'build.json'
    import shutil
    frontend = shutil.which('pyproject-build')
    assert frontend is not None, 'qualified build frontend required for STRICT CLI qualification'
    build_sites = list((Path(frontend).resolve().parent.parent / 'lib').glob('python*/site-packages'))
    assert len(build_sites) == 1
    build.write_text(json.dumps(profile('python-module-build-v1',
        dependencies=dependencies(['build', 'pyproject_hooks', 'packaging'], build_sites[0]))))
    cli('candidate', 'prove', '--candidate', candidate, '--spec', str(build), '--json')
    proof_ref = proof['artifact_ref']
    cli('requirement', 'verify', 'REQ-001', '--evidence', proof_ref)
    cli('invariant', 'verify', 'INV-001', '--evidence', proof_ref)
    cli('interface', 'verify', 'INT-001', '--evidence', proof_ref)
    cli('plan', 'reconcile', 'P-001', '--complete', '--evidence', proof_ref, '--surface', 'calc.py')
    cli('transition', 'VERIFYING')
    from harness.workspace import project_typed_scope, observability_inspected_paths
    task = yaml.safe_load((repo / '.harness/current-task.yaml').read_text())
    impact = yaml.safe_load((repo / '.harness/impact.yaml').read_text())
    scope_files, scope_refs = project_typed_scope(task, impact['impact'], inspected_paths=observability_inspected_paths(repo / '.harness'))
    proof_record = json.loads((repo / proof_ref).read_text())
    reports = {
        'complexity': {'task': 'TASK-1', 'findings': [], 'checks': {key: {'result': 'pass', 'evidence': 'simple local addition inspected'}
            for key in ('delete', 'reuse', 'stdlib', 'native', 'yagni', 'shrink')}},
        'diagnosability': {'task': 'TASK-1', 'contract_required': True, 'finding_ids': [], 'direct_dependencies': [],
            'review_scope': {'files': list(scope_files), 'contract_refs': list(scope_refs)},
            'checks': {key: 'pass' for key in ('business_keys', 'external_failure_context', 'state_transitions',
                'caller_rejections', 'sensitive_data', 'duplicate_exception_logging', 'low_value_logging')}},
        'interface': {'task': 'TASK-1', 'contracts': ['INT-001'], 'proposals': [],
            'checks': {key: 'pass' for key in ('boundary', 'dto', 'errors', 'dependency', 'compatibility', 'tests')}}}
    for kind, report in reports.items():
        path = inputs / (kind + '.json')
        path.write_text(json.dumps(report))
        scope = inputs / (kind + '-scope.json')
        scope.write_text(json.dumps({'schema': 'candidate-review-scope/v1', 'candidate_id': candidate, 'kind': kind,
            'source_fingerprint': proof_record['execution']['source_before'], 'files': list(scope_files),
            'contract_refs': list(scope_refs), 'direct_dependencies': []}))
        cli('candidate', 'review-record', '--candidate', candidate, '--kind', kind,
            '--manifest', prepared['artifact_ref'], '--scope-attestation', str(scope), '--report', str(path), '--json')
    cli('transition', 'REVIEWING')
    cli('review', 'outcome', 'PASS', '--reason-code', 'REVIEW_CLEAN')
    before_gate = (repo / 'calc.py').read_bytes()
    (repo / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
    refused = json.loads(cli('gate', '--candidate', candidate, '--json', exit_code=1).stdout)
    assert refused['ok'] is False and refused['reason_code'] == 'CANDIDATE_DRIFT'
    assert refused['mutation_started'] is False
    assert yaml.safe_load((repo / '.harness/current-task.yaml').read_text())['state'] == 'GATING'
    assert not list((repo / '.harness/evidence/candidate-acceptance').glob('*.json'))
    (repo / 'calc.py').write_bytes(before_gate)
    if gate_defect:
        requirements = yaml.safe_load((repo / '.harness/requirements.yaml').read_text())
        requirements['requirements'][0]['status'] = 'pending'
        put('requirements.yaml', requirements)
        refused = json.loads(cli('gate', '--candidate', candidate, '--json', exit_code=1).stdout)
        assert refused['ok'] is False and refused['reason_code'] == 'CANDIDATE_GATE_BLOCKED'
        blocked = yaml.safe_load((repo / '.harness/current-task.yaml').read_text())
        assert blocked['state'] == 'BLOCKED'
        assert blocked['gate']['status'] == 'BLOCKED'
        assert blocked['convergence']['count'] == 1
        assert blocked['convergence']['fingerprint']
        assert not list((repo / '.harness/evidence/candidate-acceptance').glob('*.json'))
        assert git('rev-parse', 'HEAD') == baseline
        assert (repo / '.git/index').read_bytes() == index
        return
    accepted = json.loads(cli('gate', '--candidate', candidate, '--json').stdout)
    assert accepted['ok'] is True and accepted['phase'] == 'CONVERGED'
    assert accepted['acceptance_id'] is not None
    assert yaml.safe_load((repo / '.harness/current-task.yaml').read_text())['state'] == 'CONVERGED'
    cli('transition', 'DONE')
    before_commit_context = json.loads(cli('context', '--json').stdout)
    facts = before_commit_context['control']['candidate']
    assert facts['historical_acceptance'] is True
    assert facts['historically_committed'] is False
    assert facts['current_readiness'] == 'NOT_ASSESSED'
    assert facts['generic_evidence_reuse'] is False
    message = inputs / 'message.txt'
    message.write_text('accepted sum implementation\n')
    refused = json.loads(cli('commit', '--candidate', candidate, '--message-file', str(message), '--json', exit_code=1).stdout)
    assert refused['ok'] is False and refused['reason_code'] == 'USER_AUTHORITY_REQUIRED'
    assert git('rev-parse', 'HEAD') == baseline
    assert (repo / '.git/index').read_bytes() == index
    cli('authorize', 'commit')
    if faults:
        injections = [
            (1, 'REF_PUBLISHED_POSTCHECK_FAILED', 'REF_CAS_STARTED',
             "original = domain._publish_documents\n"
             "def fault(root, documents):\n"
             "    if any(name.startswith('evidence/candidate-trace/') for name in documents):\n"
             "        raise OSError('/private/home/SECRET_TOKEN=secret-value')\n"
             "    return original(root, documents)\n"
             "domain._publish_documents = fault\n"),
            (70, 'CANDIDATE_INTERNAL_ERROR', 'TRACE_PUBLISHED',
             "original = domain.controlled_commit\n"
             "def fault(*args, **kwargs):\n"
             "    original(*args, **kwargs)\n"
             "    raise RuntimeError('/private/home/SECRET_TOKEN=secret-value')\n"
             "domain.controlled_commit = fault\n"),
        ]
        for expected_exit, reason, phase, injection in injections:
            script = ('import sys\nfrom harness import candidate_commit as domain, cli\n' + injection
                      + 'sys.exit(cli.main(sys.argv[1:]))\n')
            failed = subprocess.run([sys.executable, '-c', script, 'commit', '--candidate', candidate,
                '--message-file', str(message), '--json'], cwd=repo, env=env,
                capture_output=True, text=True, timeout=60)
            assert failed.returncode == expected_exit, failed.stdout + failed.stderr
            assert 'SECRET_TOKEN' not in failed.stdout + failed.stderr
            outcome = json.loads(failed.stdout)
            from jsonschema import validate
            from harness.schema_resources import read_schema
            validate(outcome, read_schema('candidate-command-result.schema.json'))
            assert outcome['reason_code'] == reason and outcome['phase'] == phase
            assert outcome['mutation_started'] is True
            assert outcome['candidate_id'] == candidate
            assert outcome['operation_id'] and outcome['acceptance_id']
            assert outcome['proposed_commit'] == git('rev-parse', 'HEAD')
            assert git('rev-parse', 'HEAD^') == baseline
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        delivered = subprocess.run([sys.executable, '-m', 'harness.cli', 'commit', '--candidate', candidate,
            '--message-file', str(message), '--json'], cwd=repo, env=env, stdout=write_end,
            stderr=write_end, timeout=60)
    finally:
        os.close(write_end)
    assert delivered.returncode == 0
    committed = json.loads(cli('commit', '--candidate', candidate, '--message-file', str(message), '--json').stdout)
    assert committed['ok'] is True and committed['phase'] == 'TRACE_PUBLISHED'
    assert committed['mutation_started'] is True
    assert git('rev-parse', 'HEAD') == committed['proposed_commit']
    assert git('rev-parse', 'HEAD^') == baseline
    assert (repo / '.git/index').read_bytes() == index
    state = json.loads(cli('candidate', 'status', '--candidate', candidate, '--json').stdout)
    assert state['phase'] == 'TRACE_PUBLISHED'
    assert state['proposed_commit'] == git('rev-parse', 'HEAD')
    trace_ref = committed['artifact_ref']
    operation_id = committed['operation_id']
    trace = (repo / trace_ref).read_bytes()
    cli('candidate', 'recover', '--operation', operation_id, '--json')
    assert (repo / trace_ref).read_bytes() == trace
    git('commit', '--allow-empty', '-qm', 'ordinary later HEAD with identical tree')
    assert git('rev-parse', 'HEAD^{tree}') == git('rev-parse', committed['proposed_commit'] + '^{tree}')
    later_context = json.loads(cli('context', '--json').stdout)
    facts = later_context['control']['candidate']
    assert facts['historical_acceptance'] is True
    assert facts['historically_committed'] is True
    assert facts['live_parent'] is False and facts['live_proposed'] is False
    assert facts['current_readiness'] == 'NOT_ASSESSED'
    assert facts['generic_evidence_reuse'] is False
    assert later_context['control']['gate']['status'] == 'BLOCKED'
    cli('context', 'validate')
    saved_context = (repo / '.harness/context/current.yaml').read_bytes()
    for reference, defect in ((trace_ref, 'trace_identity'),
                              (proof_ref, 'captured_proof'),
                              ('.harness/.candidate-active.json', 'pointer_task')):
        path = repo / reference
        original = path.read_bytes()
        document = json.loads(original)
        if defect == 'trace_identity':
            document['acceptance_id'] = 'sha256:' + 'f' * 64
        elif defect == 'captured_proof':
            document['record']['exit_code'] = 1
        else:
            document['task_id'] = 'TASK-999'
        path.write_text(json.dumps(document))
        invalid = cli('context', '--json', exit_code=2)
        if defect == 'trace_identity':
            # Shared admission now rejects bad terminal identity before Context loads.
            assert 'TRANSACTION_RECOVERY_BLOCKED: candidate record invalid' in invalid.stderr
        else:
            assert 'CONTEXT_SCHEMA_INVALID' in invalid.stderr
        assert (repo / '.harness/context/current.yaml').read_bytes() == saved_context
        path.write_bytes(original)
    cli('context', 'validate')
    cli('task', 'new', 'TASK-2', '--title', 'next calculation')
    archives = list((repo / '.harness/history').glob('TASK-1-*'))
    assert len(archives) == 1
    assert (archives[0] / '.candidate-operations' / (operation_id[7:] + '.json')).is_file()
    assert not (repo / '.harness/.candidate-operations').exists()
    assert not (repo / '.harness/.candidate-active.json').exists()
