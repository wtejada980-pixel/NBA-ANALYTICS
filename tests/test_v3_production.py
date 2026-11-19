import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v3_production


class V3ProductionTests(unittest.TestCase):
    def test_missing_complete_seasons_fails_without_fallback(self):
        with patch.object(v3_production, "load_seasons",
                          return_value=([], {"2022-23": 300})):
            with self.assertRaisesRegex(RuntimeError, "faltan temporadas"):
                v3_production.fit_model()

    def test_training_uses_only_the_proven_training_seasons(self):
        seasons = [{"id": str(i)} for i in range(4)]
        rows = [{"season_year": year, "id": str(i)}
                for year in (2022, 2023, 2024, 2025) for i in range(60)]
        coverage = {season: 300 for season in v3_production.REQUIRED}
        with patch.object(v3_production, "load_seasons", return_value=(seasons, coverage)), \
             patch.object(v3_production, "build_features", return_value=rows) as build, \
             patch.object(v3_production, "train", return_value={"trained": True}) as train:
            model, loaded = v3_production.fit_model()
        self.assertEqual(loaded, seasons)
        self.assertEqual(model, {"trained": True})
        self.assertEqual(len(train.call_args.args[0]), 120)
        self.assertEqual({r["season_year"] for r in train.call_args.args[0]}, {2022, 2023})

    def test_prediction_blends_v2_v3_probabilities_and_keeps_elo_reference(self):
        model = {"weights": [0.1, 0.2, 0, 0, 0, 0, 0],
                 "means": {key: 0 for key in v3_production.FEATURES},
                 "std": {key: 1 for key in v3_production.FEATURES}}
        game = {"home": {"id": "1"}, "away": {"id": "2"}}
        features = {key: 0 for key in v3_production.FEATURES}
        with patch.object(v3_production, "features_at", return_value=features), \
             patch.object(v3_production, "infer", return_value=.61), \
             patch.object(v3_production, "predict_v2", return_value={
                 "home_pct": 55.0, "away_pct": 45.0, "reason": "ventaja V2",
                 "factors": {"player_component": 0.4}}):
            result = v3_production.predict(game, model, [], "2026-11-20T12:00:00Z",
                                           teams={"1": {}, "2": {}})
        self.assertEqual(result["model"], v3_production.ACTIVE_MODEL)
        self.assertEqual((result["home_pct"], result["away_pct"]), (58.0, 42.0))
        self.assertFalse(result["calibrated"])
        self.assertIn("elo_baseline_home_pct", result)
        self.assertEqual(result["hybrid"]["v3_home_pct"], 61.0)
        self.assertEqual(result["hybrid"]["v2_home_pct"], 55.0)
        self.assertEqual(result["hybrid"]["v3_weight_pct"], 50)


if __name__ == "__main__":
    unittest.main()
