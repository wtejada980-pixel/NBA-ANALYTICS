"""V3: tests sin red, muestras fabricadas SOLAMENTE para pruebas unitarias."""
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import model_v3
import v3_dataset


def game(gid, day, h="10", a="20", hs=115, aws=103, year=2023):
    return {"id": str(gid), "date": day, "datetime": day+"T23:00:00+00:00",
            "home_id": h, "away_id": a, "home_score": hs,
            "away_score": aws, "season_year": year, "stage": 2}


class DatasetTests(unittest.TestCase):
    def test_parse_only_final_and_confirmed_season(self):
        raw = {
            "id": "1", "date": "2024-02-14T01:00Z", "season": {"year": 2023, "type": 2},
            "status": {"type": {"state": "post"}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"id": "10"}, "score": "108"},
                {"homeAway": "away", "team": {"id": "20"}, "score": "103"}]}]
        }
        self.assertEqual(v3_dataset.parse_final(raw)["home_score"], 108)
        self.assertIsNone(v3_dataset.parse_final({**raw, "season": {"type": 1, "year": 2023}}))
        self.assertIsNone(v3_dataset.parse_final({**raw, "status": {"type": {"state": "in"}}}))
        self.assertIsNone(v3_dataset.parse_final({**raw, "season": {}}))
        self.assertIsNone(v3_dataset.parse_final({**raw, "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "10"}, "score": "100"},
            {"homeAway": "away", "team": {"id": "20"}, "score": "100"}]}]}))

    def test_season_year_accepts_espn_end_year_without_label_leak(self):
        # El histórico 2023-24 puede venir etiquetado como season.year=2024.
        # La normalización al año de inicio se realiza en backfill.
        self.assertIn(2024, (v3_dataset.SEASONS["2023-24"],
                             v3_dataset.SEASONS["2023-24"] + 1))

    def test_checkpoint_valid_json_and_espn_season_end_year(self):
        from unittest.mock import patch
        import tempfile
        raw = {
            "id": "99", "date": "2023-10-15T23:00:00Z",
            "season": {"year": 2024, "type": 2},
            "status": {"type": {"state": "post"}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"id": "1"}, "score": "112"},
                {"homeAway": "away", "team": {"id": "2"}, "score": "105"}]}]
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(v3_dataset, "STORE", Path(directory)), \
                 patch.object(v3_dataset, "season_days", return_value=[date(2023, 10, 15)]), \
                 patch.object(v3_dataset, "get_events", return_value=[raw]):
                report = v3_dataset.backfill("2023-24", pause=0)
                saved = json.loads((Path(directory)/"games-2023-24.json").read_text())
                self.assertTrue(report["complete"])
                self.assertEqual(saved["games"][0]["season_year"], 2023)
                self.assertEqual(saved["games"][0]["home_score"], 112)

    def test_calendar_coverage(self):
        days = list(v3_dataset.season_days(2023))
        self.assertEqual(days[0], date(2023, 10, 1))
        self.assertEqual(days[-1], date(2024, 6, 30))
        self.assertGreater(len(days), 240)


class SelectionTests(unittest.TestCase):
    def test_selects_first_missing_season_then_next(self):
        from v3_next_season import next_season
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            self.assertEqual(next_season(p), "2022-23")
            (p/"games-2022-23.json").write_text(json.dumps({
                "season":"2022-23","complete":True}))
            self.assertEqual(next_season(p), "2023-24")
            (p/"games-2023-24.json").write_text(json.dumps({
                "season":"2023-24","complete":False}))
            self.assertEqual(next_season(p), "2023-24")


class FeaturesTests(unittest.TestCase):
    def test_does_not_use_same_day_or_future_scores(self):
        initial = [
            game(i, (date(2023, 10, 20)+timedelta(days=i)).isoformat(),
                 hs=110+i, aws=100) for i in range(5)]
        today = "2023-10-26"
        first = game(10, today, hs=160, aws=90)
        second = game(11, today, hs=90, aws=160)
        f1 = model_v3.build_features(initial+[first, second])
        tampered = model_v3.build_features(initial+[
            {**first, "home_score": 90, "away_score": 160},
            {**second, "home_score": 160, "away_score": 90}])
        a = {r["id"]: r for r in f1 if r["date"] == today}
        b = {r["id"]: r for r in tampered if r["date"] == today}
        for id in ("10", "11"):
            self.assertEqual([a[id][k] for k in model_v3.FEATURES],
                             [b[id][k] for k in model_v3.FEATURES])
            self.assertEqual(a[id]["elo_probability"], b[id]["elo_probability"])
            self.assertEqual(a[id]["y"], 1 if id == "10" else 0)
        self.assertNotEqual(a["10"]["y"], b["10"]["y"])

    def test_no_data_before_four_matches_abstains(self):
        rows = model_v3.build_features([
            game(i, (date(2023, 10, 20)+timedelta(days=i)).isoformat())
            for i in range(3)])
        self.assertEqual(rows, [])

    def test_duplicate_and_equal_scores_rejected(self):
        with self.assertRaises(ValueError):
            model_v3.build_features([game(1,"2023-10-20"),game(1,"2023-10-21")])
        with self.assertRaises(ValueError):
            model_v3.build_features([game(2,"2023-10-20",hs=100,aws=100)])

    def test_small_history_no_fake_model(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            report, weights = model_v3.evaluate(folder)
            self.assertEqual(report["status"], "insufficient_history")
            self.assertIsNone(weights)

    def test_model_probabilities_and_standardization(self):
        rows = []
        for i in range(120):
            row = {k: (i % 13 - 6)/5 for k in model_v3.FEATURES}
            row["y"] = 1 if i % 3 else 0
            rows.append(row)
        model = model_v3.train(rows, epochs=50)
        pred = model_v3.infer(model, rows[0])
        self.assertGreater(pred, 0)
        self.assertLess(pred, 1)
        with self.assertRaises(ValueError):
            model_v3.infer({**model, "feature_names": []}, rows[0])


if __name__ == "__main__":
    unittest.main()
