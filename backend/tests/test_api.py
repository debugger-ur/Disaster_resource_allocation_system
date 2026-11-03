"""End-to-end API tests for the lean DRRAS application."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["DRRAS_OFFLINE"] = "1"
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import LIMITER, make_server  # noqa: E402
from db import Store  # noqa: E402

ADMIN_PASSWORD = "CollegeProject2026!"


class Client:
    def __init__(self, base: str):
        self.base = base
        self.token = ""
        self.csrf = ""

    def call(self, method: str, path: str, body=None, csrf: bool = True):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if csrf and self.csrf and method != "GET":
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                text = response.read().decode()
                try:
                    return response.status, json.loads(text)
                except json.JSONDecodeError:
                    return response.status, text
        except urllib.error.HTTPError as error:
            text = error.read().decode()
            try:
                return error.code, json.loads(text)
            except json.JSONDecodeError:
                return error.code, text

    def login_admin(self):
        status, data = self.call("POST", "/api/admin/login", {"password": ADMIN_PASSWORD}, csrf=False)
        assert status == 200, data
        self.token, self.csrf = data["sessionToken"], data["csrfToken"]

    def register(self, email="asha@example.com", name="Asha"):
        status, data = self.call(
            "POST", "/api/auth/register",
            {"name": name, "email": email, "password": "studentpass"},
            csrf=False,
        )
        assert status == 201, data
        self.token, self.csrf = data["sessionToken"], data["csrfToken"]
        return data


def report(**overrides):
    data = {
        "disasterType": "FLOOD",
        "severity": "HIGH",
        "affectedPeople": 25,
        "description": "Flood water entered the lanes near the canal. Families are in the community hall and need food, water and medicine.",
        "locationName": "Raipur canal area, Dehradun",
        "latitude": 30.3042,
        "longitude": 78.0970,
        "contactName": "Test Reporter",
        "contactPhone": "9876500099",
        "contactEmail": "reporter@example.com",
        "resources": {"Food": 25, "Water": 50, "Medicine": 5},
        "evidence": [],
    }
    data.update(overrides)
    return data


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        LIMITER.hits.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "test.sqlite3")
        self.store.set_admin_password(ADMIN_PASSWORD)
        self.server = make_server(self.store, 0, allow_bearer=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.admin = Client(self.base)
        self.admin.login_admin()
        self.public = Client(self.base)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def submit(self, **overrides):
        status, data = self.public.call("POST", "/api/requests", report(**overrides), csrf=False)
        self.assertEqual(status, 201, data)
        return data["request"]

    def test_health_and_static_site(self):
        status, health = self.public.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["passwordConfigured"])
        self.assertTrue(health["routing"]["offline"])
        status, html = self.public.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("DRRAS", html if isinstance(html, str) else json.dumps(html))

    def test_admin_login_and_csrf_protection(self):
        wrong = Client(self.base)
        status, _ = wrong.call("POST", "/api/admin/login", {"password": "wrong"}, csrf=False)
        self.assertEqual(status, 401)
        status, _ = self.admin.call("POST", "/api/admin/seed-demo", {}, csrf=False)
        self.assertEqual(status, 403)
        status, _ = self.admin.call("POST", "/api/admin/seed-demo", {})
        self.assertEqual(status, 200)

    def test_register_login_and_duplicate_email(self):
        user = self.public.register()
        self.assertEqual(user["user"]["email"], "asha@example.com")
        status, session = self.public.call("GET", "/api/auth/session")
        self.assertEqual(status, 200)
        self.assertTrue(session["authenticated"])
        status, data = Client(self.base).call(
            "POST", "/api/auth/register",
            {"name": "Again", "email": "asha@example.com", "password": "studentpass"},
            csrf=False,
        )
        self.assertEqual(status, 409)
        client = Client(self.base)
        status, login = client.call(
            "POST", "/api/auth/login",
            {"email": "asha@example.com", "password": "studentpass"}, csrf=False,
        )
        self.assertEqual(status, 200)
        self.assertEqual(login["role"], "citizen")

    def test_report_validation(self):
        bad = report(resources={})
        status, data = self.public.call("POST", "/api/requests", bad, csrf=False)
        self.assertEqual(status, 400)
        self.assertIn("resource", data["error"].lower())
        bad = report(contactEmail="not-an-email")
        status, _ = self.public.call("POST", "/api/requests", bad, csrf=False)
        self.assertEqual(status, 400)
        bad = report(resources={"Food": "many"})
        status, _ = self.public.call("POST", "/api/requests", bad, csrf=False)
        self.assertEqual(status, 400)

    def test_duplicate_warning_is_never_automatic_rejection(self):
        first = self.submit()
        second = self.submit(
            locationName="Raipur village, Dehradun", latitude=30.3048,
            contactPhone="9876500011", contactEmail="other@example.com",
        )
        self.assertEqual(second["status"], "pending")
        status, detail = self.admin.call("GET", f"/api/admin/requests/{second['id']}")
        record = detail["request"]
        self.assertTrue(record["possibleDuplicate"])
        self.assertGreaterEqual(len(record["duplicateMatches"]), 1)
        self.assertEqual(record["duplicateMatches"][0]["id"], first["id"])
        self.assertNotEqual(record["status"], "rejected")

    def test_auto_approval_respects_administrator_rules(self):
        settings = self.store.get_settings()
        settings.update({
            "autoApproveEnabled": True, "autoApproveMaxRisk": 20,
            "autoApproveMinDescription": 40, "autoApproveSeverities": ["LOW", "MEDIUM", "HIGH"],
        })
        self.store.save_settings(settings, "test")
        approved = self.submit(severity="LOW")
        self.assertEqual(approved["status"], "approved")
        self.assertTrue(approved["autoApproved"])
        risky = self.submit(
            severity="LOW", description="Too short.", contactPhone="", contactEmail="",
            locationName="Far away", latitude=20.0, longitude=70.0,
        )
        self.assertEqual(risky["status"], "pending")

    def test_approve_reject_and_history(self):
        request = self.submit()
        status, _ = self.admin.call(
            "POST", f"/api/admin/requests/{request['id']}/action", {"action": "reject"}
        )
        self.assertEqual(status, 400)
        status, data = self.admin.call(
            "POST", f"/api/admin/requests/{request['id']}/action",
            {"action": "reject", "reason": "Duplicate of a verified incident."},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["request"]["status"], "rejected")
        labels = [item["label"] for item in data["request"]["history"]]
        self.assertIn("Rejected", labels)

    def test_public_tracking_does_not_expose_contact_details(self):
        request = self.submit()
        status, data = self.public.call("GET", f"/api/requests/{request['id']}")
        self.assertEqual(status, 200)
        serialized = json.dumps(data)
        self.assertNotIn("9876500099", serialized)
        self.assertNotIn("reporter@example.com", serialized)
        self.assertEqual(data["request"]["id"], request["id"])

    def test_recommendation_allocation_and_stock_return(self):
        request = self.submit(resources={"Food": 5, "Water": 5})
        self.admin.call("POST", f"/api/admin/requests/{request['id']}/action", {"action": "approve"})
        status, recs = self.admin.call("GET", f"/api/admin/requests/{request['id']}/recommendations")
        self.assertEqual(status, 200, recs)
        candidate = recs["best"]
        self.assertIsNotNone(candidate)
        centre = next(item for item in self.store.list_centres() if item["id"] == candidate["centreId"])
        stock_before = centre["stock"]["Food"]
        status, data = self.admin.call(
            "POST", f"/api/admin/requests/{request['id']}/allocations",
            {
                "centreId": candidate["centreId"], "items": candidate["supplied"],
                "distance": {"distanceKm": candidate["distanceKm"],
                             "durationMin": candidate["durationMin"],
                             "distanceSource": candidate["distanceSource"]},
                "overrideReason": "Test partial allocation" if candidate["missing"] else "",
            },
        )
        self.assertEqual(status, 201, data)
        allocation = data["request"]["allocation"]
        centre_after = next(item for item in self.store.list_centres() if item["id"] == candidate["centreId"])
        self.assertEqual(centre_after["stock"].get("Food", 0), stock_before - candidate["supplied"].get("Food", 0))
        status, data = self.admin.call(
            "PATCH", f"/api/admin/allocations/{allocation['id']}", {"action": "cancelled"}
        )
        self.assertEqual(status, 200, data)
        restored = next(item for item in self.store.list_centres() if item["id"] == candidate["centreId"])
        self.assertEqual(restored["stock"]["Food"], stock_before)
        self.assertEqual(data["request"]["status"], "approved")

    def test_nearby_uses_labelled_estimates_when_offline(self):
        status, data = self.public.call("GET", "/api/nearby?lat=30.3165&lon=78.0322&radius=50")
        self.assertEqual(status, 200)
        self.assertGreater(data["count"], 0)
        self.assertTrue(all(item["distanceSource"] == "estimate" for item in data["centres"]))
        status, data = self.public.call(
            "GET", "/api/nearby?lat=30.3165&lon=78.0322&resource=Medicine"
        )
        self.assertEqual(status, 200)
        self.assertTrue(all(item["stock"].get("Medicine", 0) > 0 for item in data["centres"]))

    def test_place_search_uses_local_fallback_when_offline(self):
        status, data = self.public.call("GET", "/api/places?q=Raipur")
        self.assertEqual(status, 200)
        self.assertTrue(data["results"])
        self.assertTrue(any("Raipur" in item["name"] for item in data["results"]))
        status, _ = self.public.call("GET", "/api/places?q=a")
        self.assertEqual(status, 400)

    def test_upload_validation(self):
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"test").decode()
        status, data = self.public.call(
            "POST", "/api/uploads", {"name": "photo.png", "type": "image/png", "data": png}, csrf=False
        )
        self.assertEqual(status, 201, data)
        status, _ = self.public.call(
            "POST", "/api/uploads", {"name": "bad.png", "type": "image/png", "data": "aGVsbG8="}, csrf=False
        )
        self.assertEqual(status, 400)
        status, _ = self.public.call(
            "POST", "/api/uploads", {"name": "x.txt", "type": "text/plain", "data": png}, csrf=False
        )
        self.assertEqual(status, 400)

    def test_centre_create_and_stock_update(self):
        status, data = self.admin.call("POST", "/api/admin/centres", {
            "name": "Test Medical Camp", "category": "medical_camp",
            "latitude": 30.32, "longitude": 78.04, "address": "Test road",
            "phone": "+91 135 000 0000", "availability": "available",
            "notes": "Test centre", "stock": {"Medicine": 25},
        })
        self.assertEqual(status, 201, data)
        centre = data["centre"]
        status, data = self.admin.call("PATCH", f"/api/admin/centres/{centre['id']}", {
            "availability": "limited", "stock": {"Medicine": 40},
        })
        self.assertEqual(status, 200, data)
        self.assertEqual(data["centre"]["availability"], "limited")
        self.assertEqual(data["centre"]["stock"]["Medicine"], 40)

    def test_seed_demo_is_idempotent_for_stock(self):
        self.admin.call("POST", "/api/admin/seed-demo", {})
        first = next(item for item in self.store.list_centres() if item["id"] == "HC-DDN-30")["stock"]
        self.admin.call("POST", "/api/admin/seed-demo", {})
        second = next(item for item in self.store.list_centres() if item["id"] == "HC-DDN-30")["stock"]
        self.assertEqual(first, second)
        status, data = self.admin.call("GET", "/api/admin/requests")
        self.assertEqual(len(data["requests"]), 4)

    def test_my_requests_are_private_to_the_signed_in_user(self):
        self.public.register("one@example.com", "One")
        request = self.submit()
        status, mine = self.public.call("GET", "/api/my/requests")
        self.assertEqual(status, 200)
        self.assertEqual(len(mine["requests"]), 1)
        other = Client(self.base)
        other.register("two@example.com", "Two")
        status, mine = other.call("GET", "/api/my/requests")
        self.assertEqual(mine["requests"], [])
        self.assertNotEqual(request["id"], "")


if __name__ == "__main__":
    unittest.main()
