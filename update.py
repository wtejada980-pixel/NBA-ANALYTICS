#!/usr/bin/env python3
"""Refresh static NBA forecasts from ESPN server-side (no client CORS dependency).

Unofficial ESPN endpoints; network may fail and schema may change. Failure leaves
last successful files untouched. No betting odds or automated wagering.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'latest.json'
HISTORY = ROOT / 'data' / 'history.json'
ZONE = ZoneInfo('America/Santo_Domingo')
API = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
USER_AGENT = 'NBAAnalyticsPersonalResearch/1.0 (+github-pages; low-volume)'


def get_json(endpoint: str, params: dict[str, str] | None = None, tries: int = 3):
    url = f'{API}/{endpoint}'
    if params:
        url += '?' + urlencode(params)
    last = None
    for attempt in range(tries):
        try:
            request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
            with urlopen(request, timeout=16) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise RuntimeError('Invalid ESPN response: expected JSON object')
            return result
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            last = exc
            if attempt < tries - 1:
                time.sleep(0.7 + 1.1 * attempt)
    raise RuntimeError(f'ESPN unavailable for {endpoint}: {last}')


def parse_time(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace('Z', '+00:00'))


def local_day(iso: str) -> str:
    return parse_time(iso).astimezone(ZONE).date().isoformat()


def parse_event(event: dict) -> dict | None:
    try:
        comps = event['competitions'][0]['competitors']
        home = next(c for c in comps if c.get('homeAway') == 'home')
        away = next(c for c in comps if c.get('homeAway') == 'away')
        e_date = event['date']
        status = event.get('status', {}).get('type', {}).get('state', 'pre')
        if status not in ('pre', 'in', 'post'):
            status = 'pre'
        def team(c):
            t = c['team']
            return {'id': str(t.get('id', '')), 'abbr': str(t.get('abbreviation', '')),
                    'name': t.get('displayName') or t.get('shortDisplayName') or t.get('name', 'Equipo')}
        return {
            'id': str(event['id']), 'date': local_day(e_date), 'datetime': e_date,
            'home': team(home), 'away': team(away), 'status': status,
            'home_score': int(float(home.get('score') or 0)) if status == 'post' else None,
            'away_score': int(float(away.get('score') or 0)) if status == 'post' else None,
            'source': f"https://www.espn.com/nba/game/_/gameId/{event['id']}",
        }
    except (KeyError, TypeError, ValueError, StopIteration, IndexError):
        return None


def margin(team_id: str, game: dict) -> int:
    return (game['home_score'] - game['away_score']) if team_id == game['home']['id'] else (game['away_score'] - game['home_score'])


def team_games(team_id: str, completed: list[dict], before: datetime, n: int = 8) -> list[dict]:
    relevant = [g for g in completed if parse_time(g['datetime']) < before and
                (g['home']['id'] == team_id or g['away']['id'] == team_id)]
    return sorted(relevant, key=lambda g: g['datetime'], reverse=True)[:n]


def weighted_form(team_id: str, games: list[dict]) -> dict:
    if not games:
        return {'played': 0, 'wins': 0, 'margin': 0.0, 'win_rate': 0.5, 'recent': []}
    weights = list(range(len(games), 0, -1))
    margins = [margin(team_id, game) for game in games]
    win_total = sum(m > 0 for m in margins)
    wmargin = sum(max(-25, min(25, v)) * w for v, w in zip(margins, weights)) / sum(weights)
    wrate = sum((v > 0) * w for v, w in zip(margins, weights)) / sum(weights)
    recent = []
    for game, diff in zip(games, margins):
        opp = game['away'] if game['home']['id'] == team_id else game['home']
        pts = game['home_score'] if game['home']['id'] == team_id else game['away_score']
        opp_pts = game['away_score'] if game['home']['id'] == team_id else game['home_score']
        recent.append({'date': game['date'], 'opponent': opp['abbr'], 'points': pts,
                       'opponent_points': opp_pts, 'win': diff > 0})
    return {'played': len(games), 'wins': win_total, 'margin': round(wmargin, 2),
            'win_rate': round(wrate, 3), 'recent': recent}


def stat_line(summary: dict, team_id: str) -> list[dict]:
    """Read ESPN's boxscore.players[*].statistics[*].labels / athletes / stats."""
    found = []
    for group in summary.get('boxscore', {}).get('players', []):
        if str(group.get('team', {}).get('id')) != str(team_id):
            continue
        for block in group.get('statistics', []):
            labels = [str(x).strip().upper() for x in block.get('labels', [])]
            if 'PTS' not in labels:
                continue
            for row in block.get('athletes', []):
                if row.get('didNotPlay'):
                    continue
                raw = row.get('stats') or []
                mapping = dict(zip(labels, raw))
                try:
                    pts = float(mapping.get('PTS', ''))
                except (ValueError, TypeError):
                    continue
                def stat(name):
                    try:
                        return float(mapping.get(name, 0))
                    except (TypeError, ValueError):
                        return 0.0
                who = row.get('athlete', {})
                if not who.get('id'):
                    continue
                found.append({'id': str(who['id']), 'name': who.get('displayName', 'Jugador'),
                              'pts': pts, 'reb': stat('REB'), 'ast': stat('AST')})
    return found


def player_profiles(team_id: str, recent_games: list[dict], summaries: dict[str, dict]) -> list[dict]:
    athletes = defaultdict(list)
    for game in sorted(recent_games[:5], key=lambda x: x['datetime'], reverse=True):
        stats = stat_line(summaries.get(game['id'], {}), team_id)
        for p in stats:
            athletes[p['id']].append(p)
    players = []
    for samples in athletes.values():
        if len(samples) < 2:
            continue
        pts = [s['pts'] for s in samples]
        n = len(samples)
        players.append({'name': samples[0]['name'], 'games': n,
                        'pts': round(sum(pts) / n, 1),
                        'reb': round(sum(s['reb'] for s in samples) / n, 1),
                        'ast': round(sum(s['ast'] for s in samples) / n, 1),
                        'recent_points': pts})
    return sorted(players, key=lambda p: p['pts'], reverse=True)[:5]


def player_trend(players: list[dict]) -> float:
    samples = []
    for p in players[:3]:
        pts = p['recent_points']
        if len(pts) < 4:
            continue
        recent = sum(pts[:2]) / 2
        before = sum(pts[2:]) / len(pts[2:])
        samples.append(max(-8, min(8, recent - before)))
    return 0 if not samples else max(-0.8, min(0.8, sum(samples) / len(samples) * 0.1))


def predict(game: dict, teams: dict) -> dict | None:
    home = teams[game['home']['id']]
    away = teams[game['away']['id']]
    hf, af = home['form'], away['form']
    if min(hf['played'], af['played']) < 4:
        return None
    h_rest = home.get('rest_days')
    a_rest = away.get('rest_days')
    # Local advantage and recent scoring are exploratory, not calibrated.
    home_adv = 2.4
    rest_adj = (-(1.5 if h_rest == 1 else 0) + (1.5 if a_rest == 1 else 0))
    recent_margin_adj = 0.55 * (hf['margin'] - af['margin'])
    recent_wins_adj = 4.5 * (hf['win_rate'] - af['win_rate'])
    players_adj = player_trend(home['players']) - player_trend(away['players'])
    delta = home_adv + rest_adj + recent_margin_adj + recent_wins_adj + players_adj
    raw = 1 / (1 + math.exp(-max(-60, min(60, delta)) / 11.0))
    home_probability = max(.1, min(.9, .5 + .85 * (raw - .5)))
    return {'home_pct': round(100 * home_probability, 1),
            'away_pct': round(100 * (1 - home_probability), 1),
            'factors': {'home_advantage_points': home_adv,
                        'recent_margin_component': round(recent_margin_adj, 2),
                        'recent_wins_component': round(recent_wins_adj, 2),
                        'rest_component': round(rest_adj, 2),
                        'player_component': round(players_adj, 2)},
            'model': 'forma8-v1', 'experimental': True}


def load_history() -> dict:
    try:
        v = json.loads(HISTORY.read_text(encoding='utf-8'))
        return v if isinstance(v, dict) and isinstance(v.get('predictions'), dict) else {'predictions': {}}
    except (FileNotFoundError, ValueError):
        return {'predictions': {}}


def write_json_atomic(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)


def refresh(today: date | None = None):
    now = datetime.now(timezone.utc)
    day = today or now.astimezone(ZONE).date()
    # A bounded rolling window keeps this dependency-free job within public API usage.
    start = day - timedelta(days=35)
    all_events = {}
    failed_days = []
    for i in range((day - start).days + 1):
        d = start + timedelta(days=i)
        try:
            data = get_json('scoreboard', {'dates': d.strftime('%Y%m%d'), 'limit': '100'})
        except RuntimeError:
            failed_days.append(d.isoformat())
            continue
        for item in data.get('events', []):
            event = parse_event(item)
            if event:
                all_events[event['id']] = event
    if len(failed_days) > 2:
        raise RuntimeError(f'Historical schedule incomplete on {len(failed_days)} dates; leaving previous snapshot untouched')
    schedule_errors = []
    for i in range(3):
        d = day + timedelta(days=i)
        try:
            data = get_json('scoreboard', {'dates': d.strftime('%Y%m%d'), 'limit': '100'})
        except RuntimeError:
            schedule_errors.append(d.isoformat())
            continue
        for item in data.get('events', []):
            event = parse_event(item)
            if event:
                all_events[event['id']] = event
    if schedule_errors:
        raise RuntimeError('Cannot verify schedule on ' + ', '.join(schedule_errors))
    future_dates = { (day + timedelta(days=i)).isoformat() for i in range(3) }
    schedule = sorted([e for e in all_events.values() if e['date'] in future_dates],
                      key=lambda x: x['datetime'])
    if not schedule:
        # Could legitimately be an off-season day; do not fail. Yet do not
        # fabricate "no games" if source returns malformed empty payload.
        print('No NBA games on the next three dates.')
    finished = sorted([e for e in all_events.values() if e['status'] == 'post' and
                       e['home_score'] is not None and e['away_score'] is not None],
                      key=lambda x: x['datetime'])
    involved_teams = {g[side]['id']: g[side] for g in schedule for side in ('home', 'away')}
    team_histories = {}
    need_summaries = {}
    for tid in involved_teams:
        g_date = min(parse_time(g['datetime']) for g in schedule if tid in (g['home']['id'], g['away']['id']))
        recent = team_games(tid, finished, g_date)
        team_histories[tid] = recent
        for item in recent[:5]:
            need_summaries[item['id']] = item
    summaries = {}
    for gid in need_summaries:
        try:
            summaries[gid] = get_json('summary', {'event': gid}, tries=2)
        except RuntimeError:
            # Player stats are optional; never invent them when summary fails.
            pass
    teams = {}
    for tid, info in involved_teams.items():
        hist = team_histories[tid]
        last_date = local_day(hist[0]['datetime']) if hist else None
        ref_date = min(g['date'] for g in schedule if tid in (g['home']['id'], g['away']['id']))
        rest = (date.fromisoformat(ref_date) - date.fromisoformat(last_date)).days if last_date else None
        teams[tid] = {'id': tid, 'abbr': info['abbr'], 'name': info['name'],
                      'rest_days': rest,
                      'form': weighted_form(tid, hist),
                      'players': player_profiles(tid, hist, summaries)}
    for game in schedule:
        game['prediction'] = predict(game, teams) if game['status'] == 'pre' else None
    history = load_history()
    for game in all_events.values():
        if game['status'] == 'post' and game['id'] in history['predictions']:
            record = history['predictions'][game['id']]
            record['result'] = {'home_score': game['home_score'], 'away_score': game['away_score'],
                                'winner': 'home' if game['home_score'] > game['away_score'] else 'away'}
    for game in schedule:
        if game['status'] == 'pre' and game['prediction'] and game['id'] not in history['predictions']:
            history['predictions'][game['id']] = {
                'date': game['date'], 'home': game['home']['name'], 'away': game['away']['name'],
                'home_pct': game['prediction']['home_pct'], 'away_pct': game['prediction']['away_pct'],
                'predicted_at': now.isoformat(), 'result': None}
    # Keep history files modest and predictable.
    if len(history['predictions']) > 800:
        history['predictions'] = dict(sorted(history['predictions'].items(),
                                           key=lambda p: p[1]['date'], reverse=True)[:800])
    scored = [record for record in history['predictions'].values() if record.get('result')]
    brier = None
    if scored:
        brier = round(sum((x['home_pct']/100 - (1 if x['result']['winner']=='home' else 0))**2
                          for x in scored) / len(scored), 4)
    snapshot = {
        'as_of': now.isoformat(), 'date': day.isoformat(), 'timezone': 'America/Santo_Domingo',
        'source': 'ESPN (endpoint no oficial, sin garantía de disponibilidad)',
        'source_url': 'https://www.espn.com/nba/scoreboard',
        'model': 'forma8-v1 / probabilidades experimentales',
        'games': schedule, 'teams': teams,
        'validation': {'completed_predictions': len(scored), 'brier_score': brier},
        'notes': ['No utiliza cuotas de apuestas',
                  'El historial de 35 días puede omitir resultados anteriores',
                  'La disponibilidad y lesiones en tiempo real NO se incorporan automáticamente',
                  'Las probabilidades no están calibradas ni garantizan resultados'],
    }
    # Both files are only rewritten after essential data checks pass.
    write_json_atomic(OUT, snapshot)
    write_json_atomic(HISTORY, history)
    print(f"Updated {len(schedule)} games / {len(teams)} teams, {len(summaries)} summaries; "
          f"{len(scored)} assessed predictions; date {day}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='Override date YYYY-MM-DD for testing')
    args = parser.parse_args()
    day = date.fromisoformat(args.date) if args.date else None
    try:
        refresh(day)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
