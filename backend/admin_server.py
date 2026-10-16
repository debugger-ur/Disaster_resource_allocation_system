#!/usr/bin/env python3
"""DRRAS request-review service.

Serves the static site in ``docs/`` and the JSON API that the public relief
request form and the admin dashboard talk to. Standard library only (plus the
sqlite3 module that ships with CPython), so it runs anywhere Python runs.

Usage:
    python3 backend/admin_server.py --set-password   # create/reset admin password
    python3 backend/admin_server.py                  # serve on http://0.0.0.0:8000

Environment:
    DRRAS_DB_PATH          absolute SQLite path (shared by password setup + server)
    DRRAS_COOKIE_SECURE      "1" to mark the session cookie Secure (use behind HTTPS)
    DRRAS_PORT / DRRAS_HOST  defaults for the bind address
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
STATIC_ROOT = REPO_ROOT / "docs"
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "drras.sqlite3"

SESSION_COOKIE_NAME = "drras_session"
SESSION_LIFETIME = timedelta(hours=8)
MIN_PASSWORD_LENGTH = 12
PBKDF2_ITERATIONS = 210_000
MAX_BODY_BYTES = 64 * 1024
# Bodies beyond this are never read; the connection is closed instead, so a
# huge Content-Length cannot hold the keep-alive socket hostage.
HARD_BODY_CAP = 8 * 1024 * 1024

# SameSite=Strict is the right default for a normal deployment, but it makes the
# session cookie invisible to any page embedded in a cross-site frame (an
# in-app preview, an <iframe> on the college portal): the browser drops it, so
# the first API call after signing in comes back 401 and the dashboard looks
# "expired" within a second. Run with SameSite=None in that setup.
COOKIE_SAMESITE_DEFAULT = "Strict"
COOKIE_SAMESITE_VALUES = ("Strict", "Lax", "None")

# Brute-force protection: at most this many failed sign-ins per IP per window.
LOGIN_MAX_ATTEMPTS = 8
LOGIN_WINDOW_SECONDS = 15 * 60

DISASTER_TYPES = {
    "FLOOD",
    "EARTHQUAKE",
    "FIRE",
    "LANDSLIDE",
    "INDUSTRIAL_ACCIDENT",
    "OTHER",
}
SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
RESOURCE_CATEGORIES = {"Ambulance", "RescueTeam", "MedicalTeam", "Equipment", "Supply"}
STATUSES = ("pending", "accepted", "rejected")

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_credentials (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    salt         BLOB    NOT NULL,
    iterations   INTEGER NOT NULL,
    password_hash BLOB   NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    csrf_token  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
    id                 TEXT    PRIMARY KEY,
    type               TEXT    NOT NULL,
    severity           TEXT    NOT NULL,
    affected_people    INTEGER NOT NULL,
    required_resources TEXT    NOT NULL DEFAULT '[]',
    location_name      TEXT    NOT NULL,
    latitude           REAL    NOT NULL,
    longitude          REAL    NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'pending',
    submitted_at       TEXT    NOT NULL,
    decided_at         TEXT
);

CREATE TABLE IF NOT EXISTS login_attempts (
    ip            TEXT NOT NULL,
    attempted_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
CREATE INDEX IF NOT EXISTS idx_login_ip_time ON login_attempts(ip, attempted_at);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def resolve_db_path(cli_value: str | None) -> Path:
    """CLI wins over the environment, then the repo-local default."""
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    env_value = os.environ.get("DRRAS_DB_PATH")
    if env_value:
        return Path(env_value).expanduser().resolve()
    return DEFAULT_DB_PATH


class ApiError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Store:
    """SQLite persistence. One short-lived connection per operation, so this is
    safe to use from ThreadingHTTPServer's worker threads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

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

    # ---- credentials ----

    def set_password(self, password: str) -> None:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_credentials (id, salt, iterations, password_hash, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    salt = excluded.salt,
                    iterations = excluded.iterations,
                    password_hash = excluded.password_hash,
                    updated_at = excluded.updated_at
                """,
                (salt, PBKDF2_ITERATIONS, digest, iso(utc_now())),
            )

    def has_password(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 AS ok FROM admin_credentials WHERE id = 1").fetchone()
        return row is not None

    def verify_password(self, password: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT salt, iterations, password_hash FROM admin_credentials WHERE id = 1"
            ).fetchone()
        if row is None:
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes(row["salt"]), int(row["iterations"])
        )
        return hmac.compare_digest(candidate, bytes(row["password_hash"]))

    # ---- sessions ----

    def create_session(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, csrf_token, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (self._hash(token), csrf, iso(now), iso(now + SESSION_LIFETIME)),
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
                "SELECT token_hash, csrf_token, expires_at FROM sessions WHERE token_hash = ?",
                (self._hash(token),),
            ).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")) <= utc_now():
            self.delete_session(token)
            return None
        return row

    def check_csrf(self, token: str, csrf: str) -> bool:
        session = self.get_session(token)
        if session is None or not csrf:
            return False
        return hmac.compare_digest(session["csrf_token"], csrf)

    def delete_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (self._hash(token),))

    # ---- login rate limiting ----

    def too_many_login_attempts(self, ip: str) -> bool:
        cutoff = time.time() - LOGIN_WINDOW_SECONDS
        with self._connect() as conn:
            conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (cutoff,))
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM login_attempts WHERE ip = ? AND attempted_at >= ?",
                (ip, cutoff),
            ).fetchone()
        return bool(row) and int(row["n"]) >= LOGIN_MAX_ATTEMPTS

    def record_login_failure(self, ip: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO login_attempts (ip, attempted_at) VALUES (?, ?)", (ip, time.time())
            )

    def clear_login_failures(self, ip: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))

    # ---- requests ----

    def create_request(self, data: dict) -> dict:
        request_id = f"REQ-{secrets.token_hex(4).upper()}"
        submitted = iso(utc_now())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO requests (
                    id, type, severity, affected_people, required_resources,
                    location_name, latitude, longitude, status, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    request_id,
                    data["type"],
                    data["severity"],
                    data["affectedPeople"],
                    json.dumps(data["requiredResources"]),
                    data["locationName"],
                    data["latitude"],
                    data["longitude"],
                    submitted,
                ),
            )
        return self.get_request(request_id)  # type: ignore[return-value]

    def get_request(self, request_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        return self._to_dict(row) if row else None

    def list_requests(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests ORDER BY submitted_at DESC, id DESC LIMIT 1000"
            ).fetchall()
        return [self._to_dict(row) for row in rows]

    def set_request_status(self, request_id: str, status: str) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise ApiError("That request no longer exists.", HTTPStatus.NOT_FOUND)
            if row["status"] != "pending":
                raise ApiError(
                    f"Request {request_id} was already {row['status']}.", HTTPStatus.CONFLICT
                )
            conn.execute(
                "UPDATE requests SET status = ?, decided_at = ? WHERE id = ?",
                (status, iso(utc_now()), request_id),
            )
        updated = self.get_request(request_id)
        if updated is None:  # pragma: no cover - defensive
            raise ApiError("That request no longer exists.", HTTPStatus.NOT_FOUND)
        return updated

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        """Maps snake_case columns onto the camelCase shape docs/js expects."""
        try:
            resources = json.loads(row["required_resources"])
        except (TypeError, json.JSONDecodeError):
            resources = []
        return {
            "id": row["id"],
            "type": row["type"],
            "severity": row["severity"],
            "affectedPeople": int(row["affected_people"]),
            "requiredResources": resources,
            "locationName": row["location_name"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "status": row["status"],
            "submittedAt": row["submitted_at"],
            "decidedAt": row["decided_at"],
        }


def validate_request_payload(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ApiError("Expected a JSON object.")

    def field(name: str):
        return raw.get(name)

    disaster_type = str(field("type") or "").strip().upper()
    if disaster_type not in DISASTER_TYPES:
        raise ApiError("Unknown disaster type.")

    severity = str(field("severity") or "").strip().upper()
    if severity not in SEVERITIES:
        raise ApiError("Severity must be CRITICAL, HIGH, MEDIUM or LOW.")

    affected = field("affectedPeople")
    if isinstance(affected, bool) or not isinstance(affected, (int, float)):
        raise ApiError("Affected people must be a number.")
    affected_int = int(affected)
    if affected_int < 0 or affected_int > 1_000_000_000:
        raise ApiError("Affected people cannot be negative.")

    location = str(field("locationName") or "").strip()
    if not location:
        raise ApiError("Location name is required.")
    if len(location) > 200:
        raise ApiError("Location name is too long (max 200 characters).")

    latitude = field("latitude")
    longitude = field("longitude")
    for value, label, bound in ((latitude, "Latitude", 90.0), (longitude, "Longitude", 180.0)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError(f"{label} must be a number.")
        if not (-bound <= float(value) <= bound):
            raise ApiError(f"{label} must be between {-bound} and {bound}.")

    resources_raw = field("requiredResources")
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

    return {
        "type": disaster_type,
        "severity": severity,
        "affectedPeople": affected_int,
        "requiredResources": resources,
        "locationName": html.escape(location, quote=False),
        "latitude": float(latitude),
        "longitude": float(longitude),
    }


class DrrasHandler(SimpleHTTPRequestHandler):
    """Static files out of ``docs/`` plus the JSON API, on one origin."""

    server_version = "DRRAS/1.0"
    # HTTP/1.1 keeps the browser's connections alive; every response below sets
    # an explicit Content-Length, which keep-alive requires.
    protocol_version = "HTTP/1.1"
    store: Store  # attached by the factory below
    cookie_secure = False
    cookie_samesite = COOKIE_SAMESITE_DEFAULT
    cookie_partitioned = False
    # Off by default: a token the page can read is a wider XSS surface than an
    # HttpOnly cookie, so normal deployments keep the cookie. Opt in only when the
    # app is embedded and the browser will not carry cookies across sites.
    allow_bearer_auth = False
    # Fail closed: if a request never authenticates, CSRF is still enforced.
    auth_source = "cookie"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    # ---- helpers ----

    def log_message(self, fmt: str, *args) -> None:  # keep stdout tidy
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK, extra_headers=None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in extra_headers or ():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def drain_body(self) -> None:
        """Read the whole request body before anything else.

        Every request path must drain the socket, including the ones that reject
        the call: BaseHTTPRequestHandler reuses this connection for the next
        request, so leftover body bytes would be parsed as its request line and
        answered as a bogus method (501) - request desynchronisation, not a
        4xx. Reading first and deciding second keeps the stream aligned.
        """
        self._body = b""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            raise ApiError("Invalid Content-Length.") from None
        if length <= 0:
            return
        if length > HARD_BODY_CAP:
            # Refuse and drop the connection rather than read it or leave it.
            self.close_connection = True
            raise ApiError("Request body is too large.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        self._body = self.rfile.read(length)
        if len(self._body) < length:
            # Client promised more than it sent; the stream is no longer trustworthy.
            self.close_connection = True

    def _read_json(self) -> object:
        raw = getattr(self, "_body", b"")
        if not raw:
            return {}
        if len(raw) > MAX_BODY_BYTES:
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
        """Resolves the caller to (token, source).

        An explicit Authorization header wins over the cookie. That is the only
        credential that survives an embedded frame on a browser which refuses
        third-party cookies, where login succeeds but every following call
        arrives without the session cookie and reads as "expired".
        """
        auth = self.headers.get("Authorization", "")
        if self.allow_bearer_auth and auth[:7].lower() == "bearer ":
            candidate = auth[7:].strip()
            if candidate:
                return candidate, "bearer"
        return self._cookie_token(), "cookie"

    def _session_token(self) -> str:
        """Just the token, whichever transport carried it."""
        return self._credential()[0]

    def _require_admin(self) -> sqlite3.Row:
        token, source = self._credential()
        session = self.store.get_session(token)
        if session is None:
            raise ApiError("Your admin session has expired. Sign in again.", HTTPStatus.UNAUTHORIZED)
        self.auth_source = source
        return session

    def _require_csrf(self) -> None:
        # A cross-site form cannot set custom headers, and the bearer token is not
        # attached automatically by the browser, so CSRF is already guaranteed.
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
        # Browsers reject SameSite=None unless the cookie is also Secure, and
        # Secure cookies are dropped on plain http (except http://localhost).
        if self.cookie_secure or self.cookie_samesite == "None":
            parts.append("Secure")
        # CHIPS: Partitioned is only valid alongside SameSite=None; Secure, and
        # it is what lets the session survive inside a cross-site iframe when the
        # browser blocks ordinary third-party cookies.
        if self.cookie_partitioned and self.cookie_samesite == "None":
            parts.append("Partitioned")
        return "; ".join(parts)

    # ---- routing ----

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            self._route_get(path)
            return
        if path in ("/admin", "/admin/"):
            self.path = "/admin.html"
        elif path == "/":
            self.path = "/index.html"
        self._revalidate_html = self.path.split("?", 1)[0].endswith(".html")
        self._serve_static()

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        try:
            self.drain_body()
        except ApiError as err:
            self._send_json({"error": err.message}, err.status)
            return
        self._route_post(self.path.split("?", 1)[0])

    def do_PATCH(self) -> None:  # noqa: N802
        try:
            self.drain_body()
        except ApiError as err:
            self._send_json({"error": err.message}, err.status)
            return
        self._route_patch(self.path.split("?", 1)[0])

    def end_headers(self) -> None:
        # Entry documents must always revalidate: a cached admin.html keeps
        # pointing at an old admin.js, and the page then behaves like the fix
        # never landed.
        if getattr(self, "_revalidate_html", False):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _serve_static(self) -> None:
        if not STATIC_ROOT.is_dir():
            self._send_json({"error": "Static site folder docs/ is missing."}, HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    # ---- API: read ----

    def _route_get(self, path: str) -> None:
        try:
            if path == "/api/health":
                self._send_json({"status": "ok", "passwordConfigured": self.store.has_password()})
                return
            if path == "/api/admin/session":
                session = self._require_admin()
                payload = {"authenticated": True, "csrfToken": session["csrf_token"]}
                if self.auth_source == "bearer":
                    payload["sessionToken"] = self._session_token()
                self._send_json(payload)
                return
            if path == "/api/admin/requests":
                self._require_admin()
                self._send_json({"requests": self.store.list_requests()})
                return
            if path.startswith("/api/admin/requests/"):
                self._require_admin()
                request_id = unquote(path.rsplit("/", 1)[-1])
                record = self.store.get_request(request_id)
                if record is None:
                    raise ApiError("That request no longer exists.", HTTPStatus.NOT_FOUND)
                self._send_json({"request": record})
                return
            raise ApiError("Unknown endpoint.", HTTPStatus.NOT_FOUND)
        except ApiError as err:
            self._send_json({"error": err.message}, err.status)

    # ---- API: create / auth ----

    def _route_post(self, path: str) -> None:
        try:
            if path == "/api/requests":
                payload = validate_request_payload(self._read_json())
                self._send_json({"request": self.store.create_request(payload)}, HTTPStatus.CREATED)
                return
            if path == "/api/admin/login":
                self._handle_login()
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
            raise ApiError("Unknown endpoint.", HTTPStatus.NOT_FOUND)
        except ApiError as err:
            self._send_json({"error": err.message}, err.status)

    def _handle_login(self) -> None:
        ip = self._client_ip()
        if self.store.too_many_login_attempts(ip):
            raise ApiError(
                "Too many failed sign-in attempts. Try again in a few minutes.",
                HTTPStatus.TOO_MANY_REQUESTS,
            )
        if not self.store.has_password():
            raise ApiError(
                "No admin password is configured. Run: python3 backend/admin_server.py --set-password",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        body = self._read_json()
        password = body.get("password") if isinstance(body, dict) else None
        if not isinstance(password, str) or not self.store.verify_password(password):
            self.store.record_login_failure(ip)
            raise ApiError("Incorrect password.", HTTPStatus.UNAUTHORIZED)
        self.store.clear_login_failures(ip)
        token, csrf = self.store.create_session()
        max_age = int(SESSION_LIFETIME.total_seconds())
        payload: dict = {"ok": True, "csrfToken": csrf}
        if self.allow_bearer_auth:
            # Clients that cannot use cookies (embedded frames under third-party
            # cookie blocking) authenticate with this instead.
            payload["sessionToken"] = token
            payload["authMode"] = "bearer"
        self._send_json(
            payload,
            extra_headers=[("Set-Cookie", self._cookie(token, max_age))],
        )

    # ---- API: decisions ----

    def _route_patch(self, path: str) -> None:
        try:
            self._require_admin()
            self._require_csrf()
            if not path.startswith("/api/admin/requests/"):
                raise ApiError("Unknown endpoint.", HTTPStatus.NOT_FOUND)
            request_id = unquote(path.rsplit("/", 1)[-1])
            body = self._read_json()
            if not isinstance(body, dict):
                raise ApiError("Expected a JSON object.")
            status = str(body.get("status") or "").strip().lower()
            if status not in ("accepted", "rejected"):
                raise ApiError("Status must be 'accepted' or 'rejected'.")
            self._send_json({"request": self.store.set_request_status(request_id, status)})
        except ApiError as err:
            self._send_json({"error": err.message}, err.status)


def normalize_samesite(value: str) -> str:
    """Validates the SameSite policy, accepting any capitalisation."""
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
    # Bind the store onto a per-server subclass instead of mutating DrrasHandler
    # itself: the class is shared, so assigning to it would leak this server's
    # database into every other server in the process.
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


def set_password_interactively(store: Store) -> int:
    print(f"Setting the DRRAS admin password.\nDatabase: {store.path}")
    if store.has_password():
        print("A password is already configured; the new one will replace it.")
    while True:
        password = getpass.getpass("New password (min %d chars): " % MIN_PASSWORD_LENGTH)
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"Too short - use at least {MIN_PASSWORD_LENGTH} characters.\n")
            continue
        if password != getpass.getpass("Repeat it: "):
            print("Those did not match, try again.\n")
            continue
        store.set_password(password)
        break
    print("Password stored (PBKDF2-HMAC-SHA256, salted).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DRRAS web UI + request review API")
    parser.add_argument("--set-password", action="store_true", help="create or reset the admin password, then exit")
    parser.add_argument("--db", default=None, help="SQLite file (default: $DRRAS_DB_PATH or backend/data/drras.sqlite3)")
    parser.add_argument("--host", default=os.environ.get("DRRAS_HOST", "0.0.0.0"), help="bind address (default 0.0.0.0)")
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
        help=(
            "session cookie SameSite policy (default Strict). Use None when the "
            "site is opened inside a cross-site frame or preview; it forces Secure, "
            "so HTTPS is required. (env: DRRAS_COOKIE_SAMESITE)"
        ),
    )
    parser.add_argument(
        "--allow-bearer-auth",
        action="store_true",
        default=os.environ.get("DRRAS_ALLOW_BEARER_AUTH", "") == "1",
        help=(
            "also return a bearer token on sign-in so clients that cannot carry "
            "cookies (the app embedded in a frame under third-party cookie blocking) "
            "still authenticate. Weaker against XSS than an HttpOnly cookie: enable "
            "only when you need it. (env: DRRAS_ALLOW_BEARER_AUTH=1)"
        ),
    )
    parser.add_argument(
        "--cookie-partitioned",
        action="store_true",
        default=os.environ.get("DRRAS_COOKIE_PARTITIONED", "") == "1",
        help=(
            "add the CHIPS Partitioned attribute (requires --cookie-samesite None); "
            "needed when the site is embedded in an iframe on another domain and the "
            "browser blocks third-party cookies. (env: DRRAS_COOKIE_PARTITIONED=1)"
        ),
    )
    args = parser.parse_args(argv)

    if args.cookie_partitioned and args.cookie_samesite != "None":
        parser.error("--cookie-partitioned requires --cookie-samesite None")

    # Platform-as-a-service hosts (Render, Railway, Fly) inject PORT and expect
    # the app to bind directly to it rather than to a fixed 8000.
    port_env = os.environ.get("PORT")
    if port_env and "--port" not in (argv or sys.argv[1:]):
        try:
            args.port = int(port_env)
        except ValueError:
            pass

    store = Store(resolve_db_path(args.db))

    if args.set_password:
        return set_password_interactively(store)

    cookie_secure = os.environ.get("DRRAS_COOKIE_SECURE", "") == "1"
    try:
        httpd = make_server(
            args.host,
            args.port,
            store,
            cookie_secure,
            args.cookie_samesite,
            args.cookie_partitioned,
            args.allow_bearer_auth,
        )
    except OSError as err:
        print(f"Could not bind {args.host}:{args.port} - {err}", file=sys.stderr)
        print("Something else is probably using that port; try --port 8010.", file=sys.stderr)
        return 1

    print(f"DRRAS site : http://localhost:{args.port}/")
    print(f"Admin UI   : http://localhost:{args.port}/admin")
    print(f"Database   : {store.path}")
    cookie_flags = [f"SameSite={args.cookie_samesite}"]
    if cookie_secure or args.cookie_samesite == "None":
        cookie_flags.append("Secure")
    if args.cookie_partitioned and args.cookie_samesite == "None":
        cookie_flags.append("Partitioned")
    print("Cookie     : " + "; ".join(cookie_flags))
    print(
        "Admin auth : cookie" + (" + bearer token" if args.allow_bearer_auth else "")
        + ("  (DRRAS_ALLOW_BEARER_AUTH=1)" if args.allow_bearer_auth else "")
    )
    if args.cookie_samesite == "None":
        print(
            "           SameSite=None needs https (http://localhost excepted). To open"
            " the admin in a plain new tab instead, Strict is safer."
        )
    if args.cookie_samesite != "None" and not store.has_password():
        # Only meaningful before the first sign-in, which is when this bites.
        print(
            "Tip: if this site is opened inside a frame/preview and sign-in appears to"
            " expire instantly, restart with --cookie-samesite None (needs HTTPS)."
        )
    if cookie_secure and args.cookie_samesite == "None":
        print("Note: SameSite=None is only honoured over https:// - http will drop the cookie.")
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
