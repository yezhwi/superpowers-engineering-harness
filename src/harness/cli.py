"""harness CLI (guide section 20): parse args -> init service -> render ->
exit code. No init logic here.

Exit codes:
  0 = SUCCESS
  1 = OPERATION_FAILED (e.g. outside a git repository)
  2 = INVALID_USAGE
"""

import argparse
import os
import sys

from pathlib import Path
from harness import controlplane
from harness.init import InitResult, init_current_repository
from harness.repository import RepositoryNotFoundError, find_git_root


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
    legacy_evidence = bool(argv and argv[0] == "evidence" and (len(argv) == 1 or argv[1] not in {"run", "attach"}))
    if len(argv) > 1 and argv[0] == "evidence" and argv[1] in {"run", "attach"}:
        mode = argv.pop(1)
        if mode == "attach": argv.insert(1, "--attach")
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Engineering Harness deterministic control plane",
    )
    sub = parser.add_subparsers(dest="subcommand")
    sub.add_parser("init", help="initialize .harness/ at the git repo root")
    p_status = sub.add_parser(
        "status", help="render unified persisted-state view")
    p_status.add_argument("--harness-dir", default=".harness")
    p_trans = sub.add_parser(
        "transition", help="validate and persist a state transition")
    p_trans.add_argument("target")
    p_check = sub.add_parser("check", help="run Harness checks")
    check_sub = p_check.add_subparsers(dest="check_command")
    p_minimal = check_sub.add_parser("minimal", help="persist Minimal Implementation Decision")
    p_minimal.add_argument("--file", required=True, dest="source_file")
    p_review = sub.add_parser("review", help="run Harness reviews")
    review_sub = p_review.add_subparsers(dest="review_command")
    p_complexity = review_sub.add_parser("complexity", help="persist complexity review")
    p_complexity.add_argument("--file", required=True, dest="source_file")
    p_complexity.add_argument("--base")
    p_diagnosability = review_sub.add_parser("diagnosability", help="persist diagnosability review")
    p_diagnosability.add_argument("--file", required=True, dest="source_file")
    p_diagnosability.add_argument("--base")
    p_interface_review = review_sub.add_parser("interface", help="persist interface review")
    p_interface_review.add_argument("--file", required=True, dest="source_file")
    p_interface_review.add_argument("--base")
    p_outcome = review_sub.add_parser("outcome", help="persist and route review outcome")
    p_outcome.add_argument("outcome", choices=["PASS", "VERIFICATION_GAP", "DEFECT"])
    p_outcome.add_argument("--reason-code", required=True)
    p_outcome.add_argument("--finding", action="append", default=[])
    p_ev = sub.add_parser(
        "evidence", help="run a command and save HEAD-bound evidence")
    p_ev.add_argument("--type", required=True)
    p_ev.add_argument("--scope", choices=["related","full_suite"], default="related")
    p_ev.add_argument("--command", required=True,
                      dest="evidence_command")
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
    p_imp=sub.add_parser("impact"); ims=p_imp.add_subparsers(dest="impact_action"); ims.add_parser("show"); scope=ims.add_parser("scope"); scope.add_argument("--format", choices=["yaml"], default="yaml"); adopt=ims.add_parser("adopt-path"); adopt.add_argument("value"); ignore=ims.add_parser("ignore-user-path"); ignore.add_argument("value"); ic=ims.add_parser("add-change"); ic.add_argument("value"); it=ims.add_parser("add-test"); it.add_argument("value"); idp=ims.add_parser("add-dependent"); idp.add_argument("value"); ict=ims.add_parser("add-contract"); ict.add_argument("value"); irk=ims.add_parser("add-risk"); irk.add_argument("value"); ir=ims.add_parser("require-full-suite"); ir.add_argument("--reason",required=True)
    iinterface=ims.add_parser("add-interface"); iinterface.add_argument("value"); iinterface.add_argument("--kind", choices=["http", "rpc", "event", "sdk", "plugin", "cli", "service"], required=True); iinterface.add_argument("--visibility", choices=["external"], default="external"); iinterface.add_argument("--consumer", action="append", required=True); iinterface.add_argument("--compatibility", choices=["compatible", "breaking"], required=True); iinterface.add_argument("--contract-id")
    p_mr=sub.add_parser("mr"); mr_sub=p_mr.add_subparsers(dest="mr_command"); mr_sub.add_parser("describe")
    p_auth=sub.add_parser("authorize"); p_auth.add_argument("action", choices=["commit", "full-suite", "push", "create-mr", "ready-mr", "merge", "deploy", "revoke-commit", "revoke-full-suite", "revoke-push", "revoke-create-mr", "revoke-ready-mr", "revoke-merge", "revoke-deploy"])
    p_gate=sub.add_parser("gate", help="run the deterministic quality gate"); gate_sub=p_gate.add_subparsers(dest="gate_command"); gate_sub.add_parser("preflight")
    p_telemetry=sub.add_parser("telemetry"); telemetry_sub=p_telemetry.add_subparsers(dest="telemetry_command"); telemetry_sub.add_parser("show")
    p_benchmark=sub.add_parser("benchmark"); benchmark_sub=p_benchmark.add_subparsers(dest="benchmark_command"); p_benchmark_run=benchmark_sub.add_parser("run"); p_benchmark_run.add_argument("--fixtures", required=True); p_benchmark_compare=benchmark_sub.add_parser("compare"); p_benchmark_compare.add_argument("--fixtures", required=True); p_benchmark_compare.add_argument("--baseline", required=True); p_benchmark_compare.add_argument("--adaptive", required=True); p_corpus=benchmark_sub.add_parser("corpus"); corpus_sub=p_corpus.add_subparsers(dest="corpus_command"); p_corpus_validate=corpus_sub.add_parser("validate"); p_corpus_validate.add_argument("--corpus", required=True)
    sub.add_parser("resume", help="recover BLOCKED task from typed blocker")
    p_decision = sub.add_parser("decision", help="manage persisted user decisions")
    decision_sub = p_decision.add_subparsers(dest="decision_command")
    dp = decision_sub.add_parser("propose")
    dp.add_argument("--topic", required=True); dp.add_argument("--question", required=True)
    dp.add_argument("--context", action="append", required=True); dp.add_argument("--option", action="append", required=True)
    dp.add_argument("--recommend", required=True); dp.add_argument("--reason", action="append", required=True)
    dp.add_argument("--tradeoff", action="append", default=[]); dp.add_argument("--scope", action="append", default=[]); dp.add_argument("--constraint", action="append", default=[])
    da = decision_sub.add_parser("accept"); da.add_argument("id"); da.add_argument("--option", required=True); da.add_argument("--source", choices=["accepted_recommendation", "user_override"])
    dr = decision_sub.add_parser("reject"); dr.add_argument("id"); dr.add_argument("--reason", required=True)
    ds = decision_sub.add_parser("supersede"); ds.add_argument("id"); ds.add_argument("--topic", required=True); ds.add_argument("--question", required=True); ds.add_argument("--context", action="append", required=True); ds.add_argument("--option", action="append", required=True); ds.add_argument("--recommend", required=True); ds.add_argument("--reason", action="append", required=True); ds.add_argument("--tradeoff", action="append", default=[]); ds.add_argument("--scope", action="append", default=[]); ds.add_argument("--constraint", action="append", default=[])
    dl = decision_sub.add_parser("list")
    dshow = decision_sub.add_parser("show"); dshow.add_argument("id")
    p_interface = sub.add_parser("interface", help="manage external interface contracts")
    interface_sub = p_interface.add_subparsers(dest="interface_command")
    ideclare = interface_sub.add_parser("declare"); ideclare.add_argument("--name", required=True); ideclare.add_argument("--kind", choices=["http", "rpc", "event", "sdk", "plugin", "cli", "service"], required=True); ideclare.add_argument("--consumer", action="append", required=True); ideclare.add_argument("--input", required=True); ideclare.add_argument("--output", required=True); ideclare.add_argument("--error", required=True); ideclare.add_argument("--compatibility", choices=["compatible", "breaking"], required=True); ideclare.add_argument("--rationale", required=True); ideclare.add_argument("--migration"); ideclare.add_argument("--decision-ref", action="append", default=[])
    iverify = interface_sub.add_parser("verify"); iverify.add_argument("id"); iverify.add_argument("--evidence", required=True)
    iapprove = interface_sub.add_parser("approve-breaking"); iapprove.add_argument("id"); iapprove.add_argument("--reason", required=True)
    interface_sub.add_parser("list"); ishow = interface_sub.add_parser("show"); ishow.add_argument("id")
    p_finding = sub.add_parser("finding", help="inspect findings")
    f_sub = p_finding.add_subparsers(dest="finding_command")
    f_sub.add_parser("list", help="list all findings")
    p_show = f_sub.add_parser("show", help="show one finding record")
    p_show.add_argument("id")
    p_ft=f_sub.add_parser("transition"); p_ft.add_argument("id"); p_ft.add_argument("target"); p_ft.add_argument("--evidence"); p_ft.add_argument("--test"); p_ft.add_argument("--attempt"); p_ft.add_argument("--reason"); p_ft.add_argument("--critical-related-approved", action="store_true")
    p_fr=f_sub.add_parser("resume-review"); p_fr.add_argument("id")
    p_req=sub.add_parser("requirement"); rs=p_req.add_subparsers(dest="requirement_command"); rv=rs.add_parser("verify"); rv.add_argument("id"); rv.add_argument("--evidence",required=True)
    p_inv=sub.add_parser("invariant"); ivs=p_inv.add_subparsers(dest="invariant_command"); iv=ivs.add_parser("verify"); iv.add_argument("id"); iv.add_argument("--evidence",required=True)
    p_task=sub.add_parser("task"); ts=p_task.add_subparsers(dest="task_command"); p_mid=ts.add_parser("migrate-id"); p_mid.add_argument("id")
    p_new=ts.add_parser("new"); p_new.add_argument("id"); p_new.add_argument("--title",default="")
    p_recover=ts.add_parser("recover"); p_recover.add_argument("id"); p_recover.add_argument("--title",default=""); p_recover.add_argument("--reason",required=True)
    p_classify=ts.add_parser("classify"); p_classify.add_argument("--level", choices=["Q1", "Q2", "Q3"], required=True)
    for dimension in ("scope", "contract", "data", "authorization", "security", "concurrency", "deployment"): p_classify.add_argument(f"--{dimension}", required=True)
    p_escalate=ts.add_parser("escalate"); p_escalate.add_argument("--level", choices=["Q2", "Q3"], required=True); p_escalate.add_argument("--reason", required=True)
    sub.add_parser("converge", help="deterministic convergence decision")

    args = parser.parse_args(argv)

    invocation_dir = Path.cwd()
    for attribute in ("source_file", "fixtures", "baseline", "adaptive", "corpus"):
        value = getattr(args, attribute, None)
        if value is not None:
            setattr(args, attribute, str((invocation_dir / value).resolve()))
    if args.subcommand not in {"init", "benchmark"}:
        try:
            os.chdir(find_git_root(invocation_dir))
        except RepositoryNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

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
    if args.subcommand == "transition":
        return controlplane.cmd_transition(args.target)
    if args.subcommand == "check" and args.check_command == "minimal":
        return controlplane.cmd_check_minimal(Path(args.source_file))
    if args.subcommand == "review" and args.review_command == "complexity":
        return controlplane.cmd_review_complexity(Path(args.source_file), args.base)
    if args.subcommand == "review" and args.review_command == "diagnosability":
        return controlplane.cmd_review_diagnosability(Path(args.source_file), args.base)
    if args.subcommand == "review" and args.review_command == "interface":
        return controlplane.cmd_review_interface(Path(args.source_file), args.base)
    if args.subcommand == "review" and args.review_command == "outcome":
        return controlplane.cmd_review_outcome(args.outcome, args.reason_code, args.finding)
    if args.subcommand == "evidence":
        if args.attach:
            return controlplane.cmd_evidence_attach(args.type, args.evidence_command, args.scope, Path(args.result_file) if args.result_file else None)
        if args.scope == "full_suite" and not controlplane.authorization_granted(controlplane.load_task(Path(".harness")), "full_suite"):
            print("FULL_SUITE_AUTHORIZATION_REQUIRED", file=sys.stderr); return 2
        if legacy_evidence: print("DEPRECATED: Use `harness evidence run`.", file=sys.stderr)
        return controlplane.cmd_evidence(args.type, args.evidence_command,
                                         args.finding, args.test, args.scope,
                                         args.covered_test, args.covered_test_case, args.phase,
                                         args.reuse_if_valid,
                                         args.budget_override_reason, args.budget_override_evidence,
                                         args.budget_override_hypothesis)
    if args.subcommand == "impact":
        if args.impact_action is None:
            parser.print_usage(sys.stderr)
            return 2
        return controlplane.cmd_impact(args.impact_action, getattr(args, "value", None), getattr(args, "reason", None), args)
    if args.subcommand == "mr" and args.mr_command == "describe": return controlplane.cmd_mr_describe()
    if args.subcommand == "authorize":
        granted = not args.action.startswith("revoke-")
        return controlplane.cmd_authorize(args.action.removeprefix("revoke-").replace("-", "_"), granted)
    if args.subcommand == "gate":
        return controlplane.cmd_gate_preflight() if args.gate_command == "preflight" else controlplane.cmd_gate()
    if args.subcommand == "telemetry" and args.telemetry_command == "show":
        return controlplane.cmd_telemetry_show()
    if args.subcommand == "benchmark" and args.benchmark_command == "run":
        return controlplane.cmd_benchmark_run(Path(args.fixtures))
    if args.subcommand == "benchmark" and args.benchmark_command == "compare":
        return controlplane.cmd_benchmark_compare(Path(args.fixtures), Path(args.baseline), Path(args.adaptive))
    if args.subcommand == "benchmark" and args.benchmark_command == "corpus" and args.corpus_command == "validate":
        return controlplane.cmd_benchmark_corpus_validate(Path(args.corpus))
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
            return controlplane.cmd_finding_transition(args.id,args.target,args.evidence,args.test,args.attempt,args.reason,args.critical_related_approved)
        if args.finding_command == "resume-review": return controlplane.cmd_finding_resume_review(args.id)
        parser.print_usage(sys.stderr)
        return 2
    if args.subcommand == "requirement" and args.requirement_command == "verify": return controlplane.cmd_requirement_verify(args.id,args.evidence)
    if args.subcommand == "invariant" and args.invariant_command == "verify": return controlplane.cmd_invariant_verify(args.id,args.evidence)
    if args.subcommand == "task":
        if args.task_command == "migrate-id": return controlplane.cmd_task_migrate_id(args.id)
        if args.task_command == "new": return controlplane.cmd_task_new(args.id,args.title)
        if args.task_command == "recover": return controlplane.cmd_task_recover(args.id,args.title,args.reason)
        if args.task_command == "classify": return controlplane.cmd_task_classify(args.level, {name: getattr(args, name) for name in ("scope", "contract", "data", "authorization", "security", "concurrency", "deployment")})
        if args.task_command == "escalate": return controlplane.cmd_task_escalate(args.level, args.reason)
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
    finally:
        os.chdir(original_dir)


if __name__ == "__main__":
    sys.exit(main())
