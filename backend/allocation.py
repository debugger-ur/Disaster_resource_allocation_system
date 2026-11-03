"""Nearest-centre recommendation for an approved relief request.

The score is deliberately easy to explain: stock coverage, road distance,
travel time and the centre's availability. Urgency changes the weights, so a
critical request cares more about proximity while a low-severity request cares
more about full stock coverage.
"""

from __future__ import annotations

WEIGHTS = {
    "CRITICAL": {"coverage": 40, "proximity": 45, "availability": 15},
    "HIGH": {"coverage": 48, "proximity": 37, "availability": 15},
    "MEDIUM": {"coverage": 55, "proximity": 30, "availability": 15},
    "LOW": {"coverage": 60, "proximity": 25, "availability": 15},
}
AVAILABILITY_SCORE = {"available": 1.0, "limited": 0.6, "full": 0.2, "closed": 0.0}
DISTANCE_HORIZON_KM = 45.0
TIME_HORIZON_MIN = 90.0


def requested_resources(request: dict) -> dict[str, int]:
    resources = request.get("resources") or {}
    if isinstance(resources, dict):
        return {str(name): int(amount) for name, amount in resources.items() if int(amount) > 0}
    return {}


def _coverage(stock: dict, requested: dict) -> tuple[float, dict, list]:
    supplied, missing = {}, []
    requested_total = sum(requested.values())
    covered_total = 0
    for name, amount in requested.items():
        available = int(stock.get(name, 0) or 0)
        take = min(amount, available)
        if take:
            supplied[name] = take
            covered_total += take
        if take < amount:
            missing.append(name)
    return (covered_total / requested_total if requested_total else 1.0), supplied, missing


def score_centre(centre: dict, request: dict) -> dict:
    requested = requested_resources(request)
    coverage, supplied, missing = _coverage(centre.get("stock") or {}, requested)
    severity = str(request.get("severity") or "MEDIUM").upper()
    weights = WEIGHTS.get(severity, WEIGHTS["MEDIUM"])

    distance = max(0.0, float(centre.get("distanceKm") or 0))
    duration = centre.get("durationMin")
    distance_score = max(0.0, 1 - distance / DISTANCE_HORIZON_KM)
    time_score = distance_score if duration is None else max(0.0, 1 - float(duration) / TIME_HORIZON_MIN)
    proximity = (distance_score * 0.7) + (time_score * 0.3)
    if centre.get("distanceSource") != "osrm":
        proximity *= 0.97

    availability = AVAILABILITY_SCORE.get(str(centre.get("availability")), 0.5)
    coverage_points = round(coverage * weights["coverage"], 1)
    proximity_points = round(proximity * weights["proximity"], 1)
    availability_points = round(availability * weights["availability"], 1)
    score = round(coverage_points + proximity_points + availability_points, 1)

    warnings = []
    if missing:
        warnings.append("Cannot supply: " + ", ".join(missing))
    if centre.get("availability") == "full":
        warnings.append("Centre is at capacity.")
    if centre.get("distanceSource") != "osrm":
        warnings.append("Distance is estimated because routing is unavailable.")

    return {
        "centreId": centre.get("id"),
        "name": centre.get("name"),
        "category": centre.get("category"),
        "address": centre.get("address"),
        "phone": centre.get("phone"),
        "availability": centre.get("availability"),
        "latitude": centre.get("latitude"),
        "longitude": centre.get("longitude"),
        "distanceKm": round(distance, 2),
        "durationMin": int(duration) if duration is not None else None,
        "distanceSource": centre.get("distanceSource") or "estimate",
        "stock": centre.get("stock") or {},
        "supplied": supplied,
        "missing": missing,
        "coveragePct": round(coverage * 100),
        "score": score,
        "factors": [
            {"label": "Stock coverage", "points": coverage_points,
             "detail": f"Can supply {round(coverage * 100)}% of requested quantities"},
            {"label": "Road proximity", "points": proximity_points,
             "detail": f"{distance:.1f} km"
                       + (f" · {duration} min" if duration is not None else "")},
            {"label": "Availability", "points": availability_points,
             "detail": str(centre.get("availability") or "available").title()},
        ],
        "warnings": warnings,
    }


def rank_centres(centres: list[dict], request: dict, limit: int = 5) -> dict:
    scored = [score_centre(centre, request) for centre in centres]
    scored = [item for item in scored if item["availability"] != "closed" and item["coveragePct"] > 0]
    scored.sort(key=lambda item: item["score"], reverse=True)
    best = scored[0] if scored else None
    return {
        "candidates": scored[:limit],
        "best": best,
        "requested": requested_resources(request),
        "note": (
            "Recommendations combine stock, road distance, travel time and availability. "
            "An administrator confirms the allocation before stock is deducted."
        ),
    }
