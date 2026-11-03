"""SQLite persistence for DRRAS.

One short-lived connection per operation, so this is safe to use from
ThreadingHTTPServer's worker threads. The module owns the schema, the request
verification pipeline, the help-centre directory, resource allocations and the
audit trail.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import timedelta
from http import HTTPStatus
from pathlib import Path

from drras_allocation import recommend
from drras_common import (
    ACTIVE_DISASTER_STATUSES,
    ALLOCATION_STATUSES,
    CENTRE_AVAILABILITY,
    DEFAULT_DECISION_MESSAGES,
    DEFAULT_INVENTORY,
    DEFAULT_SETTINGS,
    EVIDENCE_ALLOWED_TYPES,
    EVIDENCE_MAX_BYTES,
    HELP_CENTRE_CATEGORIES,
    MAX_RESOURCE_QUANTITY,
    OPEN_STATUSES,
    RESOURCE_CATEGORIES,
    VERIFICATION_QUEUES,
    WORKFLOW_LABELS,
    WORKFLOW_STATUSES,
    ApiError,
    escape_html,
    iso,
    labelise,
    parse_iso,
    plan_submission_grant,
    utc_now,
)
from drras_geo import bearing_label, route_geometry, route_legs, routing_status
from drras_seed import DEMO_REQUESTS, HELP_CENTRES
from drras_verification import (
    assess_risk,
    find_duplicates,
    haversine_km,
    verification_route,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_credentials (
    id            INTEGER PRIMARY KEY,
    salt          BLOB    NOT NULL,
    iterations    INTEGER NOT NULL,
    password_hash BLOB    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'admin',
    updated_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    csrf_token  TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'admin',
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
    id                 TEXT    PRIMARY KEY,
    type               TEXT    NOT NULL,
    severity           TEXT    NOT NULL,
    affected_people    INTEGER NOT NULL CHECK (affected_people >= 0),
    required_resources TEXT    NOT NULL DEFAULT '[]',
    resource_quantities TEXT   NOT NULL DEFAULT '{}',
    granted_resources  TEXT    NOT NULL DEFAULT '{}',
    location_name      TEXT    NOT NULL,
    latitude           REAL    NOT NULL,
    longitude          REAL    NOT NULL,
    description        TEXT    NOT NULL DEFAULT '',
    contact_name       TEXT,
    contact_phone      TEXT,
    contact_email      TEXT,
    status             TEXT    NOT NULL DEFAULT 'pending',
    workflow_status    TEXT    NOT NULL DEFAULT 'submitted',
    verification_queue TEXT    NOT NULL DEFAULT 'manual_review',
    risk_score         INTEGER NOT NULL DEFAULT 0,
    risk_level         TEXT    NOT NULL DEFAULT 'low',
    risk_reasons       TEXT    NOT NULL DEFAULT '[]',
    duplicate_of       TEXT,
    duplicate_matches  TEXT    NOT NULL DEFAULT '[]',
    auto_decision      TEXT,
    merged_into        TEXT,
    linked_to          TEXT    NOT NULL DEFAULT '[]',
    flagged            INTEGER NOT NULL DEFAULT 0,
    info_requested     TEXT,
    user_message       TEXT,
    decision_message   TEXT,
    client_ip          TEXT,
    is_demo            INTEGER NOT NULL DEFAULT 0,
    submitted_at       TEXT    NOT NULL,
    updated_at         TEXT,
    decided_at         TEXT
);

CREATE TABLE IF NOT EXISTS inventory (
    category TEXT    PRIMARY KEY,
    quantity INTEGER NOT NULL CHECK (quantity >= 0)
);

CREATE TABLE IF NOT EXISTS login_attempts (
    ip            TEXT NOT NULL,
    attempted_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS help_centres (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL,
    address        TEXT NOT NULL DEFAULT '',
    latitude       REAL NOT NULL,
    longitude      REAL NOT NULL,
    phone          TEXT,
    availability   TEXT NOT NULL DEFAULT 'available',
    capacity_note  TEXT,
    notes          TEXT,
    is_seed        INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS centre_stock (
    centre_id  TEXT NOT NULL REFERENCES help_centres(id) ON DELETE CASCADE,
    category   TEXT NOT NULL,
    quantity   INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    PRIMARY KEY (centre_id, category)
);

CREATE TABLE IF NOT EXISTS allocations (
    id              TEXT PRIMARY KEY,
    request_id      TEXT NOT NULL,
    centre_id       TEXT NOT NULL REFERENCES help_centres(id),
    items           TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'assigned'
                    CHECK (status IN ('recommended','assigned','dispatched','delivered','cancelled')),
    distance_km     REAL,
    duration_min    INTEGER,
    distance_source TEXT,
    rationale       TEXT NOT NULL DEFAULT '[]',
    override_reason TEXT,
    created_by      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    action     TEXT NOT NULL,
    actor      TEXT NOT NULL,
    role       TEXT,
    reason     TEXT,
    details    TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL,
    kind            TEXT NOT NULL,
    message         TEXT NOT NULL,
    visible_to_user INTEGER NOT NULL DEFAULT 1,
    actor           TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id            TEXT PRIMARY KEY,
    request_id    TEXT,
    original_name TEXT NOT NULL,
    stored_name   TEXT NOT NULL,
    mime_type     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submission_attempts (
    ip           TEXT NOT NULL,
    attempted_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
CREATE INDEX IF NOT EXISTS idx_requests_workflow ON requests(workflow_status);
CREATE INDEX IF NOT EXISTS idx_requests_submitted ON requests(submitted_at);
CREATE INDEX IF NOT EXISTS idx_login_ip_time ON login_attempts(ip, attempted_at);
CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_log(request_id, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_request ON notifications(request_id, created_at);
CREATE INDEX IF NOT EXISTS idx_evidence_hash ON evidence(sha256);
-- One live allocation per centre/request; cancelled rows do not block a retry.
CREATE UNIQUE INDEX IF NOT EXISTS idx_allocations_active
    ON allocations(request_id, centre_id) WHERE status != 'cancelled';
"""

MAGIC_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}


class Store:
    """SQLite persistence and the application's domain operations."""

    def __init__(self, path: Path, upload_dir: Path | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir = Path(upload_dir) if upload_dir else self.path.parent / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            for category, quantity in DEFAULT_INVENTORY.items():
                conn.execute(
                    "INSERT OR IGNORE INTO inventory (category, quantity) VALUES (?, ?)",
                    (category, quantity),
                )
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )
            self._seed_centres(conn)

    # ------------------------------------------------------------------
    # connection / schema
    # ------------------------------------------------------------------

    @staticmethod
    def _migrate(conn) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(requests)")}
        workflow_added = "workflow_status" not in columns
        additions = (
            ("description", "TEXT NOT NULL DEFAULT ''"),
            ("contact_name", "TEXT"),
            ("contact_phone", "TEXT"),
            ("contact_email", "TEXT"),
            ("workflow_status", "TEXT NOT NULL DEFAULT 'submitted'"),
            ("verification_queue", "TEXT NOT NULL DEFAULT 'manual_review'"),
            ("risk_score", "INTEGER NOT NULL DEFAULT 0"),
            ("risk_level", "TEXT NOT NULL DEFAULT 'low'"),
            ("risk_reasons", "TEXT NOT NULL DEFAULT '[]'"),
            ("duplicate_of", "TEXT"),
            ("duplicate_matches", "TEXT NOT NULL DEFAULT '[]'"),
            ("auto_decision", "TEXT"),
            ("merged_into", "TEXT"),
            ("linked_to", "TEXT NOT NULL DEFAULT '[]'"),
            ("flagged", "INTEGER NOT NULL DEFAULT 0"),
            ("info_requested", "TEXT"),
            ("client_ip", "TEXT"),
            ("is_demo", "INTEGER NOT NULL DEFAULT 0"),
            ("updated_at", "TEXT"),
        )
        for name, declaration in additions:
            if name not in columns:
                conn.execute(f"ALTER TABLE requests ADD COLUMN {name} {declaration}")

        session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "role" not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")

        credential_columns = {row["name"] for row in conn.execute("PRAGMA table_info(admin_credentials)")}
        if "role" not in credential_columns:
            conn.execute("ALTER TABLE admin_credentials ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")

        # Only rows that predate the workflow column need a projection.
        if workflow_added:
            conn.execute(
                "UPDATE requests SET workflow_status = CASE "
                " WHEN status = 'accepted' THEN 'approved' "
                " WHEN status = 'rejected' THEN 'rejected' "
                " ELSE 'awaiting_approval' END"
            )
        conn.execute("UPDATE requests SET updated_at = submitted_at WHERE updated_at IS NULL")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _seed_centres(self, conn) -> None:
        existing = conn.execute("SELECT COUNT(*) AS n FROM help_centres").fetchone()["n"]
        if existing:
            return
        now = iso(utc_now())
        for centre in HELP_CENTRES:
            conn.execute(
                """
                INSERT OR IGNORE INTO help_centres (
                    id, name, category, address, latitude, longitude, phone,
                    availability, capacity_note, notes, is_seed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    centre["id"], centre["name"], centre["category"], centre["address"],
                    centre["latitude"], centre["longitude"], centre["phone"],
                    centre["availability"], centre.get("capacity_note"), centre.get("notes"),
                    now, now,
                ),
            )
            for category, quantity in centre.get("stock", {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO centre_stock (centre_id, category, quantity) VALUES (?, ?, ?)",
                    (centre["id"], category, int(quantity)),
                )

    # ------------------------------------------------------------------
    # credentials, sessions, login throttling (role-aware)
    # ------------------------------------------------------------------

    def set_password(self, password: str, role: str = "admin") -> None:
        if role not in ("admin", "operator"):
            raise ValueError("Role must be 'admin' or 'operator'.")
        salt = secrets.token_bytes(16)
        iterations = 210_000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        credential_id = 1 if role == "admin" else 2
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_credentials (id, salt, iterations, password_hash, role, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    salt = excluded.salt,
                    iterations = excluded.iterations,
                    password_hash = excluded.password_hash,
                    role = excluded.role,
                    updated_at = excluded.updated_at
                """,
                (credential_id, salt, iterations, digest, role, iso(utc_now())),
            )
            self._audit(
                conn, None, "operator_password_updated", f"{role} credential", role, None,
                {"role": role}, iso(utc_now()),
            )

    def has_password(self, role: str = "admin") -> bool:
        credential_id = 1 if role == "admin" else 2
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 AS ok FROM admin_credentials WHERE id = ?", (credential_id,)
            ).fetchone()
        return row is not None

    def _credential_row(self, role: str) -> sqlite3.Row | None:
        credential_id = 1 if role == "admin" else 2
        with self._connect() as conn:
            return conn.execute(
                "SELECT salt, iterations, password_hash, role FROM admin_credentials WHERE id = ?",
                (credential_id,),
            ).fetchone()

    def verify_password(self, password: str, role: str = "admin") -> bool:
        row = self._credential_row(role)
        if row is None:
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes(row["salt"]), int(row["iterations"])
        )
        import hmac

        return hmac.compare_digest(candidate, bytes(row["password_hash"]))

    def authenticate(self, password: str) -> str | None:
        """Returns the role for a valid password, checking admin first."""
        if self.verify_password(password, "admin"):
            return "admin"
        if self.has_password("operator") and self.verify_password(password, "operator"):
            return "operator"
        return None

    def create_session(self, role: str = "admin") -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, csrf_token, role, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (self._hash(token), csrf, role, iso(now), iso(now + timedelta(hours=8))),
            )
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso(now),))
        return token, csrf

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def get_session(self, token: str) -> sqlite3.Row | None:
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token_hash, csrf_token, role, expires_at FROM sessions WHERE token_hash = ?",
                (self._hash(token),),
            ).fetchone()
        if row is None:
            return None
        if (parse_iso(row["expires_at"]) or utc_now()) <= utc_now():
            self.delete_session(token)
            return None
        return row

    def check_csrf(self, token: str, csrf: str) -> bool:
        session = self.get_session(token)
        if session is None or not csrf:
            return False
        import hmac

        return hmac.compare_digest(session["csrf_token"], csrf)

    def delete_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (self._hash(token),))

    def too_many_login_attempts(self, ip: str, limit: int = 8, window_seconds: int = 900) -> bool:
        cutoff = time.time() - window_seconds
        with self._connect() as conn:
            conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (cutoff,))
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM login_attempts WHERE ip = ? AND attempted_at >= ?",
                (ip, cutoff),
            ).fetchone()
        return bool(row) and int(row["n"]) >= limit

    def record_login_failure(self, ip: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO login_attempts (ip, attempted_at) VALUES (?, ?)", (ip, time.time())
            )

    def clear_login_failures(self, ip: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------

    def get_settings(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        settings = dict(DEFAULT_SETTINGS)
        for row in rows:
            try:
                settings[row["key"]] = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                continue
        return settings

    def update_settings(self, updates: dict, actor: str = "admin", role: str = "admin") -> dict:
        merged = {**self.get_settings(), **updates}
        medium = int(merged.get("mediumRiskThreshold", 25))
        high = int(merged.get("highRiskThreshold", 55))
        if medium >= high:
            raise ApiError(
                "The medium-risk threshold must be lower than the high-risk threshold.",
                HTTPStatus.BAD_REQUEST,
            )
        if int(merged.get("autoApproveMaxRisk", 20)) >= medium:
            raise ApiError(
                "The auto-approval risk ceiling must stay below the medium-risk threshold, "
                "so medium and high risk reports always receive human review.",
                HTTPStatus.BAD_REQUEST,
            )
        with self._connect() as conn:
            for key, value in updates.items():
                if key not in DEFAULT_SETTINGS:
                    raise ApiError(f"Unknown setting: {key}")
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value)),
                )
            self._audit(
                conn, None, "settings_updated", actor, role, None, updates, iso(utc_now())
            )
        return self.get_settings()

    # ------------------------------------------------------------------
    # inventory (central reserve)
    # ------------------------------------------------------------------

    def get_inventory(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT category, quantity FROM inventory").fetchall()
        return {row["category"]: int(row["quantity"]) for row in rows}

    def set_inventory(self, quantities: dict[str, int], actor: str = "admin", role: str = "admin") -> dict[str, int]:
        with self._connect() as conn:
            for category, quantity in quantities.items():
                conn.execute(
                    "INSERT INTO inventory (category, quantity) VALUES (?, ?) "
                    "ON CONFLICT(category) DO UPDATE SET quantity = excluded.quantity",
                    (category, int(quantity)),
                )
            self._audit(
                conn, None, "inventory_updated", actor, role, None, quantities, iso(utc_now())
            )
            rows = conn.execute("SELECT category, quantity FROM inventory").fetchall()
        return {row["category"]: int(row["quantity"]) for row in rows}

    @staticmethod
    def _load_inventory(conn) -> dict[str, int]:
        rows = conn.execute("SELECT category, quantity FROM inventory").fetchall()
        return {row["category"]: int(row["quantity"]) for row in rows}

    # ------------------------------------------------------------------
    # submission rate limiting
    # ------------------------------------------------------------------

    def check_submission_rate(self, ip: str, limit: int, window_minutes: int) -> bool:
        cutoff = time.time() - window_minutes * 60
        with self._connect() as conn:
            conn.execute("DELETE FROM submission_attempts WHERE attempted_at < ?", (cutoff,))
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM submission_attempts WHERE ip = ? AND attempted_at >= ?",
                (ip, cutoff),
            ).fetchone()
        return bool(row) and int(row["n"]) >= limit

    def record_submission_attempt(self, ip: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO submission_attempts (ip, attempted_at) VALUES (?, ?)",
                (ip, time.time()),
            )

    # ------------------------------------------------------------------
    # evidence
    # ------------------------------------------------------------------

    def add_evidence(self, original_name: str, mime_type: str, raw: bytes) -> dict:
        if mime_type not in EVIDENCE_ALLOWED_TYPES:
            raise ApiError("Only JPEG, PNG or PDF files can be attached.")
        if not raw:
            raise ApiError("The uploaded file is empty.")
        if len(raw) > EVIDENCE_MAX_BYTES:
            raise ApiError("Each file must be 5 MB or smaller.", 413)
        if not any(raw.startswith(signature) for signature in MAGIC_SIGNATURES[mime_type]):
            raise ApiError("The file content does not match its declared type.")
        digest = hashlib.sha256(raw).hexdigest()
        evidence_id = "EV-" + secrets.token_hex(8).upper()
        extension = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}[mime_type]
        stored_name = evidence_id.lower() + extension
        (self.upload_dir / stored_name).write_bytes(raw)
        safe_name = "".join(ch for ch in original_name if ch.isalnum() or ch in "._- ")[:120] or "evidence"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence (id, request_id, original_name, stored_name, mime_type,
                                      size_bytes, sha256, created_at)
                VALUES (?, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (evidence_id, safe_name, stored_name, mime_type, len(raw), digest, iso(utc_now())),
            )
        return {
            "id": evidence_id,
            "originalName": safe_name,
            "mimeType": mime_type,
            "sizeBytes": len(raw),
            "sha256": digest,
        }

    def get_evidence(self, evidence_id: str) -> tuple[sqlite3.Row, Path] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if row is None:
            return None
        path = self.upload_dir / row["stored_name"]
        if not path.is_file():
            return None
        return row, path

    def _evidence_by_ids(self, conn, ids: list[str]) -> list[sqlite3.Row]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        return conn.execute(
            f"SELECT * FROM evidence WHERE id IN ({placeholders})", ids
        ).fetchall()

    def _link_evidence(self, conn, request_id: str, ids: list[str]) -> None:
        rows = self._evidence_by_ids(conn, ids)
        if len(rows) != len(ids):
            raise ApiError("One or more uploaded files could not be found.")
        for row in rows:
            if row["request_id"] and row["request_id"] != request_id:
                raise ApiError("That file is already attached to another request.")
            conn.execute("UPDATE evidence SET request_id = ? WHERE id = ?", (request_id, row["id"]))

    def _reused_evidence(self, conn, ids: list[str], request_id: str | None = None) -> list[dict]:
        rows = self._evidence_by_ids(conn, ids)
        if not rows:
            return []
        hashes = [row["sha256"] for row in rows]
        placeholders = ",".join("?" for _ in hashes)
        reused = conn.execute(
            f"SELECT id, request_id, sha256 FROM evidence "
            f"WHERE sha256 IN ({placeholders}) AND request_id IS NOT NULL "
            f"AND request_id != ?",
            (*hashes, request_id or ""),
        ).fetchall()
        return [dict(row) for row in reused]

    # ------------------------------------------------------------------
    # help centres
    # ------------------------------------------------------------------

    @staticmethod
    def _centre_row_to_dict(row: sqlite3.Row, stock: dict[str, int]) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "categoryLabel": labelise(row["category"]),
            "address": row["address"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "phone": row["phone"],
            "availability": row["availability"],
            "availabilityLabel": row["availability"].replace("_", " ").title(),
            "capacityNote": row["capacity_note"],
            "notes": row["notes"],
            "isSeed": bool(row["is_seed"]),
            "stock": stock,
            "updatedAt": row["updated_at"],
        }

    def _load_centres(self, conn) -> list[dict]:
        rows = conn.execute("SELECT * FROM help_centres ORDER BY name").fetchall()
        stock_rows = conn.execute(
            "SELECT centre_id, category, quantity FROM centre_stock"
        ).fetchall()
        stock: dict[str, dict[str, int]] = {}
        for item in stock_rows:
            stock.setdefault(item["centre_id"], {})[item["category"]] = int(item["quantity"])
        return [self._centre_row_to_dict(row, stock.get(row["id"], {})) for row in rows]

    def list_help_centres(self) -> list[dict]:
        with self._connect() as conn:
            return self._load_centres(conn)

    def get_help_centre(self, centre_id: str) -> dict | None:
        with self._connect() as conn:
            return next((c for c in self._load_centres(conn) if c["id"] == centre_id), None)

    def update_help_centre(
        self, centre_id: str, updates: dict, actor: str = "admin", role: str = "admin"
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM help_centres WHERE id = ?", (centre_id,)).fetchone()
            if row is None:
                raise ApiError("That help centre does not exist.", 404)
            fields = {
                "name": "name",
                "category": "category",
                "address": "address",
                "phone": "phone",
                "availability": "availability",
                "capacityNote": "capacity_note",
                "notes": "notes",
            }
            for key, column in fields.items():
                if key in updates:
                    conn.execute(
                        f"UPDATE help_centres SET {column} = ? WHERE id = ?",
                        (updates[key], centre_id),
                    )
            for key in ("latitude", "longitude"):
                if key in updates:
                    conn.execute(
                        f"UPDATE help_centres SET {key} = ? WHERE id = ?",
                        (float(updates[key]), centre_id),
                    )
            if isinstance(updates.get("stock"), dict):
                for category, quantity in updates["stock"].items():
                    if category not in RESOURCE_CATEGORIES:
                        raise ApiError(f"Unknown resource category: {category}")
                    quantity = int(quantity)
                    if quantity < 0 or quantity > MAX_RESOURCE_QUANTITY:
                        raise ApiError(f"Quantity for {category} must be zero or more.")
                    conn.execute(
                        "INSERT INTO centre_stock (centre_id, category, quantity) VALUES (?, ?, ?) "
                        "ON CONFLICT(centre_id, category) DO UPDATE SET quantity = excluded.quantity",
                        (centre_id, category, quantity),
                    )
            conn.execute(
                "UPDATE help_centres SET updated_at = ? WHERE id = ?", (iso(utc_now()), centre_id)
            )
            self._audit(
                conn, None, "help_centre_updated", actor, role, None,
                {"centreId": centre_id, **updates}, iso(utc_now()),
            )
            centre = next((c for c in self._load_centres(conn) if c["id"] == centre_id), None)
        if centre is None:
            raise ApiError("That help centre does not exist.", 404)
        return centre

    def create_help_centre(self, payload: dict, actor: str = "admin", role: str = "admin") -> dict:
        now = iso(utc_now())
        category = str(payload.get("category") or "").strip()
        if category not in HELP_CENTRE_CATEGORIES:
            raise ApiError("Unknown help-centre category.")
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ApiError("Centre name is required.")
        try:
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
        except (KeyError, TypeError, ValueError):
            raise ApiError("Latitude and longitude are required.") from None
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ApiError("Coordinates are out of range.")
        availability = str(payload.get("availability") or "available")
        if availability not in CENTRE_AVAILABILITY:
            raise ApiError("Unknown availability status.")
        centre_id = "HC-" + secrets.token_hex(3).upper()
        stock = payload.get("stock") if isinstance(payload.get("stock"), dict) else {}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO help_centres (id, name, category, address, latitude, longitude, phone,
                                          availability, capacity_note, notes, is_seed, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    centre_id, escape_html(name), category, escape_html(str(payload.get("address") or "")),
                    latitude, longitude, str(payload.get("phone") or ""),
                    availability, escape_html(str(payload.get("capacityNote") or "")),
                    escape_html(str(payload.get("notes") or "")), now, now,
                ),
            )
            for item, quantity in stock.items():
                if item in RESOURCE_CATEGORIES:
                    conn.execute(
                        "INSERT OR REPLACE INTO centre_stock (centre_id, category, quantity) VALUES (?, ?, ?)",
                        (centre_id, item, max(0, int(quantity))),
                    )
            self._audit(
                conn, None, "help_centre_created", actor, role, None,
                {"centreId": centre_id, "name": name}, now,
            )
            centre = next((c for c in self._load_centres(conn) if c["id"] == centre_id), None)
        if centre is None:  # pragma: no cover - defensive
            raise ApiError("The help centre could not be created.", 500)
        return centre

    def _centres_with_distances(self, conn, latitude: float, longitude: float) -> list[dict]:
        centres = self._load_centres(conn)
        origin = (float(latitude), float(longitude))
        centres.sort(
            key=lambda c: haversine_km(origin[0], origin[1], c["latitude"], c["longitude"])
        )
        # One routing call covers the nearest centres; the rest keep explicit
        # straight-line ordering for the list.
        nearest = centres[:24]
        legs = route_legs(origin, [(c["latitude"], c["longitude"]) for c in nearest])
        by_id = {c["id"]: leg for c, leg in zip(nearest, legs)}
        for centre in centres:
            leg = by_id.get(centre["id"])
            if leg:
                centre["distanceKm"] = leg["distanceKm"]
                centre["durationMin"] = leg["durationMin"]
                centre["distanceSource"] = leg["source"]
                centre["straightLineKm"] = leg["straightLineKm"]
                centre["distanceNote"] = leg.get("note")
            else:
                straight = haversine_km(origin[0], origin[1], centre["latitude"], centre["longitude"])
                centre["distanceKm"] = round(straight * 1.34, 2)
                centre["durationMin"] = max(1, round(straight * 1.34 / 30 * 60))
                centre["distanceSource"] = "estimate"
                centre["straightLineKm"] = round(straight, 2)
                centre["distanceNote"] = "Estimated road distance."
            centre["bearing"] = bearing_label(origin, (centre["latitude"], centre["longitude"]))
        return centres

    def nearby_centres(
        self,
        latitude: float,
        longitude: float,
        *,
        category: str | None = None,
        radius_km: float | None = None,
        availability: str | None = None,
        resource: str | None = None,
        limit: int = 20,
        include_empty: bool = True,
    ) -> dict:
        with self._connect() as conn:
            centres = self._centres_with_distances(conn, latitude, longitude)
        filtered = []
        for centre in centres:
            if category and category != "all" and centre["category"] != category:
                continue
            if availability and availability != "all":
                if availability == "open" and centre["availability"] == "closed":
                    continue
                if availability not in ("open", "all") and centre["availability"] != availability:
                    continue
            if radius_km and float(centre["distanceKm"]) > radius_km:
                continue
            if resource and resource != "all" and int(centre["stock"].get(resource, 0) or 0) <= 0:
                continue
            if not include_empty and not any(int(value) > 0 for value in centre["stock"].values()):
                continue
            filtered.append(centre)
        filtered.sort(key=lambda c: (c["distanceKm"], c["name"]))
        result = filtered[: max(1, min(limit, 50))]
        source = "osrm" if any(c["distanceSource"] == "osrm" for c in centres) else "estimate"
        return {
            "origin": {"latitude": latitude, "longitude": longitude},
            "centres": result,
            "total": len(filtered),
            "routing": {
                **routing_status(),
                "resultSource": source,
                "note": (
                    "Distance and travel time from OSRM road routing."
                    if source == "osrm"
                    else "Road routing is unavailable, so distances are scaled estimates, not routed values."
                ),
            },
        }

    # ------------------------------------------------------------------
    # request creation + automated verification
    # ------------------------------------------------------------------

    @staticmethod
    def _new_request_id() -> str:
        return f"REQ-{secrets.token_hex(5).upper()}"

    @staticmethod
    def _legacy_status(workflow_status: str, merged_into: str | None) -> str:
        if merged_into:
            return "merged"
        if workflow_status == "rejected":
            return "rejected"
        if workflow_status in ("approved", "resources_assigned", "in_progress", "resolved"):
            return "accepted"
        return "pending"

    def _duplicate_pool(self, conn, submitted_at, window_hours: float) -> list[dict]:
        cutoff = iso(submitted_at - timedelta(hours=window_hours))
        rows = conn.execute(
            "SELECT * FROM requests WHERE submitted_at >= ? AND submitted_at <= ? "
            "ORDER BY submitted_at DESC LIMIT 500",
            (cutoff, iso(submitted_at)),
        ).fetchall()
        return [dict(row) for row in rows]

    def _recent_fingerprints(self, conn, submitted_at, hours: float = 6) -> list[dict]:
        cutoff = iso(submitted_at - timedelta(hours=hours))
        rows = conn.execute(
            "SELECT contact_phone, contact_email, client_ip, latitude, longitude, "
            "location_name, submitted_at FROM requests WHERE submitted_at >= ? AND submitted_at <= ?",
            (cutoff, iso(submitted_at)),
        ).fetchall()
        return [
            {
                "phone": row["contact_phone"],
                "email": row["contact_email"],
                "ip": row["client_ip"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "location_name": row["location_name"],
                "submitted_at": row["submitted_at"],
            }
            for row in rows
        ]

    def submit_request(
        self,
        data: dict,
        *,
        client_ip: str = "",
        submitted_at=None,
        evidence_ids: list[str] | None = None,
        is_demo: bool = False,
    ) -> dict:
        """Validated request in, verified and queued request out.

        Verification is synchronous so the user immediately sees where their
        report went. No path here can reject a report.
        """
        submitted = submitted_at or utc_now()
        stamp = iso(submitted)
        settings = self.get_settings()
        duplicate_window = float(settings.get("duplicateWindowHours", 72))
        description = str(data.get("description") or "").strip()
        contact_name = str(data.get("contactName") or "").strip()[:120]
        contact_phone = str(data.get("contactPhone") or "").strip()[:40]
        contact_email = str(data.get("contactEmail") or "").strip()[:160]
        evidence_ids = [str(item) for item in (evidence_ids or [])][:5]
        request_id = self._new_request_id()

        snake_new = {
            "id": request_id,
            "type": data["type"],
            "severity": data["severity"],
            "affected_people": int(data["affectedPeople"]),
            "required_resources": list(data.get("requiredResources") or []),
            "resource_quantities": dict(data.get("resourceQuantities") or {}),
            "description": description,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "contact_email": contact_email,
            "location_name": data["locationName"],
            "latitude": float(data["latitude"]),
            "longitude": float(data["longitude"]),
            "submitted_at": stamp,
            "client_ip": client_ip,
            "evidence": evidence_ids,
        }

        with self._connect() as conn:
            pool = self._duplicate_pool(conn, submitted, duplicate_window)
            duplicates = find_duplicates(
                snake_new,
                pool,
                window_hours=duplicate_window,
                threshold=int(settings.get("duplicateThreshold", 60)),
            )
            reused = self._reused_evidence(conn, evidence_ids)
            recent = self._recent_fingerprints(conn, submitted)
            risk = assess_risk(
                snake_new,
                duplicates=duplicates,
                recent_submissions=recent,
                reused_evidence=reused,
                settings=settings,
                now=submitted,
            )
            workflow_status, queue, explanation = verification_route(
                risk, duplicates, settings, snake_new
            )
            auto_approved = workflow_status == "approved"
            legacy_status = self._legacy_status(workflow_status, None)
            inventory = self._load_inventory(conn)
            granted, user_message = plan_submission_grant(
                dict(data.get("resourceQuantities") or {}), inventory, data["severity"]
            )
            decided_at = stamp if auto_approved else None
            decision_message = DEFAULT_DECISION_MESSAGES["approved"] if auto_approved else None
            duplicate_of = (
                duplicates["matches"][0]["id"] if duplicates.get("isPossibleDuplicate") else None
            )
            conn.execute(
                """
                INSERT INTO requests (
                    id, type, severity, affected_people, required_resources, resource_quantities,
                    granted_resources, location_name, latitude, longitude, description, contact_name,
                    contact_phone, contact_email, status, workflow_status, verification_queue,
                    risk_score, risk_level, risk_reasons, duplicate_of, duplicate_matches,
                    auto_decision, linked_to, flagged, user_message, decision_message, client_ip,
                    is_demo, submitted_at, updated_at, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 0,
                          ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id, data["type"], data["severity"], int(data["affectedPeople"]),
                    json.dumps(list(data.get("requiredResources") or [])),
                    json.dumps(dict(data.get("resourceQuantities") or {})),
                    json.dumps(granted), data["locationName"], float(data["latitude"]),
                    float(data["longitude"]), description, contact_name or None,
                    contact_phone or None, contact_email or None, legacy_status, workflow_status,
                    queue, int(risk["score"]), risk["level"], json.dumps(risk),
                    duplicate_of or None, json.dumps(duplicates.get("matches") or []),
                    explanation, user_message, decision_message, client_ip or None,
                    1 if is_demo else 0, stamp, stamp, decided_at,
                ),
            )
            self._link_evidence(conn, request_id, evidence_ids)
            self._audit(
                conn, request_id, "submitted", "public", None, None,
                {
                    "type": data["type"],
                    "severity": data["severity"],
                    "riskLevel": risk["level"],
                    "riskScore": risk["score"],
                },
                stamp,
            )
            self._audit(
                conn, request_id, "verification_completed", "system", "automation",
                explanation,
                {
                    "queue": queue,
                    "riskLevel": risk["level"],
                    "riskScore": risk["score"],
                    "duplicateMatches": [
                        {"id": m["id"], "similarity": m["similarity"]} for m in duplicates["matches"]
                    ],
                },
                stamp,
            )
            if auto_approved:
                self._audit(
                    conn, request_id, "auto_approved", "system", "automation",
                    explanation, {"rules": settings.get("autoApproveMaxRisk")}, stamp,
                )
            self._notify(
                conn, request_id, "status", self._submission_message(workflow_status, duplicates, duplicate_of),
                actor="system", at=stamp,
            )
            if user_message:
                self._notify(conn, request_id, "supply_note", user_message, actor="system", at=stamp)

        record = self.get_request(request_id)
        if record is None:  # pragma: no cover - defensive
            raise ApiError("The request could not be saved.", 500)
        return record

    @staticmethod
    def _submission_message(workflow_status: str, duplicates: dict, duplicate_of: str | None) -> str:
        if workflow_status == "possible_duplicate":
            return (
                "Your report has been received. It looks similar to an existing report"
                + (f" ({duplicate_of})" if duplicate_of else "")
                + ", so a coordinator will confirm whether they describe the same incident. "
                "Your report has NOT been rejected or discarded."
            )
        if workflow_status == "under_verification":
            return (
                "Your report has been received. A few details need human verification before "
                "a decision is made. It remains in the queue and has not been rejected."
            )
        if workflow_status == "approved":
            return (
                "Your report has been received and approved automatically under the command "
                "centre's configured rules. It is now eligible for resource allocation."
            )
        return (
            "Your report has been received and is awaiting a coordinator's review. "
            "You can track progress with your request ID."
        )

    def create_request(self, data: dict) -> dict:
        """Backwards-compatible entry point used by the original API/tests."""
        return self.submit_request(
            data,
            client_ip=str(data.get("clientIp") or ""),
            evidence_ids=[str(item) for item in data.get("evidence") or []],
        )

    # ------------------------------------------------------------------
    # serialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_json(raw: object, fallback):
        try:
            return json.loads(raw) if raw is not None else fallback
        except (TypeError, json.JSONDecodeError):
            return fallback

    @classmethod
    def _risk_payload(cls, raw: object) -> dict:
        parsed = cls._decode_json(raw, {})
        if isinstance(parsed, list):
            return {"score": 0, "level": "low", "reasons": parsed, "checks": [], "engine": "legacy"}
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def _row_to_admin_dict(cls, row: sqlite3.Row, detail: bool = False) -> dict:
        resources = cls._decode_json(row["required_resources"], [])
        if not isinstance(resources, list):
            resources = []
        quantities = cls._decode_json(row["resource_quantities"], {})
        granted = cls._decode_json(row["granted_resources"], {})
        matches = cls._decode_json(row["duplicate_matches"], [])
        linked = cls._decode_json(row["linked_to"], [])
        risk = cls._risk_payload(row["risk_reasons"])

        def counts(raw: dict) -> dict[str, int]:
            result: dict[str, int] = {}
            for key, value in (raw or {}).items():
                try:
                    result[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
            return result

        workflow = row["workflow_status"] or "submitted"
        payload = {
            "id": row["id"],
            "type": row["type"],
            "severity": row["severity"],
            "affectedPeople": int(row["affected_people"]),
            "requiredResources": resources,
            "resourceQuantities": counts(quantities),
            "grantedResources": counts(granted),
            "locationName": row["location_name"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "description": row["description"] or "",
            "contactName": row["contact_name"],
            "contactPhone": row["contact_phone"],
            "contactEmail": row["contact_email"],
            "status": row["status"],
            "workflowStatus": workflow,
            "workflowLabel": WORKFLOW_LABELS.get(workflow, labelise(workflow)),
            "verificationQueue": row["verification_queue"],
            "riskScore": int(row["risk_score"] or 0),
            "riskLevel": row["risk_level"] or "low",
            "risk": risk,
            "autoDecision": row["auto_decision"],
            "duplicateOf": row["duplicate_of"],
            "duplicates": matches if isinstance(matches, list) else [],
            "mergedInto": row["merged_into"],
            "linkedTo": linked if isinstance(linked, list) else [],
            "flagged": bool(row["flagged"]),
            "infoRequested": row["info_requested"],
            "submittedAt": row["submitted_at"],
            "updatedAt": row["updated_at"] or row["submitted_at"],
            "decidedAt": row["decided_at"],
            "userMessage": row["user_message"],
            "decisionMessage": row["decision_message"],
            "isDemo": bool(row["is_demo"]) if "is_demo" in row.keys() else False,
        }
        if detail:
            payload["evidence"] = []
            payload["allocations"] = []
            payload["notifications"] = []
            payload["audit"] = []
        return payload

    @classmethod
    def _row_to_public_dict(cls, row: sqlite3.Row) -> dict:
        admin = cls._row_to_admin_dict(row)
        workflow = admin["workflowStatus"]
        verification_summary = {
            "possible_duplicate": "Being checked against a similar recent report.",
            "under_verification": "Awaiting human verification of the submitted details.",
            "awaiting_approval": "In the coordinator's approval queue.",
            "approved": "Verified and approved. Eligible for resource allocation.",
            "rejected": "Reviewed and closed by the command centre.",
            "resources_assigned": "Resources have been assigned to this location.",
            "in_progress": "Response is in progress.",
            "resolved": "This request has been resolved.",
            "submitted": "Received and queued for verification.",
        }.get(workflow, "Received.")
        return {
            "id": admin["id"],
            "type": admin["type"],
            "severity": admin["severity"],
            "affectedPeople": admin["affectedPeople"],
            "requiredResources": admin["requiredResources"],
            "resourceQuantities": admin["resourceQuantities"],
            "grantedResources": admin["grantedResources"],
            "locationName": admin["locationName"],
            "latitude": admin["latitude"],
            "longitude": admin["longitude"],
            "description": admin["description"],
            "workflowStatus": workflow,
            "workflowLabel": admin["workflowLabel"],
            "verification": {
                "summary": verification_summary,
                "queue": admin["verificationQueue"],
                "humanReview": workflow
                in ("under_verification", "possible_duplicate", "awaiting_approval"),
            },
            "duplicateOf": admin["duplicateOf"],
            "submittedAt": admin["submittedAt"],
            "updatedAt": admin["updatedAt"],
            "decidedAt": admin["decidedAt"],
            "userMessage": admin["userMessage"],
            "decisionMessage": admin["decisionMessage"],
            "notifications": [],
            "allocations": [],
        }

    def _detail(self, conn, record: dict) -> dict:
        request_id = record["id"]
        evidence_rows = conn.execute(
            "SELECT id, original_name, mime_type, size_bytes, sha256, created_at "
            "FROM evidence WHERE request_id = ? ORDER BY created_at",
            (request_id,),
        ).fetchall()
        record["evidence"] = [
            {
                "id": row["id"],
                "originalName": row["original_name"],
                "mimeType": row["mime_type"],
                "sizeBytes": int(row["size_bytes"]),
                "sha256": row["sha256"],
                "url": f"/api/admin/evidence/{row['id']}",
                "uploadedAt": row["created_at"],
            }
            for row in evidence_rows
        ]
        record["allocations"] = [
            self._allocation_to_dict(row)
            for row in conn.execute(
                "SELECT * FROM allocations WHERE request_id = ? ORDER BY created_at DESC",
                (request_id,),
            ).fetchall()
        ]
        record["notifications"] = [
            {
                "id": row["id"],
                "kind": row["kind"],
                "message": row["message"],
                "visibleToUser": bool(row["visible_to_user"]),
                "actor": row["actor"],
                "createdAt": row["created_at"],
            }
            for row in conn.execute(
                "SELECT * FROM notifications WHERE request_id = ? ORDER BY id",
                (request_id,),
            ).fetchall()
        ]
        record["audit"] = [
            self._audit_to_dict(row)
            for row in conn.execute(
                "SELECT * FROM audit_log WHERE request_id = ? ORDER BY id",
                (request_id,),
            ).fetchall()
        ]
        return record

    @staticmethod
    def _allocation_to_dict(row: sqlite3.Row) -> dict:
        items = Store._decode_json(row["items"], {})
        rationale = Store._decode_json(row["rationale"], [])
        return {
            "id": row["id"],
            "requestId": row["request_id"],
            "centreId": row["centre_id"],
            "items": items if isinstance(items, dict) else {},
            "status": row["status"],
            "distanceKm": row["distance_km"],
            "durationMin": row["duration_min"],
            "distanceSource": row["distance_source"],
            "rationale": rationale if isinstance(rationale, list) else [],
            "overrideReason": row["override_reason"],
            "createdBy": row["created_by"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _audit_to_dict(row: sqlite3.Row) -> dict:
        details = Store._decode_json(row["details"], {})
        return {
            "id": row["id"],
            "requestId": row["request_id"],
            "action": row["action"],
            "actor": row["actor"],
            "role": row["role"],
            "reason": row["reason"],
            "details": details if isinstance(details, dict) else {},
            "createdAt": row["created_at"],
        }

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def get_request(self, request_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                return None
            record = self._row_to_admin_dict(row)
            return self._detail(conn, record)

    def get_public_request(self, request_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                return None
            record = self._row_to_public_dict(row)
            record["notifications"] = [
                {
                    "kind": item["kind"],
                    "message": item["message"],
                    "createdAt": item["created_at"],
                }
                for item in conn.execute(
                    "SELECT kind, message, created_at FROM notifications "
                    "WHERE request_id = ? AND visible_to_user = 1 ORDER BY id",
                    (request_id,),
                ).fetchall()
            ]
            allocations = conn.execute(
                "SELECT a.*, c.name AS centre_name, c.category AS centre_category, c.phone AS centre_phone "
                "FROM allocations a JOIN help_centres c ON c.id = a.centre_id "
                "WHERE a.request_id = ? AND a.status != 'cancelled' ORDER BY a.created_at",
                (request_id,),
            ).fetchall()
            record["allocations"] = [
                {
                    "centreName": row["centre_name"],
                    "centreCategory": row["centre_category"],
                    "centrePhone": row["centre_phone"],
                    "items": self._decode_json(row["items"], {}),
                    "status": row["status"],
                    "distanceKm": row["distance_km"],
                    "durationMin": row["duration_min"],
                    "distanceSource": row["distance_source"],
                    "createdAt": row["created_at"],
                }
                for row in allocations
            ]
            return record

    def list_requests(self, limit: int = 1000) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests ORDER BY submitted_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_admin_dict(row) for row in rows]

    def list_audit(self, limit: int = 300, request_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if request_id:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE request_id = ? ORDER BY id DESC LIMIT ?",
                    (request_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._audit_to_dict(row) for row in rows]

    def list_notifications(self, limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "id": row["id"],
                "requestId": row["request_id"],
                "kind": row["kind"],
                "message": row["message"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # audit / notification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _audit(conn, request_id, action, actor, role, reason, details, at) -> None:
        conn.execute(
            "INSERT INTO audit_log (request_id, action, actor, role, reason, details, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (request_id, action, actor, role, reason, json.dumps(details or {}), at),
        )

    @staticmethod
    def _notify(conn, request_id, kind, message, actor="system", visible=True, at=None) -> None:
        conn.execute(
            "INSERT INTO notifications (request_id, kind, message, visible_to_user, actor, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (request_id, kind, message, 1 if visible else 0, actor, at or iso(utc_now())),
        )

    # ------------------------------------------------------------------
    # decisions / workflow
    # ------------------------------------------------------------------

    def set_request_status(self, request_id: str, status: str, message: str | None = None) -> dict:
        """Legacy entry point (``accepted`` / ``rejected``).

        Kept because the original public form and its tests use it. Approval
        through this path also allocates the promised quantities from the central
        reserve, exactly as before.
        """
        if status == "accepted":
            return self.approve_request(
                request_id, message=message, actor="admin", role="admin",
                deduct_reserve=True, legacy=True,
            )
        if status == "rejected":
            return self.reject_request(
                request_id, message=message, reason=None, actor="admin", role="admin", legacy=True
            )
        raise ApiError("Status must be 'accepted' or 'rejected'.")

    def _load_row(self, conn, request_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise ApiError("That request no longer exists.", 404)
        return row

    def approve_request(
        self,
        request_id: str,
        *,
        message: str | None = None,
        reason: str | None = None,
        actor: str = "admin",
        role: str = "admin",
        deduct_reserve: bool = False,
        legacy: bool = False,
    ) -> dict:
        now = iso(utc_now())
        with self._connect() as conn:
            row = self._load_row(conn, request_id)
            workflow = row["workflow_status"] or "submitted"
            if legacy and row["status"] != "pending":
                raise ApiError(f"Request {request_id} was already {row['status']}.", 409)
            if workflow in ("rejected", "resolved"):
                raise ApiError(f"Request {request_id} was already {workflow}.", 409)
            if workflow == "approved" and not legacy:
                raise ApiError(f"Request {request_id} is already approved.", 409)

            granted = self._decode_json(row["granted_resources"], {})
            decision_message = (message or "").strip() or DEFAULT_DECISION_MESSAGES["approved"]
            if deduct_reserve:
                granted, decision_message = self._deduct_reserve(
                    conn, row, decision_message
                )
            conn.execute(
                """
                UPDATE requests SET status = ?, workflow_status = 'approved', decision_message = ?,
                    decided_at = ?, updated_at = ?, info_requested = NULL
                WHERE id = ?
                """,
                ("accepted", decision_message, now, now, request_id),
            )
            allocation_note = None
            if granted and deduct_reserve:
                self._notify(conn, request_id, "allocation", self._granted_message(granted), actor=actor, at=now)
                allocation_note = granted
            self._audit(
                conn, request_id, "approved", actor, role, reason or message,
                {"grantedResources": granted, "legacy": legacy}, now,
            )
            self._notify(
                conn, request_id, "status",
                "Your request has been APPROVED. " + (message or DEFAULT_DECISION_MESSAGES["approved"]),
                actor=actor, at=now,
            )
            conn.execute(
                "UPDATE requests SET granted_resources = ? WHERE id = ?",
                (json.dumps(granted), request_id),
            )
        record = self.get_request(request_id)
        if record is None:  # pragma: no cover
            raise ApiError("That request no longer exists.", 404)
        return record

    @staticmethod
    def _granted_message(granted: dict[str, int]) -> str:
        detail = ", ".join(f"{amount} {category}" for category, amount in sorted(granted.items()))
        return f"Resources reserved from the central reserve: {detail}."

    def _deduct_reserve(self, conn, row: sqlite3.Row, decision_message: str) -> tuple[dict, str]:
        requested = self._decode_json(row["resource_quantities"], {})
        granted: dict[str, int] = {}
        if not requested:
            return granted, decision_message
        inventory = self._load_inventory(conn)
        for category, quantity in requested.items():
            available = inventory.get(category, 0)
            delivered = min(int(quantity), available)
            if delivered > 0:
                granted[category] = delivered
                inventory[category] = available - delivered
        for category, quantity in inventory.items():
            conn.execute(
                "UPDATE inventory SET quantity = ? WHERE category = ?", (quantity, category)
            )
        short = {
            category: (quantity, granted.get(category, 0))
            for category, quantity in requested.items()
            if granted.get(category, 0) < int(quantity)
        }
        if short:
            detail = "; ".join(
                f"{delivered} of {quantity} {category}"
                for category, (quantity, delivered) in sorted(short.items())
            )
            decision_message += (
                " Supplies note: only the stock at this moment could be provided — "
                f"{detail}; this much only can be provided at the moment. The remainder "
                "follows when supplies are replenished."
            )
        return granted, decision_message

    def reject_request(
        self,
        request_id: str,
        *,
        message: str | None = None,
        reason: str | None = None,
        actor: str = "admin",
        role: str = "admin",
        legacy: bool = False,
    ) -> dict:
        now = iso(utc_now())
        with self._connect() as conn:
            row = self._load_row(conn, request_id)
            workflow = row["workflow_status"] or "submitted"
            if legacy and row["status"] != "pending":
                raise ApiError(f"Request {request_id} was already {row['status']}.", 409)
            if workflow in ("rejected", "resolved"):
                raise ApiError(f"Request {request_id} was already {workflow}.", 409)
            if workflow in ("approved", "resources_assigned", "in_progress") and not legacy:
                raise ApiError(
                    "This request is already approved. Resolve or cancel the response instead of rejecting it.",
                    409,
                )
            decision_message = (message or "").strip() or DEFAULT_DECISION_MESSAGES["rejected"]
            conn.execute(
                "UPDATE requests SET status = 'rejected', workflow_status = 'rejected', "
                "decision_message = ?, decided_at = ?, updated_at = ? WHERE id = ?",
                (decision_message, now, now, request_id),
            )
            self._audit(
                conn, request_id, "rejected", actor, role, reason or message,
                {"previousStatus": workflow}, now,
            )
            self._notify(
                conn, request_id, "status",
                "Your request was reviewed and REJECTED. " + (message or ""),
                actor=actor, at=now,
            )
        record = self.get_request(request_id)
        if record is None:  # pragma: no cover
            raise ApiError("That request no longer exists.", 404)
        return record

    def request_info(
        self, request_id: str, *, reason: str, actor: str = "admin", role: str = "admin"
    ) -> dict:
        now = iso(utc_now())
        if not str(reason or "").strip():
            raise ApiError("Explain what information is needed.")
        with self._connect() as conn:
            row = self._load_row(conn, request_id)
            conn.execute(
                "UPDATE requests SET workflow_status = 'under_verification', "
                "verification_queue = 'manual_review', info_requested = ?, updated_at = ? WHERE id = ?",
                (reason.strip(), now, request_id),
            )
            self._audit(conn, request_id, "info_requested", actor, role, reason, {}, now)
            self._notify(
                conn, request_id, "action_required",
                "The command centre needs more information: " + reason.strip(),
                actor=actor, at=now,
            )
        record = self.get_request(request_id)
        if record is None:  # pragma: no cover
            raise ApiError("That request no longer exists.", 404)
        return record

    def flag_request(
        self, request_id: str, *, reason: str, actor: str = "admin", role: str = "admin"
    ) -> dict:
        now = iso(utc_now())
        if not str(reason or "").strip():
            raise ApiError("A reason is required to flag a request.")
        with self._connect() as conn:
            self._load_row(conn, request_id)
            conn.execute(
                "UPDATE requests SET flagged = 1, updated_at = ? WHERE id = ?", (now, request_id)
            )
            self._audit(conn, request_id, "flagged", actor, role, reason, {}, now)
        record = self.get_request(request_id)
        if record is None:  # pragma: no cover
            raise ApiError("That request no longer exists.", 404)
        return record

    def merge_request(
        self, request_id: str, target_id: str, *, reason: str | None = None,
        actor: str = "admin", role: str = "admin",
    ) -> dict:
        now = iso(utc_now())
        if request_id == target_id:
            raise ApiError("A request cannot be merged into itself.")
        with self._connect() as conn:
            row = self._load_row(conn, request_id)
            target = conn.execute("SELECT id, location_name FROM requests WHERE id = ?", (target_id,)).fetchone()
            if target is None:
                raise ApiError("The request to merge into does not exist.", 404)
            if row["merged_into"]:
                raise ApiError(f"Request {request_id} is already merged into {row['merged_into']}.", 409)
            conn.execute(
                "UPDATE requests SET merged_into = ?, duplicate_of = ?, workflow_status = 'resolved', "
                "status = 'merged', decision_message = ?, decided_at = ?, updated_at = ? WHERE id = ?",
                (
                    target_id, target_id, "Merged into " + target_id + " — both reports describe the same incident.",
                    now, now, request_id,
                ),
            )
            self._audit(
                conn, request_id, "merged", actor, role, reason,
                {"mergedInto": target_id, "targetLocation": target["location_name"]}, now,
            )
            self._notify(
                conn, request_id, "status",
                f"Your report was merged with {target_id}, which covers the same incident. "
                "Relief operations continue under that request; your information was not discarded.",
                actor=actor, at=now,
            )
            # The surviving request keeps a pointer for auditing.
            linked = self._decode_json(
                conn.execute("SELECT linked_to FROM requests WHERE id = ?", (target_id,)).fetchone()["linked_to"],
                [],
            )
            if request_id not in linked:
                linked.append(request_id)
            conn.execute(
                "UPDATE requests SET linked_to = ?, updated_at = ? WHERE id = ?",
                (json.dumps(linked), now, target_id),
            )
            self._audit(
                conn, target_id, "merged_source_linked", actor, role, reason,
                {"mergedFrom": request_id}, now,
            )
        record = self.get_request(request_id)
        if record is None:  # pragma: no cover
            raise ApiError("That request no longer exists.", 404)
        return record

    def link_request(
        self, request_id: str, target_id: str, *, reason: str | None = None,
        actor: str = "admin", role: str = "admin",
    ) -> dict:
        now = iso(utc_now())
        if request_id == target_id:
            raise ApiError("A request cannot be linked to itself.")
        with self._connect() as conn:
            self._load_row(conn, request_id)
            target = conn.execute("SELECT id FROM requests WHERE id = ?", (target_id,)).fetchone()
            if target is None:
                raise ApiError("The related request does not exist.", 404)
            linked = self._decode_json(
                conn.execute("SELECT linked_to FROM requests WHERE id = ?", (request_id,)).fetchone()["linked_to"],
                [],
            )
            if target_id not in linked:
                linked.append(target_id)
            conn.execute(
                "UPDATE requests SET linked_to = ?, updated_at = ? WHERE id = ?",
                (json.dumps(linked), now, request_id),
            )
            self._audit(conn, request_id, "linked", actor, role, reason, {"linkedTo": target_id}, now)
            self._notify(
                conn, request_id, "status",
                f"This report has been linked to related report {target_id}. Both remain open.",
                actor=actor, visible=False, at=now,
            )
        record = self.get_request(request_id)
        if record is None:  # pragma: no cover
            raise ApiError("That request no longer exists.", 404)
        return record

    def keep_separate(
        self, request_id: str, *, reason: str | None = None,
        actor: str = "admin", role: str = "admin",
    ) -> dict:
        now = iso(utc_now())
        with self._connect() as conn:
            row = self._load_row(conn, request_id)
            workflow = row["workflow_status"] or "submitted"
            next_status = workflow
            if workflow in ("possible_duplicate", "submitted"):
                next_status = "awaiting_approval"
            conn.execute(
                "UPDATE requests SET duplicate_of = NULL, workflow_status = ?, "
                "verification_queue = 'manual_review', updated_at = ? WHERE id = ?",
                (next_status, now, request_id),
            )
            self._audit(
                conn, request_id, "kept_separate", actor, role, reason,
                {"previousStatus": workflow, "duplicateMatches": self._decode_json(row["duplicate_matches"], [])},
                now,
            )
            self._notify(
                conn, request_id, "status",
                "A coordinator reviewed the similar report and confirmed this is a separate incident. "
                "It continues through the approval queue.",
                actor=actor, at=now,
            )
        record = self.get_request(request_id)
        if record is None:  # pragma: no cover
            raise ApiError("That request no longer exists.", 404)
        return record

    def transition_request(
        self, request_id: str, target_status: str, *, reason: str | None = None,
        actor: str = "admin", role: str = "admin",
    ) -> dict:
        now = iso(utc_now())
        if target_status not in WORKFLOW_STATUSES:
            raise ApiError("Unknown workflow status.")
        allowed = {
            "in_progress": ("resources_assigned", "approved"),
            "resolved": ("in_progress", "resources_assigned", "approved"),
        }
        with self._connect() as conn:
            row = self._load_row(conn, request_id)
            current = row["workflow_status"] or "submitted"
            if current not in allowed.get(target_status, ()):
                raise ApiError(
                    f"Cannot move request {request_id} from {current} to {target_status}.", 409
                )
            conn.execute(
                "UPDATE requests SET workflow_status = ?, updated_at = ? WHERE id = ?",
                (target_status, now, request_id),
            )
            self._audit(
                conn, request_id, target_status, actor, role, reason,
                {"from": current, "to": target_status}, now,
            )
            message = {
                "in_progress": "Response is now in progress at your location.",
                "resolved": "Your request has been marked resolved. Thank you for reporting.",
            }[target_status]
            self._notify(conn, request_id, "status", message, actor=actor, at=now)
        record = self.get_request(request_id)
        if record is None:  # pragma: no cover
            raise ApiError("That request no longer exists.", 404)
        return record

    def apply_action(
        self,
        request_id: str,
        action: str,
        *,
        actor: str = "admin",
        role: str = "admin",
        reason: str | None = None,
        message: str | None = None,
        target_id: str | None = None,
    ) -> dict:
        action = str(action or "").strip().lower()
        if action in ("approve", "approved", "accept", "accepted"):
            return self.approve_request(
                request_id, message=message, reason=reason, actor=actor, role=role
            )
        if action in ("reject", "rejected"):
            if not (reason or message):
                raise ApiError("A reason is required when rejecting a request.")
            return self.reject_request(
                request_id, message=message, reason=reason, actor=actor, role=role
            )
        if action in ("request_info", "request-information", "need_info"):
            return self.request_info(request_id, reason=reason or message or "", actor=actor, role=role)
        if action in ("flag", "flagged"):
            return self.flag_request(request_id, reason=reason or message or "", actor=actor, role=role)
        if action == "merge":
            if not target_id:
                raise ApiError("Choose the request to merge into.")
            return self.merge_request(
                request_id, target_id, reason=reason or message, actor=actor, role=role
            )
        if action == "link":
            if not target_id:
                raise ApiError("Choose the request to link with.")
            return self.link_request(
                request_id, target_id, reason=reason or message, actor=actor, role=role
            )
        if action in ("keep_separate", "keep-separate"):
            return self.keep_separate(request_id, reason=reason or message, actor=actor, role=role)
        if action in ("in_progress", "start"):
            return self.transition_request(
                request_id, "in_progress", reason=reason or message, actor=actor, role=role
            )
        if action == "resolve":
            return self.transition_request(
                request_id, "resolved", reason=reason or message, actor=actor, role=role
            )
        raise ApiError("Unknown action.")

    # ------------------------------------------------------------------
    # allocation
    # ------------------------------------------------------------------

    def allocation_recommendations(self, request_id: str, limit: int = 6) -> dict:
        record = self.get_request(request_id)
        if record is None:
            raise ApiError("That request does not exist.", 404)
        if record["workflowStatus"] not in ("approved", "resources_assigned", "in_progress"):
            raise ApiError(
                "Resource allocation is available once a request is approved.", 409
            )
        with self._connect() as conn:
            centres = self._centres_with_distances(conn, record["latitude"], record["longitude"])
            load_rows = conn.execute(
                "SELECT centre_id, items FROM allocations WHERE status IN ('assigned','dispatched')"
            ).fetchall()
        active_load: dict[str, int] = {}
        for row in load_rows:
            items = self._decode_json(row["items"], {})
            active_load[row["centre_id"]] = active_load.get(row["centre_id"], 0) + sum(
                int(value or 0) for value in items.values()
            )
        for centre in centres:
            centre["activeLoad"] = active_load.get(centre["id"], 0)
        request_payload = {
            "severity": record["severity"],
            "required_resources": record["requiredResources"],
            "resource_quantities": record["resourceQuantities"],
        }
        result = recommend(centres, request_payload, limit=limit)
        result["request"] = {
            "id": record["id"],
            "severity": record["severity"],
            "locationName": record["locationName"],
            "latitude": record["latitude"],
            "longitude": record["longitude"],
            "workflowStatus": record["workflowStatus"],
        }
        result["existingAllocations"] = record.get("allocations", [])
        return result

    def allocate(
        self,
        request_id: str,
        centre_id: str,
        *,
        items: dict | None = None,
        actor: str = "admin",
        role: str = "admin",
        override_reason: str | None = None,
        distance: dict | None = None,
    ) -> dict:
        now = iso(utc_now())
        with self._connect() as conn:
            row = self._load_row(conn, request_id)
            workflow = row["workflow_status"]
            if workflow not in ("approved", "resources_assigned", "in_progress"):
                raise ApiError("Only an approved request can receive resources.", 409)
            centre = conn.execute("SELECT * FROM help_centres WHERE id = ?", (centre_id,)).fetchone()
            if centre is None:
                raise ApiError("That help centre does not exist.", 404)
            if centre["availability"] == "closed":
                raise ApiError("That centre is closed. Choose another centre or reopen it first.", 409)

            stock_rows = conn.execute(
                "SELECT category, quantity FROM centre_stock WHERE centre_id = ?", (centre_id,)
            ).fetchall()
            stock = {item["category"]: int(item["quantity"]) for item in stock_rows}
            requested = {
                str(category): int(amount)
                for category, amount in (items or {}).items()
                if int(amount) > 0
            }
            if not requested:
                raise ApiError("Choose at least one resource to allocate.")
            for category in requested:
                if category not in RESOURCE_CATEGORIES:
                    raise ApiError(f"Unknown resource category: {category}")
            short = {
                category: (amount, stock.get(category, 0))
                for category, amount in requested.items()
                if amount > stock.get(category, 0)
            }
            if short:
                detail = ", ".join(
                    f"{category}: requested {amount}, available {available}"
                    for category, (amount, available) in short.items()
                )
                raise ApiError(
                    f"That centre cannot cover this allocation ({detail}). "
                    "Reduce the quantities or split the allocation across centres.",
                    409,
                )
            allocation_id = "ALL-" + secrets.token_hex(4).upper()
            try:
                conn.execute(
                    """
                    INSERT INTO allocations (id, request_id, centre_id, items, status, distance_km,
                        duration_min, distance_source, rationale, override_reason, created_by,
                        created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'assigned', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        allocation_id, request_id, centre_id, json.dumps(requested),
                        (distance or {}).get("distanceKm"), (distance or {}).get("durationMin"),
                        (distance or {}).get("distanceSource"),
                        json.dumps((distance or {}).get("factors") or []),
                        override_reason, actor, now, now,
                    ),
                )
            except sqlite3.IntegrityError:
                raise ApiError(
                    "An active allocation to this centre already exists for this request.", 409
                ) from None
            for category, amount in requested.items():
                conn.execute(
                    "UPDATE centre_stock SET quantity = quantity - ? WHERE centre_id = ? AND category = ?",
                    (amount, centre_id, category),
                )
            conn.execute(
                "UPDATE requests SET workflow_status = 'resources_assigned', updated_at = ? WHERE id = ?",
                (now, request_id),
            )
            self._audit(
                conn, request_id, "resources_allocated", actor, role, override_reason,
                {
                    "allocationId": allocation_id,
                    "centreId": centre_id,
                    "centreName": centre["name"],
                    "items": requested,
                    "distanceKm": (distance or {}).get("distanceKm"),
                    "distanceSource": (distance or {}).get("distanceSource"),
                },
                now,
            )
            detail = ", ".join(f"{amount} {category}" for category, amount in sorted(requested.items()))
            self._notify(
                conn, request_id, "allocation",
                f"Resources assigned: {detail} from {centre['name']}. "
                "The team will update the delivery status.",
                actor=actor, at=now,
            )
        record = self.get_request(request_id)
        if record is None:  # pragma: no cover
            raise ApiError("That request no longer exists.", 404)
        return record

    def update_allocation_status(
        self, allocation_id: str, status: str, *, actor: str = "admin", role: str = "admin",
        reason: str | None = None,
    ) -> dict:
        if status not in ALLOCATION_STATUSES:
            raise ApiError("Unknown allocation status.")
        now = iso(utc_now())
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM allocations WHERE id = ?", (allocation_id,)).fetchone()
            if row is None:
                raise ApiError("That allocation does not exist.", 404)
            if row["status"] == "cancelled":
                raise ApiError("This allocation was already cancelled.", 409)
            if status == "cancelled" and row["status"] in ("assigned", "dispatched"):
                # Return the stock to the centre so the inventory stays honest.
                items = self._decode_json(row["items"], {})
                for category, amount in items.items():
                    conn.execute(
                        "UPDATE centre_stock SET quantity = quantity + ? WHERE centre_id = ? AND category = ?",
                        (int(amount), row["centre_id"], category),
                    )
            conn.execute(
                "UPDATE allocations SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, allocation_id),
            )
            conn.execute("UPDATE requests SET updated_at = ? WHERE id = ?", (now, row["request_id"]))
            if status == "dispatched":
                conn.execute(
                    "UPDATE requests SET workflow_status = CASE WHEN workflow_status = 'resources_assigned' "
                    "THEN 'in_progress' ELSE workflow_status END, updated_at = ? WHERE id = ?",
                    (now, row["request_id"]),
                )
            self._audit(
                conn, row["request_id"], "allocation_" + status, actor, role, reason,
                {"allocationId": allocation_id, "centreId": row["centre_id"]}, now,
            )
            message = {
                "dispatched": "A relief consignment has been dispatched to your location.",
                "delivered": "A relief consignment has been delivered at your location.",
                "cancelled": "A resource allocation was cancelled and re-planned.",
            }.get(status)
            if message:
                self._notify(conn, row["request_id"], "allocation", message, actor=actor, at=now)
            allocation = conn.execute(
                "SELECT * FROM allocations WHERE id = ?", (allocation_id,)
            ).fetchone()
        return self._allocation_to_dict(allocation)

    def list_allocations(self, limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM allocations ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._allocation_to_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # routing
    # ------------------------------------------------------------------

    def route_between(self, origin: tuple[float, float], destination: tuple[float, float]) -> dict:
        geometry = route_geometry(origin, destination)
        if geometry:
            return {
                **geometry,
                "distanceSource": geometry.get("source") or "osrm",
                "origin": {"latitude": origin[0], "longitude": origin[1]},
                "destination": {"latitude": destination[0], "longitude": destination[1]},
                "note": "Road route from OSRM.",
            }
        estimate = {
            "distanceKm": round(haversine_km(origin[0], origin[1], destination[0], destination[1]) * 1.34, 2),
            "source": "estimate",
            "distanceSource": "estimate",
            "provider": "estimate",
        }
        estimate["durationMin"] = max(1, round(estimate["distanceKm"] / 30 * 60))
        return {
            **estimate,
            "geometry": None,
            "origin": {"latitude": origin[0], "longitude": origin[1]},
            "destination": {"latitude": destination[0], "longitude": destination[1]},
            "note": (
                "Live routing is unavailable. The distance shown is a labelled estimate, "
                "so no route line is drawn."
            ),
        }

    def search_places(self, query: str) -> list[dict]:
        from drras_geo import geocode

        known = [
            {
                "name": centre["name"],
                "category": centre["category"],
                "latitude": centre["latitude"],
                "longitude": centre["longitude"],
            }
            for centre in self.list_help_centres()
        ]
        for request in self.list_requests(limit=200):
            if request["workflowStatus"] in ACTIVE_DISASTER_STATUSES:
                known.append({
                    "name": f"{request['locationName']} ({request['id']})",
                    "category": "incident",
                    "latitude": request["latitude"],
                    "longitude": request["longitude"],
                })
        return geocode(query, known)

    # ------------------------------------------------------------------
    # dashboards
    # ------------------------------------------------------------------

    def public_overview(self) -> dict:
        with self._connect() as conn:
            counts = {
                row["key"]: int(row["value"])
                for row in conn.execute(
                    "SELECT key, value FROM ("
                    "  SELECT workflow_status AS key, COUNT(*) AS value FROM requests GROUP BY workflow_status"
                    ")"
                ).fetchall()
            }
            active_rows = conn.execute(
                "SELECT * FROM requests WHERE workflow_status IN ('approved','resources_assigned','in_progress') "
                "ORDER BY submitted_at DESC LIMIT 8"
            ).fetchall()
            centres = self._load_centres(conn)
            inventory = self._load_inventory(conn)
            resolved = counts.get("resolved", 0)
            total = sum(counts.values())
            active = sum(counts.get(status, 0) for status in ACTIVE_DISASTER_STATUSES)
            people = conn.execute(
                "SELECT COALESCE(SUM(affected_people), 0) AS n FROM requests "
                "WHERE workflow_status IN ('approved','resources_assigned','in_progress','resolved')"
            ).fetchone()["n"]
            recent_allocations = conn.execute(
                "SELECT a.*, c.name AS centre_name FROM allocations a "
                "JOIN help_centres c ON c.id = a.centre_id "
                "WHERE a.status IN ('assigned','dispatched','delivered') "
                "ORDER BY a.created_at DESC LIMIT 5"
            ).fetchall()
        return {
            "stats": {
                "activeIncidents": active,
                "requestsTotal": total,
                "requestsResolved": resolved,
                "peopleReached": int(people),
                "centresOnline": sum(1 for c in centres if c["availability"] != "closed"),
                "centresTotal": len(centres),
            },
            "incidents": [
                {
                    "id": row["id"],
                    "type": row["type"],
                    "severity": row["severity"],
                    "workflowStatus": row["workflow_status"],
                    "workflowLabel": WORKFLOW_LABELS.get(row["workflow_status"], ""),
                    "locationName": row["location_name"],
                    "latitude": float(row["latitude"]),
                    "longitude": float(row["longitude"]),
                    "affectedPeople": int(row["affected_people"]),
                    "submittedAt": row["submitted_at"],
                }
                for row in active_rows
            ],
            "centralReserve": inventory,
            "recentDispatches": [
                {
                    "requestId": row["request_id"],
                    "centreName": row["centre_name"],
                    "items": self._decode_json(row["items"], {}),
                    "status": row["status"],
                    "createdAt": row["created_at"],
                }
                for row in recent_allocations
            ],
            "centres": [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "category": c["category"],
                    "categoryLabel": c["categoryLabel"],
                    "latitude": c["latitude"],
                    "longitude": c["longitude"],
                    "availability": c["availability"],
                    "phone": c["phone"],
                    "address": c["address"],
                    "stock": c["stock"],
                }
                for c in centres
            ],
        }

    def admin_stats(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT workflow_status, COUNT(*) AS n FROM requests GROUP BY workflow_status"
            ).fetchall()
            status_counts = {row["workflow_status"]: int(row["n"]) for row in rows}
            risk_rows = conn.execute(
                "SELECT risk_level, COUNT(*) AS n FROM requests WHERE workflow_status IN "
                "('submitted','under_verification','possible_duplicate','awaiting_approval') "
                "GROUP BY risk_level"
            ).fetchall()
            risk_counts = {row["risk_level"]: int(row["n"]) for row in risk_rows}
            flagged = conn.execute(
                "SELECT COUNT(*) AS n FROM requests WHERE flagged = 1"
            ).fetchone()["n"]
            queues = conn.execute(
                "SELECT verification_queue AS q, COUNT(*) AS n FROM requests WHERE workflow_status IN "
                "('submitted','under_verification','possible_duplicate','awaiting_approval') GROUP BY q"
            ).fetchall()
            centre_stock = conn.execute(
                "SELECT category, SUM(quantity) AS n FROM centre_stock GROUP BY category"
            ).fetchall()
            allocated = conn.execute(
                "SELECT items FROM allocations WHERE status IN ('assigned','dispatched')"
            ).fetchall()
        available = {row["category"]: int(row["n"] or 0) for row in centre_stock}
        allocated_counts: dict[str, int] = {}
        for row in allocated:
            for category, amount in self._decode_json(row["items"], {}).items():
                allocated_counts[category] = allocated_counts.get(category, 0) + int(amount)
        total = sum(status_counts.values())
        active = sum(status_counts.get(status, 0) for status in ACTIVE_DISASTER_STATUSES)
        return {
            "requests": {
                "total": total,
                "byStatus": status_counts,
                "awaitingVerification": sum(
                    status_counts.get(status, 0)
                    for status in ("submitted", "under_verification", "awaiting_approval")
                ),
                "possibleDuplicates": status_counts.get("possible_duplicate", 0),
                "approved": status_counts.get("approved", 0)
                + status_counts.get("resources_assigned", 0)
                + status_counts.get("in_progress", 0)
                + status_counts.get("resolved", 0),
                "rejected": status_counts.get("rejected", 0),
                "activeDisasters": active,
                "flagged": int(flagged),
            },
            "risk": {
                "high": risk_counts.get("high", 0),
                "medium": risk_counts.get("medium", 0),
                "low": risk_counts.get("low", 0),
            },
            "queues": {
                queue: int(next((row["n"] for row in queues if row["q"] == queue), 0))
                for queue in VERIFICATION_QUEUES
            },
            "resources": {
                "availableByCategory": available,
                "allocatedByCategory": allocated_counts,
                "centralReserve": self.get_inventory(),
            },
            "settings": self.get_settings(),
        }

    def seed_demo(self) -> dict:
        """Insert the sample incidents once. Safe to call repeatedly."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) AS n FROM requests WHERE is_demo = 1"
            ).fetchone()["n"]
        if existing:
            return {"inserted": 0, "message": "Demo requests already present."}

        now = utc_now()
        created: list[dict] = []
        for spec in DEMO_REQUESTS:
            submitted = now - timedelta(hours=float(spec["hours_ago"]))
            payload = {
                "type": spec["type"],
                "severity": spec["severity"],
                "affectedPeople": spec["affectedPeople"],
                "requiredResources": spec["requiredResources"],
                "resourceQuantities": spec["resourceQuantities"],
                "locationName": spec["locationName"],
                "latitude": spec["latitude"],
                "longitude": spec["longitude"],
                "description": spec["description"],
                "contactName": spec["contactName"],
                "contactPhone": spec["contactPhone"],
                "contactEmail": spec["contactEmail"],
            }
            record = self.submit_request(
                payload,
                client_ip=f"demo-seed-{spec['hours_ago']}",
                submitted_at=submitted,
                is_demo=True,
            )
            created.append(record)
            outcome = spec.get("outcome")
            try:
                if outcome in ("approved", "resources_assigned", "in_progress", "resolved"):
                    record = self.approve_request(
                        record["id"], actor="seed", role="system",
                        reason="Seeded demo request approved.",
                    )
                    recommendations = self.allocation_recommendations(record["id"], limit=4)
                    plan = recommendations.get("plan") or []
                    for entry in plan[:1]:
                        record = self.allocate(
                            record["id"], entry["centreId"], items=entry["items"],
                            actor="seed", role="system",
                            distance={
                                "distanceKm": entry["distanceKm"],
                                "durationMin": entry["durationMin"],
                                "distanceSource": entry["distanceSource"],
                            },
                        )
                    if outcome in ("in_progress", "resolved"):
                        self.transition_request(
                            record["id"], "in_progress", actor="seed", role="system",
                            reason="Seeded demo status.",
                        )
                    if outcome == "resolved":
                        # Add a short operational note, then close it.
                        self.transition_request(
                            record["id"], "resolved", actor="seed", role="system",
                            reason="Relief distributed; situation stabilised.",
                        )
                elif outcome == "rejected":
                    self.reject_request(
                        record["id"], reason=spec.get("rejectReason"),
                        message=spec.get("rejectReason"), actor="seed", role="system",
                    )
            except ApiError:
                # A demo record failing a transition must not abort seeding.
                continue
            if spec.get("outcome") == "under_verification":
                latest = self.get_request(record["id"])
                if latest and latest["workflowStatus"] in ("awaiting_approval", "submitted"):
                    with self._connect() as conn:
                        conn.execute(
                            "UPDATE requests SET workflow_status = 'under_verification', "
                            "verification_queue = 'high_risk', auto_decision = ?, updated_at = ? "
                            "WHERE id = ?",
                            (
                                "Demo record: routed to high-risk verification for the sample workflow.",
                                iso(utc_now()), record["id"],
                            ),
                        )
                        self._audit(
                            conn, record["id"], "verification_routed", "system", "seed",
                            "Sample data: routed to high-risk verification.",
                            {"queue": "high_risk"}, iso(utc_now()),
                        )
        return {
            "inserted": len(created),
            "ids": [record["id"] for record in created],
            "message": "Demo requests inserted.",
        }
