#!/usr/bin/env python3
"""DRRAS web service.

Serves the static site in ``docs/`` and the JSON API used by the public
reporting/tracking pages and the command-centre dashboard. Standard library
only (plus the sqlite3 module that ships with CPython).

Usage:
    python3 backend/admin_server.py --set-password          # create/reset admin password
    python3 backend/admin_server.py --seed-demo            # add sample incidents
    python3 backend/admin_server.py                        # serve on http://0.0.0.0:8000

Environment:
    DRRAS_DB_PATH          SQLite path (shared by password setup + server)
    DRRAS_ADMIN_PASSWORD   optional first-run admin password (12+ chars)
    DRRAS_OPERATOR_PASSWORD optional operator password (review without settings access)
    DRRAS_COOKIE_SECURE    "1" to mark the session cookie Secure (behind HTTPS)
    DRRAS_ROUTING_URL      OSRM base URL (default https://router.project-osrm.org)
    DRRAS_GEOCODING_URL    Nominatim base URL
    DRRAS_OFFLINE=1        never make outbound routing/geocoding calls
    DRRAS_PORT / DRRAS_HOST bind defaults
"""

from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import html
import json
import os
import sys
import traceback
from datetime import timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# Shared domain layer. These names are re-exported here because the original
# module was the single import point for the whole application and its tests.
from drras_common import (  # noqa: F401  (re-exported for backwards compatibility)
    ALLOCATION_STATUSES,
    CENTRE_AVAILABILITY,
    DEFAULT_ACCEPT_MESSAGE,
    DEFAULT_DECISION_MESSAGES,
    DEFAULT_INVENTORY,
    DEFAULT_REJECT_MESSAGE,
    DEFAULT_SETTINGS,
    DISASTER_TYPES,
    EVIDENCE_ALLOWED_TYPES,
    EVIDENCE_MAX_BYTES,
    HELP_CENTRE_CATEGORIES,
    MAX_RESOURCE_QUANTITY,
    MESSAGE_MAX_LENGTH,
    RESOURCE_CATEGORIES,
    SEVERITIES,
    WORKFLOW_STATUSES,
    ApiError,
    iso,
    plan_submission_grant,
    utc_now,
)
from db_store import Store  # noqa: F401  (re-exported)
from drras_geo import routing_status

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
STATIC_ROOT = REPO_ROOT / "docs"
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "drras.sqlite3"
DEFAULT_UPLOAD_DIR = BACKEND_DIR / "data" / "uploads"

SESSION_COOKIE_NAME = "drras_session"
SESSION_LIFETIME = timedelta(hours=8)
MIN_PASSWORD_LENGTH = 12
PBKDF2_ITERATIONS = 210_000
MAX_BODY_BYTES = 64 * 1024
MAX_UPLOAD_BODY_BYTES = 8 * 1024 * 1024
HARD_BODY_CAP = 12 * 1024 * 1024
MAX_DESCRIPTION_LENGTH = 2000
MAX_EVIDENCE_FILES = 5

COOKIE_SAMESITE_DEFAULT = "Strict"
COOKIE_SAMESITE_VALUES = ("Strict", "Lax", "None")

LOGIN_MAX_ATTEMPTS = 8
LOGIN_WINDOW_SECONDS = 15 * 60

STATUSES = ("pending", "accepted", "rejected")
ROLES = ("admin", "operator")

# Loopback traffic is never rate-limited: local demos and the test suite submit
# dozens of requests from 127.0.0.1, and an operator cannot spam themselves
# through a network they already control.
LOOPBACK_IPS = {"127.0.0.1", "::1", "localhost", ""}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_decision_message(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ApiError("Message must be text.")
    text = raw.strip()
    if not text:
        return None
    if len(text) > MESSAGE_MAX_LENGTH:
        raise ApiError(f"Message is too long (max {MESSAGE_MAX_LENGTH} characters).")
    return html.escape(text, quote=False)


def validate_inventory_payload(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ApiError("Expected a JSON object.")
    quantities_raw = raw.get("quantities")
    if not isinstance(quantities_raw, dict) or not quantities_raw:
        raise ApiError("'quantities' must be an object of category: amount pairs.")
    quantities: dict[str, int] = {}
    for category, amount in quantities_raw.items():
        name = str(category).strip()
        if name not in RESOURCE_CATEGORIES:
            raise ApiError(f"Unknown resource category: {name}")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ApiError(f"Quantity for {name} must be a number.")
        value = int(amount)
        if value < 0 or value > MAX_RESOURCE_QUANTITY:
            raise ApiError(f"Quantity for {name} must be between 0 and {MAX_RESOURCE_QUANTITY}.")
        quantities[name] = value
    return quantities


def _optional_text(raw: object, label: str, limit: int) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
        raise ApiError(f"{label} must be text.")
    text = str(raw).strip()
    if len(text) > limit:
        raise ApiError(f"{label} is too long (max {limit} characters).")
    return html.escape(text, quote=False)


def validate_request_payload(raw: object) -> dict:
    """Server-side validation for public submissions.

    Invalid contact details are *not* rejected here: they are deliberately
    accepted and surfaced as a risk signal for a human. Malformed or abusive
    structure is rejected.
    """
    if not isinstance(raw, dict):
        raise ApiError("Expected a JSON object.")

    disaster_type = str(raw.get("type") or "").strip().upper()
    if disaster_type not in DISASTER_TYPES:
        raise ApiError("Unknown disaster type.")

    severity = str(raw.get("severity") or "").strip().upper()
    if severity not in SEVERITIES:
        raise ApiError("Severity must be CRITICAL, HIGH, MEDIUM or LOW.")

    affected = raw.get("affectedPeople")
    if isinstance(affected, bool) or not isinstance(affected, (int, float)):
        raise ApiError("Affected people must be a number.")
    affected_int = int(affected)
    if affected_int < 0 or affected_int > 1_000_000_000:
        raise ApiError("Affected people cannot be negative.")

    location = str(raw.get("locationName") or "").strip()
    if not location:
        raise ApiError("Location name is required.")
    if len(location) > 200:
        raise ApiError("Location name is too long (max 200 characters).")

    latitude = raw.get("latitude")
    longitude = raw.get("longitude")
    for value, label, bound in ((latitude, "Latitude", 90.0), (longitude, "Longitude", 180.0)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError(f"{label} must be a number.")
        if not (-bound <= float(value) <= bound):
            raise ApiError(f"{label} must be between {-bound} and {bound}.")

    resources_raw = raw.get("requiredResources")
    if resources_raw is None:
        resources_raw = []
    if not isinstance(resources_raw, list) or len(resources_raw) > len(RESOURCE_CATEGORIES):
        raise ApiError("Required resources must be a list.")
    resources: list[str] = []
    for item in resources_raw:
        value = str(item).strip()
        if value not in RESOURCE_CATEGORIES:
            raise ApiError(f"Unknown resource category: {value}")
        if value not in resources:
            resources.append(value)

    quantities_raw = raw.get("resourceQuantities")
    if quantities_raw is None:
        quantities_raw = {}
    if not isinstance(quantities_raw, dict) or len(quantities_raw) > len(RESOURCE_CATEGORIES):
        raise ApiError("Resource quantities must be an object of category: amount pairs.")
    quantities: dict[str, int] = {}
    for category, amount in quantities_raw.items():
        name = str(category).strip()
        if name not in RESOURCE_CATEGORIES:
            raise ApiError(f"Unknown resource category: {name}")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ApiError(f"Quantity for {name} must be a number.")
        value = int(amount)
        if value < 0 or value > MAX_RESOURCE_QUANTITY:
            raise ApiError(f"Quantity for {name} must be between 0 and {MAX_RESOURCE_QUANTITY}.")
        if value == 0:
            continue
        quantities[name] = value
        if name not in resources:
            resources.append(name)

    description = str(raw.get("description") or "").strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ApiError(f"Description is too long (max {MAX_DESCRIPTION_LENGTH} characters).")

    contact_name = _optional_text(raw.get("contactName"), "Contact name", 120)
    contact_phone = _optional_text(raw.get("contactPhone"), "Contact phone", 40)
    contact_email = _optional_text(raw.get("contactEmail"), "Contact email", 160)

    evidence_raw = raw.get("evidence")
    if evidence_raw is None:
        evidence_raw = []
    if not isinstance(evidence_raw, list) or len(evidence_raw) > MAX_EVIDENCE_FILES:
        raise ApiError(f"At most {MAX_EVIDENCE_FILES} supporting files can be attached.")
    evidence: list[str] = []
    for item in evidence_raw:
        value = str(item).strip()
        if not value or len(value) > 40 or not value.startswith("EV-"):
            raise ApiError("Invalid evidence reference.")
        if value not in evidence:
            evidence.append(value)

    return {
        "type": disaster_type,
        "severity": severity,
        "affectedPeople": affected_int,
        "requiredResources": resources,
        "resourceQuantities": quantities,
        "locationName": html.escape(location, quote=False),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "description": html.escape(description, quote=False),
        "contactName": contact_name,
        "contactPhone": contact_phone,
        "contactEmail": contact_email,
        "evidence": evidence,
    }


def validate_settings_payload(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ApiError("Expected a JSON object.")
    updates: dict = {}
    if "autoApproveEnabled" in raw:
        if not isinstance(raw["autoApproveEnabled"], bool):
            raise ApiError("autoApproveEnabled must be true or false.")
        updates["autoApproveEnabled"] = raw["autoApproveEnabled"]
    if "autoApproveMaxRisk" in raw:
        value = raw["autoApproveMaxRisk"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= int(value) <= 100:
            raise ApiError("autoApproveMaxRisk must be a number between 0 and 100.")
        updates["autoApproveMaxRisk"] = int(value)
    if "autoApproveSeverities" in raw:
        values = raw["autoApproveSeverities"]
        if not isinstance(values, list):
            raise ApiError("autoApproveSeverities must be a list.")
        cleaned = [str(item).strip().upper() for item in values]
        if any(item not in SEVERITIES for item in cleaned):
            raise ApiError("Unknown severity in autoApproveSeverities.")
        updates["autoApproveSeverities"] = cleaned
    if "autoApproveMinDescriptionLength" in raw:
        value = raw["autoApproveMinDescriptionLength"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= int(value) <= 2000:
            raise ApiError("autoApproveMinDescriptionLength must be between 0 and 2000.")
        updates["autoApproveMinDescriptionLength"] = int(value)
    if "autoApproveRequireContact" in raw:
        if not isinstance(raw["autoApproveRequireContact"], bool):
            raise ApiError("autoApproveRequireContact must be true or false.")
        updates["autoApproveRequireContact"] = raw["autoApproveRequireContact"]
    if "duplicateBlockAutoApprove" in raw:
        if not isinstance(raw["duplicateBlockAutoApprove"], bool):
            raise ApiError("duplicateBlockAutoApprove must be true or false.")
        updates["duplicateBlockAutoApprove"] = raw["duplicateBlockAutoApprove"]
    for key, low, high in (
        ("duplicateWindowHours", 1, 720),
        ("duplicateThreshold", 0, 100),
        ("mediumRiskThreshold", 0, 100),
        ("highRiskThreshold", 0, 100),
        ("submissionRateLimit", 1, 1000),
        ("submissionRateWindowMinutes", 1, 1440),
    ):
        if key in raw:
            value = raw[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= int(value) <= high:
                raise ApiError(f"{key} must be a number between {low} and {high}.")
            updates[key] = int(value)
    if "routingProvider" in raw:
        if raw["routingProvider"] != "osrm":
            raise ApiError("The only supported routing provider is 'osrm'.")
        updates["routingProvider"] = "osrm"
    if not updates:
        raise ApiError("No recognised settings were supplied.")
    return updates


def validate_help_centre_payload(raw: object, *, require_all: bool = True) -> dict:
    if not isinstance(raw, dict):
        raise ApiError("Expected a JSON object.")
    payload: dict = {}
    if "name" in raw or require_all:
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ApiError("Centre name is required.")
        if len(name) > 160:
            raise ApiError("Centre name is too long.")
        payload["name"] = html.escape(name, quote=False)
    if "category" in raw or require_all:
        category = str(raw.get("category") or "").strip()
        if category not in HELP_CENTRE_CATEGORIES:
            raise ApiError("Unknown help-centre category.")
        payload["category"] = category
    if "availability" in raw or require_all:
        availability = str(raw.get("availability") or "available").strip()
        if availability not in CENTRE_AVAILABILITY:
            raise ApiError("Unknown availability status.")
        payload["availability"] = availability
    if "latitude" in raw or require_all:
        try:
            latitude = float(raw.get("latitude"))
            longitude = float(raw.get("longitude"))
        except (TypeError, ValueError):
            raise ApiError("Latitude and longitude are required.") from None
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ApiError("Coordinates are out of range.")
        payload["latitude"] = latitude
        payload["longitude"] = longitude
    for key, limit in (("address", 240), ("phone", 40), ("capacityNote", 240), ("notes", 400)):
        if key in raw:
            payload[key] = _optional_text(raw.get(key), key, limit)
    if "stock" in raw:
        stock = raw["stock"]
        if not isinstance(stock, dict):
            raise ApiError("stock must be an object of category: amount pairs.")
        cleaned: dict[str, int] = {}
        for category, amount in stock.items():
            if category not in RESOURCE_CATEGORIES:
                raise ApiError(f"Unknown resource category: {category}")
            if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                raise ApiError(f"Quantity for {category} must be a number.")
            value = int(amount)
            if value < 0 or value > MAX_RESOURCE_QUANTITY:
                raise ApiError(f"Quantity for {category} must be zero or more.")
            cleaned[category] = value
        payload["stock"] = cleaned
    return payload


def validate_evidence_payload(raw: object) -> tuple[str, str, bytes]:
    if not isinstance(raw, dict):
        raise ApiError("Expected a JSON object.")
    file_name = str(raw.get("fileName") or "evidence").strip()[:120]
    mime_type = str(raw.get("mimeType") or "").strip().lower()
    if mime_type not in EVIDENCE_ALLOWED_TYPES:
        raise ApiError("Only JPEG, PNG or PDF files can be attached.")
    encoded = raw.get("data")
    if not isinstance(encoded, str) or not encoded:
        raise ApiError("The uploaded file is missing.")
    if len(encoded) > int(EVIDENCE_MAX_BYTES * 1.4):
        raise ApiError("Each file must be 5 MB or smaller.", 413)
    try:
        binary = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError("The uploaded file is not valid base64.") from None
    return file_name or "evidence", mime_type, binary


def validate_allocation_items(raw: object) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw:
        raise ApiError("Choose at least one resource to allocate.")
    items: dict[str, int] = {}
    for category, amount in raw.items():
        if category not in RESOURCE_CATEGORIES:
            raise ApiError(f"Unknown resource category: {category}")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ApiError(f"Quantity for {category} must be a number.")
        value = int(amount)
        if value <= 0 or value > MAX_RESOURCE_QUANTITY:
            raise ApiError(f"Quantity for {category} must be a positive number.")
        items[category] = value
    return items


def _query_arg(query: dict, name: str, default=None):
    values = query.get(name)
    if not values:
        return default
    return values[0]


def _float_arg(query: dict, name: str, *, required: bool = True) -> float | None:
    raw = _query_arg(query, name)
    if raw is None or raw == "":
        if required:
            raise ApiError(f"Missing '{name}'.")
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ApiError(f"'{name}' must be a number.") from None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class DrrasHandler(SimpleHTTPRequestHandler):
    server_version = "DRRAS/2.0"
    protocol_version = "HTTP/1.1"
    store: Store
    cookie_secure = False
    cookie_samesite = COOKIE_SAMESITE_DEFAULT
    cookie_partitioned = False
    allow_bearer_auth = False
    auth_source = "cookie"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)
        self._body = b""
        self.auth_role: str | None = None

    # ---- plumbing ----

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK, extra_headers=None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for name, value in extra_headers or ():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_error_json(self, message: str, status: int) -> None:
        self._send_json({"error": message}, status)

    def drain_body(self) -> None:
        self._body = b""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            raise ApiError("Invalid Content-Length.") from None
        if length <= 0:
            return
        if length > HARD_BODY_CAP:
            self.close_connection = True
            raise ApiError("Request body is too large.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        self._body = self.rfile.read(length)
        if len(self._body) < length:
            self.close_connection = True

    def _read_json(self, limit: int = MAX_BODY_BYTES) -> object:
        raw = getattr(self, "_body", b"")
        if not raw:
            return {}
        if len(raw) > limit:
            raise ApiError("Request body is too large.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError("Request body must be valid JSON.") from None

    def _cookie_token(self) -> str:
        raw = self.headers.get("Cookie")
        if not raw:
            return ""
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return ""
        morsel = cookie.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else ""

    def _credential(self) -> tuple[str, str]:
        auth = self.headers.get("Authorization", "")
        if self.allow_bearer_auth and auth[:7].lower() == "bearer ":
            candidate = auth[7:].strip()
            if candidate:
                return candidate, "bearer"
        return self._cookie_token(), "cookie"

    def _session_token(self) -> str:
        return self._credential()[0]

    def _require_admin(self, allowed_roles: tuple[str, ...] | None = None):
        token, source = self._credential()
        session = self.store.get_session(token)
        if session is None:
            self.auth_role = None
            raise ApiError("Your admin session has expired. Sign in again.", HTTPStatus.UNAUTHORIZED)
        self.auth_source = source
        role = session["role"] if "role" in session.keys() else "admin"
        self.auth_role = role or "admin"
        if allowed_roles and self.auth_role not in allowed_roles:
            raise ApiError(
                f"Your role ({self.auth_role}) is not allowed to perform this action.",
                HTTPStatus.FORBIDDEN,
            )
        return session

    def _require_csrf(self) -> None:
        if self.auth_source == "bearer":
            return
        token = self._session_token()
        supplied = self.headers.get("X-CSRF-Token", "")
        if not self.store.check_csrf(token, supplied):
            raise ApiError("Missing or invalid CSRF token.", HTTPStatus.FORBIDDEN)

    def _client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "unknown"

    def _cookie(self, value: str, max_age: int) -> str:
        parts = [
            f"{SESSION_COOKIE_NAME}={value}",
            "Path=/",
            "HttpOnly",
            f"SameSite={self.cookie_samesite}",
            f"Max-Age={max_age}",
        ]
        if self.cookie_secure or self.cookie_samesite == "None":
            parts.append("Secure")
        if self.cookie_partitioned and self.cookie_samesite == "None":
            parts.append("Partitioned")
        return "; ".join(parts)

    # ---- routing ----

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._guard(lambda: self._route_get(parsed.path, parse_qs(parsed.query)))
            return
        path = parsed.path
        if path in ("/admin", "/admin/"):
            self.path = "/admin.html"
        elif path == "/":
            self.path = "/index.html"
        self._revalidate_html = self.path.split("?", 1)[0].endswith(".html")
        self._serve_static()

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        self._guard(lambda: self._handle_body("POST", parsed))

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        self._guard(lambda: self._handle_body("PATCH", parsed))

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        self._guard(lambda: self._handle_body("PUT", parsed))

    def _handle_body(self, method: str, parsed) -> None:
        try:
            self.drain_body()
        except ApiError as err:
            self._send_error_json(err.message, err.status)
            return
        if method == "POST":
            self._route_post(parsed.path, parse_qs(parsed.query))
        elif method == "PATCH":
            self._route_patch(parsed.path)
        else:
            self._route_put(parsed.path)

    def _guard(self, operation) -> None:
        """Converts ApiError (and unexpected failures) into a JSON response."""
        try:
            operation()
        except ApiError as err:
            self._send_error_json(err.message, err.status)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:  # pragma: no cover - defensive
            traceback.print_exc()
            self._send_error_json(
                "The server hit an unexpected error. Please try again.", HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def end_headers(self) -> None:
        if getattr(self, "_revalidate_html", False):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _serve_static(self) -> None:
        if not STATIC_ROOT.is_dir():
            self._send_error_json("Static site folder docs/ is missing.", HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    # ---- API: read ----

    def _route_get(self, path: str, query: dict) -> None:
        if path == "/api/health":
            self._send_json({
                "status": "ok",
                "passwordConfigured": self.store.has_password(),
                "service": "DRRAS",
                "version": "2.0",
                "demoData": self._has_demo_data(),
                "routing": routing_status(),
            })
            return
        if path == "/api/overview":
            self._send_json(self.store.public_overview())
            return
        if path == "/api/help-centres":
            centres = self.store.list_help_centres()
            self._send_json({"centres": centres, "categories": HELP_CENTRE_CATEGORIES})
            return
        if path == "/api/nearby":
            latitude = _float_arg(query, "lat")
            longitude = _float_arg(query, "lon")
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ApiError("Coordinates are out of range.")
            category = _query_arg(query, "category", "all")
            if category not in HELP_CENTRE_CATEGORIES and category not in (None, "all"):
                raise ApiError("Unknown help-centre category.")
            availability = _query_arg(query, "availability", "all")
            resource = _query_arg(query, "resource", "all")
            if resource not in RESOURCE_CATEGORIES and resource not in (None, "all"):
                raise ApiError("Unknown resource category.")
            radius = _float_arg(query, "radius", required=False)
            if radius is not None and not (0 < radius <= 200):
                raise ApiError("Radius must be between 0 and 200 km.")
            try:
                limit = int(_query_arg(query, "limit", 20))
            except (TypeError, ValueError):
                raise ApiError("limit must be a number.") from None
            payload = self.store.nearby_centres(
                latitude, longitude, category=category, radius_km=radius,
                availability=availability, resource=resource, limit=max(1, min(limit, 50)),
            )
            self._send_json(payload)
            return
        if path == "/api/places":
            q = str(_query_arg(query, "q", "") or "").strip()
            if len(q) < 2:
                raise ApiError("Enter at least two characters to search.")
            if len(q) > 120:
                raise ApiError("Search text is too long.")
            self._send_json({"results": self.store.search_places(q)})
            return
        if path == "/api/route":
            try:
                origin_lat = float(_query_arg(query, "fromLat"))
                origin_lon = float(_query_arg(query, "fromLon"))
                dest_lat = float(_query_arg(query, "toLat"))
                dest_lon = float(_query_arg(query, "toLon"))
            except (TypeError, ValueError):
                raise ApiError("Four coordinates are required: fromLat, fromLon, toLat, toLon.") from None
            for lat, lon in ((origin_lat, origin_lon), (dest_lat, dest_lon)):
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ApiError("Coordinates are out of range.")
            self._send_json(self.store.route_between((origin_lat, origin_lon), (dest_lat, dest_lon)))
            return
        if path == "/api/inventory":
            self._send_json({"inventory": self.store.get_inventory()})
            return
        if path.startswith("/api/requests/"):
            request_id = unquote(path.rsplit("/", 1)[-1])
            record = self.store.get_public_request(request_id)
            if record is None:
                raise ApiError("That request was not found.", HTTPStatus.NOT_FOUND)
            self._send_json({"request": record})
            return

        # ---- admin reads ----
        if path == "/api/admin/session":
            session = self._require_admin()
            payload = {
                "authenticated": True,
                "csrfToken": session["csrf_token"],
                "role": self.auth_role,
            }
            if self.auth_source == "bearer":
                payload["sessionToken"] = self._session_token()
            self._send_json(payload)
            return
        if path == "/api/admin/requests":
            self._require_admin()
            self._send_json({"requests": self.store.list_requests()})
            return
        if path.startswith("/api/admin/requests/") and path.endswith("/recommendations"):
            self._require_admin()
            request_id = unquote(path.split("/")[-2])
            self._send_json(self.store.allocation_recommendations(request_id))
            return
        if path.startswith("/api/admin/requests/"):
            self._require_admin()
            request_id = unquote(path.rsplit("/", 1)[-1])
            record = self.store.get_request(request_id)
            if record is None:
                raise ApiError("That request no longer exists.", HTTPStatus.NOT_FOUND)
            self._send_json({"request": record})
            return
        if path == "/api/admin/stats":
            self._require_admin()
            self._send_json(self.store.admin_stats())
            return
        if path == "/api/admin/audit":
            self._require_admin()
            try:
                limit = int(_query_arg(query, "limit", 300))
            except (TypeError, ValueError):
                raise ApiError("limit must be a number.") from None
            request_id = _query_arg(query, "requestId")
            self._send_json({
                "audit": self.store.list_audit(limit=max(1, min(limit, 1000)), request_id=request_id)
            })
            return
        if path == "/api/admin/notifications":
            self._require_admin()
            self._send_json({"notifications": self.store.list_notifications()})
            return
        if path == "/api/admin/allocations":
            self._require_admin()
            self._send_json({"allocations": self.store.list_allocations()})
            return
        if path == "/api/admin/help-centres":
            self._require_admin()
            self._send_json({
                "centres": self.store.list_help_centres(),
                "categories": HELP_CENTRE_CATEGORIES,
            })
            return
        if path == "/api/admin/inventory":
            self._require_admin()
            self._send_json({"inventory": self.store.get_inventory()})
            return
        if path == "/api/admin/settings":
            self._require_admin()
            self._send_json({
                "settings": self.store.get_settings(),
                "defaults": DEFAULT_SETTINGS,
                "routing": routing_status(),
            })
            return
        if path.startswith("/api/admin/evidence/"):
            self._require_admin()
            evidence_id = unquote(path.rsplit("/", 1)[-1])
            found = self.store.get_evidence(evidence_id)
            if found is None:
                raise ApiError("That file was not found.", HTTPStatus.NOT_FOUND)
            row, file_path = found
            data = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", row["mime_type"])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'inline; filename="{row["stored_name"]}"')
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            return
        raise ApiError("Unknown endpoint.", HTTPStatus.NOT_FOUND)

    def _has_demo_data(self) -> bool:
        try:
            with self.store._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM requests WHERE is_demo = 1"
                ).fetchone()
            return bool(row and int(row["n"]) > 0)
        except Exception:  # pragma: no cover - defensive
            return False

    # ---- API: public submissions ----

    def _route_post(self, path: str, query: dict) -> None:
        if path == "/api/requests":
            ip = self._client_ip()
            settings = self.store.get_settings()
            if ip not in LOOPBACK_IPS and self.store.check_submission_rate(
                ip,
                int(settings.get("submissionRateLimit", 6)),
                int(settings.get("submissionRateWindowMinutes", 10)),
            ):
                raise ApiError(
                    "Too many reports from this connection. Please wait a few minutes or call 112 "
                    "if this is an emergency.",
                    HTTPStatus.TOO_MANY_REQUESTS,
                )
            payload = validate_request_payload(self._read_json())
            if ip not in LOOPBACK_IPS:
                self.store.record_submission_attempt(ip)
            evidence = payload.pop("evidence", [])
            record = self.store.submit_request(
                payload, client_ip=ip, evidence_ids=evidence
            )
            public = self.store.get_public_request(unquote(record["id"]))
            if public is None:  # pragma: no cover - defensive
                raise ApiError("The request could not be saved.", 500)
            public["status"] = record["status"]
            public["grantedResources"] = record["grantedResources"]
            public["userMessage"] = record["userMessage"]
            self._send_json(
                {
                    "request": public,
                    "verification": {
                        "queue": record["verificationQueue"],
                        "workflowStatus": record["workflowStatus"],
                        "summary": public["verification"]["summary"],
                    },
                },
                HTTPStatus.CREATED,
            )
            return
        if path == "/api/uploads":
            ip = self._client_ip()
            if ip not in LOOPBACK_IPS and self.store.check_submission_rate(ip, 20, 10):
                raise ApiError("Too many uploads from this connection.", HTTPStatus.TOO_MANY_REQUESTS)
            file_name, mime_type, binary = validate_evidence_payload(
                self._read_json(MAX_UPLOAD_BODY_BYTES)
            )
            evidence = self.store.add_evidence(file_name, mime_type, binary)
            self._send_json({"evidence": evidence}, HTTPStatus.CREATED)
            return
        if path == "/api/admin/login":
            self._login()
            return
        if path == "/api/admin/logout":
            self._require_admin()
            self._require_csrf()
            self.store.delete_session(self._session_token())
            self._send_json(
                {"ok": True},
                extra_headers=[("Set-Cookie", self._cookie("", 0))],
            )
            return

        # ---- admin mutations ----
        self._require_admin()
        self._require_csrf()

        if path.startswith("/api/admin/requests/") and path.endswith("/action"):
            request_id = unquote(path.split("/")[-2])
            body = self._read_json()
            if not isinstance(body, dict):
                raise ApiError("Expected a JSON object.")
            action = str(body.get("action") or "").strip()
            if not action:
                raise ApiError("An action is required.")
            reason = validate_decision_message(body.get("reason"))
            message = validate_decision_message(body.get("message"))
            updated = self.store.apply_action(
                request_id, action, actor="admin", role=self.auth_role or "admin",
                reason=reason, message=message,
                target_id=(str(body["targetId"]) if body.get("targetId") else None),
            )
            self._send_json({"request": updated})
            return
        if path.startswith("/api/admin/requests/") and path.endswith("/allocations"):
            request_id = unquote(path.split("/")[-2])
            body = self._read_json()
            if not isinstance(body, dict):
                raise ApiError("Expected a JSON object.")
            centre_id = str(body.get("centreId") or "").strip()
            if not centre_id:
                raise ApiError("Choose a help centre.")
            items = validate_allocation_items(body.get("items"))
            distance = body.get("distance") if isinstance(body.get("distance"), dict) else None
            override_reason = validate_decision_message(body.get("overrideReason"))
            updated = self.store.allocate(
                request_id, centre_id, items=items,
                actor="admin", role=self.auth_role or "admin",
                override_reason=override_reason, distance=distance,
            )
            self._send_json({"request": updated}, HTTPStatus.CREATED)
            return
        if path == "/api/admin/seed-demo":
            self._require_role("admin")
            self._send_json(self.store.seed_demo())
            return
        if path == "/api/admin/help-centres":
            self._require_role("admin")
            payload = validate_help_centre_payload(self._read_json(), require_all=True)
            centre = self.store.create_help_centre(
                payload, actor="admin", role=self.auth_role or "admin"
            )
            self._send_json({"centre": centre}, HTTPStatus.CREATED)
            return
        raise ApiError("Unknown endpoint.", HTTPStatus.NOT_FOUND)

    def _require_role(self, role: str) -> None:
        self._require_admin((role,))

    def _login(self) -> None:
        ip = self._client_ip()
        if self.store.too_many_login_attempts(ip, LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS):
            raise ApiError(
                "Too many failed sign-in attempts. Wait 15 minutes and try again.",
                HTTPStatus.TOO_MANY_REQUESTS,
            )
        body = self._read_json()
        password = body.get("password") if isinstance(body, dict) else None
        if not self.store.has_password() or not isinstance(password, str):
            self.store.record_login_failure(ip)
            raise ApiError("Incorrect password.", HTTPStatus.UNAUTHORIZED)
        role = self.store.authenticate(password)
        if role is None:
            self.store.record_login_failure(ip)
            raise ApiError("Incorrect password.", HTTPStatus.UNAUTHORIZED)
        self.store.clear_login_failures(ip)
        token, csrf = self.store.create_session(role)
        max_age = int(SESSION_LIFETIME.total_seconds())
        body: dict = {"ok": True, "csrfToken": csrf, "role": role}
        if self.allow_bearer_auth:
            body["sessionToken"] = token
            body["authMode"] = "bearer"
        self._send_json(body, extra_headers=[("Set-Cookie", self._cookie(token, max_age))])

    # ---- API: decisions (legacy PATCH + new allocation/centre updates) ----

    def _route_patch(self, path: str) -> None:
        self._require_admin()
        self._require_csrf()
        if path.startswith("/api/admin/requests/"):
            request_id = unquote(path.rsplit("/", 1)[-1])
            body = self._read_json()
            if not isinstance(body, dict):
                raise ApiError("Expected a JSON object.")
            status = str(body.get("status") or "").strip().lower()
            message = validate_decision_message(body.get("message"))
            reason = validate_decision_message(body.get("reason"))
            if status in ("accepted", "approved"):
                if status == "accepted":
                    updated = self.store.approve_request(
                        request_id, message=message, reason=reason,
                        actor="admin", role=self.auth_role or "admin",
                        deduct_reserve=True, legacy=True,
                    )
                else:
                    updated = self.store.approve_request(
                        request_id, message=message, reason=reason,
                        actor="admin", role=self.auth_role or "admin",
                    )
            elif status in ("rejected",):
                updated = self.store.reject_request(
                    request_id, message=message, reason=reason,
                    actor="admin", role=self.auth_role or "admin", legacy=True,
                )
            elif status in ("request_info", "info_requested"):
                updated = self.store.request_info(
                    request_id, reason=reason or message or "Additional information required.",
                    actor="admin", role=self.auth_role or "admin",
                )
            elif status in ("flagged", "flag"):
                updated = self.store.flag_request(
                    request_id, reason=reason or message or "Flagged for review.",
                    actor="admin", role=self.auth_role or "admin",
                )
            else:
                raise ApiError("Status must be 'accepted' or 'rejected'.")
            self._send_json({"request": updated})
            return
        if path.startswith("/api/admin/allocations/"):
            allocation_id = unquote(path.rsplit("/", 1)[-1])
            body = self._read_json()
            if not isinstance(body, dict):
                raise ApiError("Expected a JSON object.")
            status = str(body.get("status") or "").strip().lower()
            if status not in ALLOCATION_STATUSES:
                raise ApiError("Unknown allocation status.")
            reason = validate_decision_message(body.get("reason"))
            allocation = self.store.update_allocation_status(
                allocation_id, status, actor="admin", role=self.auth_role or "admin",
                reason=reason,
            )
            self._send_json({"allocation": allocation})
            return
        if path.startswith("/api/admin/help-centres/"):
            self._require_role("admin")
            centre_id = unquote(path.rsplit("/", 1)[-1])
            updates = validate_help_centre_payload(self._read_json(), require_all=False)
            if not updates:
                raise ApiError("No changes were supplied.")
            centre = self.store.update_help_centre(
                centre_id, updates, actor="admin", role=self.auth_role or "admin"
            )
            self._send_json({"centre": centre})
            return
        raise ApiError("Unknown endpoint.", HTTPStatus.NOT_FOUND)

    # ---- API: settings / inventory ----

    def _route_put(self, path: str) -> None:
        self._require_admin()
        self._require_csrf()
        if path == "/api/admin/inventory":
            self._require_role("admin")
            quantities = validate_inventory_payload(self._read_json())
            self._send_json({
                "inventory": self.store.set_inventory(
                    quantities, actor="admin", role=self.auth_role or "admin"
                )
            })
            return
        if path == "/api/admin/settings":
            self._require_role("admin")
            updates = validate_settings_payload(self._read_json())
            settings = self.store.update_settings(
                updates, actor="admin", role=self.auth_role or "admin"
            )
            self._send_json({"settings": settings})
            return
        raise ApiError("Unknown endpoint.", HTTPStatus.NOT_FOUND)


# ---------------------------------------------------------------------------
# server factory / CLI
# ---------------------------------------------------------------------------


def normalize_samesite(value: str) -> str:
    cleaned = (value or "").strip().title()
    if cleaned not in COOKIE_SAMESITE_VALUES:
        raise ValueError(
            "SameSite must be one of: " + ", ".join(COOKIE_SAMESITE_VALUES) + f" (got {value!r})."
        )
    return cleaned


def make_server(
    host: str,
    port: int,
    store: Store,
    cookie_secure: bool,
    cookie_samesite: str = COOKIE_SAMESITE_DEFAULT,
    cookie_partitioned: bool = False,
    allow_bearer_auth: bool = False,
) -> ThreadingHTTPServer:
    handler = type(
        "BoundDrrasHandler",
        (DrrasHandler,),
        {
            "store": store,
            "cookie_secure": cookie_secure,
            "cookie_samesite": normalize_samesite(cookie_samesite),
            "cookie_partitioned": bool(cookie_partitioned),
            "allow_bearer_auth": bool(allow_bearer_auth),
        },
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def set_password_interactively(store: Store, role: str = "admin") -> int:
    print(f"Setting the DRRAS {role} password.\nDatabase: {store.path}")
    if store.has_password(role):
        print("A password is already configured for this role; the new one will replace it.")
    while True:
        password = getpass.getpass("New password (min %d chars): " % MIN_PASSWORD_LENGTH)
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"Too short - use at least {MIN_PASSWORD_LENGTH} characters.\n")
            continue
        if password != getpass.getpass("Repeat it: "):
            print("Those did not match, try again.\n")
            continue
        store.set_password(password, role)
        break
    print("Password stored (PBKDF2-HMAC-SHA256, salted).")
    return 0


def resolve_db_path(cli_value: str | None) -> Path:
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    env_value = os.environ.get("DRRAS_DB_PATH")
    if env_value:
        return Path(env_value).expanduser().resolve()
    return DEFAULT_DB_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DRRAS web UI + request review API")
    parser.add_argument("--set-password", action="store_true", help="create or reset a password, then exit")
    parser.add_argument("--role", choices=ROLES, default="admin", help="role for --set-password (default admin)")
    parser.add_argument("--seed-demo", action="store_true", help="insert sample incidents and exit")
    parser.add_argument("--db", default=None, help="SQLite file (default: $DRRAS_DB_PATH or backend/data/drras.sqlite3)")
    parser.add_argument("--host", default=os.environ.get("DRRAS_HOST", "0.0.0.0"), help="bind address")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("DRRAS_PORT", "8000")),
        help="port (default 8000; $PORT overrides for PaaS hosts)",
    )
    parser.add_argument(
        "--cookie-samesite",
        default=os.environ.get("DRRAS_COOKIE_SAMESITE", COOKIE_SAMESITE_DEFAULT),
        choices=COOKIE_SAMESITE_VALUES,
        type=normalize_samesite,
        help="session cookie SameSite policy (env: DRRAS_COOKIE_SAMESITE)",
    )
    parser.add_argument(
        "--allow-bearer-auth",
        action="store_true",
        default=os.environ.get("DRRAS_ALLOW_BEARER_AUTH", "") == "1",
        help="also return a bearer token on sign-in for embedded frames without cookies",
    )
    parser.add_argument(
        "--cookie-partitioned",
        action="store_true",
        default=os.environ.get("DRRAS_COOKIE_PARTITIONED", "") == "1",
        help="add CHIPS Partitioned (requires --cookie-samesite None)",
    )
    args = parser.parse_args(argv)

    if args.cookie_partitioned and args.cookie_samesite != "None":
        parser.error("--cookie-partitioned requires --cookie-samesite None")

    port_env = os.environ.get("PORT")
    if port_env and "--port" not in (argv or sys.argv[1:]):
        try:
            args.port = int(port_env)
        except ValueError:
            pass

    db_path = resolve_db_path(args.db)
    upload_env = os.environ.get("DRRAS_UPLOAD_DIR")
    upload_dir = Path(upload_env).expanduser().resolve() if upload_env else db_path.parent / "uploads"
    store = Store(db_path, upload_dir=upload_dir)

    if args.set_password:
        return set_password_interactively(store, args.role)

    if args.seed_demo:
        result = store.seed_demo()
        print(result["message"])
        for request_id in result.get("ids", []):
            print("  " + request_id)
        return 0

    for env_name, role in (("DRRAS_ADMIN_PASSWORD", "admin"), ("ADMIN_PASSWORD", "admin"),
                           ("DRRAS_OPERATOR_PASSWORD", "operator")):
        env_password = os.environ.get(env_name)
        if not env_password:
            continue
        if len(env_password) < MIN_PASSWORD_LENGTH:
            print(
                f"Warning: {env_name} is too short (minimum {MIN_PASSWORD_LENGTH} characters); ignoring.",
                file=sys.stderr,
            )
        elif not store.has_password(role):
            store.set_password(env_password, role)
            print(f"{role.title()} password initialised from {env_name}.")

    cookie_secure = os.environ.get("DRRAS_COOKIE_SECURE", "") == "1"
    try:
        httpd = make_server(
            args.host, args.port, store, cookie_secure,
            args.cookie_samesite, args.cookie_partitioned, args.allow_bearer_auth,
        )
    except OSError as err:
        print(f"Could not bind {args.host}:{args.port} - {err}", file=sys.stderr)
        print("Something else is probably using that port; try --port 8010.", file=sys.stderr)
        return 1

    print(f"DRRAS site : http://localhost:{args.port}/")
    print(f"Admin UI   : http://localhost:{args.port}/admin")
    print(f"Database   : {store.path}")
    print(f"Uploads    : {store.upload_dir}")
    cookie_flags = [f"SameSite={args.cookie_samesite}"]
    if cookie_secure or args.cookie_samesite == "None":
        cookie_flags.append("Secure")
    if args.cookie_partitioned and args.cookie_samesite == "None":
        cookie_flags.append("Partitioned")
    print("Cookie     : " + "; ".join(cookie_flags))
    print("Road routing: " + routing_status()["routingUrl"])
    if args.cookie_samesite == "None":
        print("           SameSite=None needs https (http://localhost excepted).")
    if not store.has_password():
        print("No admin password yet -> python3 backend/admin_server.py --set-password")
    print("Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
