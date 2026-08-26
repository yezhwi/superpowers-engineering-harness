"""harness CLI (guide section 20): parse args -> init service -> render ->
exit code. No init logic here.

Exit codes:
  0 = SUCCESS
  1 = OPERATION_FAILED (e.g. outside a git repository)
  2 = INVALID_USAGE
"""

import argparse
import sys

from pathlib import Path
from harness import controlplane
from harness.init import InitResult, init_current_repository
from harness.repository import RepositoryNotFoundError


def _render(result: InitResult) -> str:
    lines = [f"Harness initialized at {result.harness_dir}"]
    if result.created:
        lines.append("Created:")
        lines.extend(f"  created  {p.name}" for p in result.created)
    if result.skipped:
        lines.append("Skipped (already present, untouched):")
        lines.extend(f"  skipped  {p.name}" for p in result.skipped)
    return "\n".join(lines)


def main(argv=None) -> int:
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
    p_ev = sub.add_parser(
        "evidence", help="run a command and save HEAD-bound evidence")
    p_ev.add_argument("--type", required=True)
    p_ev.add_argument("--scope", choices=["related","full_suite"], default="related")
    p_ev.add_argument("--command", required=True,
                      dest="evidence_command")
    p_ev.add_argument("--finding")
    p_ev.add_argument("--test")
    p_ev.add_argument("--covered-test", action="append", default=[])
    p_ev.add_argument("--phase", choices=["red", "green", "full"])
    p_imp=sub.add_parser("impact"); ims=p_imp.add_subparsers(dest="impact_action"); ims.add_parser("show"); ic=ims.add_parser("add-change"); ic.add_argument("value"); it=ims.add_parser("add-test"); it.add_argument("value"); idp=ims.add_parser("add-dependent"); idp.add_argument("value"); ict=ims.add_parser("add-contract"); ict.add_argument("value"); irk=ims.add_parser("add-risk"); irk.add_argument("value"); ir=ims.add_parser("require-full-suite"); ir.add_argument("--reason",required=True)
    p_auth=sub.add_parser("authorize"); p_auth.add_argument("action",choices=["full-suite","revoke-full-suite"])
    sub.add_parser("gate", help="run the deterministic quality gate")
    p_finding = sub.add_parser("finding", help="inspect findings")
    f_sub = p_finding.add_subparsers(dest="finding_command")
    f_sub.add_parser("list", help="list all findings")
    p_show = f_sub.add_parser("show", help="show one finding record")
    p_show.add_argument("id")
    p_ft=f_sub.add_parser("transition"); p_ft.add_argument("id"); p_ft.add_argument("target"); p_ft.add_argument("--evidence"); p_ft.add_argument("--test"); p_ft.add_argument("--attempt"); p_ft.add_argument("--reason"); p_ft.add_argument("--critical-related-approved", action="store_true")
    p_req=sub.add_parser("requirement"); rs=p_req.add_subparsers(dest="requirement_command"); rv=rs.add_parser("verify"); rv.add_argument("id"); rv.add_argument("--evidence",required=True)
    p_inv=sub.add_parser("invariant"); ivs=p_inv.add_subparsers(dest="invariant_command"); iv=ivs.add_parser("verify"); iv.add_argument("id"); iv.add_argument("--evidence",required=True)
    p_task=sub.add_parser("task"); ts=p_task.add_subparsers(dest="task_command"); p_mid=ts.add_parser("migrate-id"); p_mid.add_argument("id")
    p_new=ts.add_parser("new"); p_new.add_argument("id"); p_new.add_argument("--title",default="")
    p_recover=ts.add_parser("recover"); p_recover.add_argument("id"); p_recover.add_argument("--title",default=""); p_recover.add_argument("--reason",required=True)
    sub.add_parser("converge", help="deterministic convergence decision")

    args = parser.parse_args(argv)

    if args.subcommand == "init":
        try:
            result = init_current_repository()
        except RepositoryNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(_render(result))
        return 0
    if args.subcommand == "status":
        return controlplane.cmd_status()
    if args.subcommand == "transition":
        return controlplane.cmd_transition(args.target)
    if args.subcommand == "check" and args.check_command == "minimal":
        return controlplane.cmd_check_minimal(Path(args.source_file))
    if args.subcommand == "review" and args.review_command == "complexity":
        return controlplane.cmd_review_complexity(Path(args.source_file))
    if args.subcommand == "evidence":
        
        if args.scope == "full_suite" and not controlplane.load_task(Path(".harness")).get("authorization",{}).get("full_suite",{}).get("granted"):
            print("FULL_SUITE_AUTHORIZATION_REQUIRED", file=sys.stderr); return 2
        return controlplane.cmd_evidence(args.type, args.evidence_command,
                                         args.finding, args.test, args.scope,
                                         args.covered_test, args.phase)
    if args.subcommand == "impact": return controlplane.cmd_impact(args.impact_action,getattr(args,"value",None),getattr(args,"reason",None))
    if args.subcommand == "authorize": return controlplane.cmd_authorize_full_suite(args.action == "full-suite")
    if args.subcommand == "gate":
        return controlplane.cmd_gate()
    if args.subcommand == "finding":
        if args.finding_command == "list":
            return controlplane.cmd_finding_list()
        if args.finding_command == "show":
            return controlplane.cmd_finding_show(args.id)
        if args.finding_command == "transition":
            return controlplane.cmd_finding_transition(args.id,args.target,args.evidence,args.test,args.attempt,args.reason,args.critical_related_approved)
        parser.print_usage(sys.stderr)
        return 2
    if args.subcommand == "requirement" and args.requirement_command == "verify": return controlplane.cmd_requirement_verify(args.id,args.evidence)
    if args.subcommand == "invariant" and args.invariant_command == "verify": return controlplane.cmd_invariant_verify(args.id,args.evidence)
    if args.subcommand == "task":
        if args.task_command == "migrate-id": return controlplane.cmd_task_migrate_id(args.id)
        if args.task_command == "new": return controlplane.cmd_task_new(args.id,args.title)
        if args.task_command == "recover": return controlplane.cmd_task_recover(args.id,args.title,args.reason)
        return 2
    if args.subcommand == "converge":
        return controlplane.cmd_converge()

    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
