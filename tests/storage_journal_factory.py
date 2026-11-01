"""Kernel fixtures: internal plans are not external execution grants."""
import hashlib
import json

from storage_factory import identity

OP = "a" * 32


def action(kind, target, *, source=None, node_identity=None, content=None, sha256=None):
    return {"kind": kind, "source": source, "target": target,
            "identity": node_identity, "content": content, "sha256": sha256}


def plan(repo, actions, *, bound=False):
    import subprocess

    result = {"version": 1, "kind": "storage_plan", "operation": "M1" if bound else "ACTIVATE",
              "operation_id": OP, "workspace_root": str(repo), "workspace_id": "2" * 32,
              "store_id": "1" * 32, "old_generation_id": "3" * 32 if bound else None,
              "candidate_generation_id": None, "task_id": "TASK-001",
              "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
              "scope_digest": "4" * 64, "manifest_digest": "5" * 64,
              "ready": True, "actions": actions}
    result["plan_digest"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def authority(value):
    return {"version": 1, "decision_id": "DEC-001", "plan_digest": value["plan_digest"],
            "grant_digest": "6" * 64, "maintenance_digest": "7" * 64}


def activation_plan(repo):
    private = ".harness-store-prepare-" + OP
    return plan(repo, [action("mkdir", private), action("mkdir", private + "/receipts"),
                       action("move", ".harness-store", source=private)])


def turnover_plan(repo):
    store = repo / ".harness-store"
    slot = store / "retained/roots" / OP
    slot.mkdir(mode=0o700)
    candidate = slot / "candidate"
    candidate.mkdir(mode=0o700)
    (candidate / "fixture.txt").write_text("candidate")
    value = plan(repo, [action("move", f".harness-store/retained/roots/{OP}/previous",
                              source=".harness", node_identity=identity(repo / ".harness")),
                        action("move", ".harness", source=f".harness-store/retained/roots/{OP}/candidate",
                               node_identity=identity(candidate))], bound=True)
    value["operation"] = "TURNOVER"
    value.pop("plan_digest")
    value["plan_digest"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return value
