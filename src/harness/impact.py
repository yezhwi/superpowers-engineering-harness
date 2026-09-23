"""Canonical typed impact-contract normalization shared by control-plane consumers."""


class ImpactContractError(ValueError):
    """Stable malformed impact-contract signal."""


def typed_contracts(impact: dict) -> list[dict[str, str]]:
    """Normalize legacy strings to generic; never infer kind from text."""
    values = impact.get("contracts", [])
    if not isinstance(values, list):
        raise ImpactContractError("IMPACT_CONTRACT_KIND_INVALID")
    result = []
    for item in values:
        if isinstance(item, str):
            if not item:
                raise ImpactContractError("IMPACT_CONTRACT_KIND_INVALID")
            result.append({"ref": item, "kind": "generic"})
            continue
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("ref"), str)
            or not item["ref"]
            or item.get("kind") not in {"generic", "permission", "persistence"}
        ):
            raise ImpactContractError("IMPACT_CONTRACT_KIND_INVALID")
        result.append({"ref": item["ref"], "kind": item["kind"]})
    return result


def contract_paths(impact: dict) -> list[str]:
    """Return only legacy-compatible generic refs for filesystem consumers."""
    return [item["ref"] for item in typed_contracts(impact) if item["kind"] == "generic"]
