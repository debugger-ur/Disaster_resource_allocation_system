"""Unit tests for the duplicate and risk engines.

The engines are pure functions, so these tests exercise them without a
database or HTTP server. They focus on the safety property the project
promises: automation may route work to a person, but it can never reject.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DRRAS_OFFLINE", "1")

from drras_common import DEFAULT_SETTINGS, iso, utc_now  # noqa: E402
from drras_verification import (  # noqa: E402
    assess_risk,
    auto_approval_decision,
    find_duplicates,
    verification_route,
)

NOW = utc_now()


def existing_row(**overrides):
    row = {
        "id": "REQ-EXISTING01",
        "type": "FLOOD",
        "severity": "HIGH",
        "affected_people": 120,
        "required_resources": ["Supply", "RescueTeam"],
        "resource_quantities": {"Supply": 80, "RescueTeam": 2},
        "description": "Flood water has entered homes near the canal. Families need drinking water and a rescue boat.",
        "contact_name": "Asha",
        "contact_phone": "+91 98111 22334",
        "contact_email": "asha@example.org",
        "location_name": "Raipur, Dehradun",
        "latitude": 30.3195,
        "longitude": 78.0401,
        "submitted_at": iso(NOW - timedelta(minutes=25)),
        "workflow_status": "awaiting_approval",
        "merged_into": None,
        "client_ip": "127.0.0.1",
    }
    row.update(overrides)
    return row


def new_request(**overrides):
    row = existing_row(
        id="REQ-NEW0000001",
        submitted_at=iso(NOW),
        workflow_status="submitted",
        **{k: v for k, v in overrides.items() if k not in {"latitude", "longitude"}},
    )
    row["latitude"] = overrides.get("latitude", 30.3196)
    row["longitude"] = overrides.get("longitude", 78.0402)
    return row


class DuplicateDetectionTests(unittest.TestCase):
    def test_near_identical_report_is_flagged_with_explanations(self):
        result = find_duplicates(new_request(), [existing_row()])
        self.assertTrue(result["isPossibleDuplicate"], result)
        self.assertEqual(result["matches"][0]["id"], "REQ-EXISTING01")
        self.assertGreaterEqual(result["maxScore"], result["threshold"])
        codes = {factor["code"] for factor in result["matches"][0]["factors"]}
        self.assertTrue({"location", "category", "contact", "resources"} <= codes, codes)
        self.assertIn("REQ-EXISTING01", result["summary"])
        self.assertIn("looks like the same incident", result["summary"])

    def test_distant_unrelated_report_is_not_a_duplicate(self):
        result = find_duplicates(
            new_request(description="A building collapsed after an earthquake. Need heavy equipment."),
            [
                existing_row(
                    id="REQ-FAR0000001",
                    type="FIRE",
                    latitude=29.9457,
                    longitude=78.1642,
                    description="A forest fire is burning on the ridge above the village.",
                    contact_phone="+91 90000 00001",
                    contact_email="other@example.org",
                    required_resources=["Equipment"],
                )
            ],
        )
        self.assertFalse(result["isPossibleDuplicate"])
        self.assertEqual(result["matches"], [])

    def test_reports_outside_the_window_are_ignored(self):
        old = existing_row(submitted_at=iso(NOW - timedelta(hours=80)))
        result = find_duplicates(new_request(), [old], window_hours=72)
        self.assertFalse(result["isPossibleDuplicate"])

    def test_threshold_is_configurable(self):
        base = existing_row(
            latitude=30.3255,
            longitude=78.0455,
            contact_phone="+91 90000 00009",
            contact_email="else@example.org",
            description="Water is rising on the road near the market.",
            required_resources=["Supply"],
        )
        strict = find_duplicates(new_request(), [base], threshold=95)
        relaxed = find_duplicates(new_request(), [base], threshold=40)
        self.assertGreaterEqual(relaxed["maxScore"], strict["maxScore"])
        self.assertFalse(strict["isPossibleDuplicate"])
        self.assertTrue(relaxed["isPossibleDuplicate"])


class RiskScoringTests(unittest.TestCase):
    def test_thin_description_and_repeats_raise_the_score(self):
        request = new_request(
            description="Help",
            contact_phone="+91 98111 22334",
            required_resources=[],
            resource_quantities={},
        )
        repeats = [
            {
                "phone": "+91 98111 22334",
                "email": "asha@example.org",
                "ip": "10.0.0.7",
                "submitted_at": iso(NOW - timedelta(minutes=m)),
            }
            for m in (0, 4, 9)
        ]
        risk = assess_risk(request, recent_submissions=repeats, settings=DEFAULT_SETTINGS, now=NOW)
        codes = {reason["code"] for reason in risk["reasons"]}
        self.assertIn("missing_description", codes)
        self.assertIn("repeated_submissions", codes)
        self.assertGreaterEqual(risk["score"], DEFAULT_SETTINGS["mediumRiskThreshold"])
        self.assertEqual(risk["level"], "high" if risk["score"] >= DEFAULT_SETTINGS["highRiskThreshold"] else "medium")
        self.assertTrue(any(check["status"] == "ok" for check in risk["checks"]))
        self.assertEqual(risk["thresholds"]["medium"], DEFAULT_SETTINGS["mediumRiskThreshold"])

    def test_missing_contact_is_a_reason_not_a_rejection(self):
        request = new_request(contact_phone="", contact_email="")
        risk = assess_risk(request, settings=DEFAULT_SETTINGS, now=NOW)
        codes = {reason["code"] for reason in risk["reasons"]}
        self.assertIn("missing_contact", codes)
        status, queue, _ = verification_route(
            risk, {"isPossibleDuplicate": False}, DEFAULT_SETTINGS, request
        )
        self.assertIn(status, ("awaiting_approval", "under_verification", "submitted"))
        self.assertNotEqual(status, "rejected")

    def test_reused_evidence_is_explained_not_rejected(self):
        risk = assess_risk(
            new_request(),
            reused_evidence=[{"request_id": "REQ-OLDER0001", "id": "EV-1"}],
            settings=DEFAULT_SETTINGS,
            now=NOW,
        )
        reason = next(item for item in risk["reasons"] if item["code"] == "reused_evidence")
        self.assertIn("REQ-OLDER0001", reason["detail"])
        self.assertIn(risk["level"], ("low", "medium", "high"))

    def test_duplicate_signal_adds_points(self):
        duplicates = find_duplicates(new_request(), [existing_row()])
        clean = assess_risk(new_request(), settings=DEFAULT_SETTINGS, now=NOW)
        risky = assess_risk(new_request(), duplicates=duplicates, settings=DEFAULT_SETTINGS, now=NOW)
        self.assertGreater(risky["score"], clean["score"])
        self.assertTrue(any(reason["code"] == "duplicate_signal" for reason in risky["reasons"]))


class AutoApprovalTests(unittest.TestCase):
    def clean_request(self):
        return new_request(
            description=(
                "Flood water has entered twenty homes near the canal in Raipur. "
                "Families need clean drinking water and blankets tonight."
            ),
            contact_phone="+91 98111 22334",
            contact_email="asha@example.org",
            severity="LOW",
        )

    def enabled_settings(self, **overrides):
        settings = dict(DEFAULT_SETTINGS)
        settings.update(
            autoApproveEnabled=True,
            autoApproveMaxRisk=20,
            autoApproveMinDescriptionLength=20,
            autoApproveRequireContact=True,
            autoApproveSeverities=["LOW", "MEDIUM"],
        )
        settings.update(overrides)
        return settings

    def test_clean_low_risk_report_can_be_approved_automatically(self):
        request = self.clean_request()
        risk = assess_risk(request, settings=self.enabled_settings(), now=NOW)
        approved, explanation = auto_approval_decision(
            request, risk, {"isPossibleDuplicate": False}, self.enabled_settings()
        )
        self.assertTrue(approved, explanation)
        self.assertIn("Low risk", explanation)

    def test_duplicate_always_blocks_auto_approval(self):
        request = self.clean_request()
        risk = assess_risk(request, settings=self.enabled_settings(), now=NOW)
        approved, explanation = auto_approval_decision(
            request, risk, {"isPossibleDuplicate": True}, self.enabled_settings()
        )
        self.assertFalse(approved)
        self.assertIn("duplicate", explanation.lower())

    def test_high_risk_and_disabled_rules_block_auto_approval(self):
        request = self.clean_request()
        high_risk = {"score": 80, "level": "high"}
        approved, explanation = auto_approval_decision(
            request, high_risk, {"isPossibleDuplicate": False}, self.enabled_settings()
        )
        self.assertFalse(approved)
        self.assertIn("human review", explanation)

        low_risk = {"score": 5, "level": "low"}
        approved, explanation = auto_approval_decision(
            request, low_risk, {"isPossibleDuplicate": False}, self.enabled_settings(autoApproveEnabled=False)
        )
        self.assertFalse(approved)
        self.assertIn("disabled", explanation)

    def test_routing_never_returns_a_rejection(self):
        request = self.clean_request()
        low = assess_risk(request, settings=DEFAULT_SETTINGS, now=NOW)
        status, queue, _ = verification_route(low, {"isPossibleDuplicate": False}, DEFAULT_SETTINGS, request)
        self.assertEqual(status, "awaiting_approval")
        self.assertEqual(queue, "manual_review")

        duplicate = find_duplicates(new_request(), [existing_row()])
        status, queue, explanation = verification_route(low, duplicate, DEFAULT_SETTINGS, new_request())
        self.assertEqual(status, "possible_duplicate")
        self.assertEqual(queue, "duplicate_review")
        self.assertIn("A person decides", explanation)

        high = {"score": 90, "level": "high"}
        status, queue, _ = verification_route(high, {"isPossibleDuplicate": False}, DEFAULT_SETTINGS, request)
        self.assertEqual(status, "under_verification")
        self.assertEqual(queue, "high_risk")


if __name__ == "__main__":
    unittest.main()
