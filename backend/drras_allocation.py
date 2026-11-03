"""Transparent, explainable resource-allocation recommendations.

The engine compares every help centre on four things an operator cares about:
whether it can cover the request, how far it is, whether it is open, and how
much load it is already carrying (so one centre is not drained while an equally
suitable neighbour sits idle). Every candidate carries the factor breakdown that
produced its score, which is what the admin UI shows before a dispatch.
"""

from __future__ import annotations

SEVERITY_WEIGHTS = {
    # coverage, proximity, availability, fairness
    "CRITICAL": {"coverage": 40, "proximity": 40, "availability": 12, "fairness": 8},
    "HIGH": {"coverage": 45, "proximity": 32, "availability": 13, "fairness": 10},
    "MEDIUM": {"coverage": 48, "proximity": 26, "availability": 14, "fairness": 12},
    "LOW": {"coverage": 50, "proximity": 20, "availability": 15, "fairness": 15},
}
AVAILABILITY_SCORE = {"available": 1.0, "limited": 0.62, "full": 0.2, "closed": 0.0}
# Beyond these horizons the distance/time terms are zero; keeps rural centres comparable.
PROXIMITY_HORIZON_KM = 45.0
TRAVEL_TIME_HORIZON_MIN = 90.0


def _requested_quantities(request: dict) -> dict[str, int]:
    quantities = request.get("resource_quantities") or request.get("resourceQuantities") or {}
    if not isinstance(quantities, dict) or not quantities:
        # Category-only requests get a nominal single unit per category so a
        # centre with that resource still ranks above one without it.
        return {category: 1 for category in request.get("required_resources") or request.get("requiredResources") or []}
    return {str(category): int(amount) for category, amount in quantities.items() if int(amount) > 0}


def _coverage(centre: dict, requested: dict[str, int]) -> tuple[float, dict[str, int], list[str]]:
    stock = centre.get("stock") or {}
    supplied: dict[str, int] = {}
    missing: list[str] = []
    total_weight = 0.0
    covered_weight = 0.0
    for category, quantity in requested.items():
        total_weight += quantity
        available = int(stock.get(category, 0) or 0)
        take = min(quantity, available)
        if take > 0:
            supplied[category] = take
            covered_weight += take
        if take < quantity:
            missing.append(category)
    if total_weight == 0:
        return 1.0, {}, []
    return covered_weight / total_weight, supplied, missing


def score_centre(
    centre: dict,
    request: dict,
    *,
    distance_km: float,
    duration_min: float | None,
    distance_source: str,
    active_load: int = 0,
) -> dict:
    requested = _requested_quantities(request)
    coverage, supplied, missing = _coverage(centre, requested)
    severity = str(request.get("severity") or "MEDIUM").upper()
    weights = SEVERITY_WEIGHTS.get(severity, SEVERITY_WEIGHTS["MEDIUM"])

    availability = AVAILABILITY_SCORE.get(str(centre.get("availability") or "available"), 0.5)
    # Closed centres should not be recommended at all unless nothing else exists.
    if str(centre.get("availability")) == "closed":
        coverage_score = 0.0
    else:
        coverage_score = coverage

    distance_score = max(0.0, 1 - (max(0.0, distance_km) / PROXIMITY_HORIZON_KM))
    # Travel time matters independently of distance: a nearby centre on a broken
    # road can be slower than one slightly further away. If the router returned
    # no duration, fall back to the distance term.
    if duration_min is None:
        time_score = distance_score
    else:
        time_score = max(0.0, 1 - (max(0.0, float(duration_min)) / TRAVEL_TIME_HORIZON_MIN))
    proximity = (distance_score * 0.72) + (time_score * 0.28)
    if distance_source != "osrm":
        # Keep estimates comparable but never let one outrank a better-routed
        # centre by an invisible margin.
        proximity *= 0.97

    stock_total = sum(int(value or 0) for value in (centre.get("stock") or {}).values())
    load_ratio = active_load / (active_load + stock_total) if (active_load + stock_total) else 0.0
    fairness = max(0.0, 1 - load_ratio)

    points = {
        "coverage": round(coverage_score * weights["coverage"], 1),
        "proximity": round(proximity * weights["proximity"], 1),
        "availability": round(availability * weights["availability"], 1),
        "fairness": round(fairness * weights["fairness"], 1),
    }
    score = round(sum(points.values()), 1)

    rationale = [
        {
            "code": "coverage",
            "label": "Stock coverage",
            "detail": (
                f"Can cover {round(coverage * 100)}% of the requested quantities"
                + (f" (short: {', '.join(missing)})" if missing else "")
            ),
            "points": points["coverage"],
        },
        {
            "code": "proximity",
            "label": "Road distance & travel time",
            "detail": (
                f"{distance_km:.1f} km"
                + (f" · {duration_min} min" if duration_min is not None else "")
                + (" (estimated)" if distance_source != "osrm" else " (routed)")
            ),
            "points": points["proximity"],
        },
        {
            "code": "availability",
            "label": "Availability",
            "detail": f"Centre status: {centre.get('availability') or 'available'}",
            "points": points["availability"],
        },
        {
            "code": "fairness",
            "label": "Load balancing",
            "detail": (
                f"{active_load} unit(s) already committed from this centre"
                if active_load
                else "No active commitments from this centre"
            ),
            "points": points["fairness"],
        },
    ]

    warnings = []
    if missing:
        warnings.append(
            "Cannot supply " + ", ".join(missing) + " from this centre alone."
        )
    if str(centre.get("availability")) == "closed":
        warnings.append("This centre is currently closed.")
    elif str(centre.get("availability")) == "full":
        warnings.append("This centre reports that it is at capacity.")
    if distance_source != "osrm":
        warnings.append("Road distance is estimated because the routing service did not answer.")

    return {
        "centreId": centre.get("id"),
        "name": centre.get("name"),
        "category": centre.get("category"),
        "address": centre.get("address"),
        "phone": centre.get("phone"),
        "availability": centre.get("availability"),
        "latitude": centre.get("latitude"),
        "longitude": centre.get("longitude"),
        "distanceKm": round(float(distance_km), 2),
        "durationMin": int(duration_min) if duration_min is not None else None,
        "distanceSource": distance_source,
        "stock": centre.get("stock") or {},
        "supplied": supplied,
        "missing": missing,
        "coveragePct": round(coverage * 100),
        "activeLoad": active_load,
        "score": score,
        "factors": rationale,
        "warnings": warnings,
    }


def recommend(centres: list[dict], request: dict, limit: int = 6) -> dict:
    """Rank centres and propose a multi-centre plan that covers the request."""
    requested = _requested_quantities(request)
    candidates = []
    for centre in centres:
        candidates.append(
            score_centre(
                centre,
                request,
                distance_km=float(centre.get("distanceKm") or 0),
                duration_min=centre.get("durationMin"),
                distance_source=str(centre.get("distanceSource") or "estimate"),
                active_load=int(centre.get("activeLoad") or 0),
            )
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)

    # Greedy plan: best-scoring centre first, then cover the remainder from the
    # next best that still has stock. Never promises more than a centre holds.
    remaining = dict(requested)
    plan = []
    for candidate in candidates:
        if not any(amount > 0 for amount in remaining.values()):
            break
        if candidate["availability"] == "closed":
            continue
        stock = candidate["stock"]
        items = {}
        for category, needed in remaining.items():
            available = int(stock.get(category, 0) or 0)
            take = min(needed, available)
            if take > 0:
                items[category] = take
                remaining[category] = needed - take
        if items:
            plan.append({
                "centreId": candidate["centreId"],
                "name": candidate["name"],
                "category": candidate["category"],
                "distanceKm": candidate["distanceKm"],
                "durationMin": candidate["durationMin"],
                "distanceSource": candidate["distanceSource"],
                "items": items,
                "score": candidate["score"],
            })
    planned_total = sum(sum(item["items"].values()) for item in plan)
    requested_total = sum(requested.values())
    return {
        "candidates": candidates[: max(1, limit)],
        "plan": plan,
        "requested": requested,
        "coveredPct": round(100 * planned_total / requested_total) if requested_total else 100,
        "uncovered": {key: value for key, value in remaining.items() if value > 0},
        "note": (
            "Recommendations use live road distance, current centre stock, availability and "
            "existing commitments. An administrator must confirm before stock is committed."
        ),
    }
