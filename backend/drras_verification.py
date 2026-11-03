"""Deterministic duplicate detection and suspicious-request risk scoring.

Both engines are deliberately transparent: every point that contributes to a
duplicate score or a risk score is returned with a short human-readable reason,
so an administrator can see *why* the system flagged a report. Nothing here
rejects a request. The worst outcome is "a person should look at this".
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from drras_common import DEFAULT_SETTINGS, parse_iso

# Places used only for a cheap consistency check between the typed location
# name and the coordinates picked on the map. Approximate district centroids.
PLACE_GAZETTEER = {
    "dehradun": (30.3165, 78.0322),
    "doon": (30.3165, 78.0322),
    "mussoorie": (30.4598, 78.0644),
    "rishikesh": (30.0869, 78.2676),
    "haridwar": (29.9457, 78.1642),
    "roorkee": (29.8543, 77.8880),
    "vikasnagar": (30.4100, 77.7800),
    "doiwala": (30.1900, 78.1210),
    "selaqui": (30.1150, 78.0750),
    "chakrata": (30.7000, 77.8600),
    "tyuni": (30.5600, 77.8400),
    "kalsi": (30.5200, 77.8500),
    "raipur": (30.3050, 78.1000),
    "clement town": (30.2660, 78.0100),
    "rajpur": (30.3500, 78.0700),
    "patel nagar": (30.3000, 78.0200),
    "premnagar": (30.3300, 77.9700),
    "chamoli": (30.4090, 79.3200),
    "uttarkashi": (30.7300, 78.4500),
    "tehri": (30.3800, 78.4800),
    "pauri": (30.1500, 78.7800),
    "srinagar": (30.2200, 78.7900),
    "kotdwar": (29.7470, 78.5220),
    "lansdowne": (29.8400, 78.6800),
    "nainital": (29.3800, 79.4500),
    "haldwani": (29.2200, 79.5200),
    "ramnagar": (29.3900, 79.1200),
    "almora": (29.5900, 79.6600),
    "pithoragarh": (29.5800, 80.2200),
    "champawat": (29.3300, 80.0900),
    "bageshwar": (29.8400, 79.7700),
    "rudrapur": (28.9800, 79.4000),
    "kashipur": (29.2100, 78.9600),
}

# Supported operating area (Uttarakhand + immediate surroundings). Requests
# outside it are not refused - they are surfaced for a human to check, because
# mis-typed coordinates are far more common than malicious far-away reports.
SUPPORTED_BOUNDS = {"min_lat": 28.0, "max_lat": 31.8, "min_lon": 76.8, "max_lon": 81.2}

RELATED_TYPES = {
    ("FLOOD", "LANDSLIDE"),
    ("FIRE", "INDUSTRIAL_ACCIDENT"),
    ("EARTHQUAKE", "LANDSLIDE"),
    ("FLOOD", "EARTHQUAKE"),
}

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "are", "was", "were",
    "have", "has", "had", "our", "their", "there", "here", "please", "need",
    "needed", "needs", "require", "required", "request", "help", "urgent",
    "urgently", "immediately", "very", "also", "some", "many", "people", "area",
    "village", "in", "at", "on", "of", "to", "a", "an", "is", "it", "we", "us",
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalise_text(value: object) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def tokens(value: object) -> set[str]:
    return {word for word in normalise_text(value).split() if word not in STOPWORDS and len(word) > 1}


def description_similarity(left: object, right: object) -> float:
    """Blend token overlap with sequence ratio (0..1)."""
    a, b = normalise_text(left), normalise_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_tokens, b_tokens = tokens(a), tokens(b)
    union = a_tokens | b_tokens
    jaccard = len(a_tokens & b_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    return round(0.6 * jaccard + 0.4 * sequence, 3)


def digits_only(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def contact_matches(left_phone: object, left_email: object, right_phone: object, right_email: object) -> bool:
    left_digits, right_digits = digits_only(left_phone), digits_only(right_phone)
    if left_digits and right_digits and left_digits[-10:] == right_digits[-10:]:
        return True
    left_mail = str(left_email or "").strip().lower()
    right_mail = str(right_email or "").strip().lower()
    return bool(left_mail and right_mail and left_mail == right_mail)


def is_valid_phone(value: object) -> bool:
    digits = digits_only(value)
    if not digits:
        return False
    if len(digits) in (10, 11, 12, 13):
        return True
    return False


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def is_valid_email(value: object) -> bool:
    return bool(EMAIL_RE.match(str(value or "").strip()))


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _related_type(left: str, right: str) -> bool:
    pair = (str(left).upper(), str(right).upper())
    return pair in RELATED_TYPES or pair[::-1] in RELATED_TYPES


def _time_factor(submitted: datetime | None, now: datetime, window_hours: float) -> float:
    if submitted is None or window_hours <= 0:
        return 0.0
    hours = max(0.0, (now - submitted).total_seconds() / 3600)
    if hours > window_hours:
        return 0.0
    return max(0.0, 1 - hours / window_hours)


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


def _resource_overlap(left: object, right: object) -> float:
    a = {str(item) for item in (left or [])}
    b = {str(item) for item in (right or [])}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_duplicates(
    new_request: dict,
    existing: list[dict],
    *,
    window_hours: float = DEFAULT_SETTINGS["duplicateWindowHours"],
    threshold: int = DEFAULT_SETTINGS["duplicateThreshold"],
    max_results: int = 3,
) -> dict:
    """Scores a new report against existing reports.

    ``existing`` rows are plain dicts with snake_case keys as returned by the
    store. The function is pure so it can be unit-tested without a database.
    """
    now = _now()
    submitted_now = parse_iso(new_request.get("submitted_at") or new_request.get("submittedAt")) or now
    lat = float(new_request["latitude"])
    lon = float(new_request["longitude"])
    matches: list[dict] = []

    for row in existing or []:
        if row.get("id") == new_request.get("id"):
            continue
        if row.get("merged_into"):
            continue
        try:
            distance = haversine_km(lat, lon, float(row["latitude"]), float(row["longitude"]))
        except (KeyError, TypeError, ValueError):
            continue
        # A shared description hundreds of kilometres away is a common template,
        # not the same incident. Keep the comparison local.
        if distance > 50:
            continue
        submitted = parse_iso(row.get("submitted_at"))
        time_factor = _time_factor(submitted, submitted_now, window_hours)
        if submitted is not None and time_factor == 0:
            continue

        same_type = str(row.get("type", "")).upper() == str(new_request.get("type", "")).upper()
        related = _related_type(row.get("type", ""), new_request.get("type", ""))
        desc_similarity = description_similarity(
            row.get("description"), new_request.get("description")
        )
        contact_same = contact_matches(
            row.get("contact_phone"), row.get("contact_email"),
            new_request.get("contact_phone"), new_request.get("contact_email"),
        )
        resource_similarity = _resource_overlap(
            _json_list(row.get("required_resources")),
            new_request.get("required_resources"),
        )

        points = {
            "location": _distance_points(distance),
            "category": 16 if same_type else (8 if related else 0),
            "description": round(desc_similarity * 24),
            "time": round(time_factor * 10),
            "contact": 10 if contact_same else 0,
            "resources": round(resource_similarity * 10),
        }
        score = min(100, sum(points.values()))
        if score < 45:
            continue

        factors = []
        if points["location"]:
            factors.append({
                "code": "location",
                "label": "Location proximity",
                "detail": f"{distance:.2f} km from the reported area",
                "points": points["location"],
            })
        if points["category"]:
            factors.append({
                "code": "category",
                "label": "Disaster category",
                "detail": (
                    f"Same category ({row.get('type')})" if same_type
                    else f"Related categories ({row.get('type')} / {new_request.get('type')})"
                ),
                "points": points["category"],
            })
        if points["description"]:
            factors.append({
                "code": "description",
                "label": "Description similarity",
                "detail": f"{round(desc_similarity * 100)}% similar wording",
                "points": points["description"],
            })
        if points["time"]:
            factors.append({
                "code": "time",
                "label": "Submission time",
                "detail": f"Submitted {_human_age(submitted, submitted_now)}",
                "points": points["time"],
            })
        if points["contact"]:
            factors.append({
                "code": "contact",
                "label": "Contact details",
                "detail": "Same phone number or email as the existing report",
                "points": points["contact"],
            })
        if points["resources"]:
            factors.append({
                "code": "resources",
                "label": "Resources requested",
                "detail": f"{round(resource_similarity * 100)}% overlap in requested resources",
                "points": points["resources"],
            })

        matches.append({
            "id": row.get("id"),
            "locationName": row.get("location_name"),
            "type": row.get("type"),
            "severity": row.get("severity"),
            "submittedAt": row.get("submitted_at"),
            "status": row.get("workflow_status"),
            "distanceKm": round(distance, 2),
            "similarity": score,
            "descriptionSimilarity": round(desc_similarity * 100),
            "contactMatch": contact_same,
            "factors": factors,
        })

    matches.sort(key=lambda item: item["similarity"], reverse=True)
    matches = matches[:max_results]
    max_score = matches[0]["similarity"] if matches else 0
    is_duplicate = max_score >= threshold
    if not matches:
        summary = "No similar report found in the recent window."
    elif is_duplicate:
        summary = (
            f"{matches[0]['id']} at {matches[0]['locationName']} looks like the same "
            f"incident ({max_score}% match, {matches[0]['distanceKm']} km away)."
        )
    elif max_score >= 45:
        summary = (
            f"{matches[0]['id']} at {matches[0]['locationName']} is similar "
            f"({max_score}% match) but below the duplicate threshold of {threshold}%."
        )
    else:
        summary = f"{len(matches)} loosely similar report(s) found; none above the duplicate threshold."

    return {
        "matches": matches,
        "maxScore": max_score,
        "threshold": threshold,
        "isPossibleDuplicate": is_duplicate,
        "summary": summary,
        "windowHours": window_hours,
    }


def _json_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _human_age(submitted: datetime | None, now: datetime) -> str:
    if submitted is None:
        return "at an unknown time"
    minutes = int(max(0, (now - submitted).total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h ago"
    return f"{hours // 24} d ago"


def _place_mismatch(location_name: str, latitude: float, longitude: float) -> tuple[str, float] | None:
    """Returns the gazetteer place and distance when the typed name disagrees
    with the coordinates by a suspicious margin."""
    name = _norm(location_name)
    best = None
    for place, (plat, plon) in PLACE_GAZETTEER.items():
        if place in name:
            distance = haversine_km(latitude, longitude, plat, plon)
            if best is None or distance < best[1]:
                best = (place, distance)
    if best and best[1] > 30:
        return best
    return None


def assess_risk(
    new_request: dict,
    *,
    duplicates: dict | None = None,
    recent_submissions: list[dict] | None = None,
    reused_evidence: list[dict] | None = None,
    settings: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Scores a request from 0 (nothing unusual) to 100 (needs a human now).

    ``recent_submissions`` contains dicts with ``phone``, ``email``, ``ip`` and
    ``submitted_at`` for the last few hours (including this submission).
    ``reused_evidence`` contains rows ``{"request_id", "id"}`` for evidence
    hashes already uploaded on a different request.
    """
    cfg = {**DEFAULT_SETTINGS, **(settings or {})}
    now = now or _now()
    reasons: list[dict] = []
    checks: list[dict] = []

    def add(code: str, label: str, detail: str, points: int, severity: str = "warning") -> None:
        reasons.append({"code": code, "label": label, "detail": detail, "points": points})
        checks.append({"code": code, "label": label, "detail": detail, "status": severity, "points": points})

    def ok(code: str, label: str, detail: str = "Looks valid") -> None:
        checks.append({"code": code, "label": label, "detail": detail, "status": "ok", "points": 0})

    description = str(new_request.get("description") or "").strip()
    phone = str(new_request.get("contact_phone") or "").strip()
    email = str(new_request.get("contact_email") or "").strip()
    latitude = float(new_request.get("latitude", 0))
    longitude = float(new_request.get("longitude", 0))
    severity = str(new_request.get("severity") or "").upper()
    affected = int(new_request.get("affected_people") or 0)

    # --- information completeness -----------------------------------------
    if len(description) < 20:
        add(
            "missing_description",
            "Description is thin",
            "Fewer than 20 characters describing what happened. Field teams cannot verify the situation from this alone.",
            12,
        )
    else:
        ok("description", "Description provided", f"{len(description)} characters of detail")

    if not new_request.get("required_resources"):
        checks.append({
            "code": "resources",
            "label": "Resources listed",
            "detail": "No specific resource was requested - the assessor will decide from the description.",
            "status": "info",
            "points": 0,
        })
    else:
        ok("resources", "Resources listed", ", ".join(str(item) for item in new_request["required_resources"]))

    # --- contact validity ---------------------------------------------------
    if not phone and not email:
        add("missing_contact", "No contact details", "Neither a phone number nor an email was supplied, so the report cannot be verified by call-back.", 14)
    elif phone and not is_valid_phone(phone):
        add("invalid_phone", "Invalid phone number", f"'{phone}' is not a usable phone number (10-13 digits expected).", 18)
    elif email and not is_valid_email(email):
        add("invalid_email", "Invalid email address", f"'{email}' does not look like a valid email address.", 15)
    else:
        ok("contact", "Contact details valid", "A call-back is possible for verification")

    # --- location consistency ----------------------------------------------
    if abs(latitude) < 0.0001 and abs(longitude) < 0.0001:
        add("null_island", "Coordinates missing", "Latitude and longitude are both zero - the map cannot place this report.", 25)
    else:
        bounds = SUPPORTED_BOUNDS
        outside = not (
            bounds["min_lat"] <= latitude <= bounds["max_lat"]
            and bounds["min_lon"] <= longitude <= bounds["max_lon"]
        )
        mismatch = _place_mismatch(str(new_request.get("location_name") or ""), latitude, longitude)
        if mismatch:
            place, distance = mismatch
            add(
                "location_mismatch",
                "Location name and pin disagree",
                f"The pin is {distance:.0f} km away from {place.title()}, which the location name mentions.",
                20,
            )
        elif outside:
            add(
                "outside_region",
                "Unusual coordinates",
                "The pin falls outside the supported Uttarakhand operating area. Check it against the typed location.",
                12,
            )
        else:
            ok("location", "Location consistent", f"{latitude:.4f}, {longitude:.4f}")

    # --- conflicting details ------------------------------------------------
    if severity == "CRITICAL" and affected <= 1:
        add("conflicting_details", "Conflicting details", "Marked CRITICAL but fewer than two people are reported affected.", 10)
    if severity in ("CRITICAL", "HIGH") and not new_request.get("required_resources"):
        add(
            "no_resource_for_high_severity",
            "No resources requested",
            "A high-severity report lists no required resources, so the response cannot be planned yet.",
            6,
        )

    # --- repeated submissions ----------------------------------------------
    recent = recent_submissions or []
    phone_digits = digits_only(phone)
    same_contact = [
        row for row in recent
        if (
            (phone_digits and digits_only(row.get("phone"))[-10:] == phone_digits[-10:])
            or (email and _norm(row.get("email")) == _norm(email))
        )
    ]
    if len(same_contact) >= 3:
        points = 22 if len(same_contact) < 5 else 30
        add(
            "repeated_submissions",
            "Repeated submissions",
            f"{len(same_contact)} reports from this contact in the last few hours.",
            points,
        )
    elif len(same_contact) == 2:
        checks.append({
            "code": "repeated_submissions",
            "label": "Repeated submissions",
            "detail": "This contact has one other recent report - common for follow-up information.",
            "status": "info",
            "points": 0,
        })
    else:
        ok("repeated_submissions", "No repeated submissions", "First recent report from this contact")

    ip = str(new_request.get("client_ip") or "")
    same_ip = [row for row in recent if ip and row.get("ip") == ip]
    if len(same_ip) >= 5:
        add(
            "ip_burst",
            "Submission burst from one device",
            f"{len(same_ip)} reports from the same network address in the last hour.",
            20,
        )

    # Different locations for one contact in a short window is a classic
    # template/copy-paste signal, but also happens when a volunteer reports
    # several affected sites. Points are modest and go to a human.
    if same_contact:
        far_places = 0
        seen = set()
        for row in same_contact:
            try:
                if haversine_km(latitude, longitude, float(row["latitude"]), float(row["longitude"])) > 20:
                    label = _norm(row.get("location_name"))
                    if label and label not in seen:
                        seen.add(label)
                        far_places += 1
            except (KeyError, TypeError, ValueError):
                continue
        if far_places >= 2:
            add(
                "inconsistent_locations",
                "Inconsistent locations",
                f"The same contact reported {far_places + 1} far-apart locations within the window.",
                15,
            )

    # --- evidence reuse -----------------------------------------------------
    if reused_evidence:
        reuse = reused_evidence[0]
        add(
            "reused_evidence",
            "Photo already submitted",
            f"An uploaded file is byte-identical to evidence on {reuse.get('request_id')}. "
            "Confirm it shows this incident rather than a previous one.",
            25,
        )
    elif new_request.get("evidence"):
        ok("evidence", "Evidence attached", f"{len(new_request['evidence'])} supporting file(s)")
    else:
        checks.append({
            "code": "evidence",
            "label": "Evidence",
            "detail": "No photographs or documents attached. Not required, but it helps verification.",
            "status": "info",
            "points": 0,
        })

    # --- duplicate signal ---------------------------------------------------
    if duplicates:
        max_score = int(duplicates.get("maxScore") or 0)
        if duplicates.get("isPossibleDuplicate"):
            add(
                "duplicate_signal",
                "Possible duplicate",
                duplicates.get("summary", "A similar recent report exists."),
                15,
            )
        elif max_score >= 45:
            checks.append({
                "code": "duplicate_signal",
                "label": "Similar report",
                "detail": duplicates.get("summary", ""),
                "status": "info",
                "points": 0,
            })
        else:
            ok("duplicate_signal", "No duplicate found", duplicates.get("summary", ""))

    score = min(100, sum(item["points"] for item in reasons))
    medium = int(cfg.get("mediumRiskThreshold", 25))
    high = int(cfg.get("highRiskThreshold", 55))
    level = "high" if score >= high else ("medium" if score >= medium else "low")
    reasons.sort(key=lambda item: item["points"], reverse=True)

    return {
        "score": score,
        "level": level,
        "reasons": reasons,
        "checks": checks,
        "engine": "drras-risk-v1",
        "thresholds": {"medium": medium, "high": high},
    }


def auto_approval_decision(
    request: dict, risk: dict, duplicates: dict, settings: dict
) -> tuple[bool, str]:
    """Evaluates the administrator-configured auto-approval rules.

    Returns ``(approved, explanation)``. The explanation is stored in the audit
    log so an operator can always see why the machine approved something - and
    why it declined to. Auto-approval can never reject a request.
    """
    cfg = {**DEFAULT_SETTINGS, **(settings or {})}
    if not cfg.get("autoApproveEnabled"):
        return False, "Automatic approval is disabled by the administrator."
    if risk.get("level") != "low":
        return False, f"Risk level is {risk.get('level')}, so human review is required."
    if int(risk.get("score", 0)) > int(cfg.get("autoApproveMaxRisk", 20)):
        return False, (
            f"Risk score {risk.get('score')} is above the configured auto-approval "
            f"ceiling of {cfg.get('autoApproveMaxRisk')}."
        )
    severity = str(request.get("severity") or "").upper()
    allowed = [str(item).upper() for item in cfg.get("autoApproveSeverities", [])]
    if severity not in allowed:
        return False, f"Severity {severity} is not in the auto-approval list ({', '.join(allowed) or 'none'})."
    if duplicates.get("isPossibleDuplicate") and cfg.get("duplicateBlockAutoApprove", True):
        return False, "A possible duplicate match requires a person to merge or separate it."
    description = str(request.get("description") or "").strip()
    minimum = int(cfg.get("autoApproveMinDescriptionLength", 20))
    if len(description) < minimum:
        return False, f"Description is shorter than the required {minimum} characters."
    if cfg.get("autoApproveRequireContact", True) and not (
        request.get("contact_phone") or request.get("contact_email")
    ):
        return False, "A usable contact detail is required before automatic approval."
    if request.get("contact_phone") and not is_valid_phone(request.get("contact_phone")):
        return False, "The supplied phone number is not valid."
    return True, (
        f"Low risk ({risk.get('score')}/100), {severity} severity, description and "
        "contact validated, no blocking duplicate - matches the configured rules."
    )


def verification_route(risk: dict, duplicates: dict, settings: dict, request: dict) -> tuple[str, str, str]:
    """Chooses ``(workflow_status, queue, explanation)`` after verification."""
    cfg = {**DEFAULT_SETTINGS, **(settings or {})}
    if duplicates.get("isPossibleDuplicate"):
        return (
            "possible_duplicate",
            "duplicate_review",
            "Sent to duplicate review: a similar recent report exists. "
            "A person decides whether to merge, link or keep both.",
        )
    if risk.get("level") == "high":
        return (
            "under_verification",
            "high_risk",
            "Sent to high-risk verification: the report matched several suspicion checks "
            "and must be reviewed by a person before any decision.",
        )
    approved, explanation = auto_approval_decision(request, risk, duplicates, cfg)
    if approved:
        return "approved", "auto_approval", explanation
    if risk.get("level") == "medium":
        return (
            "awaiting_approval",
            "manual_review",
            "Medium risk: awaits administrator review. " + explanation,
        )
    return (
        "awaiting_approval",
        "manual_review",
        "Low risk, but automatic approval is not applicable: " + explanation,
    )
