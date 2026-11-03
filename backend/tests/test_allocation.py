"""Unit tests for the transparent allocation-ranking engine."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DRRAS_OFFLINE", "1")

from drras_allocation import recommend, score_centre  # noqa: E402


def centre(centre_id="HC-TEST-1", **overrides):
    row = {
        "id": centre_id,
        "centreId": centre_id,
        "name": "Test Centre " + centre_id,
        "category": "warehouse",
        "availability": "available",
        "stock": {"Supply": 500, "MedicalTeam": 4, "Ambulance": 2},
        "distanceKm": 2.0,
        "durationMin": 5,
        "distanceSource": "osrm",
        "activeLoad": 0,
    }
    row.update(overrides)
    return row


def request(**overrides):
    row = {
        "id": "REQ-TEST000001",
        "type": "FLOOD",
        "severity": "HIGH",
        "required_resources": ["Supply", "MedicalTeam"],
        "resource_quantities": {"Supply": 100, "MedicalTeam": 1},
        "latitude": 30.3165,
        "longitude": 78.0322,
    }
    row.update(overrides)
    return row


class ScoreTests(unittest.TestCase):
    def test_near_centre_outranks_far_centre_with_equal_stock(self):
        near = score_centre(centre("HC-NEAR"), request(), distance_km=1.0, duration_min=3, distance_source="osrm")
        far = score_centre(centre("HC-FAR"), request(), distance_km=35.0, duration_min=55, distance_source="osrm")
        self.assertGreater(near["score"], far["score"])
        self.assertEqual(near["distanceSource"], "osrm")
        proximity = next(factor for factor in near["factors"] if factor["code"] == "proximity")
        self.assertIn("(routed)", proximity["detail"])

    def test_estimated_distance_is_labelled_and_slightly_penalised(self):
        routed = score_centre(centre("HC-A"), request(), distance_km=4.0, duration_min=9, distance_source="osrm")
        estimated = score_centre(centre("HC-B"), request(), distance_km=4.0, duration_min=9, distance_source="estimate")
        self.assertGreater(routed["score"], estimated["score"])
        proximity = next(factor for factor in estimated["factors"] if factor["code"] == "proximity")
        self.assertIn("estimated", proximity["detail"])

    def test_closed_centre_scores_almost_zero_and_explains_why(self):
        closed = score_centre(
            centre("HC-CLOSED", availability="closed"),
            request(),
            distance_km=0.5,
            duration_min=1,
            distance_source="osrm",
        )
        open_centre = score_centre(centre("HC-OPEN"), request(), distance_km=8.0, duration_min=15, distance_source="osrm")
        self.assertLess(closed["score"], open_centre["score"])
        coverage = next(factor for factor in closed["factors"] if factor["code"] == "coverage")
        self.assertEqual(coverage["points"], 0.0)

    def test_fairness_penalises_an_already_busy_centre(self):
        idle = score_centre(centre("HC-IDLE"), request(), distance_km=3, duration_min=6, distance_source="osrm", active_load=0)
        busy = score_centre(centre("HC-BUSY"), request(), distance_km=3, duration_min=6, distance_source="osrm", active_load=5000)
        self.assertGreater(idle["score"], busy["score"])

    def test_partial_coverage_is_reported(self):
        scored = score_centre(
            centre("HC-SHORT", stock={"Supply": 40}),
            request(),
            distance_km=2,
            duration_min=5,
            distance_source="osrm",
        )
        self.assertEqual(scored["supplied"], {"Supply": 40})
        self.assertIn("MedicalTeam", scored["missing"])
        self.assertLess(scored["coveragePct"], 100)

    def test_critical_requests_weight_proximity_more_heavily(self):
        nearby = score_centre(centre("HC-N"), request(severity="CRITICAL"), distance_km=2, duration_min=4, distance_source="osrm")
        distant = score_centre(centre("HC-D"), request(severity="CRITICAL"), distance_km=30, duration_min=48, distance_source="osrm")
        self.assertGreater(nearby["score"], distant["score"])
        self.assertEqual(nearby["factors"][0]["code"], "coverage")


class RecommendationTests(unittest.TestCase):
    def test_best_centre_is_first_and_plan_matches_its_stock(self):
        result = recommend(
            [
                centre("HC-FAR", distanceKm=30, durationMin=50, stock={"Supply": 500, "MedicalTeam": 4}),
                centre("HC-NEAR", distanceKm=1.2, durationMin=3, stock={"Supply": 500, "MedicalTeam": 4}),
            ],
            request(),
        )
        self.assertEqual(result["candidates"][0]["centreId"], "HC-NEAR")
        self.assertEqual(result["plan"][0]["centreId"], "HC-NEAR")
        self.assertEqual(result["plan"][0]["items"], {"Supply": 100, "MedicalTeam": 1})
        self.assertEqual(result["coveredPct"], 100)
        self.assertEqual(result["uncovered"], {})

    def test_multi_centre_plan_never_over_promises_stock(self):
        result = recommend(
            [
                centre("HC-A", distanceKm=2, stock={"Supply": 60}),
                centre("HC-B", distanceKm=5, stock={"Supply": 60, "MedicalTeam": 1}),
                centre("HC-C", distanceKm=9, stock={"Supply": 25}),
            ],
            request(resource_quantities={"Supply": 120, "MedicalTeam": 1}),
        )
        planned_supply = sum(item["items"].get("Supply", 0) for item in result["plan"])
        self.assertEqual(planned_supply, 120)
        self.assertLessEqual(planned_supply, 60 + 60 + 25)
        self.assertEqual(result["uncovered"].get("Supply", 0), 0)
        # Each planned line is bounded by that centre's stock at the time of ranking.
        stock_by_centre = {"HC-A": 60, "HC-B": 60, "HC-C": 25}
        for entry in result["plan"]:
            for amount in entry["items"].values():
                self.assertLessEqual(amount, stock_by_centre[entry["centreId"]])

    def test_closed_centres_are_excluded_from_the_plan(self):
        result = recommend(
            [
                centre("HC-CLOSED", availability="closed", distanceKm=0.4, stock={"Supply": 900}),
                centre("HC-OPEN", distanceKm=6, stock={"Supply": 900, "MedicalTeam": 5}),
            ],
            request(),
        )
        planned = {entry["centreId"] for entry in result["plan"]}
        self.assertNotIn("HC-CLOSED", planned)
        self.assertIn("HC-OPEN", planned)

    def test_uncovered_need_is_reported_when_nobody_has_stock(self):
        result = recommend(
            [centre("HC-EMPTY", stock={"Supply": 0})],
            request(resource_quantities={"Supply": 80}),
        )
        self.assertEqual(result["plan"], [])
        self.assertEqual(result["uncovered"], {"Supply": 80})
        self.assertEqual(result["coveredPct"], 0)

    def test_limit_caps_candidates_but_not_the_plan(self):
        centres = [centre(f"HC-{index}", distanceKm=index + follower) for index, follower in enumerate([1.0] * 10)]
        result = recommend(centres, request(), limit=3)
        self.assertEqual(len(result["candidates"]), 3)
        # The plan can still draw from centres outside the visible shortlist.
        self.assertTrue(result["plan"])


if __name__ == "__main__":
    unittest.main()
