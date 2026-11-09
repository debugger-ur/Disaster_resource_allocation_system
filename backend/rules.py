"""Explainable duplicate detection, risk scoring and auto-approval rules.

Nothing in this module rejects a report. Automation may only approve a report
that meets every safe condition configured by an administrator; everything else
goes to a person for review.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from config import DISASTER_LABELS, DISASTER_TYPES, parse_iso

RELATED_TYPES = {
    frozenset(("FLOOD", "LANDSLIDE")),
    frozenset(("FIRE", "INDUSTRIAL_ACCIDENT")),
    frozenset(("EARTHQUAKE", "LANDSLIDE")),
}
STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "are", "was", "were",
    "have", "has", "had", "our", "there", "here", "please", "need", "needed",
    "needs", "require", "required", "request", "help", "urgent", "urgently",
    "immediately", "very", "also", "some", "many", "people", "area", "village",
    "in", "at", "on", "of", "to", "a", "an", "is", "it", "we", "us", "near",
}
# The seed data and demo use Uttarakhand. Reports outside this box are still
# accepted, but receive a risk flag because the coordinate may be a typo.
OPERATING_BOUNDS = {"minLat": 28.0, "maxLat": 31.8, "minLon": 76.8, "maxLon": 81.2}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _normalise(value: object) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: object) -> set[str]:
    return {word for word in _normalise(value).split() if len(word) > 1 and word not in STOPWORDS}


def description_similarity(left: object, right: object) -> float:
    """Blend word overlap with a character-level ratio (0 to 1)."""
    a, b = _normalise(left), _normalise(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    left_words, right_words = _tokens(a), _tokens(b)
    union = left_words | right_words
    overlap = len(left_words & right_words) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    return round((overlap * 0.7) + (sequence * 0.3), 3)


def _as_resources(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _distance_points(distance_km: float) -> int:
    if distance_km <= 0.25:
        return 30
    if distance_km <= 1:
        return 26
    if distance_km <= 3:
        return 20
    if distance_km <= 8:
        return 12
    if distance_km <= 20:
        return 5
    return 0


def find_duplicates(new_report: dict, recent: list[dict], settings: dict) -> list[dict]:
    """Compare a report with recent reports and return the strongest matches."""
    window = float(settings.get("duplicateWindowHours", 72))
    threshold = int(settings.get("duplicateThreshold", 55))
    now = parse_iso(new_report.get("created_at")) or datetime.now(timezone.utc)
    matches = []

    for row in recent:
        if row.get("id") == new_report.get("id"):
            continue
        try:
            distance = haversine_km(
                float(new_report["latitude"]), float(new_report["longitude"]),
                float(row["latitude"]), float(row["longitude"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if distance > 50:
            continue

        created = parse_iso(row.get("created_at"))
        if created is None:
            continue
        age_hours = max(0.0, (now - created).total_seconds() / 3600)
        if age_hours > window:
            continue
        time_points = round(15 * max(0.0, 1 - age_hours / window))

        same_type = str(row.get("type")) == str(new_report.get("type"))
        related = frozenset((str(row.get("type")), str(new_report.get("type")))) in RELATED_TYPES
        category_points = 25 if same_type else (12 if related else 0)
        similarity = description_similarity(row.get("description"), new_report.get("description"))
        description_points = round(similarity * 30)
        location_points = _distance_points(distance)

        points = {
            "location": location_points,
            "category": category_points,
            "description": description_points,
            "time": time_points,
        }
        score = min(100, sum(points.values()))
        if score < 35:
            continue

        reasons = []
        if location_points:
            reasons.append(f"{distance:.1f} km from an existing report (+{location_points})")
        if category_points:
            label = "same" if same_type else "related"
            reasons.append(f"{label} disaster category (+{category_points})")
        if description_points:
            reasons.append(f"{round(similarity * 100)}% description similarity (+{description_points})")
        if time_points:
            reasons.append(f"reported {age_hours:.1f} hours ago (+{time_points})")

        matches.append({
            "id": row.get("id"),
            "type": row.get("type"),
            "typeLabel": DISASTER_LABELS.get(str(row.get("type")), str(row.get("type"))),
            "locationName": row.get("location_name"),
            "distanceKm": round(distance, 2),
            "score": score,
            "reasons": reasons,
            "isPossibleDuplicate": score >= threshold,
        })

    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:3]


def assess_risk(report: dict, duplicates: list[dict], contact_count: int) -> dict:
    """Return a 0-100 risk score with every contributing reason named."""
    score = 0
    reasons = []

    def add(points: int, text: str) -> None:
        nonlocal score
        score += points
        reasons.append(text)

    if len(str(report.get("description") or "")) < 40:
        add(15, "Very short description")
    if not report.get("contact_phone") and not report.get("contact_email"):
        add(25, "No phone number or email provided")
    if str(report.get("severity")) == "CRITICAL" and int(report.get("people") or 0) <= 2:
        add(15, "Critical severity but very few people reported")
    if contact_count >= 2:
        add(15, f"{contact_count} other reports from the same contact today")
    if not (
        OPERATING_BOUNDS["minLat"] <= float(report["latitude"]) <= OPERATING_BOUNDS["maxLat"]
        and OPERATING_BOUNDS["minLon"] <= float(report["longitude"]) <= OPERATING_BOUNDS["maxLon"]
    ):
        add(20, "Location is outside the usual operating area")
    if duplicates and duplicates[0]["isPossibleDuplicate"]:
        add(25, "Strong similarity to an existing report")
    total_resources = sum(_as_resources(report.get("resources")).values())
    if total_resources > 5000:
        add(10, "Unusually large resource request")

    score = min(100, score)
    level = "high" if score >= 55 else ("medium" if score >= 25 else "low")
    return {"score": score, "level": level, "reasons": reasons}


def auto_approval(report: dict, risk: dict, duplicates: list[dict], settings: dict) -> tuple[bool, str]:
    """Check every administrator-defined condition for safe auto-approval."""
    if not settings.get("autoApproveEnabled"):
        return False, "Auto-approval is turned off."
    if risk["score"] > int(settings.get("autoApproveMaxRisk", 20)):
        return False, "Risk score is above the automatic approval limit."
    if report.get("severity") not in settings.get("autoApproveSeverities", []):
        return False, "Severity is not in the safe list."
    if len(str(report.get("description") or "")) < int(settings.get("autoApproveMinDescription", 40)):
        return False, "Description is shorter than the required length."
    if settings.get("autoApproveRequireContact") and not (
        report.get("contact_phone") or report.get("contact_email")
    ):
        return False, "A contact method is required."
    if any(match.get("isPossibleDuplicate") for match in duplicates):
        return False, "A possible duplicate needs human review."
    if not _as_resources(report.get("resources")):
        return False, "No resources were requested."
    return True, "Every safe auto-approval rule passed."


def available_types() -> list[dict]:
    """Small helper used by the health/meta endpoint."""
    return [{"value": item, "label": DISASTER_LABELS[item]} for item in DISASTER_TYPES]
