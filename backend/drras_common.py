"""Shared domain vocabulary, time helpers and small pure functions.

Everything in this module is import-safe from both the storage layer and the
HTTP layer, so there is no circular import between them.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from http import HTTPStatus

# ---------------------------------------------------------------------------
# Domain vocabulary
# ---------------------------------------------------------------------------

DISASTER_TYPES = (
    "FLOOD",
    "EARTHQUAKE",
    "FIRE",
    "LANDSLIDE",
    "INDUSTRIAL_ACCIDENT",
    "OTHER",
)
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

RESOURCE_CATEGORIES = ("Ambulance", "RescueTeam", "MedicalTeam", "Equipment", "Supply")
RESOURCE_LABELS = {
    "Ambulance": "Ambulance",
    "RescueTeam": "Rescue team",
    "MedicalTeam": "Medical team",
    "Equipment": "Equipment",
    "Supply": "Food & supply kits",
}

# Workflow statuses required by the review pipeline.
WORKFLOW_STATUSES = (
    "submitted",
    "under_verification",
    "possible_duplicate",
    "awaiting_approval",
    "approved",
    "rejected",
    "resources_assigned",
    "in_progress",
    "resolved",
)
WORKFLOW_LABELS = {
    "submitted": "Submitted",
    "under_verification": "Under verification",
    "possible_duplicate": "Possible duplicate",
    "awaiting_approval": "Awaiting approval",
    "approved": "Approved",
    "rejected": "Rejected",
    "resources_assigned": "Resources assigned",
    "in_progress": "In progress",
    "resolved": "Resolved",
}
# Statuses that make a request eligible for resource allocation.
ALLOCATABLE_STATUSES = (
    "approved",
    "resources_assigned",
    "in_progress",
)
OPEN_STATUSES = (
    "submitted",
    "under_verification",
    "possible_duplicate",
    "awaiting_approval",
    "approved",
    "resources_assigned",
    "in_progress",
)
ACTIVE_DISASTER_STATUSES = ("approved", "resources_assigned", "in_progress")

RISK_LEVELS = ("low", "medium", "high")
RISK_LABELS = {"low": "Low risk", "medium": "Medium risk", "high": "High risk"}

VERIFICATION_QUEUES = ("auto_approval", "manual_review", "duplicate_review", "high_risk")
QUEUE_LABELS = {
    "auto_approval": "Auto-approval candidate",
    "manual_review": "Manual review",
    "duplicate_review": "Duplicate review",
    "high_risk": "High-risk verification",
}

HELP_CENTRE_CATEGORIES = (
    "hospital",
    "relief_camp",
    "food_water",
    "rescue_team",
    "warehouse",
    "shelter",
    "medical_camp",
    "other",
)
HELP_CENTRE_LABELS = {
    "hospital": "Hospital",
    "relief_camp": "Relief camp",
    "food_water": "Food & water distribution",
    "rescue_team": "Rescue team",
    "warehouse": "Warehouse",
    "shelter": "Shelter",
    "medical_camp": "Medical camp",
    "other": "Other help centre",
}
CENTRE_AVAILABILITY = ("available", "limited", "full", "closed")
CENTRE_AVAILABILITY_LABELS = {
    "available": "Available",
    "limited": "Limited",
    "full": "At capacity",
    "closed": "Closed",
}

ALLOCATION_STATUSES = ("recommended", "assigned", "dispatched", "delivered", "cancelled")
ALLOCATION_LABELS = {
    "recommended": "Recommended",
    "assigned": "Assigned",
    "dispatched": "Dispatched",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
}

# Supplies physically on hand in the central reserve. Kept for backwards
# compatibility with the original API; distributed stock lives per help centre.
DEFAULT_INVENTORY = {
    "Ambulance": 3,
    "RescueTeam": 18,
    "MedicalTeam": 5,
    "Equipment": 2,
    "Supply": 1500,
}
MAX_RESOURCE_QUANTITY = 1_000_000_000
MESSAGE_MAX_LENGTH = 1000
EVIDENCE_MAX_BYTES = 5 * 1024 * 1024
EVIDENCE_ALLOWED_TYPES = ("image/jpeg", "image/png", "application/pdf")

# Defaults for administrator-configurable verification rules.
DEFAULT_SETTINGS = {
    "autoApproveEnabled": False,
    "autoApproveMaxRisk": 20,
    "autoApproveSeverities": ["LOW", "MEDIUM"],
    "autoApproveMinDescriptionLength": 20,
    "autoApproveRequireContact": True,
    "duplicateBlockAutoApprove": True,
    "duplicateWindowHours": 72,
    "duplicateThreshold": 60,
    "mediumRiskThreshold": 25,
    "highRiskThreshold": 55,
    "submissionRateLimit": 6,
    "submissionRateWindowMinutes": 10,
    "routingProvider": "osrm",
}

# Messages delivered to the user with an admin decision.
DEFAULT_ACCEPT_MESSAGE = (
    "Your relief request has been ACCEPTED (approved) by the command centre. "
    "Relief units are being prepared for dispatch to your location. "
    "Please stay in a safe, accessible area and keep your communication line open."
)
DEFAULT_REJECT_MESSAGE = (
    "Your relief request has been reviewed and REJECTED by the command centre. "
    "This typically happens when the zone is already covered by ongoing operations "
    "or the request was merged with a duplicate. "
    "If you are in immediate danger, please contact local emergency services (112)."
)
DEFAULT_INFO_MESSAGE = (
    "The command centre needs a little more information before this request can be "
    "approved. Please reply with the details requested, or call the control room."
)
DEFAULT_DECISION_MESSAGES = {
    "accepted": DEFAULT_ACCEPT_MESSAGE,
    "approved": DEFAULT_ACCEPT_MESSAGE,
    "rejected": DEFAULT_REJECT_MESSAGE,
    "request_info": DEFAULT_INFO_MESSAGE,
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def labelise(value: str | None) -> str:
    """``RESCUE_TEAM`` -> ``Rescue team`` for display fallbacks."""
    text = str(value or "").replace("_", " ").strip().lower()
    return text[:1].upper() + text[1:] if text else ""


def escape_html(value: str) -> str:
    return html.escape(str(value), quote=False)


def plan_submission_grant(
    requested: dict[str, int], available: dict[str, int], severity: str
) -> tuple[dict[str, int], str | None]:
    """Decides what the user is promised the moment they ask.

    Returns ``(grantedResources, user_message)``. When the ask is beyond the
    supplies on hand ("off the limits") and the situation is CRITICAL, the user
    is granted at least the stock present at that moment and told exactly how
    much that is. Non-critical over-limit asks get no automatic grant — they are
    flagged for the admin, who decides what can be provided.
    """
    if not requested:
        return {}, None
    short = {
        category: (quantity, available.get(category, 0))
        for category, quantity in requested.items()
        if quantity > available.get(category, 0)
    }
    if not short:
        return dict(requested), None
    if severity == "CRITICAL":
        granted = {
            category: min(quantity, available.get(category, 0))
            for category, quantity in requested.items()
        }
        granted = {category: amount for category, amount in granted.items() if amount > 0}
        detail = "; ".join(
            f"{granted.get(category, 0)} of {quantity} {category} (in stock now: {stock})"
            for category, (quantity, stock) in sorted(short.items())
        )
        message = (
            "Critical situation: the supplies you asked for are beyond the limits "
            f"of what is in stock right now. You are guaranteed at least the supplies "
            f"present at this moment: {detail}. In other words, this much only can "
            "be provided at the moment; the rest will be dispatched when supplies "
            "are replenished."
        )
        return granted, message
    detail = "; ".join(
        f"{category}: asked {quantity}, in stock {stock}"
        for category, (quantity, stock) in sorted(short.items())
    )
    message = (
        "The supplies you asked for are beyond the limits of what is in stock "
        f"right now ({detail}). Your request has been flagged for admin review; "
        "an admin will decide what can be provided at the moment."
    )
    return {}, message
