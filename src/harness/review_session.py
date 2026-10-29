"""Managed review metering. An unmetered or over-budget session cannot become PASS."""

from dataclasses import dataclass, field


class ReviewSessionError(ValueError):
    pass


@dataclass
class Session:
    budget_seconds: float
    budget_calls: int
    budget_tokens: int
    required_paths: frozenset
    reviewed_paths: set = field(default_factory=set)
    seconds: float = 0
    calls: int = 0
    tokens: int = 0
    switches: int = 0
    max_switches: int = 1
    metered: bool = False
    historical_obligations: tuple = ()
    increment: tuple = ()


def _check_budget(session):
    if (type(session.budget_calls) is not int or type(session.budget_tokens) is not int
            or session.budget_calls < 1 or session.budget_tokens < 1
            or type(session.budget_seconds) not in {int, float} or session.budget_seconds <= 0
            or type(session.max_switches) is not int or session.max_switches < 0):
        raise ReviewSessionError("REVIEW_BUDGET_INVALID")


def meter(session, *, seconds, calls, tokens):
    _check_budget(session)
    if (type(seconds) not in {int, float} or type(calls) is not int or type(tokens) is not int
            or seconds < 0 or calls < 0 or tokens < 0):
        raise ReviewSessionError("REVIEW_METER_INVALID")
    session.seconds += seconds
    session.calls += calls
    session.tokens += tokens
    session.metered = True


def switch_model(session):
    session.switches += 1


def conclude(session, verdict):
    """Compute the verdict. Shell-launched models are outside this session."""
    _check_budget(session)
    if verdict not in {"PASS", "VERIFICATION_GAP", "DEFECT", "INCOMPLETE"}:
        raise ReviewSessionError("REVIEW_VERDICT_INVALID")
    missing = sorted(set(session.required_paths) - set(session.reviewed_paths))
    over = (session.seconds > session.budget_seconds or session.calls > session.budget_calls
            or session.tokens > session.budget_tokens or session.switches > session.max_switches)
    accepted = (verdict == "PASS" and session.metered and session.calls >= 1
                and not over and not missing)
    result = "PASS" if accepted else ("INCOMPLETE" if verdict == "PASS" else verdict)
    return {
        "verdict": result,
        "accepted_pass": accepted,
        "over_budget": over,
        "unmetered": not session.metered,
        "missing_paths": missing,
        "historical_obligations": list(session.historical_obligations),
        "increment": list(session.increment),
        "enforcement": "managed-session-only",
        "partial_done": False,
    }


def conclude_document(document):
    if not isinstance(document, dict):
        raise ReviewSessionError("REVIEW_SESSION_INVALID")
    try:
        session = Session(
            budget_seconds=document["budget_seconds"],
            budget_calls=document["budget_calls"],
            budget_tokens=document["budget_tokens"],
            required_paths=frozenset(document["required_paths"]),
            reviewed_paths=set(document.get("reviewed_paths", [])),
            switches=document.get("switches", 0),
            max_switches=document.get("max_switches", 1),
            historical_obligations=tuple(document.get("historical_obligations", ())),
            increment=tuple(document.get("increment", ())),
        )
    except (KeyError, TypeError) as exc:
        raise ReviewSessionError("REVIEW_SESSION_INVALID") from exc
    usage = document.get("usage", [])
    if not isinstance(usage, list):
        raise ReviewSessionError("REVIEW_METER_INVALID")
    for event in usage:
        if not isinstance(event, dict):
            raise ReviewSessionError("REVIEW_METER_INVALID")
        meter(session, seconds=event.get("seconds", 0), calls=event.get("calls", 0), tokens=event.get("tokens", 0))
    return conclude(session, document.get("verdict", "INCOMPLETE"))
