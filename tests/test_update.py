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
    def test_public_elo_ratings_are_derived_from_completed_games(self):
        finished = [{
            'id':'1','datetime':'2026-11-01T20:00:00+00:00','status':'post',
            'home':{'id':'10','abbr':'AAA','name':'Team A'},
            'away':{'id':'20','abbr':'BBB','name':'Team B'},
            'home_score':120,'away_score':100
        }]
        events = {'1': finished[0], '2': {
            'id':'2','datetime':'2026-11-14T20:00:00+00:00','status':'pre',
            'home':{'id':'10','abbr':'AAA','name':'Team A'},
            'away':{'id':'30','abbr':'CCC','name':'Team C'}
        }}
        rows = update.public_elo_ratings(finished, events, '2026-11-13T00:00:00+00:00')
        self.assertEqual([x['id'] for x in rows], ['10','20'])
        self.assertGreater(rows[0]['rating'], rows[1]['rating'])
        self.assertEqual(rows[0]['games'], 1)

    def test_official_date_override_for_okc_portland(self):
        event = sample_event(event_id='401909965', state='post')
        event['date'] = '2026-11-11T04:00:00Z'
        parsed = update.parse_event(event)
        self.assertEqual(parsed['date'], '2026-11-10')

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
                    {'athlete': {'id': '100', 'displayName': 'Jugador Ejemplo'}, 'starter': True,
                     'stats': ['33:12', '25', '6', '8']},
                    {'athlete': {'id': '101', 'displayName': 'Sin jugar'}, 'didNotPlay': True, 'stats': []},
                ]}]},
        ]}}
        players = update.stat_line(data, '10')
        self.assertEqual(len(players), 1)
        self.assertTrue(players[0]['starter'])
        self.assertEqual((players[0]['pts'], players[0]['reb'], players[0]['ast']), (25, 6, 8))
        self.assertEqual(players[0]['min'], '33:12')

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
          {'id':'100','name':'Jugador','pts':24,'reb':5,'ast':7,'starter':True},
          {'id':'101','name':'Suplente','pts':12,'reb':3,'ast':4,'starter':False}
        ]}}}
        rows = update.player_profiles('10', [game, game, game, game], box)
        starter = next(player for player in rows if player['id'] == '100')
        self.assertEqual(starter['pts'], 24.0)
        self.assertTrue(starter['possible_starter'])
        self.assertEqual((starter['starter_games'], starter['sample_games']), (4, 4))

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

    def test_archived_games_keep_only_real_pre_match_predictions(self):
        from datetime import date
        game = update.parse_event(sample_event(event_id='1', state='post'))
        another = update.parse_event(sample_event(event_id='2', state='post'))
        game['date'] = another['date'] = '2026-11-04'
        history = {'predictions': {'1': {
          'date':'2026-11-04', 'home_pct':60, 'away_pct':40,
          'predicted_at':'2026-11-04T12:00:00Z',
          'scheduled_at':'2026-11-04T22:00:00Z',
          'model':'v2', 'result':{'winner':'home'}}}}
        rows = update.archived_games({'1':game, '2':another}, history, date(2026,11,9))
        self.assertEqual(len(rows),2)
        self.assertTrue(rows[0]['historical'])
        self.assertEqual(rows[0]['prediction']['home_pct'],60)
        self.assertIsNone(rows[1]['prediction'])
        self.assertEqual(rows[0]['home_score'],120)

    def test_archived_games_include_cached_player_boxscore(self):
        from datetime import date
        game=update.parse_event(sample_event(event_id='box',state='post'))
        box={'player_stats':{'10':[{'id':'h1','name':'Local','pts':22,'reb':9,'ast':4}],
                             '20':[{'id':'a1','name':'Visitante','pts':18,'reb':5,'ast':7}]}}
        rows=update.archived_games({'box':game},{'predictions':{}},date(2026,11,9),
                                   box_cache={'box':box})
        self.assertEqual(rows[0]['player_stats']['10'][0]['pts'],22)

    def test_archive_boxscore_backfill_caches_verified_espn_stats(self):
        from datetime import date
        from unittest.mock import patch
        game=update.parse_event(sample_event(event_id='box',state='post'))
        game['date']='2026-11-04'
        payload={'boxscore':{'players':[
            {'team':{'id':'10'},'statistics':[{'labels':['PTS','REB','AST'],
             'athletes':[{'athlete':{'id':'h1','displayName':'Local'},'stats':['22','9','4']}]}]},
            {'team':{'id':'20'},'statistics':[{'labels':['PTS','REB','AST'],
             'athletes':[{'athlete':{'id':'a1','displayName':'Visitante'},'stats':['18','5','7']}]}]}
        ]}}
        with patch.object(update,'get_json',return_value=payload) as fetch:
            count=update.cache_archive_boxscores([game],{},date(2026,11,9))
        self.assertEqual(count,1)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(update.game_box_record(payload,game)['player_stats']['10'][0]['reb'],9)

    def test_archived_games_only_last_seven_days(self):
        from datetime import date
        old = update.parse_event(sample_event(event_id='old'))
        old['date']='2026-10-30'
        recent = update.parse_event(sample_event(event_id='recent'))
        recent['date']='2026-11-06'
        rows = update.archived_games({'old':old,'recent':recent},
                                     {'predictions': {}}, date(2026,11,9))
        self.assertEqual([g['id'] for g in rows], ['recent'])

    def test_archive_does_not_invent_final_scores(self):
        from datetime import date
        running = update.parse_event(sample_event(event_id='running',state='in'))
        running['date']='2026-11-08'
        rows = update.archived_games({'running':running},{'predictions':{}},
                                     date(2026,11,9))
        self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0]['home_score'])
        self.assertIsNone(rows[0]['away_score'])

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

    def test_input_snapshot_keeps_pregame_player_and_injury_data(self):
        from datetime import datetime, timezone
        game = {'id':'42','datetime':'2026-11-07T22:00:00Z',
                'home':{'id':'10'},'away':{'id':'20'},
                'context':{'news':[{'title':'Noticia NBA','source':'Medio','published':'hoy',
                                    'feed':'Google News','url':'https://example.com'}]}}
        teams = {
          '10': {'form':{'played':8,'wins':5,'margin':4.5,'win_rate':.62,
                         'points_for':111,'points_against':107},
                 'rest_days':2,'player_trend':.4,
                 'players':[{'id':'100','name':'Jugador','games':5,'pts':24.2,
                             'reb':6.1,'ast':5.0,'recent_points':[28,22,24,23]}]},
          '20': {'form':{'played':8,'wins':4,'margin':0,'win_rate':.5},
                 'rest_days':1,'player_trend':0,'players':[]}}
        injuries = {'42': {'home':{'source':'ESPN','items':[
            {'player':'Jugador','status':'Cuestionable','reason':'Tobillo'}]},
            'away':{'source':'ESPN','items':[]}}}
        snap = update.build_input_snapshot(game, teams, injuries,
            {'model':'v2','home_pct':58.5,'away_pct':41.5},
            datetime(2026,11,7,19,tzinfo=timezone.utc))
        self.assertEqual(snap['home_pct'],58.5)
        self.assertEqual(snap['inputs']['home']['players'][0]['recent_points'],[28,22,24,23])
        self.assertEqual(snap['inputs']['home']['injury_report']['items'][0]['status'],'Cuestionable')
        self.assertEqual(snap['inputs']['away']['injury_report']['items'],[])
        self.assertEqual(snap['context']['news'][0]['source'],'Medio')
        self.assertNotIn('url',snap['context']['news'][0])

    def test_input_snapshots_require_pregame_time_and_skip_rapid_duplicates(self):
        from datetime import datetime, timezone
        from copy import deepcopy
        record={}
        def snapshot(at, score=58.5):
            return {'captured_at':at,'scheduled_at':'2026-11-07T22:00:00Z',
                    'home_pct':score,'away_pct':100-score,'inputs':{'feature':1}}
        first=snapshot('2026-11-07T19:00:00Z')
        self.assertTrue(update.append_input_snapshot(record,first))
        self.assertFalse(update.append_input_snapshot(record,deepcopy(first)))
        self.assertTrue(update.append_input_snapshot(record,snapshot('2026-11-07T19:10:00Z',60)))
        self.assertFalse(update.append_input_snapshot(record,snapshot('2026-11-07T22:01:00Z')))
        self.assertEqual(len(record['input_snapshots']),2)

    def test_injury_snapshots_only_cover_games_within_36_hours(self):
        from datetime import datetime, timezone
        now=datetime(2026,11,7,18,tzinfo=timezone.utc)
        games=[
          {'id':'today','status':'pre','datetime':'2026-11-07T20:00:00Z',
           'home':{'id':'10'},'away':{'id':'20'},
           'context':{'injuries':{'home':{'items':[{'player':'A','status':'Fuera'}],
                                            'source':'ESPN'},
                                  'away':{'items':[],'source':'ESPN'}}}},
          {'id':'tomorrow','status':'pre','datetime':'2026-11-08T16:00:00Z',
           'home':{'id':'30'},'away':{'id':'40'}},
          {'id':'later','status':'pre','datetime':'2026-11-09T20:00:00Z',
           'home':{'id':'30'},'away':{'id':'50'}}]
        fetched=[]
        def fetch(team_id):
            fetched.append(team_id)
            return ([{'player':'B','status':'Probable'}],'ESPN')
        result=update.capture_upcoming_injuries(games,now,fetch)
        self.assertEqual(fetched,['30','40'])
        self.assertEqual(set(result),{'today','tomorrow'})
        self.assertEqual(result['today']['home']['items'][0]['player'],'A')


if __name__ == '__main__':
    unittest.main()
