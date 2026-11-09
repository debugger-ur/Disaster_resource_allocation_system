"""Shared constants, validation and small helpers for DRRAS.

The web application deliberately uses only the Python standard library.
All user input is validated here, before it reaches the database.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from http import HTTPStatus

DISASTER_TYPES = ("FLOOD", "EARTHQUAKE", "FIRE", "LANDSLIDE", "INDUSTRIAL_ACCIDENT", "OTHER")
DISASTER_LABELS = {
    "FLOOD": "Flood",
    "EARTHQUAKE": "Earthquake",
    "FIRE": "Fire",
    "LANDSLIDE": "Landslide",
    "INDUSTRIAL_ACCIDENT": "Industrial accident",
    "OTHER": "Other",
}
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

# The resource list is intentionally simple enough to explain in a viva.
RESOURCES = ("Food", "Water", "Medicine", "RescueTeam", "MedicalTeam", "Shelter", "Other")
RESOURCE_LABELS = {
    "Food": "Food packets",
    "Water": "Drinking water",
    "Medicine": "Medicines",
    "RescueTeam": "Rescue team",
    "MedicalTeam": "Medical team",
    "Shelter": "Shelter kits",
    "Other": "Other supplies",
}

STATUSES = ("pending", "approved", "rejected", "assigned", "in_progress", "resolved")
STATUS_LABELS = {
    "pending": "Pending review",
    "approved": "Approved",
    "rejected": "Rejected",
    "assigned": "Resources assigned",
    "in_progress": "Response in progress",
    "resolved": "Resolved",
}
QUEUES = ("auto_approval", "manual_review", "duplicate_review", "high_risk")
QUEUE_LABELS = {
    "auto_approval": "Auto-approved",
    "manual_review": "Manual review",
    "duplicate_review": "Possible duplicate",
    "high_risk": "High risk",
}

CENTRE_CATEGORIES = (
    "hospital",
    "relief_camp",
    "food_water",
    "rescue_team",
    "warehouse",
    "shelter",
    "medical_camp",
    "other",
)
CENTRE_LABELS = {
    "hospital": "Hospital",
    "relief_camp": "Relief camp",
    "food_water": "Food & water point",
    "rescue_team": "Rescue base",
    "warehouse": "Warehouse",
    "shelter": "Shelter",
    "medical_camp": "Medical camp",
    "other": "Other centre",
}
AVAILABILITY = ("available", "limited", "full", "closed")
ALLOCATION_STATUSES = ("assigned", "dispatched", "delivered", "cancelled")

DEFAULT_SETTINGS = {
    "autoApproveEnabled": False,
    "autoApproveMaxRisk": 20,
    "autoApproveSeverities": ["LOW", "MEDIUM"],
    "autoApproveMinDescription": 40,
    "autoApproveRequireContact": True,
    "duplicateWindowHours": 72,
    "duplicateThreshold": 55,
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()-]{8,18}$")


class ApiError(Exception):
    """An expected error that can be returned to the browser as JSON."""

    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status = int(status)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: object) -> datetime | None:
    try:
        text = str(value or "").replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def json_dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def json_loads(value: object, fallback: object):
    try:
        return json.loads(str(value)) if value else fallback
    except (TypeError, ValueError):
        return fallback


def clean_text(value: object, maximum: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:maximum]


def normalise_email(value: object) -> str:
    return str(value or "").strip().lower()


def valid_email(value: object) -> bool:
    return bool(EMAIL_RE.match(normalise_email(value)))


def valid_phone(value: object) -> bool:
    return bool(PHONE_RE.match(str(value or "").strip()))


def _integer(value: object, label: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ApiError(f"{label} must be a whole number.") from None
    if not low <= number <= high:
        raise ApiError(f"{label} must be between {low} and {high}.")
    return number


def _coordinate(value: object, label: str, limit: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError(f"{label} is missing or invalid.") from None
    if not -limit <= number <= limit:
        raise ApiError(f"{label} is out of range.")
    return round(number, 6)


def validate_submission(payload: object) -> dict:
    """Validate a disaster report and return clean values for the database."""
    if not isinstance(payload, dict):
        raise ApiError("Expected a JSON object.")

    disaster_type = str(payload.get("disasterType") or "").upper()
    if disaster_type not in DISASTER_TYPES:
        raise ApiError("Choose a valid disaster type.")

    severity = str(payload.get("severity") or "MEDIUM").upper()
    if severity not in SEVERITIES:
        raise ApiError("Choose a valid severity level.")

    description = clean_text(payload.get("description"), 2000)
    if len(description) < 10:
        raise ApiError("Please describe what happened in at least 10 characters.")

    location = clean_text(payload.get("locationName"), 200)
    if len(location) < 2:
        raise ApiError("A location name is required.")

    resources = payload.get("resources")
    if not isinstance(resources, dict):
        raise ApiError("Choose at least one resource.")
    clean_resources = {}
    for key, value in resources.items():
        if key not in RESOURCES:
            raise ApiError(f"Unknown resource: {key}")
        try:
            amount = int(float(value or 0))
        except (TypeError, ValueError):
            raise ApiError("Resource quantities must be whole numbers.") from None
        if amount < 0 or amount > 100000:
            raise ApiError("Resource quantities must be between 1 and 100000.")
        if amount > 0:
            clean_resources[key] = amount
    if not clean_resources:
        raise ApiError("Request at least one resource with a quantity.")

    phone = clean_text(payload.get("contactPhone"), 30)
    email = normalise_email(payload.get("contactEmail"))
    if phone and not valid_phone(phone):
        raise ApiError("That phone number does not look valid.")
    if email and not valid_email(email):
        raise ApiError("That email address does not look valid.")

    evidence = payload.get("evidence") or []
    if not isinstance(evidence, list) or len(evidence) > 3:
        raise ApiError("You can attach at most three files.")
    evidence = [str(item) for item in evidence if str(item).strip()][:3]

    return {
        "type": disaster_type,
        "severity": severity,
        "people": _integer(payload.get("affectedPeople", 1), "People affected", 1, 100000),
        "description": description,
        "location_name": location,
        "latitude": _coordinate(payload.get("latitude"), "Latitude", 90),
        "longitude": _coordinate(payload.get("longitude"), "Longitude", 180),
        "contact_name": clean_text(payload.get("contactName"), 120),
        "contact_phone": phone,
        "contact_email": email,
        "resources": clean_resources,
        "evidence": evidence,
    }



def validate_stock(value: object) -> dict:
    if not isinstance(value, dict):
        raise ApiError("Stock must be an object of resource quantities.")
    stock = {}
    for key, amount in value.items():
        if key not in RESOURCES:
            raise ApiError(f"Unknown resource: {key}")
        try:
            number = int(float(amount or 0))
        except (TypeError, ValueError):
            raise ApiError("Stock quantities must be whole numbers.") from None
        if number < 0 or number > 1000000:
            raise ApiError("Stock quantities must be between 0 and 1000000.")
        stock[key] = number
    return stock


def validate_centre(payload: object, partial: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise ApiError("Expected a JSON object.")
    data = {}
    if not partial or "name" in payload:
        name = clean_text(payload.get("name"), 120)
        if len(name) < 3:
            raise ApiError("Centre name is required.")
        data["name"] = name
    if not partial or "category" in payload:
        category = str(payload.get("category") or "")
        if category not in CENTRE_CATEGORIES:
            raise ApiError("Choose a valid centre category.")
        data["category"] = category
    if not partial or "latitude" in payload:
        data["latitude"] = _coordinate(payload.get("latitude"), "Latitude", 90)
    if not partial or "longitude" in payload:
        data["longitude"] = _coordinate(payload.get("longitude"), "Longitude", 180)
    if not partial or "address" in payload:
        data["address"] = clean_text(payload.get("address"), 200)
    if not partial or "phone" in payload:
        data["phone"] = clean_text(payload.get("phone"), 30)
    if not partial or "availability" in payload:
        availability = str(payload.get("availability") or "available")
        if availability not in AVAILABILITY:
            raise ApiError("Choose a valid availability status.")
        data["availability"] = availability
    if not partial or "notes" in payload:
        data["notes"] = clean_text(payload.get("notes"), 300)
    if "stock" in payload:
        data["stock"] = validate_stock(payload.get("stock"))
    if not partial and "stock" not in data:
        data["stock"] = {}
    return data


def validate_settings(payload: object, current: dict) -> dict:
    if not isinstance(payload, dict):
        raise ApiError("Expected a JSON object.")
    settings = dict(current)
    if "autoApproveEnabled" in payload:
        settings["autoApproveEnabled"] = bool(payload["autoApproveEnabled"])
    if "autoApproveRequireContact" in payload:
        settings["autoApproveRequireContact"] = bool(payload["autoApproveRequireContact"])
    if "autoApproveMaxRisk" in payload:
        settings["autoApproveMaxRisk"] = _integer(payload["autoApproveMaxRisk"], "Risk limit", 0, 100)
    if "autoApproveMinDescription" in payload:
        settings["autoApproveMinDescription"] = _integer(
            payload["autoApproveMinDescription"], "Description length", 10, 500
        )
    if "autoApproveSeverities" in payload:
        values = payload["autoApproveSeverities"]
        if not isinstance(values, list) or any(item not in SEVERITIES for item in values):
            raise ApiError("Choose valid auto-approval severities.")
        settings["autoApproveSeverities"] = values
    if "duplicateWindowHours" in payload:
        settings["duplicateWindowHours"] = _integer(payload["duplicateWindowHours"], "Duplicate window", 1, 720)
    if "duplicateThreshold" in payload:
        settings["duplicateThreshold"] = _integer(payload["duplicateThreshold"], "Duplicate threshold", 20, 100)
    return settings
