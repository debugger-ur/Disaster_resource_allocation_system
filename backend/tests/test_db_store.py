"""Persistence and workflow tests for the DRRAS store.

These exercise the real SQLite schema, the verification pipeline, allocation
transactions and the audit trail without going through HTTP.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DRRAS_OFFLINE", "1")

from db_store import Store  # noqa: E402
from drras_common import ApiError, DEFAULT_SETTINGS  # noqa: E402


def submission(**overrides):
    payload = {
        "type": "FLOOD",
        "severity": "LOW",
        "affectedPeople": 60,
        "locationName": "Raipur canal area, Dehradun",
        "latitude": 30.3195,
        "longitude": 78.0401,
        "description": (
            "Flood water has entered about twenty homes near the Raipur canal. "
            "Families need clean drinking water and blankets for the night."
        ),
        "contactName": "Asha Devi",
        "contactPhone": "+91 98111 22334",
        "contactEmail": "asha@example.org",
        "requiredResources": ["Supply"],
        "resourceQuantities": {"Supply": 40},
    }
    payload.update(overrides)
    return payload


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self, **overrides):
        return self.store.submit_request(submission(**overrides), client_ip="127.0.0.1")

    def approve(self, request_id):
        return self.store.apply_action(request_id, "approve", message="Approved in test.")

    def test_submission_is_verified_and_audited_without_ever_rejecting(self):
        record = self.submit()
        self.assertIn(
            record["workflowStatus"],
            ("submitted", "under_verification", "possible_duplicate", "awaiting_approval", "approved"),
        )
        self.assertNotEqual(record["status"], "rejected")
        self.assertIn(record["verificationQueue"], ("auto_approval", "manual_review", "duplicate_review", "high_risk"))
        self.assertIn("score", record["risk"])
        self.assertTrue(record["risk"]["checks"])
        actions = {row["action"] for row in self.store.list_audit(request_id=record["id"])}
        self.assertIn("submitted", actions)
        self.assertIn("verification_completed", actions)

    def test_duplicate_pair_can_be_merged_without_losing_either_report(self):
        first = self.submit()
        second = self.submit(
            description=(
                "Flood water is rising again near the Raipur canal. Twenty homes are "
                "affected and families still need drinking water and blankets."
            ),
            contactName="Asha",
        )
        self.assertEqual(second["workflowStatus"], "possible_duplicate")
        self.assertEqual(second["duplicateOf"], first["id"])

        merged = self.store.apply_action(
            second["id"], "merge", target_id=first["id"], reason="Same colony and contact"
        )
        self.assertEqual(merged["workflowStatus"], "resolved")
        self.assertEqual(merged["mergedInto"], first["id"])
        self.assertIn("Merged into", merged["decisionMessage"])

        survivor = self.store.get_request(first["id"])
        self.assertIn(second["id"], survivor["linkedTo"])
        actions = {row["action"] for row in self.store.list_audit(request_id=second["id"])}
        self.assertIn("merged", actions)
        self.assertTrue(any("merged_source_linked" == row["action"] for row in self.store.list_audit(request_id=first["id"])))

    def test_keep_separate_returns_a_duplicate_to_the_approval_queue(self):
        first = self.submit()
        second = self.submit()
        self.assertEqual(second["workflowStatus"], "possible_duplicate")
        kept = self.store.keep_separate(second["id"], reason="Different colony on the same road")
        self.assertIn(kept["workflowStatus"], ("awaiting_approval", "under_verification"))
        self.assertIsNone(self.store.get_request(second["id"])["mergedInto"])
        approved = self.approve(second["id"])
        self.assertEqual(approved["workflowStatus"], "approved")
        self.assertTrue(approved["decisionMessage"])
        self.assertNotEqual(first["id"], second["id"])

    def test_allocation_commits_stock_refuses_over_allocation_and_restores_on_cancel(self):
        record = self.submit()
        self.approve(record["id"])
        recommendations = self.store.allocation_recommendations(record["id"])
        self.assertTrue(recommendations["candidates"])
        candidate = recommendations["candidates"][0]
        self.assertTrue(candidate["supplied"])
        centre_id = candidate["centreId"]
        items = candidate["supplied"]
        before = {row["id"]: dict(row["stock"]) for row in self.store.list_help_centres()}[centre_id]

        updated = self.store.allocate(
            record["id"],
            centre_id,
            items=items,
            actor="admin",
            role="admin",
            distance={
                "distanceKm": candidate["distanceKm"],
                "durationMin": candidate["durationMin"],
                "distanceSource": candidate["distanceSource"],
                "factors": candidate["factors"],
            },
        )
        self.assertEqual(updated["workflowStatus"], "resources_assigned")
        self.assertEqual(len(updated["allocations"]), 1)
        allocation = updated["allocations"][0]
        after = {row["id"]: dict(row["stock"]) for row in self.store.list_help_centres()}[centre_id]
        for category, amount in items.items():
            self.assertEqual(after[category], before[category] - amount)

        with self.assertRaises(ApiError):
            self.store.allocate(record["id"], centre_id, items={"Supply": 10_000_000})

        # The database's partial unique index blocks a second active allocation
        # to the same centre for the same request.
        with self.assertRaises(ApiError) as duplicate:
            self.store.allocate(record["id"], centre_id, items=items)
        self.assertEqual(duplicate.exception.status, 409)

        cancelled = self.store.update_allocation_status(
            allocation["id"], "cancelled", reason="Test cancellation"
        )
        self.assertEqual(cancelled["status"], "cancelled")
        restored = {row["id"]: dict(row["stock"]) for row in self.store.list_help_centres()}[centre_id]
        self.assertEqual(restored, before)
        actions = {row["action"] for row in self.store.list_audit(request_id=record["id"])}
        self.assertIn("resources_allocated", actions)
        self.assertIn("allocation_cancelled", actions)

    def test_dispatch_and_delivery_update_the_request_and_notify_the_reporter(self):
        record = self.submit()
        self.approve(record["id"])
        candidate = self.store.allocation_recommendations(record["id"])["candidates"][0]
        self.store.allocate(record["id"], candidate["centreId"], items=candidate["supplied"])
        allocation_id = self.store.get_request(record["id"])["allocations"][0]["id"]

        self.store.update_allocation_status(allocation_id, "dispatched")
        self.assertEqual(self.store.get_request(record["id"])["workflowStatus"], "in_progress")
        self.store.update_allocation_status(allocation_id, "delivered")
        public = self.store.get_public_request(record["id"])
        messages = " ".join(item["message"] for item in public["notifications"])
        self.assertIn("dispatched", messages)
        self.assertIn("delivered", messages)

    def test_settings_validation_keeps_risk_tiers_coherent(self):
        settings = self.store.get_settings()
        with self.assertRaises(ApiError):
            self.store.update_settings({"mediumRiskThreshold": 70, "highRiskThreshold": 40})
        with self.assertRaises(ApiError):
            self.store.update_settings({"autoApproveMaxRisk": settings["mediumRiskThreshold"]})
        updated = self.store.update_settings(
            {"duplicateThreshold": 65, "duplicateWindowHours": 48, "submissionRateLimit": 8}
        )
        self.assertEqual(updated["duplicateThreshold"], 65)
        self.assertEqual(updated["duplicateWindowHours"], 48)
        self.assertEqual(updated["submissionRateLimit"], 8)
        actions = {row["action"] for row in self.store.list_audit()}
        self.assertIn("settings_updated", actions)

    def test_auto_approval_is_opt_in_and_can_only_approve(self):
        record = self.submit()
        self.assertNotEqual(record["workflowStatus"], "approved")
        self.assertEqual(record["verificationQueue"], "manual_review")

        self.store.update_settings(
            {
                "autoApproveEnabled": True,
                "autoApproveMaxRisk": 20,
                "autoApproveSeverities": ["LOW"],
                "autoApproveRequireContact": True,
                "duplicateBlockAutoApprove": True,
            }
        )
        approved = self.submit(
            type="FIRE",
            severity="LOW",
            locationName="Chakrata Road market, Dehradun",
            latitude=30.3550,
            longitude=77.9850,
            description=(
                "A small electrical fire damaged one shop on Chakrata Road. The fire "
                "service has left and the shopkeeper needs three tarpaulins."
            ),
            contactName="Vikram Singh",
            contactPhone="+91 98990 12121",
            contactEmail="vikram@example.org",
            requiredResources=["Equipment"],
            resourceQuantities={"Equipment": 1},
        )
        self.assertEqual(approved["workflowStatus"], "approved", approved["risk"])
        self.assertEqual(approved["verificationQueue"], "auto_approval")
        self.assertTrue(approved["decisionMessage"])
        actions = {row["action"] for row in self.store.list_audit(request_id=approved["id"])}
        self.assertIn("auto_approved", actions)

    def test_nearby_filter_by_resource_and_category(self):
        payload = self.store.nearby_centres(
            30.3165, 78.0322, resource="MedicalTeam", availability="all", limit=50
        )
        self.assertGreater(payload["total"], 0)
        for centre in payload["centres"]:
            self.assertGreater(centre["stock"].get("MedicalTeam", 0), 0)
        hospitals = self.store.nearby_centres(
            30.3165, 78.0322, category="hospital", availability="all", limit=50
        )
        self.assertGreater(hospitals["total"], 0)
        self.assertTrue(all(row["category"] == "hospital" for row in hospitals["centres"]))
        empty = self.store.nearby_centres(
            30.3165, 78.0322, resource="Ambulance", availability="closed", limit=50
        )
        self.assertEqual(empty["centres"], [])

    def test_public_view_does_not_leak_contact_details(self):
        mine = self.submit()
        self.submit(
            contactName="Other Person",
            contactPhone="+91 90000 11111",
            contactEmail="other@example.org",
            locationName="Vikasnagar",
            latitude=30.4680,
            longitude=77.9500,
        )
        public = self.store.get_public_request(mine["id"])
        serialised = repr(public)
        self.assertNotIn("98111 22334", serialised)
        self.assertNotIn("asha@example.org", serialised)
        self.assertNotIn("contactPhone", public)
        self.assertIn("workflowStatus", public)
        self.assertEqual(public["id"], mine["id"])

    def test_demo_seed_is_idempotent_and_realistic(self):
        result = self.store.seed_demo()
        self.assertEqual(result["inserted"], 9)
        statuses = {row["workflowStatus"] for row in self.store.list_requests()}
        self.assertTrue({"possible_duplicate", "under_verification", "resources_assigned", "resolved"} <= statuses)
        duplicates = [row for row in self.store.list_requests() if row["workflowStatus"] == "possible_duplicate"]
        self.assertTrue(duplicates)
        self.assertTrue(duplicates[0]["duplicateOf"])
        again = self.store.seed_demo()
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(len(self.store.list_requests()), 9)


if __name__ == "__main__":
    unittest.main()
