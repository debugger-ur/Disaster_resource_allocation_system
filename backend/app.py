"""DRRAS web server: a small JSON API plus the static site.

Run locally:
    python3 backend/app.py --set-password
    python3 backend/app.py
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import mimetypes
import os
import sys
import threading
import time
import traceback
import urllib.parse
from collections import defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import (
    ALLOCATION_STATUSES,
    AVAILABILITY,
    CENTRE_CATEGORIES,
    DISASTER_LABELS,
    RESOURCES,
    RESOURCE_LABELS,
    STATUSES,
    SEVERITIES,
    ApiError,
    validate_centre,
    validate_settings,
    validate_stock,
    validate_submission,
)
from db import Store
from geo import routing_status, search_places

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "docs"
DEFAULT_DB = BASE_DIR / "backend" / "data" / "drras.sqlite3"
MAX_BODY = 9 * 1024 * 1024
MAX_UPLOAD = 5 * 1024 * 1024
MIME_TYPES = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n", "application/pdf": b"%PDF-"}
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}


class RateLimiter:
    """Tiny in-memory limiter; enough for a single-process college deployment."""

    def __init__(self) -> None:
        self.hits: dict[str, list[float]] = defaultdict(list)
        self.lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        with self.lock:
            recent = [stamp for stamp in self.hits[key] if stamp > now - window_seconds]
            self.hits[key] = recent
            if len(recent) >= limit:
                return False
            recent.append(now)
            if len(self.hits) > 2000:
                self.hits.clear()
            return True


LIMITER = RateLimiter()


class DrrasHandler(BaseHTTPRequestHandler):
    store: Store
    allow_bearer: bool = False
    allowed_origin: str = ""
    server_version = "DRRAS/3.0"

    # ---------- request plumbing ----------

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        query = {key: values[-1] for key, values in urllib.parse.parse_qs(parsed.query).items()}
        try:
            if parsed.path.startswith("/api/"):
                self._route_api(method, parsed.path, query)
            elif method == "GET":
                self._serve_static(parsed.path)
            else:
                raise ApiError("Method not allowed.", 405)
        except ApiError as error:
            self._send_json({"error": error.message}, error.status)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            traceback.print_exc()
            self._send_json({"error": "The server hit an unexpected error."}, 500)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._common_headers()
        self._send_cors_headers()
        self.send_header("Allow", "GET, POST, PATCH, OPTIONS")
        self.end_headers()

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if self.allowed_origin and origin == self.allowed_origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")

    def _common_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        # OSM's tile servers require a valid cross-origin referrer. Sending
        # "same-origin" stripped it and caused HTTP 403 "Access blocked" tiles.
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https://tile.openstreetmap.org "
            "https://*.tile.openstreetmap.org; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
            "form-action 'self'; base-uri 'self'",
        )

    def _send_json(self, payload: object, status: int = 200, cookies: list[str] | None = None) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._common_headers()
        self._send_cors_headers()
        for cookie in cookies or []:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError("Invalid request length.") from None
        if length <= 0 or length > MAX_BODY:
            raise ApiError("Request body is empty or too large.", 413)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError("Expected valid JSON.") from None
        if not isinstance(payload, dict):
            raise ApiError("Expected a JSON object.")
        return payload

    def _cookie(self, name: str, value: str, max_age: int = 43200) -> str:
        secure = "; Secure" if os.environ.get("DRRAS_COOKIE_SECURE") == "1" else ""
        return f"{name}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}"

    def _client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        return (forwarded.split(",")[0].strip() if forwarded else self.client_address[0]) or "unknown"

    def _session(self, role: str | None = None) -> dict:
        token = ""
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "drras_session":
                token = value
        if not token and self.allow_bearer:
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                token = header[7:].strip()
        if not token:
            raise ApiError("Please sign in first.", 401)
        session = self.store.get_session(token)
        if not session:
            raise ApiError("Your session has expired. Please sign in again.", 401)
        session["token"] = token
        if role and session["role"] != role:
            raise ApiError("You do not have permission for this action.", 403)
        return session

    def _csrf(self, session: dict) -> None:
        if not hmac_compare(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
            raise ApiError("Security token expired. Refresh the page and try again.", 403)

    def _session_payload(self, session: dict) -> dict:
        payload = {
            "authenticated": True,
            "role": session["role"],
            "csrfToken": session["csrf"],
        }
        if self.allow_bearer:
            payload["sessionToken"] = session["token"]
        return payload

    # ---------- routing ----------

    def _route_api(self, method: str, path: str, query: dict) -> None:
        if method == "GET":
            self._api_get(path, query)
        elif method == "POST":
            self._api_post(path)
        elif method == "PATCH":
            self._api_patch(path)
        else:
            raise ApiError("Method not allowed.", 405)

    def _api_get(self, path: str, query: dict) -> None:
        if path == "/api/health":
            self._send_json({
                "status": "ok",
                "service": "DRRAS",
                "version": "3.0",
                "passwordConfigured": self.store.has_admin_password(),
                "routing": routing_status(),
                "demoData": self.store.has_demo_data(),
            })
            return
        if path == "/api/meta":
            self._send_json({
                "disasterTypes": [{"value": k, "label": DISASTER_LABELS[k]} for k in DISASTER_LABELS],
                "severities": SEVERITIES,
                "resources": RESOURCE_LABELS,
                "centreCategories": CENTRE_CATEGORIES,
                "availability": AVAILABILITY,
                "statuses": STATUSES,
                "allocationStatuses": ALLOCATION_STATUSES,
            })
            return
        if path == "/api/overview":
            self._send_json(self.store.public_overview())
            return
        if path == "/api/centres":
            self._send_json({"centres": self.store.list_centres()})
            return
        if path == "/api/nearby":
            lat = _float_arg(query, "lat")
            lon = _float_arg(query, "lon")
            radius = _float_arg(query, "radius", 50)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ApiError("Coordinates are out of range.")
            if not 0 < radius <= 200:
                raise ApiError("Radius must be between 0 and 200 km.")
            try:
                limit = min(50, max(1, int(query.get("limit", 20))))
            except ValueError:
                raise ApiError("Limit must be a number.") from None
            self._send_json(self.store.nearby_centres(
                lat, lon, category=query.get("category", ""),
                availability=query.get("availability", ""), resource=query.get("resource", ""),
                radius_km=radius, limit=limit,
            ))
            return
        if path == "/api/places":
            if not LIMITER.allow("places:" + self._client_ip(), 30, 60):
                raise ApiError("Too many place searches. Try again in a minute.", 429)
            text = str(query.get("q", "")).strip()
            if len(text) < 2:
                raise ApiError("Enter at least two characters.")
            self._send_json({"results": search_places(text, self.store.list_centres())})
            return
        if path == "/api/route":
            origin = (_float_arg(query, "fromLat"), _float_arg(query, "fromLon"))
            target = (_float_arg(query, "toLat"), _float_arg(query, "toLon"))
            for lat, lon in (origin, target):
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ApiError("Coordinates are out of range.")
            from geo import route_between
            self._send_json(route_between(origin, target))
            return
        if path.startswith("/api/requests/"):
            request_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            record = self.store.get_public_request(request_id)
            if not record:
                raise ApiError("That request was not found.", 404)
            self._send_json({"request": record})
            return
        if path.startswith("/api/admin/"):
            self._admin_get(path, query)
            return
        raise ApiError("Unknown endpoint.", 404)

    def _admin_get(self, path: str, query: dict) -> None:
        session = self._session("admin")
        if path == "/api/admin/session":
            self._send_json(self._session_payload(session))
            return
        if path == "/api/admin/stats":
            self._send_json(self.store.admin_stats())
            return
        if path == "/api/admin/requests":
            self._send_json({"requests": self.store.list_requests(
                status=query.get("status", ""), queue=query.get("queue", ""), search=query.get("search", "")
            )})
            return
        if path.startswith("/api/admin/requests/") and path.endswith("/recommendations"):
            request_id = urllib.parse.unquote(path.split("/")[-2])
            self._send_json(self.store.recommendations(request_id))
            return
        if path.startswith("/api/admin/requests/"):
            request_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            record = self.store.get_request(request_id)
            if not record:
                raise ApiError("Request not found.", 404)
            self._send_json({"request": record})
            return
        if path == "/api/admin/centres":
            self._send_json({"centres": self.store.list_centres(), "categories": CENTRE_CATEGORIES})
            return
        if path == "/api/admin/allocations":
            self._send_json({"allocations": self.store.list_allocations()})
            return
        if path == "/api/admin/settings":
            self._send_json({"settings": self.store.get_settings(), "routing": routing_status()})
            return
        if path.startswith("/api/admin/evidence/"):
            evidence_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            found = self.store.get_evidence(evidence_id)
            if not found:
                raise ApiError("File not found.", 404)
            row, file_path = found
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", row["mime_type"])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'inline; filename="{row["stored_name"]}"')
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
            return
        raise ApiError("Unknown admin endpoint.", 404)

    def _api_post(self, path: str) -> None:
        if path == "/api/admin/login":
            if not LIMITER.allow("admin_login:" + self._client_ip(), 8, 900):
                raise ApiError("Too many sign-in attempts. Wait 15 minutes.", 429)
            if not self.store.has_admin_password():
                raise ApiError("No admin password is configured on the server.", 409)
            body = self._read_json()
            if not self.store.verify_admin_password(str(body.get("password", ""))):
                raise ApiError("Incorrect admin password.", 401)
            session = self.store.create_session("admin")
            self._send_json(self._session_payload(session), 200,
                            [self._cookie("drras_session", session["token"])])
            return
        if path == "/api/admin/logout":
            session = self._session("admin")
            self._csrf(session)
            self.store.delete_session(session["token"])
            self._send_json({"ok": True}, 200, [self._cookie("drras_session", "", 0)])
            return
        if path == "/api/requests":
            if not LIMITER.allow("submit:" + self._client_ip(), 10, 600):
                raise ApiError("Too many reports from this connection. Try again later.", 429)
            data = validate_submission(self._read_json())
            evidence = data.pop("evidence")
            record = self.store.submit_request(data, evidence)
            public = self.store.get_public_request(record["id"])
            self._send_json({
                "request": public,
                "verification": {
                    "queue": record["reviewQueue"],
                    "summary": "Possible duplicate — a coordinator will compare it with the earlier report."
                    if record["possibleDuplicate"] else "Report received and added to the review queue.",
                },
            }, 201)
            return
        if path == "/api/uploads":
            if not LIMITER.allow("upload:" + self._client_ip(), 20, 600):
                raise ApiError("Too many uploads. Try again later.", 429)
            evidence = self._save_upload(self._read_json())
            self._send_json({"evidence": evidence}, 201)
            return
        if path.startswith("/api/admin/"):
            self._admin_post(path)
            return
        raise ApiError("Unknown endpoint.", 404)

    def _admin_post(self, path: str) -> None:
        session = self._session("admin")
        self._csrf(session)
        actor = "admin"
        if path.startswith("/api/admin/requests/") and path.endswith("/action"):
            request_id = urllib.parse.unquote(path.split("/")[-2])
            body = self._read_json()
            note = str(body.get("reason") or body.get("message") or "").strip()[:1000]
            self._send_json({"request": self.store.apply_action(
                request_id, str(body.get("action") or ""), note, actor
            )})
            return
        if path.startswith("/api/admin/requests/") and path.endswith("/allocations"):
            request_id = urllib.parse.unquote(path.split("/")[-2])
            body = self._read_json()
            items = validate_stock(body.get("items"))
            items = {key: value for key, value in items.items() if value > 0}
            self._send_json({"request": self.store.allocate(
                request_id, str(body.get("centreId") or ""), items, actor,
                body.get("distance") if isinstance(body.get("distance"), dict) else None,
                str(body.get("overrideReason") or "").strip()[:500],
            )}, 201)
            return
        if path == "/api/admin/centres":
            data = validate_centre(self._read_json())
            self._send_json({"centre": self.store.create_centre(data)}, 201)
            return
        if path == "/api/admin/seed-demo":
            self._send_json(self.store.seed_demo())
            return
        raise ApiError("Unknown admin endpoint.", 404)

    def _api_patch(self, path: str) -> None:
        session = self._session("admin")
        self._csrf(session)
        if path == "/api/admin/settings":
            body = self._read_json()
            settings = validate_settings(body, self.store.get_settings())
            self._send_json({"settings": self.store.save_settings(settings, "admin")})
            return
        if path.startswith("/api/admin/centres/"):
            centre_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            data = validate_centre(self._read_json(), partial=True)
            self._send_json({"centre": self.store.update_centre(centre_id, data, "admin")})
            return
        if path.startswith("/api/admin/allocations/"):
            allocation_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            body = self._read_json()
            self._send_json({"request": self.store.update_allocation(
                allocation_id, str(body.get("action") or ""), "admin"
            )})
            return
        raise ApiError("Unknown admin endpoint.", 404)

    # ---------- uploads and static files ----------

    def _save_upload(self, body: dict) -> dict:
        mime = str(body.get("type") or "")
        name = str(body.get("name") or "evidence")[:120]
        if mime not in MIME_TYPES:
            raise ApiError("Only JPEG, PNG and PDF files are accepted.")
        try:
            content = base64.b64decode(str(body.get("data") or ""), validate=True)
        except (ValueError, TypeError):
            raise ApiError("The file could not be decoded.") from None
        if not content or len(content) > MAX_UPLOAD:
            raise ApiError("Files must be between 1 byte and 5 MB.")
        if not content.startswith(MIME_TYPES[mime]):
            raise ApiError("The file contents do not match its type.")
        return self.store.add_evidence(name, mime, content, EXTENSIONS[mime])

    def _serve_static(self, path: str) -> None:
        if path in ("/", "/index.html"):
            relative = "index.html"
        elif path in ("/admin", "/admin/"):
            relative = "admin.html"
        else:
            relative = path.lstrip("/")
        target = (DOCS_DIR / relative).resolve()
        if DOCS_DIR not in target.parents and target != DOCS_DIR:
            raise ApiError("Not found.", 404)
        if not target.is_file():
            raise ApiError("Not found.", 404)
        data = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        if target.suffix == ".html":
            self.send_header("Cache-Control", "no-cache")
        elif "vendor" in target.parts:
            self.send_header("Cache-Control", "public, max-age=604800")
        else:
            self.send_header("Cache-Control", "public, max-age=300")
        self._common_headers()
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(data)


def hmac_compare(left: str, right: str) -> bool:
    """Constant-time comparison without importing hmac in every helper."""
    import hmac
    return hmac.compare_digest(str(left or ""), str(right or ""))


def _float_arg(query: dict, name: str, default: float | None = None) -> float:
    value = query.get(name)
    if value is None or value == "":
        if default is not None:
            return default
        raise ApiError(f"{name} is required.")
    try:
        return float(value)
    except ValueError:
        raise ApiError(f"{name} must be a number.") from None


def make_server(store: Store, port: int = 0, allow_bearer: bool = False) -> ThreadingHTTPServer:
    handler = type("BoundDrrasHandler", (DrrasHandler,), {
        "store": store,
        "allow_bearer": allow_bearer,
        "allowed_origin": os.environ.get("DRRAS_ALLOWED_ORIGIN", ""),
    })
    return ThreadingHTTPServer(("0.0.0.0", port), handler)


def resolve_db_path(value: str | None) -> Path:
    return Path(value or os.environ.get("DRRAS_DB_PATH") or DEFAULT_DB)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DRRAS disaster relief server")
    parser.add_argument("--db", help="SQLite database file")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--set-password", action="store_true", help="Set the admin password and exit")
    parser.add_argument("--seed-demo", action="store_true", help="Insert sample requests and exit")
    parser.add_argument("--allow-bearer-auth", action="store_true", help="Allow token fallback for embedded previews")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    store = Store(resolve_db_path(args.db))
    if args.set_password:
        password = getpass.getpass("New admin password (12+ characters): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise SystemExit("Passwords did not match.")
        if len(password) < 12:
            raise SystemExit("Use at least 12 characters.")
        store.set_admin_password(password)
        print("Admin password saved.")
        return
    if args.seed_demo:
        print(store.seed_demo())
        return

    bootstrap = os.environ.get("DRRAS_ADMIN_PASSWORD", "")
    if bootstrap and not store.has_admin_password():
        if len(bootstrap) < 12:
            print("DRRAS_ADMIN_PASSWORD ignored: it must be at least 12 characters.", file=sys.stderr)
        else:
            store.set_admin_password(bootstrap)
            print("Admin password initialised from DRRAS_ADMIN_PASSWORD.")

    allow_bearer = args.allow_bearer_auth or os.environ.get("DRRAS_ALLOW_BEARER_AUTH") == "1"
    server = make_server(store, args.port, allow_bearer)
    print(f"DRRAS running on http://0.0.0.0:{args.port} (admin: /admin)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
