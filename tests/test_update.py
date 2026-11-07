import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update


def sample_event(event_id='1', state='post', hs='120', aws='108'):
    return {
        'id': event_id, 'date': '2026-11-04T22:00:00Z',
        'status': {'type': {'state': state}},
        'competitions': [{'competitors': [
            {'homeAway': 'home', 'team': {'id': '10', 'abbreviation': 'AAA', 'displayName': 'Team A'}, 'score': hs},
            {'homeAway': 'away', 'team': {'id': '20', 'abbreviation': 'BBB', 'displayName': 'Team B'}, 'score': aws},
        ]}]
    }


class ParseTests(unittest.TestCase):
    def test_event(self):
        event = update.parse_event(sample_event())
        self.assertEqual(event['home_score'], 120)
        self.assertEqual(event['away_score'], 108)
        self.assertEqual(event['date'], '2026-11-04')
        self.assertEqual(update.margin('10', event), 12)
        self.assertEqual(update.margin('20', event), -12)

    def test_pre_event_has_no_score(self):
        event = update.parse_event(sample_event(state='pre'))
        self.assertIsNone(event['home_score'])
        self.assertIsNone(event['away_score'])

    def test_players_summary(self):
        data = {'boxscore': {'players': [
            {'team': {'id': '10'}, 'statistics': [
                {'labels': ['MIN', 'PTS', 'REB', 'AST'], 'athletes': [
                    {'athlete': {'id': '100', 'displayName': 'Jugador Ejemplo'}, 'stats': ['33', '25', '6', '8']},
                    {'athlete': {'id': '101', 'displayName': 'Sin jugar'}, 'didNotPlay': True, 'stats': []},
                ]}]},
        ]}}
        players = update.stat_line(data, '10')
        self.assertEqual(len(players), 1)
        self.assertFalse(players[0]['starter'])
        self.assertEqual((players[0]['pts'], players[0]['reb'], players[0]['ast']), (25, 6, 8))

    def test_history_is_auditable_and_sorted(self):
        record={"date":"2026-11-06","home":"Equipo Local","away":"Equipo Visitante",
          "home_pct":60,"away_pct":40,"model":"v2","predicted_at":"2026-11-06T19:00:00Z",
          "scheduled_at":"2026-11-06T20:00:00Z",
          "result":{"winner":"home","home_score":104,"away_score":100}}
        other={**record,"predicted_at":"2026-11-06T21:00:00Z"}
        rows=update.public_history({"predictions":{"good":record,"late":other}})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["id"],"good")
        self.assertEqual(rows[0]["result"]["home_score"],104)

    def test_head_to_head_uses_earlier_results_only(self):
        game=update.parse_event(sample_event(event_id="3",state="pre"))
        early=update.parse_event(sample_event(event_id="1"))
        late=update.parse_event(sample_event(event_id="4"))
        late["datetime"]="2026-11-09T22:00:00Z"
        hist=update.recent_meetings(game,[early,late])
        self.assertEqual(len(hist),0)  # Igual fecha y hora: no incluir
        game["datetime"]="2026-11-07T22:00:00Z"
        hist=update.recent_meetings(game,[early,late])
        self.assertEqual(len(hist),1)
        self.assertEqual(hist[0]["home_score"],120)

    def test_locked_prediction_is_immutable(self):
        record = {'home_pct': 63.4, 'away_pct': 36.6, 'model': 'v2',
          'predicted_at': '2026-11-06T19:00:00Z',
          'scheduled_at': '2026-11-06T20:00:00Z'}
        self.assertEqual(update.locked_prediction(record)['home_pct'], 63.4)
        self.assertTrue(update.locked_prediction(record)['locked'])
        self.assertIsNone(update.locked_prediction(
          {**record, 'predicted_at': '2026-11-06T20:01:00Z'}))

    def test_cache_missing_and_invalid(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.json'
            self.assertEqual(update.load_cache(path, 'events'), {})
            path.write_text('not json')
            self.assertEqual(update.load_cache(path, 'events'), {})
            path.write_text('{"events":{"42":{"id":"42"}}}')
            self.assertEqual(len(update.load_cache(path, 'events')), 1)

    def test_player_profiles_use_cached_stats(self):
        game = update.parse_event(sample_event())
        box = {'1': {'player_stats': {'10': [
          {'id':'100','name':'Jugador','pts':24,'reb':5,'ast':7,'starter':True}
        ]}}}
        rows = update.player_profiles('10', [game, game], box)
        self.assertEqual(rows[0]['pts'], 24.0)

    def test_revision_keeps_original_and_timestamp(self):
        from datetime import datetime, timezone
        record = {'home_pct': 55, 'away_pct': 45, 'model': 'v2',
                  'predicted_at': '2026-11-07T12:00:00Z',
                  'scheduled_at': '2026-11-07T22:00:00Z'}
        updated = {'home_pct': 61.3, 'away_pct': 38.7, 'model':'v2',
                   'reason':'Forma deportiva nueva.'}
        rev = update.save_pre_match_revision(record, updated,
                  datetime(2026,11,7,16,0,tzinfo=timezone.utc))
        self.assertAlmostEqual(rev['home_pct'], 61.3)
        self.assertEqual(record['home_pct'], 55)
        self.assertEqual(len(record['revisions']),1)
        again = update.save_pre_match_revision(record, updated,
                  datetime(2026,11,7,17,0,tzinfo=timezone.utc))
        self.assertEqual(len(record['revisions']),1)
        self.assertEqual(again['predicted_at'],rev['predicted_at'])

    def test_revision_after_tipoff_is_not_saved(self):
        from datetime import datetime, timezone
        record = {'home_pct': 55, 'away_pct': 45, 'model': 'v2',
                  'predicted_at': '2026-11-07T12:00:00Z',
                  'scheduled_at': '2026-11-07T22:00:00Z'}
        update.save_pre_match_revision(record,{'home_pct':85,'away_pct':15},
                  datetime(2026,11,7,22,1,tzinfo=timezone.utc))
        self.assertNotIn('revisions',record)

    def test_revision_invalid_is_ignored(self):
        from datetime import datetime, timezone
        record = {'home_pct': 55, 'away_pct': 45, 'model': 'v2',
                  'predicted_at': '2026-11-07T12:00:00Z',
                  'scheduled_at': '2026-11-07T22:00:00Z'}
        update.save_pre_match_revision(record,{'home_pct':90,'away_pct':90},
                  datetime(2026,11,7,16,0,tzinfo=timezone.utc))
        self.assertNotIn('revisions',record)

    def test_valid_probabilities(self):
        home = {'form': {'played':8,'margin': 7.0, 'win_rate':.7}, 'rest_days':2, 'players':[]}
        away = {'form': {'played':8,'margin': -5.0, 'win_rate':.3}, 'rest_days':1, 'players':[]}
        game = {'home': {'id':'10'}, 'away': {'id':'20'}}
        pred = update.predict(game, {'10':home, '20':away})
        self.assertAlmostEqual(pred['home_pct']+pred['away_pct'], 100.0)
        self.assertGreater(pred['home_pct'], pred['away_pct'])

    def test_abstain_if_not_enough_games(self):
        team = {'form': {'played':2,'margin':5, 'win_rate':.7},'rest_days':2,'players':[]}
        game = {'home': {'id':'10'},'away':{'id':'20'}}
        self.assertIsNone(update.predict(game, {'10':team, '20':team}))


if __name__ == '__main__':
    unittest.main()
