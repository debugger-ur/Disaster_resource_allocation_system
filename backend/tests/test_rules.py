"""Unit tests for duplicate detection, risk scoring and allocation ranking."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["DRRAS_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from allocation import rank_centres  # noqa: E402
from config import DEFAULT_SETTINGS  # noqa: E402
from rules import assess_risk, auto_approval, description_similarity, find_duplicates, haversine_km  # noqa: E402


def now():
    return datetime.now(timezone.utc)


def new_report(**overrides):
    data = {
        "id": "REQ-NEW", "type": "FLOOD", "severity": "HIGH", "people": 30,
        "description": "Flood water entered the lanes near the canal. Families need food, water and medicine.",
        "latitude": 30.304, "longitude": 78.097, "contact_phone": "9876500099",
        "contact_email": "a@example.com", "resources": {"Food": 30, "Water": 60},
        "created_at": now().isoformat(),
    }
    data.update(overrides)
    return data


def old_report(**overrides):
    data = {
        "id": "REQ-OLD", "type": "FLOOD", "severity": "HIGH", "people": 28,
        "description": "Flood water entered the lanes near the canal. Families need food, water and medicine.",
        "latitude": 30.305, "longitude": 78.098, "contact_phone": "9876500011",
        "contact_email": "b@example.com", "resources": {"Food": 25},
        "created_at": (now() - timedelta(hours=2)).isoformat(),
    }
    data.update(overrides)
    return data


class RuleTests(unittest.TestCase):
    def test_haversine_and_description_similarity(self):
        self.assertAlmostEqual(haversine_km(30.3, 78.0, 30.3, 78.0), 0, places=3)
        self.assertGreater(haversine_km(30.3, 78.0, 30.4, 78.1), 10)
        self.assertGreater(description_similarity("Flood water near the canal", "Flood water near canal"), 0.7)
        self.assertLess(description_similarity("Flood water near the canal", "A shop caught fire"), 0.3)

    def test_duplicate_detection_explains_the_score(self):
        matches = find_duplicates(new_report(), [old_report()], DEFAULT_SETTINGS)
        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match["id"], "REQ-OLD")
        self.assertTrue(match["isPossibleDuplicate"])
        self.assertGreaterEqual(match["score"], DEFAULT_SETTINGS["duplicateThreshold"])
        self.assertTrue(match["reasons"])
        self.assertLess(match["distanceKm"], 1)

    def test_old_or_far_reports_are_not_duplicates(self):
        old = old_report(created_at=(now() - timedelta(days=10)).isoformat())
        self.assertEqual(find_duplicates(new_report(), [old], DEFAULT_SETTINGS), [])
        far = old_report(latitude=29.0, longitude=77.0)
        self.assertEqual(find_duplicates(new_report(), [far], DEFAULT_SETTINGS), [])

    def test_risk_flags_missing_contact_and_outside_area(self):
        risk = assess_risk(
            new_report(contact_phone="", contact_email="", latitude=20.0, longitude=70.0,
                       severity="CRITICAL", people=2),
            [], 0,
        )
        self.assertGreaterEqual(risk["score"], 45)
        self.assertEqual(risk["level"], "high")
        self.assertTrue(any("phone" in reason.lower() for reason in risk["reasons"]))
        self.assertTrue(any("outside" in reason.lower() for reason in risk["reasons"]))

    def test_auto_approval_requires_every_safe_condition(self):
        settings = dict(DEFAULT_SETTINGS)
        self.assertFalse(auto_approval(new_report(), {"score": 0}, [], settings)[0])
        settings["autoApproveEnabled"] = True
        settings["autoApproveSeverities"] = ["LOW", "MEDIUM", "HIGH"]
        allowed, reason = auto_approval(new_report(), {"score": 5}, [], settings)
        self.assertTrue(allowed, reason)
        blocked, _ = auto_approval(new_report(contact_phone="", contact_email=""), {"score": 5}, [], settings)
        self.assertFalse(blocked)
        duplicate = [{"isPossibleDuplicate": True}]
        self.assertFalse(auto_approval(new_report(), {"score": 5}, duplicate, settings)[0])

    def test_ranking_prefers_stock_and_proximity(self):
        request = {"severity": "CRITICAL", "resources": {"Food": 10, "Water": 10}}
        centres = [
            {"id": "near", "name": "Near", "category": "relief_camp", "availability": "available",
             "latitude": 30.3, "longitude": 78.0, "distanceKm": 2, "durationMin": 5,
             "distanceSource": "osrm", "stock": {"Food": 50, "Water": 50}},
            {"id": "far", "name": "Far", "category": "warehouse", "availability": "available",
             "latitude": 30.5, "longitude": 78.3, "distanceKm": 30, "durationMin": 60,
             "distanceSource": "osrm", "stock": {"Food": 50, "Water": 50}},
            {"id": "closed", "name": "Closed", "category": "other", "availability": "closed",
             "latitude": 30.3, "longitude": 78.0, "distanceKm": 1, "durationMin": 2,
             "distanceSource": "osrm", "stock": {"Food": 50, "Water": 50}},
        ]
        result = rank_centres(centres, request)
        self.assertEqual(result["best"]["centreId"], "near")
        self.assertNotIn("closed", [item["centreId"] for item in result["candidates"]])
        self.assertEqual(result["best"]["coveragePct"], 100)
        self.assertEqual(result["best"]["supplied"], {"Food": 10, "Water": 10})

    def test_partial_coverage_is_reported(self):
        request = {"severity": "HIGH", "resources": {"Food": 10, "Medicine": 5}}
        centre = [{"id": "one", "name": "One", "category": "relief_camp", "availability": "limited",
                   "latitude": 30.3, "longitude": 78.0, "distanceKm": 3, "durationMin": 8,
                   "distanceSource": "estimate", "stock": {"Food": 10}}]
        result = rank_centres(centre, request)
        self.assertEqual(result["best"]["supplied"], {"Food": 10})
        self.assertEqual(result["best"]["missing"], ["Medicine"])
        self.assertLess(result["best"]["coveragePct"], 100)
        self.assertTrue(result["best"]["warnings"])


if __name__ == "__main__":
    unittest.main()
