"""Security tests for evidence uploads and reuse detection."""

from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DRRAS_OFFLINE", "1")

import admin_server  # noqa: E402

PASSWORD = "upload test password"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl9sAAAAASUVORK5CYII="
)


class UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = admin_server.Store(Path(cls.tmp.name) / "test.sqlite3")
        cls.store.set_password(PASSWORD)
        cls.httpd = admin_server.make_server("127.0.0.1", 0, cls.store, False)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, cookie=None, csrf=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if cookie:
            req.add_header("Cookie", cookie)
        if csrf:
            req.add_header("X-CSRF-Token", csrf)
        try:
            with urllib.request.urlopen(req) as resp:
                payload = resp.read()
                return resp.status, (payload if raw else json.loads(payload or b"{}")), resp.headers
        except urllib.error.HTTPError as err:
            payload = err.read()
            try:
                parsed = json.loads(payload or b"{}")
            except json.JSONDecodeError:
                parsed = {"raw": payload}
            return err.code, parsed, err.headers

    def login(self):
        status, payload, headers = self.request(
            "POST", "/api/admin/login", {"password": PASSWORD}
        )
        self.assertEqual(status, 200)
        cookie = headers.get("Set-Cookie", "").split(";")[0]
        return cookie, payload["csrfToken"]

    def upload(self, mime="image/png", data=PNG, name="flood.png"):
        return self.request(
            "POST",
            "/api/uploads",
            {"fileName": name, "mimeType": mime, "data": base64.b64encode(data).decode()},
        )

    def submit(self, evidence_id, **overrides):
        payload = {
            "type": "FLOOD",
            "severity": "LOW",
            "affectedPeople": 40,
            "locationName": "Raipur canal area, Dehradun",
            "latitude": 30.3195,
            "longitude": 78.0401,
            "description": (
                "Flood water has entered homes near the Raipur canal. Families need "
                "clean drinking water and blankets for the night."
            ),
            "contactName": "Asha",
            "contactPhone": "+91 98111 22334",
            "contactEmail": "asha@example.org",
            "requiredResources": ["Supply"],
            "resourceQuantities": {"Supply": 20},
            "evidence": [evidence_id],
        }
        payload.update(overrides)
        return self.request("POST", "/api/requests", payload)

    def test_valid_png_upload_is_private_until_an_admin_fetches_it(self):
        status, payload, _ = self.upload()
        self.assertEqual(status, 201, payload)
        evidence = payload["evidence"]
        self.assertTrue(evidence["id"].startswith("EV-"))
        self.assertEqual(evidence["mimeType"], "image/png")

        status, _, _ = self.request("GET", f"/api/admin/evidence/{evidence['id']}")
        self.assertIn(status, (401, 403))

        cookie, _ = self.login()
        status, body, headers = self.request(
            "GET", f"/api/admin/evidence/{evidence['id']}", cookie=cookie, raw=True
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, PNG)
        self.assertEqual(headers.get("Content-Type"), "image/png")
        self.assertIn("nosniff", headers.get("X-Content-Type-Options", ""))

    def test_disallowed_type_and_content_mismatch_are_rejected(self):
        status, payload, _ = self.upload(mime="image/gif", data=b"GIF89a")
        self.assertEqual(status, 400)
        self.assertIn("JPEG", payload["error"])

        status, payload, _ = self.upload(mime="image/png", data=b"%PDF-1.7 not really a png")
        self.assertEqual(status, 400)
        self.assertIn("does not match", payload["error"])

        status, payload, _ = self.upload(mime="image/png", data=b"")
        self.assertEqual(status, 400)

    def test_evidence_is_attached_to_the_request_and_reuse_raises_risk(self):
        _, first, _ = self.upload()
        _, second, _ = self.upload(name="same-photo.png")
        self.assertNotEqual(first["evidence"]["id"], second["evidence"]["id"])
        self.assertEqual(first["evidence"]["sha256"], second["evidence"]["sha256"])

        status, created, _ = self.submit(first["evidence"]["id"])
        self.assertEqual(status, 201, created)
        request_id = created["request"]["id"]
        status, public, _ = self.request("GET", f"/api/requests/{request_id}")
        self.assertEqual(status, 200)
        self.assertNotIn("evidence", public["request"])

        status, reused, _ = self.submit(
            second["evidence"]["id"],
            locationName="Chakrata Road market, Dehradun",
            latitude=30.3550,
            longitude=77.9850,
            description=(
                "A fire damaged a shop on Chakrata Road. The owner needs tarpaulins "
                "to cover the roof before tonight."
            ),
            contactName="Vikram",
            contactPhone="+91 98990 12121",
            contactEmail="vikram@example.org",
            type="FIRE",
            requiredResources=["Equipment"],
            resourceQuantities={"Equipment": 2},
        )
        self.assertEqual(status, 201, reused)
        self.assertNotEqual(reused["request"]["workflowStatus"], "rejected")

        admin = self.store.get_request(request_id)
        self.assertEqual(admin["evidence"][0]["id"], first["evidence"]["id"])
        self.assertEqual(admin["evidence"][0]["mimeType"], "image/png")
        reused_admin = self.store.get_request(reused["request"]["id"])
        reasons = {item["code"] for item in reused_admin["risk"]["reasons"]}
        self.assertIn("reused_evidence", reasons)
        self.assertNotEqual(reused_admin["workflowStatus"], "rejected")


if __name__ == "__main__":
    unittest.main()
