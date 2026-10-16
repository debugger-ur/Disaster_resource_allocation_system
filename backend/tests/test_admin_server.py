"""End-to-end tests for the DRRAS request-review API.

Run from the repository root:
    python3 -m unittest discover -s backend/tests -v
"""

from __future__ import annotations

import http.cookiejar
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import admin_server  # noqa: E402

PASSWORD = "correct horse battery staple"


class ServerTestCase(unittest.TestCase):
    """Boots the real handler against a throwaway SQLite file."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.httpd, cls.store, cls.base = cls._start(Path(cls.tmp.name) / "test.sqlite3")
        cls.store.set_password(PASSWORD)

    @classmethod
    def _start(
        cls,
        db_path: Path,
        cookie_secure: bool = False,
        cookie_samesite=None,
        cookie_partitioned: bool = False,
    ):
        store = admin_server.Store(db_path)
        kwargs = {} if cookie_samesite is None else {"cookie_samesite": cookie_samesite}
        if cookie_partitioned:
            kwargs["cookie_partitioned"] = True
        httpd = admin_server.make_server("127.0.0.1", 0, store, cookie_secure, **kwargs)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        return httpd, store, base

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def setUp(self) -> None:
        # Isolate each test's rows/sessions without touching the shared schema.
        with self.store._connect() as conn:
            conn.execute("DELETE FROM requests")
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM login_attempts")
        self.cookies: str | None = None
        self.csrf: str | None = None

    # ---- HTTP plumbing ----

    def _request(self, method: str, path: str, body=None, csrf: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.cookies:
            req.add_header("Cookie", self.cookies)
        if csrf and self.csrf:
            req.add_header("X-CSRF-Token", self.csrf)
        try:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read() or b"{}")
                return resp.status, payload, resp.headers
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:  # pragma: no cover - defensive
                payload = {"raw": raw.decode(errors="replace")}
            return err.code, payload, err.headers

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, body=None, csrf=False):
        return self._request("POST", path, body if body is not None else {}, csrf=csrf)

    def patch(self, path, body=None, csrf=False):
        return self._request("PATCH", path, body if body is not None else {}, csrf=csrf)

    def login(self, password: str = PASSWORD):
        status, payload, headers = self.post("/api/admin/login", {"password": password})
        if status == 200:
            self.csrf = payload["csrfToken"]
            raw = headers.get("Set-Cookie", "")
            self.cookies = raw.split(";")[0]
        return status, payload, headers

    def make_request(self, **overrides):
        payload = {
            "type": "FLOOD",
            "severity": "CRITICAL",
            "affectedPeople": 250,
            "requiredResources": ["Ambulance", "MedicalTeam"],
            "locationName": "Ramnagar",
            "latitude": 29.02,
            "longitude": 79.43,
        }
        payload.update(overrides)
        return self.post("/api/requests", payload)

    def unique(self, **overrides):
        """Create a request whose id cannot collide across tests."""
        status, payload, _ = self.make_request(**overrides)
        self.assertEqual(status, 201, payload)
        return payload["request"]


class PublicRequestTests(ServerTestCase):
    def test_valid_request_is_created_as_pending(self):
        record = self.unique()
        self.assertTrue(record["id"].startswith("REQ-"))
        self.assertEqual(record["status"], "pending")
        self.assertEqual(record["affectedPeople"], 250)
        self.assertEqual(record["requiredResources"], ["Ambulance", "MedicalTeam"])
        self.assertAlmostEqual(record["latitude"], 29.02)
        self.assertIsNotNone(record["submittedAt"])
        self.assertIsNone(record["decidedAt"])

    def test_fields_are_typed_as_the_frontend_expects(self):
        record = self.unique()
        # admin.js does Number(x).toFixed(4) / .toLocaleString() / .replaceAll()
        self.assertIsInstance(record["affectedPeople"], int)
        self.assertIsInstance(record["latitude"], float)
        self.assertIsInstance(record["longitude"], float)
        self.assertIsInstance(record["type"], str)
        self.assertIsInstance(record["requiredResources"], list)

    def test_rejects_unknown_type(self):
        status, payload, _ = self.make_request(type="HURRICANE")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_rejects_unknown_severity(self):
        status, payload, _ = self.make_request(severity="CATASTROPHIC")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_rejects_negative_affected_people(self):
        status, payload, _ = self.make_request(affectedPeople=-5)
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_rejects_out_of_range_coordinates(self):
        for overrides in ({"latitude": 95}, {"latitude": -91}, {"longitude": 181}, {"longitude": -181}):
            status, _, _ = self.make_request(**overrides)
            self.assertEqual(status, 400, overrides)

    def test_rejects_non_numeric_coordinates(self):
        status, payload, _ = self.make_request(latitude="not-a-number")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_rejects_empty_location_name(self):
        status, payload, _ = self.make_request(locationName="   ")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_rejects_unknown_resource_category(self):
        status, payload, _ = self.make_request(requiredResources=["Helicopter"])
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_rejects_non_list_required_resources(self):
        status, _, _ = self.make_request(requiredResources="Ambulance")
        self.assertEqual(status, 400)

    def test_empty_resources_are_allowed(self):
        record = self.unique(requiredResources=[])
        self.assertEqual(record["requiredResources"], [])

    def test_duplicate_resources_are_collapsed(self):
        record = self.unique(requiredResources=["Supply", "Supply"])
        self.assertEqual(record["requiredResources"], ["Supply"])

    def test_lowercase_enums_are_normalised(self):
        record = self.unique(type="fire", severity="high")
        self.assertEqual((record["type"], record["severity"]), ("FIRE", "HIGH"))

    def test_html_in_location_is_escaped(self):
        record = self.unique(locationName="<script>alert(1)</script>")
        self.assertNotIn("<script>", record["locationName"])

    def test_oversized_body_is_refused(self):
        status, payload, _ = self.make_request(locationName="x" * 300)
        self.assertEqual(status, 400)

    def test_malformed_json_is_refused(self):
        req = urllib.request.Request(
            self.base + "/api/requests",
            data=b"{not json",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            self.fail("expected 400")
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 400)

    def test_admin_can_list_and_read_requests(self):
        record = self.unique()
        self.login()
        status, payload, _ = self.get("/api/admin/requests")
        self.assertEqual(status, 200)
        self.assertIn(record["id"], [r["id"] for r in payload["requests"]])

        status, single, _ = self.get("/api/admin/requests/" + record["id"])
        self.assertEqual(status, 200)
        self.assertEqual(single["request"]["id"], record["id"])

    def test_admin_listing_requires_a_session(self):
        status, _, _ = self.get("/api/admin/requests")
        self.assertEqual(status, 401)


class ReviewTests(ServerTestCase):
    def test_accept_requires_session_and_csrf(self):
        record = self.unique()

        # anonymous
        status, _, _ = self.patch("/api/admin/requests/" + record["id"], {"status": "accepted"})
        self.assertEqual(status, 401)

        self.login()
        saved_csrf = self.csrf
        self.csrf = None
        status, payload, _ = self.patch("/api/admin/requests/" + record["id"], {"status": "accepted"})
        self.assertEqual(status, 403, payload)  # session present, CSRF missing
        self.csrf = saved_csrf

        status, payload, _ = self.patch("/api/admin/requests/" + record["id"], {"status": "accepted"}, csrf=True)
        self.assertEqual(status, 200)
        self.assertEqual(payload["request"]["status"], "accepted")
        self.assertIsNotNone(payload["request"]["decidedAt"])

    def test_reject_is_recorded(self):
        record = self.unique()
        self.login()
        status, payload, _ = self.patch(
            "/api/admin/requests/" + record["id"], {"status": "rejected"}, csrf=True
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["request"]["status"], "rejected")

    def test_a_request_can_only_be_reviewed_once(self):
        record = self.unique()
        self.login()
        first, _, _ = self.patch("/api/admin/requests/" + record["id"], {"status": "accepted"}, csrf=True)
        self.assertEqual(first, 200)
        status, payload, _ = self.patch("/api/admin/requests/" + record["id"], {"status": "rejected"}, csrf=True)
        self.assertEqual(status, 409)
        self.assertIn("already", payload["error"].lower())

    def test_invalid_status_value(self):
        record = self.unique()
        self.login()
        status, payload, _ = self.patch(
            "/api/admin/requests/" + record["id"], {"status": "maybe"}, csrf=True
        )
        self.assertEqual(status, 400)

    def test_unknown_request_id(self):
        self.login()
        status, _, _ = self.patch("/api/admin/requests/REQ-NOPE1234", {"status": "accepted"}, csrf=True)
        self.assertEqual(status, 404)


class AuthTests(ServerTestCase):
    def test_login_issues_httponly_samesite_cookie(self):
        status, payload, headers = self.login()
        self.assertEqual(status, 200)
        self.assertIn("csrfToken", payload)
        cookie = headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn(admin_server.SESSION_COOKIE_NAME, cookie)
        self.assertNotIn(PASSWORD, cookie)

    def test_wrong_password_is_rejected(self):
        status, payload, _ = self.login(password="wrong wrong wrong")
        self.assertEqual(status, 401)
        self.assertIn("error", payload)

    def test_session_endpoint_reflects_state(self):
        status, _, _ = self.get("/api/admin/session")
        self.assertEqual(status, 401)
        self.login()
        status, payload, _ = self.get("/api/admin/session")
        self.assertEqual(status, 200)
        self.assertTrue(payload["authenticated"])

    def test_logout_revokes_the_session(self):
        self.login()
        status, _, _ = self.post("/api/admin/logout", {}, csrf=True)
        self.assertEqual(status, 200)
        self.cookies = None
        status, _, _ = self.get("/api/admin/requests")
        self.assertEqual(status, 401)

    def test_logout_requires_csrf(self):
        self.login()
        saved, self.csrf = self.csrf, None
        status, _, _ = self.post("/api/admin/logout", {}, csrf=False)
        self.assertEqual(status, 403)
        self.csrf = saved

    def test_expired_session_is_refused(self):
        self.login()
        token = self.cookies.split("=", 1)[1]
        stale = (admin_server.utc_now() - admin_server.SESSION_LIFETIME).replace(microsecond=0)
        with self.store._connect() as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                (admin_server.iso(stale), self.store._hash(token)),
            )
        status, payload, _ = self.get("/api/admin/requests")
        self.assertEqual(status, 401)

    def test_password_is_not_stored_in_plaintext(self):
        row = self.store.path
        with sqlite3.connect(row) as conn:
            salt, iterations, digest = conn.execute(
                "SELECT salt, iterations, password_hash FROM admin_credentials WHERE id = 1"
            ).fetchone()
        self.assertNotIn(PASSWORD.encode(), bytes(digest))
        self.assertNotIn(PASSWORD.encode(), bytes(salt))
        self.assertGreaterEqual(iterations, 100_000)
        self.assertEqual(len(bytes(digest)), 32)

    def test_rate_limits_repeated_failures(self):
        for _ in range(admin_server.LOGIN_MAX_ATTEMPTS):
            self.login(password="nope nope nope nope")
        status, payload, _ = self.login()  # even the right password is throttled now
        self.assertEqual(status, 429)
        self.store.clear_login_failures("127.0.0.1")


class StaticAndMiscTests(ServerTestCase):
    def test_health_endpoint(self):
        with urllib.request.urlopen(self.base + "/api/health") as resp:
            payload = json.loads(resp.read())
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["passwordConfigured"])

    def test_site_root_serves_index(self):
        with urllib.request.urlopen(self.base + "/") as resp:
            body = resp.read().decode()
        self.assertIn("Disaster Relief Resource Allocation System", body)

    def test_admin_alias_and_static_assets(self):
        for path in ("/admin", "/admin.html", "/css/style.css", "/js/main.js", "/css/admin.css", "/js/admin.js"):
            with urllib.request.urlopen(self.base + path) as resp:
                self.assertEqual(resp.status, 200, path)

    def test_no_directory_listing_or_traversal(self):
        for path in ("/../", "/..%2fadmin_server.py", "/data/"):
            try:
                with urllib.request.urlopen(self.base + path) as resp:
                    body = resp.read().decode(errors="replace")
            except urllib.error.HTTPError as err:
                self.assertIn(err.code, (400, 403, 404), path)
                continue
            self.assertNotIn("pbkdf2_hmac", body, path)

    def test_unknown_api_endpoint_is_json_404(self):
        status, payload, _ = self.get("/api/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", payload)

    def test_cookie_secure_opt_in(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        httpd, store, base = self._start(Path(tmp.name) / "secure.sqlite3", cookie_secure=True)
        store.set_password(PASSWORD)
        try:
            req = urllib.request.Request(
                base + "/api/admin/login",
                data=json.dumps({"password": PASSWORD}).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                cookie = resp.headers.get("Set-Cookie", "")
            self.assertIn("Secure", cookie)
        finally:
            httpd.shutdown()
            httpd.server_close()


class CookiePolicyTests(ServerTestCase):
    """The session cookie's attributes decide whether sign-in survives at all."""

    def set_cookie_for(self, *, cookie_secure=False, cookie_samesite=None, cookie_partitioned=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kwargs = {} if cookie_samesite is None else {"cookie_samesite": cookie_samesite}
        httpd, store, base = self._start(
            Path(tmp.name) / "c.sqlite3", cookie_secure, cookie_partitioned=cookie_partitioned, **kwargs
        )
        store.set_password(PASSWORD)
        try:
            req = urllib.request.Request(
                base + "/api/admin/login",
                data=json.dumps({"password": PASSWORD}).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                return resp.headers.get("Set-Cookie", "")
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_default_is_strict_and_not_secure(self):
        cookie = self.set_cookie_for()
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)

    def test_none_implies_secure(self):
        # Browsers refuse SameSite=None without Secure, so the pair is mandatory.
        cookie = self.set_cookie_for(cookie_samesite="None")
        self.assertIn("SameSite=None", cookie)
        self.assertIn("Secure", cookie)

    def test_lax_is_supported_for_same_site_embeds(self):
        cookie = self.set_cookie_for(cookie_samesite="Lax")
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn("Secure", cookie)

    def test_cookie_name_path_and_max_age_present(self):
        cookie = self.set_cookie_for(cookie_samesite="None")
        self.assertTrue(cookie.startswith(admin_server.SESSION_COOKIE_NAME + "="))
        self.assertIn("Path=/", cookie)
        self.assertIn(f"Max-Age={int(admin_server.SESSION_LIFETIME.total_seconds())}", cookie)

    def test_strict_policy_round_trips_over_plain_http(self):
        """Baseline that the iframe case lacks: with Strict and no Secure flag the
        cookie is stored and returned, so sign-in survives the next request."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Strict + no Secure flag: usable over plain http.
        httpd, store, base = self._start(Path(tmp.name) / "s.sqlite3", False)
        store.set_password(PASSWORD)
        record = store.create_request(
            admin_server.validate_request_payload(
                {
                    "type": "FLOOD",
                    "severity": "HIGH",
                    "affectedPeople": 5,
                    "requiredResources": [],
                    "locationName": "Test",
                    "latitude": 1.0,
                    "longitude": 2.0,
                }
            )
        )
        try:
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            login = urllib.request.Request(
                base + "/api/admin/login",
                data=json.dumps({"password": PASSWORD}).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            opener.open(login).read()
            payload = json.loads(opener.open(base + "/api/admin/requests").read())
            self.assertIn(record["id"], [r["id"] for r in payload["requests"]])
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_secure_cookie_from_none_policy_is_not_sent_over_plain_http(self):
        """Pins the trap: choosing None on a plain-http host reproduces the exact
        'signed in but immediately unauthenticated' failure, because Secure cookies
        are withheld. Use None only behind TLS."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        httpd, store, base = self._start(Path(tmp.name) / "h.sqlite3", False, cookie_samesite="None")
        store.set_password(PASSWORD)
        try:
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            login = urllib.request.Request(
                base + "/api/admin/login",
                data=json.dumps({"password": PASSWORD}).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            opener.open(login).read()
            cookie = next(c for c in jar if c.name == admin_server.SESSION_COOKIE_NAME)
            self.assertTrue(cookie.secure, "None must imply Secure")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                opener.open(base + "/api/admin/requests")
            self.assertEqual(ctx.exception.code, 401)  # cookie stored, never sent
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_rejects_unknown_policy(self):
        with self.assertRaises(ValueError):
            admin_server.normalize_samesite("Nope")
        for good in ("strict", "LAX", "none", " None "):
            self.assertIn(admin_server.normalize_samesite(good), ("Strict", "Lax", "None"))

    def test_partitioned_attribute_for_embedded_frames(self):
        cookie = self.set_cookie_for(cookie_samesite="None", cookie_partitioned=True)
        self.assertIn("Partitioned", cookie)
        self.assertIn("SameSite=None", cookie)
        self.assertIn("Secure", cookie)

    def test_partitioned_is_ignored_without_none(self):
        # Browsers reject Partitioned unless SameSite=None, so it is dropped rather
        # than emitting a cookie that would be silently discarded.
        cookie = self.set_cookie_for(cookie_samesite="Strict", cookie_partitioned=True)
        self.assertNotIn("Partitioned", cookie)

    def test_cli_refuses_partitioned_without_none(self):
        with self.assertRaises(SystemExit) as ctx:
            admin_server.main(["--cookie-partitioned"])
        self.assertEqual(ctx.exception.code, 2)


class ValidationUnitTests(unittest.TestCase):
    """Direct unit coverage of the payload validator's edge cases."""

    def base_payload(self):
        return {
            "type": "FLOOD",
            "severity": "LOW",
            "affectedPeople": 1,
            "requiredResources": [],
            "locationName": "Dehradun",
            "latitude": 0,
            "longitude": 0,
        }

    def test_rejects_non_object(self):
        with self.assertRaises(admin_server.ApiError):
            admin_server.validate_request_payload([1, 2, 3])

    def test_booleans_are_not_numbers(self):
        payload = self.base_payload()
        payload["affectedPeople"] = True
        with self.assertRaises(admin_server.ApiError):
            admin_server.validate_request_payload(payload)

    def test_float_affected_people_is_truncated(self):
        payload = self.base_payload()
        payload["affectedPeople"] = 12.9
        self.assertEqual(admin_server.validate_request_payload(payload)["affectedPeople"], 12)

    def test_missing_optional_resources_defaults_to_empty(self):
        payload = self.base_payload()
        del payload["requiredResources"]
        self.assertEqual(admin_server.validate_request_payload(payload)["requiredResources"], [])

    def test_boundary_coordinates_accepted(self):
        payload = self.base_payload()
        payload.update({"latitude": -90, "longitude": 180})
        self.assertEqual(admin_server.validate_request_payload(payload)["latitude"], -90.0)

    def test_too_long_location_rejected(self):
        payload = self.base_payload()
        payload["locationName"] = "a" * 201
        with self.assertRaises(admin_server.ApiError):
            admin_server.validate_request_payload(payload)


class StoreUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = admin_server.Store(Path(self.tmp.name) / "unit.sqlite3")

    def test_schema_is_idempotent(self):
        admin_server.Store(self.store.path)  # re-opening must not error

    def test_password_roundtrip_and_reset(self):
        self.assertFalse(self.store.has_password())
        self.store.set_password("alpha bravo charlie")
        self.assertTrue(self.store.verify_password("alpha bravo charlie"))
        self.assertFalse(self.store.verify_password("alpha bravo delta"))
        self.store.set_password("delta echo foxtrot")
        self.assertFalse(self.store.verify_password("alpha bravo charlie"))
        self.assertTrue(self.store.verify_password("delta echo foxtrot"))

    def test_verify_without_password_configured(self):
        self.assertFalse(self.store.verify_password("anything"))

    def test_session_lifecycle(self):
        token, csrf = self.store.create_session()
        self.assertIsNotNone(self.store.get_session(token))
        self.assertTrue(self.store.check_csrf(token, csrf))
        self.assertFalse(self.store.check_csrf(token, "wrong"))
        self.assertFalse(self.store.check_csrf("", csrf))
        self.store.delete_session(token)
        self.assertIsNone(self.store.get_session(token))

    def test_unknown_session_token(self):
        self.assertIsNone(self.store.get_session("does-not-exist"))
        self.assertFalse(self.store.check_csrf("does-not-exist", "x"))

    def test_set_status_on_missing_row(self):
        with self.assertRaises(admin_server.ApiError):
            self.store.set_request_status("REQ-MISSING", "accepted")

    def test_corrupt_resources_json_degrades_gracefully(self):
        record = self.store.create_request(
            admin_server.validate_request_payload(
                {
                    "type": "FIRE",
                    "severity": "HIGH",
                    "affectedPeople": 3,
                    "requiredResources": [],
                    "locationName": "X",
                    "latitude": 1.0,
                    "longitude": 2.0,
                }
            )
        )
        with self.store._connect() as conn:
            conn.execute("UPDATE requests SET required_resources = 'garbage' WHERE id = ?", (record["id"],))
        self.assertEqual(self.store.get_request(record["id"])["requiredResources"], [])


if __name__ == "__main__":
    unittest.main()
