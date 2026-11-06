"""Pruebas v2 aisladas: sin red ni probabilidades inventadas."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import model_v2
import validation


def event(gid, day, home="10", away="20", hp=125, ap=105):
    return {
        "id": str(gid), "datetime": day + "T23:00:00Z",
        "status": "post",
        "home": {"id": home}, "away": {"id": away},
        "home_score": hp, "away_score": ap,
    }


def team(margin, wins, pts, allowed, n=10):
    return {
        "form": {"played": n, "margin": margin,
                 "win_rate": wins, "points_for": pts, "points_against": allowed},
        "rest_days": 2, "players": [], "player_trend": 0,
    }


class ModelTests(unittest.TestCase):
    def test_elo_changes_only_with_prior_games(self):
        old = event("1", "2026-10-28")
        future = event("2", "2026-11-09", hp=80, ap=130)
        cutoff = "2026-11-06T00:00:00Z"
        ratings = model_v2.elo_before([old, future], cutoff)
        baseline = model_v2.elo_before([old], cutoff)
        self.assertEqual(ratings, baseline)
        self.assertGreater(ratings["10"], ratings["20"])

    def test_elo_baseline_only_uses_given_ratings(self):
        game = {"home":{"id":"10"},"away":{"id":"20"}}
        first = model_v2.elo_baseline_probability(game,{})
        strong = model_v2.elo_baseline_probability(game,{"10":1650,"20":1450})
        self.assertGreater(strong, first)
        self.assertGreater(first,50)

    def test_elo_reverses_when_underdog_wins(self):
        g = event("1", "2026-10-28", hp=95, ap=110)
        r = model_v2.elo_before([g], "2026-11-06T00:00:00Z")
        self.assertGreater(r["20"], r["10"])

    def test_stronger_team_favored_and_probabilities_sum_100(self):
        game = {"home": {"id": "10"}, "away": {"id": "20"}}
        teams = {"10": team(10, .8, 120, 106), "20": team(-8, .2, 101, 120)}
        result = model_v2.predict(game, teams, {"10": 1570, "20": 1430})
        self.assertGreater(result["home_pct"], result["away_pct"])
        self.assertEqual(result["home_pct"] + result["away_pct"], 100.0)
        self.assertEqual(result["model"], "elo-forma10-v2")
        self.assertFalse(result["calibrated"])
        self.assertTrue(result["reason"].startswith("Ventaja por "))
        self.assertLessEqual(len(result["reason"]), 140)

    def test_not_enough_prior_games_is_abstention(self):
        game = {"home": {"id": "10"}, "away": {"id": "20"}}
        teams = {"10": team(10,.9,118,101,n=3), "20": team(-10,.1,101,118,n=10)}
        self.assertIsNone(model_v2.predict(game, teams, {}))

    def test_small_sample_is_conservative(self):
        game = {"home": {"id": "10"}, "away": {"id": "20"}}
        a = {"10": team(12,.9,130,103,n=4), "20": team(-12,.1,95,128,n=4)}
        b = {"10": team(12,.9,130,103,n=10), "20": team(-12,.1,95,128,n=10)}
        pa = model_v2.predict(game, a, {"10": 1600, "20": 1400})
        pb = model_v2.predict(game, b, {"10": 1600, "20": 1400})
        self.assertLess(pa["home_pct"], pb["home_pct"])


class ValidationTests(unittest.TestCase):
    def test_brier_and_accuracy(self):
        records = {
            "a": {"home_pct": 80, "model": "v2", "result": {"winner": "home"}},
            "b": {"home_pct": 20, "model": "v2", "result": {"winner": "away"}},
            "c": {"home_pct": 45, "model": "v2", "result": None},
        }
        report = validation.evaluate(records)
        self.assertEqual(report["completed_predictions"], 2)
        self.assertAlmostEqual(report["brier_score"], .04)
        self.assertEqual(report["favorite_accuracy_pct"], 100.0)
        self.assertEqual(report["by_model"]["v2"]["n"], 2)
        self.assertEqual(len(report["calibration"]), 2)

    def test_empty_history_and_bad_probabilities(self):
        self.assertIsNone(validation.evaluate({})["brier_score"])
        records = {"x": {"home_pct": "nan", "result": {"winner": "home"}}}
        self.assertEqual(validation.evaluate(records)["completed_predictions"], 0)

    def test_baseline_compare_same_set_only(self):
        records = {
          "a":{"home_pct":70,"elo_baseline_home_pct":60,"result":{"winner":"home"}},
          "b":{"home_pct":80,"result":{"winner":"away"}}
        }
        report = validation.evaluate(records)
        self.assertEqual(report["completed_predictions"],2)
        self.assertEqual(report["elo_comparison"]["n"],1)
        self.assertAlmostEqual(report["elo_comparison"]["model_brier"],.09)
        self.assertAlmostEqual(report["elo_comparison"]["elo_brier"],.16)

    def test_never_grade_predictions_after_tipoff(self):
        records={"a":{"home_pct":99,"result":{"winner":"home"},
          "predicted_at":"2026-11-06T20:01:00Z",
          "scheduled_at":"2026-11-06T20:00:00Z"}}
        self.assertEqual(validation.evaluate(records)["completed_predictions"],0)

    def test_brier_penalizes_overconfident_errors(self):
        good = validation.evaluate({"1": {"home_pct": 60, "result": {"winner": "home"}}})
        bad = validation.evaluate({"1": {"home_pct": 95, "result": {"winner": "away"}}})
        self.assertLess(good["brier_score"], bad["brier_score"])


if __name__ == "__main__":
    unittest.main()
