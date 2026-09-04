"""Rule-based risk classification for adaptive Harness workflows."""

RISK_LEVELS = ("Q1", "Q2", "Q3")
PROFILES = {"Q1": "FAST", "Q2": "STANDARD", "Q3": "STRICT"}
DIMENSION_VALUES = {
    "scope": {"low", "high"},
    "contract": {"none", "low", "high"},
    "data": {"none", "low", "high"},
    "authorization": {"none", "low", "high"},
    "security": {"none", "low", "high"},
    "concurrency": {"none", "low", "high"},
    "deployment": {"none", "low", "high"},
}


class RiskClassificationError(ValueError):
    """Raised when classification is missing, unsafe, or non-monotonic."""


def required_level(dimensions: dict[str, str]) -> str:
    if set(dimensions) != set(DIMENSION_VALUES):
        raise RiskClassificationError("RISK_DIMENSIONS_INVALID")
    for name, allowed in DIMENSION_VALUES.items():
        if dimensions[name] not in allowed:
            raise RiskClassificationError("RISK_DIMENSIONS_INVALID")
    if any(
        dimensions[name] == "high"
        for name in (
            "data",
            "authorization",
            "security",
            "concurrency",
            "deployment",
        )
    ):
        return "Q3"
    if dimensions["contract"] != "none" or dimensions["scope"] == "high":
        return "Q2"
    return "Q1"


def classify(level: str, dimensions: dict[str, str]) -> str:
    if level not in RISK_LEVELS:
        raise RiskClassificationError("RISK_LEVEL_INVALID")
    if RISK_LEVELS.index(level) < RISK_LEVELS.index(required_level(dimensions)):
        raise RiskClassificationError("RISK_LEVEL_UNDERSPECIFIED")
    return PROFILES[level]


def validate_escalation(current: str, target: str) -> None:
    if current not in RISK_LEVELS or target not in RISK_LEVELS:
        raise RiskClassificationError("RISK_LEVEL_INVALID")
    if RISK_LEVELS.index(target) <= RISK_LEVELS.index(current):
        raise RiskClassificationError("RISK_DOWNGRADE_FORBIDDEN")
