"""Pruebas de integridad para comparación temporal y pronósticos V3 congelados."""
import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import v3_shadow


class ShadowTests(unittest.TestCase):
    def test_no_same_day_result_leaks_into_features(self):
        games=[]
        for i in range(7):
            day=f"2026-10-{20+i:02d}"
            games.append({"id":str(i),"date":day,"datetime":day+"T23:00:00+00:00",
                          "home_id":"1","away_id":"2",
                          "home_score":110+i,"away_score":99})
        forecast="2026-10-28T12:00:00+00:00"
        a=v3_shadow.features_at(games,"1","2",forecast)
        changed=games+[{"id":"bad","date":"2026-10-28",
                        "datetime":"2026-10-28T20:00:00+00:00",
                        "home_id":"1","away_id":"2",
                        "home_score":200,"away_score":50}]
        b=v3_shadow.features_at(changed,"1","2",forecast)
        self.assertEqual(a,b)
        self.assertIsNotNone(a)

    def test_stores_future_prediction_once_and_never_after_tipoff(self):
        from unittest.mock import patch
        now=datetime(2026,11,9,18,0,tzinfo=timezone.utc)
        history={"predictions":{"game-1":{
            "home_pct":62,"away_pct":38,
            "predicted_at":"2026-11-08T18:00:00Z",
            "scheduled_at":"2026-11-10T02:00:00Z",
            "result":None}}}
        cache={"events":{"game-1":{
            "id":"game-1","status":"pre",
            "datetime":"2026-11-10T02:00:00Z",
            "home":{"id":"1"},"away":{"id":"2"}}}}
        trained=[{"season_year":2022} for _ in range(101)]
        with patch.object(v3_shadow,"build_features",return_value=trained), \
             patch.object(v3_shadow,"train",return_value={"mock":"model"}), \
             patch.object(v3_shadow,"features_at",return_value={"elo_difference":1}), \
             patch.object(v3_shadow,"infer",return_value=.61):
            report=v3_shadow.build_report(history,cache,[],now=now)
            self.assertEqual(report["retrospective"]["n"],0)
            self.assertIn("game-1",report["forecasts"])
            saved=report["forecasts"]["game-1"]
            self.assertEqual(saved["v3_home_pct"],61.0)
            after=v3_shadow.build_report(history,cache,[],previous=report,
                now=datetime(2026,11,10,3,0,tzinfo=timezone.utc))
            self.assertEqual(after["forecasts"]["game-1"],saved)
            self.assertEqual(after["prospective"]["n"],0)

    def test_missing_earlier_games_abstains(self):
        self.assertIsNone(v3_shadow.features_at([],"1","2","2026-11-09T15:00:00Z"))

    def test_invalid_probability_is_not_used(self):
        self.assertIsNone(v3_shadow._percent({"home_pct":99,"away_pct":99}))
        self.assertIsNone(v3_shadow._percent({"home_pct":"nan","away_pct":50}))

    def test_current_cache_excludes_upcoming(self):
        rows=v3_shadow.current_final_games({"events":{
            "a":{"id":"a","datetime":"2026-11-08T22:00Z",
                 "status":"pre","home_score":None,"away_score":None,
                 "home":{"id":"1"},"away":{"id":"2"}},
            "b":{"id":"b","datetime":"2026-11-08T22:00Z",
                 "status":"post","home_score":102,"away_score":90,
                 "home":{"id":"1"},"away":{"id":"2"}}}})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["id"],"b")


if __name__=="__main__":
    unittest.main()
