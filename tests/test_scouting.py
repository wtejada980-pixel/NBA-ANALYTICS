"""Probar que el análisis contextual no altere resultados ni pronósticos."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scouting import analyze


def team(id, name):
    return {"id": id, "name": name}


class ScoutingTests(unittest.TestCase):
    def setUp(self):
        self.game = {
            "home": team("10", "Local"), "away": team("20", "Visitante"),
            "prediction": {"home_pct": 56.7, "away_pct": 43.3, "model": "v2"}
        }
        self.teams = {
            "10": {"form": {"played": 10, "wins": 5, "margin": -2,
                            "points_for": 105, "points_against": 109},
                   "rest_days": 1},
            "20": {"form": {"played": 10, "wins": 8, "margin": 9,
                            "points_for": 118, "points_against": 108},
                   "rest_days": 2},
        }

    def test_alerts_from_actual_form_without_changing_original(self):
        before = dict(self.game["prediction"])
        report = analyze(self.game, self.teams)
        self.assertEqual(self.game["prediction"], before)
        self.assertEqual(report["favorite"], "Local")
        self.assertEqual(report["favorite_pct_original"], 56.7)
        self.assertEqual(report["classification"], "Partido muy cerrado")
        self.assertTrue(any("margen" in note for note in report["observations"]))
        self.assertTrue(any("descanso" in note for note in report["observations"]))
        self.assertIn("no una nueva probabilidad", report["scope"])

    def test_invalid_prediction_does_not_generate_analysis(self):
        self.assertIsNone(analyze(
            {**self.game, "prediction": {"home_pct": 70, "away_pct": 70}},
            self.teams))
        self.assertIsNone(analyze(
            {**self.game, "prediction": None},
            self.teams))

    def test_missing_team_data_is_marked_missing(self):
        report = analyze(self.game, {})
        self.assertEqual(report["home_form"]["games"], 0)
        self.assertIsNone(report["away_form"]["for"])

    def test_percentages_are_never_recomputed(self):
        self.game["prediction"]["home_pct"] = 70
        self.game["prediction"]["away_pct"] = 30
        self.assertEqual(analyze(self.game, self.teams)["favorite_pct_original"], 70)


if __name__ == "__main__":
    unittest.main()
