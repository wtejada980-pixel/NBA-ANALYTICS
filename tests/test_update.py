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
