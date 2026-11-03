"""SQLite storage and the DRRAS workflow.

One short-lived connection is opened per operation, which is safe with the
threaded HTTP server. Important decisions are written to the audit table so the
administrator can see what happened and why.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from allocation import rank_centres
from config import (
    ALLOCATION_STATUSES,
    AVAILABILITY,
    CENTRE_LABELS,
    DEFAULT_SETTINGS,
    DISASTER_LABELS,
    QUEUE_LABELS,
    RESOURCE_LABELS,
    RESOURCES,
    STATUS_LABELS,
    ApiError,
    json_dumps,
    json_loads,
    normalise_email,
    now_iso,
)
from geo import road_legs
from rules import assess_risk, auto_approval, find_duplicates
from seed import CENTRES, demo_requests

SCHEMA = """
CREATE TABLE IF NOT EXISTS citizen_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_login (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    password_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    csrf TEXT NOT NULL,
    role TEXT NOT NULL,
    user_id INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relief_requests (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES citizen_users(id),
    type TEXT NOT NULL,
    severity TEXT NOT NULL,
    people INTEGER NOT NULL,
    description TEXT NOT NULL,
    location_name TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    contact_name TEXT,
    contact_phone TEXT,
    contact_email TEXT,
    resources TEXT NOT NULL,
    status TEXT NOT NULL,
    review_queue TEXT,
    risk_score INTEGER NOT NULL DEFAULT 0,
    risk_level TEXT NOT NULL DEFAULT 'low',
    risk_reasons TEXT NOT NULL DEFAULT '[]',
    duplicate_matches TEXT NOT NULL DEFAULT '[]',
    auto_approved INTEGER NOT NULL DEFAULT 0,
    admin_note TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_evidence (
    id TEXT PRIMARY KEY,
    request_id TEXT REFERENCES relief_requests(id) ON DELETE SET NULL,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relief_centres (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    address TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    phone TEXT,
    availability TEXT NOT NULL,
    notes TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS centre_stock (
    centre_id TEXT NOT NULL REFERENCES relief_centres(id) ON DELETE CASCADE,
    resource TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY (centre_id, resource)
);
CREATE TABLE IF NOT EXISTS relief_allocations (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES relief_requests(id),
    centre_id TEXT NOT NULL REFERENCES relief_centres(id),
    items TEXT NOT NULL,
    status TEXT NOT NULL,
    distance_km REAL,
    duration_min INTEGER,
    distance_source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requests_status ON relief_requests(status);
CREATE INDEX IF NOT EXISTS idx_requests_created ON relief_requests(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_events(request_id, created_at);
CREATE INDEX IF NOT EXISTS idx_alloc_request ON relief_allocations(request_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_allocation
    ON relief_allocations(request_id) WHERE status != 'cancelled';
"""

PASSWORD_ITERATIONS = 200_000
SESSION_HOURS = 12
PUBLIC_ACTIONS = {
    "submitted", "auto_approved", "approved", "rejected", "info_requested",
    "resources_assigned", "dispatched", "delivered", "cancelled", "in_progress", "resolved",
}
ACTION_LABELS = {
    "submitted": "Report submitted",
    "auto_approved": "Automatically approved",
    "approved": "Approved by coordinator",
    "rejected": "Rejected",
    "info_requested": "More information requested",
    "resources_assigned": "Resources assigned",
    "dispatched": "Resources dispatched",
    "delivered": "Resources delivered",
    "cancelled": "Allocation cancelled",
    "in_progress": "Response started",
    "resolved": "Request resolved",
    "duplicate_flagged": "Duplicate warning raised",
    "settings_updated": "Settings updated",
    "centre_updated": "Centre updated",
}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), PASSWORD_ITERATIONS
        )
        return hmac.compare_digest(expected.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def _request_dict(row: sqlite3.Row, admin: bool = False) -> dict:
    data = {
        "id": row["id"],
        "disasterType": row["type"],
        "typeLabel": DISASTER_LABELS.get(row["type"], row["type"]),
        "severity": row["severity"],
        "people": row["people"],
        "description": row["description"],
        "locationName": row["location_name"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "resources": json_loads(row["resources"], {}),
        "status": row["status"],
        "statusLabel": STATUS_LABELS.get(row["status"], row["status"]),
        "riskLevel": row["risk_level"],
        "autoApproved": bool(row["auto_approved"]),
        "isDemo": bool(row["is_demo"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    if admin:
        matches = json_loads(row["duplicate_matches"], [])
        data.update({
            "userId": row["user_id"],
            "contactName": row["contact_name"],
            "contactPhone": row["contact_phone"],
            "contactEmail": row["contact_email"],
            "reviewQueue": row["review_queue"],
            "reviewQueueLabel": (
                QUEUE_LABELS.get(row["review_queue"], "Manual review")
                if row["review_queue"] else "—"
            ),
            "riskScore": row["risk_score"],
            "riskReasons": json_loads(row["risk_reasons"], []),
            "duplicateMatches": matches,
            "possibleDuplicate": any(item.get("isPossibleDuplicate") for item in matches),
            "adminNote": row["admin_note"],
        })
    elif row["status"] == "rejected" and row["admin_note"]:
        data["adminNote"] = row["admin_note"]
    return data


def _allocation_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "centreId": row["centre_id"],
        "centreName": row["centre_name"] if "centre_name" in row.keys() else None,
        "items": json_loads(row["items"], {}),
        "status": row["status"],
        "distanceKm": row["distance_km"],
        "durationMin": row["duration_min"],
        "distanceSource": row["distance_source"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


class Store:
    def __init__(self, path: Path, upload_dir: Path | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir = Path(upload_dir) if upload_dir else self.path.parent / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
                    (key, json_dumps(value)),
                )
        self._seed_centres()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ---------- accounts and sessions ----------

    def has_demo_data(self) -> bool:
        with self._connect() as conn:
            return conn.execute(
                "SELECT 1 FROM relief_requests WHERE is_demo = 1 LIMIT 1"
            ).fetchone() is not None

    def has_admin_password(self) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM admin_login WHERE id = 1").fetchone() is not None

    def set_admin_password(self, password: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO admin_login (id, password_hash, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET password_hash=excluded.password_hash, "
                "updated_at=excluded.updated_at",
                (hash_password(password), now_iso()),
            )

    def verify_admin_password(self, password: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT password_hash FROM admin_login WHERE id = 1").fetchone()
        return bool(row and verify_password(password, row["password_hash"]))

    def register_user(self, name: str, email: str, password: str) -> dict:
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO citizen_users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (name, normalise_email(email), hash_password(password), now_iso()),
                )
                user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            raise ApiError("An account with that email already exists.", 409) from None
        return {"id": user_id, "name": name, "email": normalise_email(email)}

    def verify_user(self, email: str, password: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM citizen_users WHERE email = ?", (normalise_email(email),)
            ).fetchone()
        if row and verify_password(password, row["password_hash"]):
            return {"id": row["id"], "name": row["name"], "email": row["email"]}
        return None

    def get_user(self, user_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT id, name, email FROM citizen_users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def create_session(self, role: str, user_id: int | None = None) -> dict:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        created = datetime.now(timezone.utc)
        expires = created + timedelta(hours=SESSION_HOURS)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO auth_sessions (token_hash, csrf, role, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (hashlib.sha256(token.encode()).hexdigest(), csrf, role, user_id,
                 created.isoformat(), expires.isoformat()),
            )
        return {"token": token, "csrf": csrf, "role": role, "userId": user_id}

    def get_session(self, token: str) -> dict | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM auth_sessions WHERE token_hash = ? AND expires_at > ?",
                (token_hash, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM auth_sessions WHERE token_hash = ?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )

    # ---------- settings ----------

    def get_settings(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        settings = dict(DEFAULT_SETTINGS)
        for row in rows:
            settings[row["key"]] = json_loads(row["value"], DEFAULT_SETTINGS.get(row["key"]))
        return settings

    def save_settings(self, settings: dict, actor: str) -> dict:
        with self._connect() as conn:
            for key, value in settings.items():
                conn.execute(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json_dumps(value)),
                )
            conn.execute(
                "INSERT INTO audit_events (request_id, action, actor, note, created_at) VALUES (NULL, ?, ?, ?, ?)",
                ("settings_updated", actor, "Auto-approval and duplicate rules changed", now_iso()),
            )
        return self.get_settings()

    # ---------- reports ----------

    def submit_request(self, data: dict, user_id: int | None, evidence_ids: list[str]) -> dict:
        settings = self.get_settings()
        created = now_iso()
        duplicate_matches = []
        with self._connect() as conn:
            window_start = (
                datetime.now(timezone.utc) - timedelta(hours=int(settings["duplicateWindowHours"]))
            ).isoformat()
            recent = conn.execute(
                "SELECT * FROM relief_requests WHERE created_at >= ? AND status != 'rejected'",
                (window_start,),
            ).fetchall()
            contact_count = 0
            for row in recent:
                same_phone = (
                    data.get("contact_phone") and str(row["contact_phone"] or "").replace(" ", "")[-10:]
                    == str(data["contact_phone"]).replace(" ", "")[-10:]
                )
                same_email = (
                    data.get("contact_email")
                    and normalise_email(row["contact_email"]) == data["contact_email"]
                )
                contact_count += 1 if (same_phone or same_email) else 0

        new_report = {**data, "created_at": created, "id": None}
        duplicate_matches = find_duplicates(new_report, [dict(row) for row in recent], settings)
        risk = assess_risk(new_report, duplicate_matches, contact_count)
        approved, approval_reason = auto_approval(new_report, risk, duplicate_matches, settings)
        if approved:
            status, queue = "approved", "auto_approval"
        else:
            status = "pending"
            queue = (
                "duplicate_review" if any(item["isPossibleDuplicate"] for item in duplicate_matches)
                else ("high_risk" if risk["level"] == "high" else "manual_review")
            )

        request_id = "REQ-" + secrets.token_hex(4).upper()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO relief_requests "
                "(id, user_id, type, severity, people, description, location_name, latitude, longitude, "
                "contact_name, contact_phone, contact_email, resources, status, review_queue, risk_score, "
                "risk_level, risk_reasons, duplicate_matches, auto_approved, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id, user_id, data["type"], data["severity"], data["people"],
                    data["description"], data["location_name"], data["latitude"], data["longitude"],
                    data["contact_name"], data["contact_phone"], data["contact_email"],
                    json_dumps(data["resources"]), status, queue, risk["score"], risk["level"],
                    json_dumps(risk["reasons"]), json_dumps(duplicate_matches),
                    1 if approved else 0, created, created,
                ),
            )
            for evidence_id in evidence_ids:
                conn.execute(
                    "UPDATE request_evidence SET request_id = ? WHERE id = ? AND request_id IS NULL",
                    (request_id, evidence_id),
                )
            self._audit(conn, request_id, "submitted", "citizen", "Report received")
            if approved:
                self._audit(conn, request_id, "auto_approved", "system", approval_reason)
            if duplicate_matches and not approved:
                self._audit(
                    conn, request_id, "duplicate_flagged", "system",
                    "Possible duplicate flagged for human review",
                )
        return self.get_request(request_id)

    def get_request(self, request_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM relief_requests WHERE id = ?", (request_id,)).fetchone()
            if not row:
                return None
            data = _request_dict(row, admin=True)
            data["history"] = self._history(conn, request_id, public=False)
            data["evidence"] = [
                {"id": item["id"], "name": item["original_name"], "type": item["mime_type"],
                 "size": item["size_bytes"]}
                for item in conn.execute(
                    "SELECT * FROM request_evidence WHERE request_id = ? ORDER BY created_at", (request_id,)
                ).fetchall()
            ]
            allocation = conn.execute(
                "SELECT a.*, c.name AS centre_name FROM relief_allocations a "
                "JOIN relief_centres c ON c.id = a.centre_id "
                "WHERE a.request_id = ? AND a.status != 'cancelled' "
                "ORDER BY a.created_at DESC LIMIT 1",
                (request_id,),
            ).fetchone()
            data["allocation"] = _allocation_dict(allocation)
        return data

    def get_public_request(self, request_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM relief_requests WHERE id = ?", (request_id,)).fetchone()
            if not row:
                return None
            data = _request_dict(row)
            data["history"] = self._history(conn, request_id, public=True)
            allocation = conn.execute(
                "SELECT a.*, c.name AS centre_name FROM relief_allocations a "
                "JOIN relief_centres c ON c.id = a.centre_id "
                "WHERE a.request_id = ? AND a.status != 'cancelled' "
                "ORDER BY a.created_at DESC LIMIT 1",
                (request_id,),
            ).fetchone()
            data["allocation"] = _allocation_dict(allocation)
        return data

    def list_my_requests(self, user_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM relief_requests WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        return [_request_dict(row) for row in rows]

    def _history(self, conn, request_id: str, public: bool) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM audit_events WHERE request_id = ? ORDER BY id", (request_id,)
        ).fetchall()
        history = []
        for row in rows:
            if public and row["action"] not in PUBLIC_ACTIONS:
                continue
            history.append({
                "action": row["action"],
                "label": ACTION_LABELS.get(row["action"], row["action"]),
                "note": row["note"] if (not public or row["action"] in {"approved", "rejected", "info_requested", "auto_approved"}) else None,
                "createdAt": row["created_at"],
            })
        return history

    def _audit(self, conn, request_id: str | None, action: str, actor: str, note: str = "") -> None:
        conn.execute(
            "INSERT INTO audit_events (request_id, action, actor, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (request_id, action, actor, note, now_iso()),
        )

    def list_requests(self, status: str = "", queue: str = "", search: str = "") -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM relief_requests ORDER BY created_at DESC").fetchall()
        items = []
        needle = search.lower().strip()
        for row in rows:
            if status and row["status"] != status:
                continue
            if queue and row["review_queue"] != queue:
                continue
            data = _request_dict(row, admin=True)
            if needle and not any(
                needle in str(data[key]).lower()
                for key in ("id", "locationName", "description", "disasterType")
            ):
                continue
            items.append(data)
        return items

    def apply_action(self, request_id: str, action: str, reason: str, actor: str) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM relief_requests WHERE id = ?", (request_id,)).fetchone()
            if not row:
                raise ApiError("Request not found.", 404)
            status = row["status"]
            if action == "approve":
                if status != "pending":
                    raise ApiError("Only a pending request can be approved.", 409)
                new_status, audit_action = "approved", "approved"
            elif action == "reject":
                if status not in ("pending", "approved"):
                    raise ApiError("This request cannot be rejected now.", 409)
                if not reason:
                    raise ApiError("Give a reason for rejecting the request.")
                active = conn.execute(
                    "SELECT 1 FROM relief_allocations WHERE request_id = ? AND status != 'cancelled'",
                    (request_id,),
                ).fetchone()
                if active:
                    raise ApiError("Cancel the active allocation before rejecting.", 409)
                new_status, audit_action = "rejected", "rejected"
            elif action == "request_info":
                if status != "pending" or not reason:
                    raise ApiError("A pending request and a message are required.")
                new_status, audit_action = "pending", "info_requested"
            elif action == "start":
                if status not in ("approved", "assigned"):
                    raise ApiError("Approve the request and assign resources before starting.", 409)
                new_status, audit_action = "in_progress", "in_progress"
            elif action == "resolve":
                if status not in ("approved", "assigned", "in_progress"):
                    raise ApiError("This request cannot be resolved yet.", 409)
                new_status, audit_action = "resolved", "resolved"
            else:
                raise ApiError("Unknown request action.")
            conn.execute(
                "UPDATE relief_requests SET status = ?, review_queue = ?, admin_note = COALESCE(?, admin_note), "
                "updated_at = ? WHERE id = ?",
                (new_status, None if action in ("approve", "reject") else row["review_queue"],
                 reason or None, now_iso(), request_id),
            )
            self._audit(conn, request_id, audit_action, actor, reason)
        return self.get_request(request_id)

    # ---------- evidence ----------

    def add_evidence(self, original_name: str, mime_type: str, content: bytes, extension: str) -> dict:
        evidence_id = "EV-" + secrets.token_hex(6).upper()
        stored_name = evidence_id + extension
        (self.upload_dir / stored_name).write_bytes(content)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO request_evidence (id, request_id, original_name, stored_name, mime_type, "
                "size_bytes, created_at) VALUES (?, NULL, ?, ?, ?, ?, ?)",
                (evidence_id, original_name[:120], stored_name, mime_type, len(content), now_iso()),
            )
        return {"id": evidence_id, "name": original_name, "type": mime_type, "size": len(content)}

    def get_evidence(self, evidence_id: str):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM request_evidence WHERE id = ?", (evidence_id,)).fetchone()
        return (row, self.upload_dir / row["stored_name"]) if row else None

    # ---------- centres and recommendations ----------

    def _seed_centres(self) -> None:
        with self._connect() as conn:
            if conn.execute("SELECT COUNT(*) AS n FROM relief_centres").fetchone()["n"]:
                return
            for centre in CENTRES:
                self._insert_centre(conn, centre, demo=True)

    def _insert_centre(self, conn, centre: dict, demo: bool) -> None:
        created = now_iso()
        conn.execute(
            "INSERT INTO relief_centres (id, name, category, address, latitude, longitude, phone, "
            "availability, notes, is_demo, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                centre["id"], centre["name"], centre["category"], centre.get("address", ""),
                centre["latitude"], centre["longitude"], centre.get("phone", ""),
                centre.get("availability", "available"), centre.get("notes", ""),
                1 if demo else 0, created, created,
            ),
        )
        for resource, quantity in centre.get("stock", {}).items():
            if resource in RESOURCES and int(quantity) > 0:
                conn.execute(
                    "INSERT INTO centre_stock (centre_id, resource, quantity) VALUES (?, ?, ?)",
                    (centre["id"], resource, int(quantity)),
                )

    def list_centres(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM relief_centres ORDER BY name").fetchall()
            stock_rows = conn.execute("SELECT * FROM centre_stock").fetchall()
        stocks: dict[str, dict] = {}
        for row in stock_rows:
            stocks.setdefault(row["centre_id"], {})[row["resource"]] = row["quantity"]
        return [{
            "id": row["id"], "name": row["name"], "category": row["category"],
            "categoryLabel": CENTRE_LABELS.get(row["category"], row["category"].replace("_", " ").title()),
            "address": row["address"], "latitude": row["latitude"], "longitude": row["longitude"],
            "phone": row["phone"], "availability": row["availability"], "notes": row["notes"],
            "isDemo": bool(row["is_demo"]), "stock": stocks.get(row["id"], {}),
        } for row in rows]

    def create_centre(self, data: dict) -> dict:
        centre_id = "HC-" + secrets.token_hex(3).upper()
        with self._connect() as conn:
            self._insert_centre(conn, {**data, "id": centre_id}, demo=False)
        return next(item for item in self.list_centres() if item["id"] == centre_id)

    def update_centre(self, centre_id: str, data: dict, actor: str) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM relief_centres WHERE id = ?", (centre_id,)).fetchone()
            if not row:
                raise ApiError("Help centre not found.", 404)
            fields = ["name", "category", "address", "latitude", "longitude", "phone", "availability", "notes"]
            values = {key: data.get(key, row[key]) for key in fields}
            conn.execute(
                "UPDATE relief_centres SET name=?, category=?, address=?, latitude=?, longitude=?, "
                "phone=?, availability=?, notes=?, updated_at=? WHERE id=?",
                (*[values[key] for key in fields], now_iso(), centre_id),
            )
            if "stock" in data:
                for resource, quantity in data["stock"].items():
                    conn.execute(
                        "INSERT INTO centre_stock (centre_id, resource, quantity) VALUES (?, ?, ?) "
                        "ON CONFLICT(centre_id, resource) DO UPDATE SET quantity=excluded.quantity",
                        (centre_id, resource, max(0, int(quantity))),
                    )
            self._audit(conn, None, "centre_updated", actor, f"Centre {centre_id} updated")
        return next(item for item in self.list_centres() if item["id"] == centre_id)

    def nearby_centres(self, lat: float, lon: float, category: str = "", availability: str = "",
                       resource: str = "", radius_km: float = 50, limit: int = 20) -> dict:
        centres = self.list_centres()
        from rules import haversine_km
        filtered = []
        for centre in centres:
            if category and centre["category"] != category:
                continue
            if availability and centre["availability"] != availability:
                continue
            if resource and int(centre["stock"].get(resource, 0)) <= 0:
                continue
            distance = haversine_km(lat, lon, centre["latitude"], centre["longitude"])
            if distance <= radius_km:
                filtered.append({**centre, "straightLineKm": round(distance, 2)})
        filtered.sort(key=lambda item: item["straightLineKm"])
        filtered = filtered[:limit]
        legs = road_legs((lat, lon), [(item["latitude"], item["longitude"]) for item in filtered])
        for centre, leg in zip(filtered, legs):
            centre.update({
                "distanceKm": leg["distanceKm"],
                "durationMin": leg["durationMin"],
                "distanceSource": leg["source"],
                "distanceNote": leg["note"],
            })
        return {
            "origin": {"latitude": lat, "longitude": lon},
            "centres": filtered,
            "count": len(filtered),
            "resourceLabels": RESOURCE_LABELS,
        }

    def recommendations(self, request_id: str) -> dict:
        request = self.get_request(request_id)
        if not request:
            raise ApiError("Request not found.", 404)
        if request["status"] not in ("approved", "assigned", "in_progress"):
            raise ApiError("Approve the request before finding help centres.", 409)
        centres = self.list_centres()
        legs = road_legs(
            (request["latitude"], request["longitude"]),
            [(item["latitude"], item["longitude"]) for item in centres],
        )
        enriched = []
        for centre, leg in zip(centres, legs):
            enriched.append({**centre, "distanceKm": leg["distanceKm"],
                             "durationMin": leg["durationMin"], "distanceSource": leg["source"]})
        return rank_centres(enriched, request)

    def allocate(self, request_id: str, centre_id: str, items: dict, actor: str,
                 distance: dict | None, override_reason: str) -> dict:
        if not items:
            raise ApiError("Choose at least one resource to assign.")
        with self._connect() as conn:
            request = conn.execute("SELECT * FROM relief_requests WHERE id = ?", (request_id,)).fetchone()
            if not request:
                raise ApiError("Request not found.", 404)
            if request["status"] not in ("approved", "assigned", "in_progress"):
                raise ApiError("Only approved requests can receive resources.", 409)
            active = conn.execute(
                "SELECT 1 FROM relief_allocations WHERE request_id = ? AND status != 'cancelled'",
                (request_id,),
            ).fetchone()
            if active:
                raise ApiError("This request already has an allocation. Cancel it first.", 409)
            centre = conn.execute("SELECT * FROM relief_centres WHERE id = ?", (centre_id,)).fetchone()
            if not centre:
                raise ApiError("Help centre not found.", 404)
            if centre["availability"] == "closed":
                raise ApiError("That centre is closed.", 409)
            requested = json_loads(request["resources"], {})
            stock = {
                row["resource"]: row["quantity"]
                for row in conn.execute("SELECT * FROM centre_stock WHERE centre_id = ?", (centre_id,))
            }
            clean = {}
            for resource, amount in items.items():
                quantity = int(amount)
                if resource not in RESOURCES or quantity <= 0:
                    continue
                if quantity > int(requested.get(resource, 0)):
                    raise ApiError(f"Assignment exceeds the requested quantity of {resource}.")
                if quantity > int(stock.get(resource, 0)):
                    raise ApiError(f"The centre only has {stock.get(resource, 0)} {resource}.")
                clean[resource] = quantity
            if not clean:
                raise ApiError("Choose at least one valid resource quantity.")
            covered = sum(clean.values())
            wanted = sum(int(value) for value in requested.values())
            if covered < wanted and not override_reason:
                raise ApiError("This is a partial allocation. Add an override reason.")
            for resource, quantity in clean.items():
                conn.execute(
                    "UPDATE centre_stock SET quantity = quantity - ? WHERE centre_id = ? AND resource = ?",
                    (quantity, centre_id, resource),
                )
            allocation_id = "ALLOC-" + secrets.token_hex(4).upper()
            distance = distance or {}
            conn.execute(
                "INSERT INTO relief_allocations (id, request_id, centre_id, items, status, distance_km, "
                "duration_min, distance_source, created_at, updated_at) VALUES (?, ?, ?, ?, 'assigned', ?, ?, ?, ?, ?)",
                (allocation_id, request_id, centre_id, json_dumps(clean),
                 distance.get("distanceKm"), distance.get("durationMin"),
                 distance.get("distanceSource") or "estimate", now_iso(), now_iso()),
            )
            conn.execute(
                "UPDATE relief_requests SET status = 'assigned', updated_at = ? WHERE id = ?",
                (now_iso(), request_id),
            )
            self._audit(
                conn, request_id, "resources_assigned", actor,
                f"{covered} unit(s) from {centre['name']}" + (f" — {override_reason}" if override_reason else ""),
            )
        return self.get_request(request_id)

    def list_allocations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT a.*, c.name AS centre_name, r.location_name FROM relief_allocations a "
                "JOIN relief_centres c ON c.id = a.centre_id "
                "JOIN relief_requests r ON r.id = a.request_id ORDER BY a.created_at DESC"
            ).fetchall()
        return [{**_allocation_dict(row), "requestId": row["request_id"],
                 "locationName": row["location_name"]} for row in rows]

    def update_allocation(self, allocation_id: str, action: str, actor: str) -> dict:
        if action not in ("dispatched", "delivered", "cancelled"):
            raise ApiError("Unknown allocation action.")
        with self._connect() as conn:
            allocation = conn.execute(
                "SELECT * FROM relief_allocations WHERE id = ?", (allocation_id,)
            ).fetchone()
            if not allocation:
                raise ApiError("Allocation not found.", 404)
            current = allocation["status"]
            if current in ("delivered", "cancelled"):
                raise ApiError("This allocation is already closed.", 409)
            if action == "dispatched" and current != "assigned":
                raise ApiError("Only an assigned allocation can be dispatched.", 409)
            if action == "delivered" and current != "dispatched":
                raise ApiError("Dispatch the allocation before marking it delivered.", 409)
            if action == "cancelled":
                for resource, quantity in json_loads(allocation["items"], {}).items():
                    conn.execute(
                        "INSERT INTO centre_stock (centre_id, resource, quantity) VALUES (?, ?, ?) "
                        "ON CONFLICT(centre_id, resource) DO UPDATE SET quantity = quantity + excluded.quantity",
                        (allocation["centre_id"], resource, int(quantity)),
                    )
            new_status = "cancelled" if action == "cancelled" else action
            conn.execute(
                "UPDATE relief_allocations SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now_iso(), allocation_id),
            )
            if action == "cancelled":
                conn.execute(
                    "UPDATE relief_requests SET status = 'approved', updated_at = ? WHERE id = ?",
                    (now_iso(), allocation["request_id"]),
                )
            elif action == "dispatched":
                conn.execute(
                    "UPDATE relief_requests SET status = 'in_progress', updated_at = ? WHERE id = ?",
                    (now_iso(), allocation["request_id"]),
                )
            else:
                conn.execute(
                    "UPDATE relief_requests SET status = 'resolved', updated_at = ? WHERE id = ?",
                    (now_iso(), allocation["request_id"]),
                )
            self._audit(conn, allocation["request_id"], new_status, actor,
                        f"Allocation {allocation_id} {new_status}")
        return self.get_request(allocation["request_id"])

    # ---------- dashboards and demo data ----------

    def public_overview(self) -> dict:
        with self._connect() as conn:
            counts = {row["status"]: row["n"] for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM relief_requests GROUP BY status"
            )}
            rows = conn.execute(
                "SELECT * FROM relief_requests WHERE status IN ('approved','assigned','in_progress') "
                "ORDER BY created_at DESC LIMIT 6"
            ).fetchall()
            centres = conn.execute("SELECT COUNT(*) AS n FROM relief_centres").fetchone()["n"]
            people = conn.execute(
                "SELECT COALESCE(SUM(people), 0) AS n FROM relief_requests "
                "WHERE status IN ('approved','assigned','in_progress','resolved')"
            ).fetchone()["n"]
            dispatches = conn.execute(
                "SELECT a.*, c.name AS centre_name, r.location_name FROM relief_allocations a "
                "JOIN relief_centres c ON c.id = a.centre_id JOIN relief_requests r ON r.id = a.request_id "
                "WHERE a.status IN ('dispatched','delivered') ORDER BY a.updated_at DESC LIMIT 5"
            ).fetchall()
        return {
            "stats": {
                "activeIncidents": counts.get("approved", 0) + counts.get("assigned", 0) + counts.get("in_progress", 0),
                "centres": centres,
                "peopleReached": people,
                "resolved": counts.get("resolved", 0),
            },
            "incidents": [_request_dict(row) for row in rows],
            "dispatches": [{
                "requestId": row["request_id"], "location": row["location_name"],
                "centre": row["centre_name"], "status": row["status"],
                "items": json_loads(row["items"], {}), "at": row["updated_at"],
            } for row in dispatches],
        }

    def admin_stats(self) -> dict:
        with self._connect() as conn:
            counts = {row["status"]: row["n"] for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM relief_requests GROUP BY status"
            )}
            queues = {row["review_queue"]: row["n"] for row in conn.execute(
                "SELECT review_queue, COUNT(*) AS n FROM relief_requests "
                "WHERE status = 'pending' GROUP BY review_queue"
            )}
            centres = conn.execute("SELECT COUNT(*) AS n FROM relief_centres").fetchone()["n"]
            stock = conn.execute("SELECT COALESCE(SUM(quantity), 0) AS n FROM centre_stock").fetchone()["n"]
            allocations = conn.execute(
                "SELECT COUNT(*) AS n FROM relief_allocations WHERE status != 'cancelled'"
            ).fetchone()["n"]
        return {
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "approved": counts.get("approved", 0),
            "rejected": counts.get("rejected", 0),
            "active": counts.get("assigned", 0) + counts.get("in_progress", 0),
            "resolved": counts.get("resolved", 0),
            "duplicates": queues.get("duplicate_review", 0),
            "highRisk": queues.get("high_risk", 0),
            "centres": centres,
            "stockUnits": stock,
            "allocations": allocations,
        }

    def seed_demo(self) -> dict:
        with self._connect() as conn:
            old = conn.execute(
                "SELECT * FROM relief_allocations WHERE request_id LIKE 'REQ-DEMO-%' AND status != 'cancelled'"
            ).fetchall()
            for allocation in old:
                for resource, quantity in json_loads(allocation["items"], {}).items():
                    conn.execute(
                        "INSERT INTO centre_stock (centre_id, resource, quantity) VALUES (?, ?, ?) "
                        "ON CONFLICT(centre_id, resource) DO UPDATE SET quantity = quantity + excluded.quantity",
                        (allocation["centre_id"], resource, int(quantity)),
                    )
            conn.execute("DELETE FROM relief_allocations WHERE request_id LIKE 'REQ-DEMO-%'")
            conn.execute("DELETE FROM request_evidence WHERE request_id LIKE 'REQ-DEMO-%'")
            conn.execute("DELETE FROM audit_events WHERE request_id LIKE 'REQ-DEMO-%'")
            conn.execute("DELETE FROM relief_requests WHERE id LIKE 'REQ-DEMO-%'")
            created = now_iso()
            for item in demo_requests():
                conn.execute(
                    "INSERT INTO relief_requests (id, user_id, type, severity, people, description, "
                    "location_name, latitude, longitude, contact_name, contact_phone, contact_email, "
                    "resources, status, review_queue, risk_score, risk_level, risk_reasons, "
                    "duplicate_matches, auto_approved, is_demo, created_at, updated_at) "
                    "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, 1, ?, ?)",
                    (
                        item["id"], item["type"], item["severity"], item["people"], item["description"],
                        item["location_name"], item["latitude"], item["longitude"], item["contact_name"],
                        item["contact_phone"], item["contact_email"], json_dumps(item["resources"]),
                        item["status"], item["queue"], item["risk"], item["risk_level"],
                        json_dumps([f"Sample data: {item['risk']} risk points"]), item["auto"], created, created,
                    ),
                )
                self._audit(conn, item["id"], "submitted", "demo", "Sample request")
                if item["status"] == "approved":
                    self._audit(conn, item["id"], "auto_approved", "system", "Sample auto-approval")
                if item["status"] == "resolved":
                    self._audit(conn, item["id"], "resolved", "demo", "Sample completed response")
            # The second demo report is a deliberate near-duplicate of the first.
            conn.execute(
                "UPDATE relief_requests SET duplicate_matches = ? WHERE id = 'REQ-DEMO-1002'",
                (json_dumps([{
                    "id": "REQ-DEMO-1001", "type": "FLOOD", "typeLabel": "Flood",
                    "locationName": "Raipur canal area, Dehradun", "distanceKm": 0.2,
                    "score": 86, "isPossibleDuplicate": True,
                    "reasons": ["0.2 km from an existing report (+30)",
                                "same disaster category (+25)",
                                "high description similarity (+21)",
                                "reported recently (+10)"],
                }]),),
            )
            # Give the assigned sample a real allocation so the detail view is complete.
            request = conn.execute("SELECT * FROM relief_requests WHERE id = 'REQ-DEMO-1003'").fetchone()
            centre = conn.execute("SELECT * FROM relief_centres WHERE id = 'HC-DDN-30'").fetchone()
            if request and centre:
                items = {"RescueTeam": 2, "Other": 5}
                for resource, quantity in items.items():
                    conn.execute(
                        "UPDATE centre_stock SET quantity = MAX(0, quantity - ?) "
                        "WHERE centre_id = ? AND resource = ?",
                        (quantity, centre["id"], resource),
                    )
                conn.execute(
                    "INSERT INTO relief_allocations (id, request_id, centre_id, items, status, "
                    "distance_km, duration_min, distance_source, created_at, updated_at) "
                    "VALUES ('ALLOC-DEMO-1003', 'REQ-DEMO-1003', 'HC-DDN-30', ?, 'assigned', 6.4, 14, "
                    "'estimate', ?, ?)",
                    (json_dumps(items), created, created),
                )
                self._audit(conn, request["id"], "resources_assigned", "demo",
                            "7 units from NDRF Rescue Base, Dehradun")
        return {"inserted": len(demo_requests()), "centres": len(self.list_centres())}
