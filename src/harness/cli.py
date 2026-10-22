"""harness CLI (guide section 20): parse args -> init service -> render ->
exit code. No init logic here.

Exit codes:
  0 = SUCCESS
  1 = OPERATION_FAILED (e.g. outside a git repository)
  2 = INVALID_USAGE
"""

import argparse
import difflib
import json
import os
import re
import sys

from pathlib import Path
from harness import controlplane
from harness.collect_evidence import VALID_TYPES
from harness.init import InitResult, init_current_repository
from harness.repository import RepositoryNotFoundError, find_git_root


class _HarnessArgumentParser(argparse.ArgumentParser):
    """Suggest near matches without changing parsing or command execution."""

    def parse_known_args(self, args=None, namespace=None):
        parsed, extras = super().parse_known_args(args, namespace)
        self._unknown_args = extras
        self._hint_options = self._option_string_actions
        for action in self._actions:
            if isinstance(action, argparse._SubParsersAction):
                selected = action.choices.get(getattr(parsed, action.dest, None))
                if selected is not None:
                    self._hint_options = selected._hint_options
        return parsed, extras

    def error(self, message: str) -> None:
        match = re.fullmatch(r"argument [^:]+: invalid choice: '([^']+)' \(choose from (.+)\)", message)
        if match:
            unknown, raw_choices = match.groups()
            choices = re.findall(r"'([^']+)'", raw_choices)
            if suggestion := difflib.get_close_matches(unknown, choices, n=1, cutoff=0.6):
                message += f"\nDid you mean: {suggestion[0]}?"
        elif message.startswith("unrecognized arguments:"):
            for argument in self._unknown_args:
                if argument == "--":
                    break
                if not argument.startswith("--"):
                    continue
                option = argument.split("=", 1)[0]
                matches = difflib.get_close_matches(
                    option, self._hint_options, n=2, cutoff=0.8
                )
                if not matches:
                    continue
                if len(matches) == 2 and (
                    difflib.SequenceMatcher(None, matches[0], option).ratio()
                    == difflib.SequenceMatcher(None, matches[1], option).ratio()
                ):
                    continue
                message += f"\nDid you mean: {matches[0]}?"
                break
        super().error(message)


class _PruneArgumentParser(argparse.ArgumentParser):
    """Keep rejected prune tokens outside the public diagnostic boundary."""

    def error(self, message: str) -> None:
        del message
        raise SystemExit(controlplane.render_task_prune_refusal("INVALID_ARGUMENTS"))


def _task_prune(argv: list[str]) -> int:
    parser = _PruneArgumentParser(prog="harness task prune")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan-id")
    args = parser.parse_args(argv)
    if args.apply != bool(args.plan_id):
        parser.error("invalid prune execution arguments")
    try:
        os.chdir(find_git_root(Path.cwd()))
    except (RepositoryNotFoundError, OSError):
        return controlplane.render_task_prune_refusal("REPOSITORY_NOT_FOUND")
    return controlplane.cmd_task_prune(args.apply, args.plan_id)


class _CandidateUsageError(ValueError):
    pass


class _CandidateArgumentParser(_HarnessArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs['allow_abbrev'] = False
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise _CandidateUsageError('CANDIDATE_UNSUPPORTED')


def _candidate_invocation(argv):
    return bool(argv and (argv[0] in {'candidate', 'commit'} or (
        argv[0] == 'gate' and any(arg.startswith('--cand') or arg.split('=', 1)[0] in {'--c', '--ca', '--can'}
                                 for arg in argv[1:]))))


def _candidate_command_name(argv):
    if argv[0] == 'candidate':
        return 'candidate ' + argv[1] if len(argv) > 1 and argv[1] in {
            'prepare', 'prove', 'review-record', 'status', 'recover'} else 'candidate'
    return argv[0]


class _SilentStream:
    def write(self, text):
        return len(text)

    def flush(self):
        pass


def _emit_candidate_result(document, exit_code):
    """Delivery failure cannot replace the primary durable operation outcome."""
    from jsonschema import validate
    from harness.schema_resources import read_schema
    validate(document, read_schema('candidate-command-result.schema.json'))
    try:
        sys.stdout.write(json.dumps(document, sort_keys=True, separators=(',', ':')) + '\n')
        sys.stdout.flush()
    except (OSError, ValueError):
        # Avoid another failed flush during interpreter shutdown (exit 120).
        sys.stdout = _SilentStream()
    return exit_code


def _execute_candidate(args, command):
    from harness import candidate_commit as domain
    from harness.telemetry_lock import telemetry_lock

    try:
        root = find_git_root(Path.cwd())
        os.chdir(root)
    except RepositoryNotFoundError:
        return _emit_candidate_result(domain.command_result(None, command, reason='CANDIDATE_UNSUPPORTED'), 1)
    except Exception:
        return _emit_candidate_result(domain.command_result(None, command, reason='CANDIDATE_INTERNAL_ERROR'), 70)
    try:
        with telemetry_lock(root / '.harness'):
            document, exit_code = _candidate_outcome(root, args, command)
    except Exception:
        document = domain.unavailable_command_result(command,
            candidate_id=getattr(args, 'candidate', None), operation_id=getattr(args, 'operation', None))
        exit_code = 70
    # A slow/dead consumer must not extend the cooperation lock lifetime.
    if document['reason_code'] == 'USER_AUTHORITY_REQUIRED':
        try:
            controlplane._print_authority_halt(document['reason_code'])
        except (OSError, ValueError):
            sys.stderr = _SilentStream()
    return _emit_candidate_result(document, exit_code)


def _candidate_outcome(root, args, command):
    from harness import candidate_commit as domain

    payload, reason, exit_code = None, None, 0
    try:
        if command == 'candidate prepare':
            payload = domain.prepare(root, args.candidate_paths)
        elif command == 'candidate prove':
            payload = domain.prove(root, args.candidate, args.spec)
        elif command == 'candidate review-record':
            payload = domain.review_record(root, args.candidate, args.kind, args.manifest,
                                           args.scope_attestation, args.report)
        elif command == 'candidate status':
            payload = domain.status(root, args.candidate)
        elif command == 'candidate recover':
            payload = domain.recover(root, args.operation)
        elif command == 'gate':
            payload = domain.accept(root, args.candidate)
        else:
            payload = domain.controlled_commit(root, args.candidate, args.message_file)
    except RepositoryNotFoundError:
        reason, exit_code = 'CANDIDATE_UNSUPPORTED', 1
    except domain.CandidateRefusal as exc:
        reason, exit_code = exc.code, 1
    except Exception:
        reason, exit_code = 'CANDIDATE_INTERNAL_ERROR', 70
    document = domain.command_result(root, command, payload, reason=reason,
                                    candidate_id=getattr(args, 'candidate', None),
                                    operation_id=getattr(args, 'operation', None))
    return document, exit_code


def _render(result: InitResult) -> str:
    lines = [f"Harness initialized at {result.harness_dir}"]
    if result.created:
        lines.append("Created:")
        lines.extend(f"  created  {p.name}" for p in result.created)
    if result.skipped:
        lines.append("Skipped (already present, untouched):")
        lines.extend(f"  skipped  {p.name}" for p in result.skipped)
    return "\n".join(lines)


def _main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:2] == ["task", "prune"]:
        return _task_prune(argv[2:])
    if argv[:2] == ["evidence", "plan"]:
        diagnostic = _HarnessArgumentParser(prog="harness evidence plan")
        diagnostic.add_argument("--json", dest="json_output", action="store_true")
        options = diagnostic.parse_args(argv[2:])
        try:
            os.chdir(find_git_root(Path.cwd()))
        except RepositoryNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        return controlplane.cmd_evidence_plan(options.json_output)
    legacy_evidence = bool(
        argv
        and argv[0] == "evidence"
        and (len(argv) == 1 or argv[1] not in {"run", "attach"})
    )
    if len(argv) > 1 and argv[0] == "evidence" and argv[1] in {"run", "attach"}:
        mode = argv.pop(1)
        if mode == "attach":
            argv.insert(1, "--attach")
    parser_class = _CandidateArgumentParser if _candidate_invocation(argv) else _HarnessArgumentParser
    parser = parser_class(
        prog="harness",
        description="Engineering Harness deterministic control plane",
    )
    sub = parser.add_subparsers(dest="subcommand")
    sub.add_parser("init", help="initialize .harness/ at the git repo root")
    p_explain = sub.add_parser("explain", help="explain a diagnostic code and safe next step")
    p_explain.add_argument("code")
    p_status = sub.add_parser("status", help="render unified persisted-state view")
    p_status.add_argument("--harness-dir", default=".harness")
    p_plan = sub.add_parser("plan", help="inspect canonical implementation plan")
    plan_sub = p_plan.add_subparsers(dest="plan_command", required=True)
    p_plan_status = plan_sub.add_parser("status", help="report read-only plan status")
    p_plan_status.add_argument("--json", dest="plan_json", action="store_true")
    p_plan_status.add_argument("--verbose", dest="plan_verbose", action="store_true")
    p_plan_sync = plan_sub.add_parser(
        "sync-markdown", help="project canonical Plan state into explicit Markdown"
    )
    p_plan_sync.add_argument("target")
    p_plan_begin = plan_sub.add_parser("begin", help="begin canonical next Plan Item")
    p_plan_begin.add_argument("item_id")
    p_plan_block = plan_sub.add_parser("block", help="block active Plan Item")
    p_plan_block.add_argument("item_id")
    p_plan_block.add_argument("--reason", required=True)
    p_plan_resume = plan_sub.add_parser("resume", help="resume blocked Plan Item")
    p_plan_resume.add_argument("item_id")
    p_plan_reconcile = plan_sub.add_parser(
        "reconcile", help="record terminal Plan Item disposition"
    )
    p_plan_reconcile.add_argument("item_id")
    disposition = p_plan_reconcile.add_mutually_exclusive_group(required=True)
    disposition.add_argument(
        "--complete", dest="plan_disposition", action="store_const", const="COMPLETE"
    )
    disposition.add_argument(
        "--skipped", dest="plan_disposition", action="store_const", const="SKIPPED"
    )
    disposition.add_argument(
        "--superseded",
        dest="plan_disposition",
        action="store_const",
        const="SUPERSEDED",
    )
    disposition.add_argument("--auto", dest="plan_auto", action="store_true")
    p_plan_reconcile.add_argument("--reason")
    p_plan_reconcile.add_argument("--decision", dest="decision_id")
    p_plan_reconcile.add_argument("--replacement", action="append", default=[])
    p_plan_reconcile.add_argument("--evidence", action="append", default=[])
    p_plan_reconcile.add_argument("--surface", action="append", default=[])
    p_plan_refresh = plan_sub.add_parser(
        "refresh-proof", help="refresh COMPLETE item proof"
    )
    p_plan_refresh.add_argument("item_id")
    p_plan_refresh.add_argument("--evidence", action="append", default=[])
    p_plan_refresh.add_argument("--surface", action="append", default=[])
    plan_sub.add_parser(
        "upgrade-execution", help="upgrade all-pending Q3 execution to v2"
    )
    plan_sub.add_parser(
        "sync-fingerprint", help="refresh empty Plan execution fingerprint"
    )
    p_architecture = sub.add_parser(
        "architecture", help="publish and inspect canonical Architecture"
    )
    architecture_sub = p_architecture.add_subparsers(
        dest="architecture_command", required=True
    )
    architecture_publish = architecture_sub.add_parser("publish")
    architecture_publish.add_argument("--file", required=True, dest="source_file")
    for command in ("validate", "check", "summary"):
        architecture_read = architecture_sub.add_parser(command)
        architecture_read.add_argument(
            "--json", dest="architecture_json", action="store_true"
        )
    architecture_resolve = architecture_sub.add_parser("resolve")
    architecture_resolve.add_argument("path")
    architecture_resolve.add_argument(
        "--json", dest="architecture_json", action="store_true"
    )
    architecture_scope = architecture_sub.add_parser("scope")
    architecture_scope_sub = architecture_scope.add_subparsers(
        dest="architecture_scope_action", required=True
    )
    for action in ("add", "remove"):
        architecture_scope_command = architecture_scope_sub.add_parser(action)
        architecture_scope_command.add_argument("module_id")
    p_context = sub.add_parser("context", help="generate a validated derived Context")
    context_mode = p_context.add_mutually_exclusive_group()
    context_mode.add_argument("--compact", dest="context_mode", action="store_const", const="compact")
    context_mode.add_argument("--full", dest="context_mode", action="store_const", const="full")
    p_context.add_argument("--json", dest="context_json", action="store_true")
    p_context.add_argument("--profile-json", type=Path)
    p_context.add_argument("--progress", action="store_true")
    context_sub = p_context.add_subparsers(dest="context_command")
    for command, help_text in (("validate", "validate saved Context without rewriting it"),
                               ("explain", "explain the validated saved selection")):
        context_read = context_sub.add_parser(command, help=help_text)
        context_read.add_argument("--json", dest="context_json", action="store_true", default=argparse.SUPPRESS)
    from .context.escalation import REPORTED_TRIGGERS
    context_expand = context_sub.add_parser("expand", help="report a task-bound Context expansion")
    context_expand.add_argument("--trigger", choices=REPORTED_TRIGGERS, required=True)
    context_expand.add_argument("--reason", required=True)
    context_expand.add_argument("--json", dest="context_json", action="store_true", default=argparse.SUPPRESS)
    p_trans = sub.add_parser(
        "transition", help="validate and persist a state transition"
    )
    p_trans.add_argument("target")
    p_trans.add_argument("--reason")
    p_align = sub.add_parser("align", help="bootstrap and inspect alignment contracts")
    align_sub = p_align.add_subparsers(dest="align_command", required=True)
    for command in ("init", "freeze", "check", "status", "diff"):
        align_sub.add_parser(command)
    p_align_revise = align_sub.add_parser("revise")
    p_align_revise.add_argument("--reason", required=True)
    p_check = sub.add_parser("check", help="run Harness checks")
    check_sub = p_check.add_subparsers(dest="check_command")
    check_sub.add_parser(
        "admission", help="report all implementation-entry admission defects"
    )
    p_minimal = check_sub.add_parser(
        "minimal", help="persist Minimal Implementation Decision"
    )
    p_minimal.add_argument("--file", required=True, dest="source_file")
    p_review = sub.add_parser("review", help="run Harness reviews")
    review_sub = p_review.add_subparsers(dest="review_command")
    p_complexity = review_sub.add_parser("complexity", help="persist complexity review")
    p_complexity.add_argument("--file", required=True, dest="source_file")
    p_complexity.add_argument("--base")
    p_diagnosability = review_sub.add_parser(
        "diagnosability", help="persist diagnosability review"
    )
    p_diagnosability.add_argument("--file", required=True, dest="source_file")
    p_diagnosability.add_argument("--base")
    p_interface_review = review_sub.add_parser(
        "interface", help="persist interface review"
    )
    p_interface_review.add_argument("--file", required=True, dest="source_file")
    p_interface_review.add_argument("--base")
    p_outcome = review_sub.add_parser(
        "outcome", help="persist and route review outcome"
    )
    p_outcome.add_argument("outcome", choices=["PASS", "VERIFICATION_GAP", "DEFECT"])
    p_outcome.add_argument("--reason-code", required=True)
    p_outcome.add_argument("--finding", action="append", default=[])
    p_ev = sub.add_parser("evidence", help="run/attach HEAD-bound evidence, or inspect with evidence plan --json")
    p_ev.add_argument("--type", required=True, choices=sorted(VALID_TYPES))
    p_ev.add_argument("--scope", default="related")
    p_ev.add_argument("--command", required=True, dest="evidence_command")
    p_ev.add_argument("--finding")
    p_ev.add_argument("--test")
    p_ev.add_argument("--covered-test", action="append", default=[])
    p_ev.add_argument("--covered-test-case", action="append", default=[])
    p_ev.add_argument("--phase", choices=["red", "green", "full"])
    p_ev.add_argument("--reuse-if-valid", action="store_true")
    p_ev.add_argument("--attach", action="store_true")
    p_ev.add_argument("--result-file")
    p_ev.add_argument("--budget-override-reason")
    p_ev.add_argument("--budget-override-evidence")
    p_ev.add_argument("--budget-override-hypothesis")
    p_imp = sub.add_parser("impact")
    ims = p_imp.add_subparsers(dest="impact_action")
    ims.add_parser("show")
    reconcile = ims.add_parser("reconcile", help="validate an impact proposal without execution")
    reconcile.add_argument("--file", required=True, dest="source_file", type=Path)
    reconcile.add_argument("--dry-run", action="store_true")
    migration = ims.add_parser('migrate-scope', help='reconstruct scope from explicitly selected source authority')
    migration.add_argument('--file', required=True, dest='source_file', type=Path)
    scope = ims.add_parser("scope")
    scope.add_argument("--format", choices=["yaml"], default="yaml")
    adopt = ims.add_parser("adopt-path")
    adopt.add_argument("value")
    ignore = ims.add_parser("ignore-user-path")
    ignore.add_argument("value")
    ic = ims.add_parser("add-change")
    ic.add_argument("value")
    it = ims.add_parser("add-test")
    it.add_argument("value")
    idp = ims.add_parser("add-dependent")
    idp.add_argument("value")
    ict = ims.add_parser("add-contract")
    ict.add_argument("value")
    ict.add_argument(
        "--kind", choices=["generic", "permission", "persistence"], default="generic"
    )
    irk = ims.add_parser("add-risk")
    irk.add_argument("value")
    iinterface = ims.add_parser("add-interface")
    iinterface.add_argument("value")
    iinterface.add_argument(
        "--kind",
        choices=["http", "rpc", "event", "sdk", "plugin", "cli", "service"],
        required=True,
    )
    iinterface.add_argument("--visibility", choices=["external"], default="external")
    iinterface.add_argument("--consumer", action="append", required=True)
    iinterface.add_argument(
        "--compatibility", choices=["compatible", "breaking"], required=True
    )
    iinterface.add_argument("--contract-id")
    p_mr = sub.add_parser("mr")
    mr_sub = p_mr.add_subparsers(dest="mr_command")
    mr_sub.add_parser("describe")
    p_auth = sub.add_parser("authorize")
    p_auth.add_argument(
        "action",
        choices=[
            "commit",
            "push",
            "create-mr",
            "ready-mr",
            "merge",
            "deploy",
            "revoke-commit",
            "revoke-push",
            "revoke-create-mr",
            "revoke-ready-mr",
            "revoke-merge",
            "revoke-deploy",
        ],
    )
    p_gate = sub.add_parser("gate", help="run the deterministic quality gate")
    gate_sub = p_gate.add_subparsers(dest="gate_command")
    gate_sub.add_parser("preflight")
    p_gate.add_argument("--candidate")
    p_gate.add_argument("--json", action="store_true", dest="gate_json")
    p_telemetry = sub.add_parser("telemetry")
    telemetry_sub = p_telemetry.add_subparsers(dest="telemetry_command")
    telemetry_sub.add_parser("show")
    telemetry_report = telemetry_sub.add_parser(
        "report", help="report task-bound cumulative host usage"
    )
    telemetry_report.add_argument("--usage-file", dest="source_file", required=True)
    p_benchmark = sub.add_parser("benchmark")
    benchmark_sub = p_benchmark.add_subparsers(dest="benchmark_command")
    p_benchmark_run = benchmark_sub.add_parser("run")
    p_benchmark_run.add_argument("--fixtures", required=True)
    p_benchmark_alignment = benchmark_sub.add_parser("alignment")
    p_benchmark_alignment.add_argument("--records", required=True)
    p_benchmark_compare = benchmark_sub.add_parser("compare")
    p_benchmark_compare.add_argument("--fixtures", required=True)
    p_benchmark_compare.add_argument("--baseline", required=True)
    p_benchmark_compare.add_argument("--adaptive", required=True)
    p_corpus = benchmark_sub.add_parser("corpus")
    corpus_sub = p_corpus.add_subparsers(dest="corpus_command")
    p_corpus_validate = corpus_sub.add_parser("validate")
    p_corpus_validate.add_argument("--corpus", required=True)
    p_architecture_corpus = benchmark_sub.add_parser("architecture-corpus")
    architecture_corpus_sub = p_architecture_corpus.add_subparsers(
        dest="architecture_corpus_command"
    )
    p_architecture_corpus_validate = architecture_corpus_sub.add_parser("validate")
    p_architecture_corpus_validate.add_argument("--corpus", required=True)
    p_architecture_compare = benchmark_sub.add_parser("architecture-compare")
    p_architecture_compare.add_argument(
        "--experiment", choices=["drift_detection", "context_recovery"], required=True
    )
    p_architecture_compare.add_argument("--fixtures", required=True)
    p_architecture_compare.add_argument("--baseline", required=True)
    p_architecture_compare.add_argument("--adaptive", required=True)
    sub.add_parser("resume", help="recover BLOCKED task from typed blocker")
    p_decision = sub.add_parser("decision", help="manage persisted user decisions")
    decision_sub = p_decision.add_subparsers(dest="decision_command")
    dp = decision_sub.add_parser("propose")
    dp.add_argument('--file', dest='source_file', type=Path)
    dp.add_argument("--topic")
    dp.add_argument("--question")
    dp.add_argument("--context", action="append")
    dp.add_argument("--option", action="append")
    dp.add_argument("--recommend")
    dp.add_argument("--reason", action="append")
    dp.add_argument("--tradeoff", action="append", default=[])
    dp.add_argument("--scope", action="append", default=[])
    dp.add_argument("--constraint", action="append", default=[])
    da = decision_sub.add_parser("accept")
    da.add_argument("id")
    da.add_argument("--option", required=True)
    da.add_argument("--source", choices=["accepted_recommendation", "user_override"])
    dr = decision_sub.add_parser("reject")
    dr.add_argument("id")
    dr.add_argument("--reason", required=True)
    ds = decision_sub.add_parser("supersede")
    ds.add_argument("id")
    ds.add_argument("--topic", required=True)
    ds.add_argument("--question", required=True)
    ds.add_argument("--context", action="append", required=True)
    ds.add_argument("--option", action="append", required=True)
    ds.add_argument("--recommend", required=True)
    ds.add_argument("--reason", action="append", required=True)
    ds.add_argument("--tradeoff", action="append", default=[])
    ds.add_argument("--scope", action="append", default=[])
    ds.add_argument("--constraint", action="append", default=[])
    decision_sub.add_parser("reindex")
    decision_sub.add_parser("list")
    dshow = decision_sub.add_parser("show")
    dshow.add_argument("id")
    p_interface = sub.add_parser(
        "interface", help="manage external interface contracts"
    )
    interface_sub = p_interface.add_subparsers(dest="interface_command")
    ideclare = interface_sub.add_parser("declare")
    ideclare.add_argument("--name", required=True)
    ideclare.add_argument(
        "--kind",
        choices=["http", "rpc", "event", "sdk", "plugin", "cli", "service"],
        required=True,
    )
    ideclare.add_argument("--consumer", action="append", required=True)
    ideclare.add_argument("--input", required=True)
    ideclare.add_argument("--output", required=True)
    ideclare.add_argument("--error", required=True)
    ideclare.add_argument(
        "--compatibility", choices=["compatible", "breaking"], required=True
    )
    ideclare.add_argument("--rationale", required=True)
    ideclare.add_argument("--migration")
    ideclare.add_argument("--decision-ref", action="append", default=[])
    iverify = interface_sub.add_parser("verify")
    iverify.add_argument("id")
    iverify.add_argument("--evidence", required=True)
    iapprove = interface_sub.add_parser("approve-breaking")
    iapprove.add_argument("id")
    iapprove.add_argument("--reason", required=True)
    interface_sub.add_parser("list")
    ishow = interface_sub.add_parser("show")
    ishow.add_argument("id")
    p_finding = sub.add_parser("finding", help="inspect findings")
    f_sub = p_finding.add_subparsers(dest="finding_command")
    f_sub.add_parser("list", help="list all findings")
    p_show = f_sub.add_parser("show", help="show one finding record")
    p_show.add_argument("id")
    p_ft = f_sub.add_parser("transition")
    p_ft.add_argument("id")
    p_ft.add_argument("target")
    p_ft.add_argument("--evidence")
    p_ft.add_argument("--test")
    p_ft.add_argument("--attempt")
    p_ft.add_argument("--reason")
    p_ft.add_argument("--critical-related-approved", action="store_true")
    p_refresh = f_sub.add_parser("refresh-proof", help="refresh FIXED proof without advancing lifecycle")
    p_refresh.add_argument("id")
    p_refresh.add_argument("--evidence", required=True)
    p_fr = f_sub.add_parser("resume-review")
    p_fr.add_argument("id")
    p_req = sub.add_parser("requirement")
    rs = p_req.add_subparsers(dest="requirement_command")
    rv = rs.add_parser("verify")
    rv.add_argument("id")
    rv.add_argument("--evidence", required=True)
    p_inv = sub.add_parser("invariant")
    ivs = p_inv.add_subparsers(dest="invariant_command")
    iv = ivs.add_parser("verify")
    iv.add_argument("id")
    iv.add_argument("--evidence", required=True)
    p_task = sub.add_parser("task")
    ts = p_task.add_subparsers(dest="task_command")
    p_mid = ts.add_parser("migrate-id")
    p_mid.add_argument("id")
    p_new = ts.add_parser("new")
    p_new.add_argument("id")
    p_new.add_argument("--title", default="")
    p_recover = ts.add_parser("recover")
    p_recover.add_argument("id")
    p_recover.add_argument("--title", default="")
    p_recover.add_argument("--reason", required=True)
    p_prune = ts.add_parser("prune")
    p_prune.add_argument("--apply", action="store_true")
    p_prune.add_argument("--plan-id")
    p_classify = ts.add_parser("classify")
    p_classify.add_argument("--level", choices=["Q1", "Q2", "Q3"], required=True)
    for dimension in (
        "scope",
        "contract",
        "data",
        "authorization",
        "security",
        "concurrency",
        "deployment",
    ):
        p_classify.add_argument(f"--{dimension}", required=True)
    p_escalate = ts.add_parser("escalate")
    p_escalate.add_argument("--level", choices=["Q2", "Q3"], required=True)
    p_escalate.add_argument("--reason", required=True)
    p_existing = ts.add_parser("verify-existing")
    p_existing.add_argument("--reference", required=True)
    p_existing.add_argument("--reason", required=True)
    p_existing.add_argument(
        "--conclusion",
        required=True,
        choices=["already_satisfied", "duplicate_request", "requires_reproduction"],
    )
    p_existing.add_argument("--accept-diff")
    p_existing.add_argument("--untraceable-reason")
    sub.add_parser("converge", help="deterministic convergence decision")
    p_candidate = sub.add_parser("candidate", help="manage immutable commit candidates")
    candidate_sub = p_candidate.add_subparsers(dest="candidate_command", required=True)
    candidate_prepare = candidate_sub.add_parser("prepare")
    candidate_prepare.add_argument("--path", action="append", required=True, dest="candidate_paths")
    candidate_prepare.add_argument("--json", action="store_true", required=True, dest="candidate_json")
    candidate_prove = candidate_sub.add_parser("prove")
    candidate_prove.add_argument("--candidate", required=True)
    candidate_prove.add_argument("--spec", required=True, type=Path)
    candidate_prove.add_argument("--json", action="store_true", required=True)
    candidate_review = candidate_sub.add_parser("review-record")
    candidate_review.add_argument("--candidate", required=True)
    candidate_review.add_argument("--kind", choices=["complexity", "diagnosability", "interface"], required=True)
    candidate_review.add_argument("--manifest", required=True, type=Path)
    candidate_review.add_argument("--scope-attestation", required=True, type=Path)
    candidate_review.add_argument("--report", required=True, type=Path)
    candidate_review.add_argument("--json", action="store_true", required=True)
    candidate_status = candidate_sub.add_parser("status")
    candidate_status.add_argument("--candidate", required=True)
    candidate_status.add_argument("--json", action="store_true", required=True)
    candidate_recover = candidate_sub.add_parser("recover")
    candidate_recover.add_argument("--operation", required=True)
    candidate_recover.add_argument("--json", action="store_true", required=True)
    p_commit = sub.add_parser("commit", help="publish an accepted candidate locally")
    p_commit.add_argument("--candidate", required=True)
    p_commit.add_argument("--message-file", required=True, type=Path)
    p_commit.add_argument("--json", action="store_true", required=True)

    args = parser.parse_args(argv)
    if _candidate_invocation(argv):
        if args.subcommand == 'gate' and (not args.gate_json or args.gate_command is not None):
            raise _CandidateUsageError('CANDIDATE_UNSUPPORTED')
        return _execute_candidate(args, _candidate_command_name(argv))
    if args.subcommand == "context" and args.context_command and args.context_mode:
        parser.error("Context mode flags apply only to generation")
    if args.subcommand == "plan" and args.plan_command == "reconcile":
        disposition = args.plan_disposition
        has_proof = bool(args.evidence or args.surface)
        has_decision = bool(args.reason or args.decision_id or args.replacement)
        if args.plan_auto and (disposition or has_proof or has_decision):
            parser.error("--auto accepts no disposition, proof, or semantic options")
        if disposition == "COMPLETE" and has_decision:
            parser.error("--complete accepts only --evidence and --surface")
        if disposition == "SKIPPED" and (
            not args.reason
            or not args.decision_id
            or has_proof
            or args.replacement
        ):
            parser.error("--skipped requires --reason and --decision only")
        if disposition == "SUPERSEDED" and (
            not args.reason
            or not args.decision_id
            or not args.replacement
            or has_proof
        ):
            parser.error(
                "--superseded requires --reason, --decision, and --replacement only"
            )

    invocation_dir = Path.cwd()
    for attribute in ("source_file", "fixtures", "baseline", "adaptive", "corpus"):
        value = getattr(args, attribute, None)
        if value is not None:
            setattr(args, attribute, str((invocation_dir / value).resolve()))
    if args.subcommand not in {"init", "benchmark", "explain"}:
        try:
            os.chdir(find_git_root(invocation_dir))
        except RepositoryNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.subcommand == "explain":
        return controlplane.cmd_explain(args.code)
    if args.subcommand == "init":
        try:
            result = init_current_repository()
        except RepositoryNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(_render(result))
        return 0
    if args.subcommand == "status":
        return controlplane.cmd_status(Path(args.harness_dir).resolve())
    if args.subcommand == "plan" and args.plan_command == "status":
        return controlplane.cmd_plan_status(args.plan_json, args.plan_verbose)
    if args.subcommand == "plan" and args.plan_command == "sync-markdown":
        return controlplane.cmd_plan_sync_markdown(args.target)
    if args.subcommand == "plan" and args.plan_command == "sync-fingerprint":
        return controlplane.cmd_plan_sync_fingerprint()
    if args.subcommand == "plan":
        return controlplane.cmd_plan_mutation(args)
    if args.subcommand == "architecture":
        return controlplane.cmd_architecture(args)
    if args.subcommand == "context":
        return controlplane.cmd_context(
            args.context_command, args.context_mode or "compact", args.context_json,
            trigger=getattr(args, "trigger", None), reason=getattr(args, "reason", None),
            profile_json=args.profile_json, progress=args.progress,
        )
    if args.subcommand == "transition":
        return controlplane.cmd_transition(args.target, reason=args.reason)
    if args.subcommand == "align":
        return controlplane.cmd_align(args.align_command, reason=getattr(args, "reason", None))
    if args.subcommand == "check" and args.check_command == "minimal":
        return controlplane.cmd_check_minimal(Path(args.source_file))
    if args.subcommand == "check" and args.check_command == "admission":
        return controlplane.cmd_check_admission()
    if args.subcommand == "review" and args.review_command == "complexity":
        return controlplane.cmd_review_complexity(Path(args.source_file), args.base)
    if args.subcommand == "review" and args.review_command == "diagnosability":
        return controlplane.cmd_review_diagnosability(Path(args.source_file), args.base)
    if args.subcommand == "review" and args.review_command == "interface":
        return controlplane.cmd_review_interface(Path(args.source_file), args.base)
    if args.subcommand == "review" and args.review_command == "outcome":
        return controlplane.cmd_review_outcome(
            args.outcome, args.reason_code, args.finding
        )
    if args.subcommand == "evidence":
        if args.scope == "full_suite":
            print("FULL_SUITE_FORBIDDEN", file=sys.stderr)
            return 2
        if args.scope != "related":
            print("EVIDENCE_SCOPE_INVALID", file=sys.stderr)
            return 2
        if args.attach:
            return controlplane.cmd_evidence_attach(
                args.type,
                args.evidence_command,
                args.scope,
                Path(args.result_file) if args.result_file else None,
            )
        if legacy_evidence:
            print("DEPRECATED: Use `harness evidence run`.", file=sys.stderr)
        return controlplane.cmd_evidence(
            args.type,
            args.evidence_command,
            args.finding,
            args.test,
            args.scope,
            args.covered_test,
            args.covered_test_case,
            args.phase,
            args.reuse_if_valid,
            args.budget_override_reason,
            args.budget_override_evidence,
            args.budget_override_hypothesis,
        )
    if args.subcommand == "impact":
        if args.impact_action is None:
            parser.print_usage(sys.stderr)
            return 2
        return controlplane.cmd_impact(
            args.impact_action,
            getattr(args, "value", None),
            getattr(args, "reason", None),
            args,
        )
    if args.subcommand == "mr" and args.mr_command == "describe":
        return controlplane.cmd_mr_describe()
    if args.subcommand == "authorize":
        granted = not args.action.startswith("revoke-")
        return controlplane.cmd_authorize(
            args.action.removeprefix("revoke-").replace("-", "_"), granted
        )
    if args.subcommand == "gate":
        return (
            controlplane.cmd_gate_preflight()
            if args.gate_command == "preflight"
            else controlplane.cmd_gate()
        )
    if args.subcommand == "telemetry" and args.telemetry_command == "report":
        return controlplane.cmd_telemetry_report(Path(args.source_file))
    if args.subcommand == "telemetry" and args.telemetry_command == "show":
        return controlplane.cmd_telemetry_show()
    if args.subcommand == "benchmark" and args.benchmark_command == "run":
        return controlplane.cmd_benchmark_run(Path(args.fixtures))
    if args.subcommand == "benchmark" and args.benchmark_command == "alignment":
        return controlplane.cmd_benchmark_alignment(Path(args.records))
    if args.subcommand == "benchmark" and args.benchmark_command == "compare":
        return controlplane.cmd_benchmark_compare(
            Path(args.fixtures), Path(args.baseline), Path(args.adaptive)
        )
    if (
        args.subcommand == "benchmark"
        and args.benchmark_command == "corpus"
        and args.corpus_command == "validate"
    ):
        return controlplane.cmd_benchmark_corpus_validate(Path(args.corpus))
    if (
        args.subcommand == "benchmark"
        and args.benchmark_command == "architecture-corpus"
        and args.architecture_corpus_command == "validate"
    ):
        return controlplane.cmd_architecture_benchmark_corpus_validate(
            Path(args.corpus)
        )
    if (
        args.subcommand == "benchmark"
        and args.benchmark_command == "architecture-compare"
    ):
        return controlplane.cmd_architecture_benchmark_compare(
            Path(args.fixtures),
            Path(args.baseline),
            Path(args.adaptive),
            args.experiment,
        )
    if args.subcommand == "resume":
        return controlplane.cmd_resume()
    if args.subcommand == "decision":
        return controlplane.cmd_decision(args)
    if args.subcommand == "interface":
        return controlplane.cmd_interface(args)
    if args.subcommand == "finding":
        if args.finding_command == "list":
            return controlplane.cmd_finding_list()
        if args.finding_command == "show":
            return controlplane.cmd_finding_show(args.id)
        if args.finding_command == "transition":
            return controlplane.cmd_finding_transition(
                args.id,
                args.target,
                args.evidence,
                args.test,
                args.attempt,
                args.reason,
                args.critical_related_approved,
            )
        if args.finding_command == "refresh-proof":
            return controlplane.cmd_finding_refresh_proof(args.id, args.evidence)
        if args.finding_command == "resume-review":
            return controlplane.cmd_finding_resume_review(args.id)
        parser.print_usage(sys.stderr)
        return 2
    if args.subcommand == "requirement" and args.requirement_command == "verify":
        return controlplane.cmd_requirement_verify(args.id, args.evidence)
    if args.subcommand == "invariant" and args.invariant_command == "verify":
        return controlplane.cmd_invariant_verify(args.id, args.evidence)
    if args.subcommand == "task":
        if args.task_command == "migrate-id":
            return controlplane.cmd_task_migrate_id(args.id)
        if args.task_command == "new":
            return controlplane.cmd_task_new(args.id, args.title)
        if args.task_command == "recover":
            return controlplane.cmd_task_recover(args.id, args.title, args.reason)
        if args.task_command == "prune":
            if args.apply != bool(args.plan_id):
                p_prune.error("--apply and --plan-id are required together")
            return controlplane.cmd_task_prune(args.apply, args.plan_id)
        if args.task_command == "classify":
            return controlplane.cmd_task_classify(
                args.level,
                {
                    name: getattr(args, name)
                    for name in (
                        "scope",
                        "contract",
                        "data",
                        "authorization",
                        "security",
                        "concurrency",
                        "deployment",
                    )
                },
            )
        if args.task_command == "escalate":
            return controlplane.cmd_task_escalate(args.level, args.reason)
        if args.task_command == "verify-existing":
            return controlplane.cmd_task_verify_existing(
                args.reference,
                args.reason,
                args.conclusion,
                args.accept_diff,
                args.untraceable_reason,
            )
        return 2
    if args.subcommand == "converge":
        return controlplane.cmd_converge()
    parser.print_usage(sys.stderr)
    return 2


def main(argv=None) -> int:
    """Run CLI without leaking its repository-root CWD into caller process."""
    original_dir = Path.cwd()
    try:
        return _main(argv)
    except _CandidateUsageError:
        from harness.candidate_commit import command_result
        arguments = list(sys.argv[1:] if argv is None else argv)
        return _emit_candidate_result(command_result(None, _candidate_command_name(arguments),
                                                     reason='CANDIDATE_UNSUPPORTED'), 2)
    finally:
        os.chdir(original_dir)


if __name__ == "__main__":
    sys.exit(main())
