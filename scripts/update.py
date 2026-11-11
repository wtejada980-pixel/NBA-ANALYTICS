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
from context_sources import collect
from model_v2 import predict as predict_v2, elo_before, elo_baseline_probability
from validation import evaluate
from scouting import analyze as analyze_scouting

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'latest.json'
HISTORY = ROOT / 'data' / 'history.json'
EVENT_CACHE = ROOT / 'data' / 'events-cache.json'
BOX_CACHE = ROOT / 'data' / 'player-box-cache.json'
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


def team_games(team_id: str, completed: list[dict], before: datetime, n: int = 10) -> list[dict]:
    relevant = [g for g in completed if parse_time(g['datetime']) < before and
                (g['home']['id'] == team_id or g['away']['id'] == team_id)]
    return sorted(relevant, key=lambda g: g['datetime'], reverse=True)[:n]


def weighted_form(team_id: str, games: list[dict]) -> dict:
    if not games:
        return {'played': 0, 'wins': 0, 'margin': 0.0, 'win_rate': 0.5, 'recent': [], 'points_for': None, 'points_against': None}
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
    pts_for = sum(row['points'] * w for row, w in zip(recent, weights)) / sum(weights)
    pts_against = sum(row['opponent_points'] * w for row, w in zip(recent, weights)) / sum(weights)
    return {'played': len(games), 'wins': win_total, 'margin': round(wmargin, 2),
            'win_rate': round(wrate, 3), 'points_for': round(pts_for, 1),
            'points_against': round(pts_against, 1), 'recent': recent}


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
                              'pts': pts, 'reb': stat('REB'), 'ast': stat('AST'),
                              'starter': row.get('starter') is True or row.get('isStarter') is True})
    return found


def player_profiles(team_id: str, recent_games: list[dict], summaries: dict[str, dict]) -> list[dict]:
    athletes = defaultdict(list)
    for game in sorted(recent_games[:5], key=lambda x: x['datetime'], reverse=True):
        saved = summaries.get(game['id'], {})
        stats = saved.get('player_stats', {}).get(str(team_id)) if isinstance(saved, dict) else None
        if stats is None:
            stats = stat_line(saved, team_id)
        for p in stats:
            athletes[p['id']].append(p)
    players = []
    for samples in athletes.values():
        if len(samples) < 2:
            continue
        pts = [s['pts'] for s in samples]
        n = len(samples)
        players.append({'id': samples[0]['id'], 'name': samples[0]['name'], 'games': n,
                        'pts': round(sum(pts) / n, 1),
                        'reb': round(sum(s['reb'] for s in samples) / n, 1),
                        'ast': round(sum(s['ast'] for s in samples) / n, 1),
                        'recent_points': pts})
    return sorted(players, key=lambda p: p['pts'], reverse=True)[:15]


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


def load_cache(path: Path, key: str) -> dict:
    """Una caché rota o inexistente nunca se confunde con resultados reales."""
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
        value = document.get(key, {})
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, ValueError, OSError, AttributeError):
        return {}


def locked_prediction(record: dict | None) -> dict | None:
    """Congelar el primer porcentaje registrado antes del salto inicial."""
    if not isinstance(record, dict):
        return None
    try:
        if parse_time(record['predicted_at']) >= parse_time(record['scheduled_at']):
            return None
        home, away = float(record['home_pct']), float(record['away_pct'])
        if not (math.isfinite(home) and math.isfinite(away)
                and 0 <= home <= 100 and 0 <= away <= 100
                and abs(home + away - 100) < 0.2):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return {'home_pct': home, 'away_pct': away,
            'reason': str(record.get('reason') or 'Pronóstico registrado antes del inicio.'),
            'model': str(record.get('model') or 'sin versión'),
            'experimental': True, 'calibrated': False,
            'predicted_at': record['predicted_at'], 'locked': True}



def save_pre_match_revision(record: dict, recalculated: dict | None, at: datetime) -> dict | None:
    """Guardar una revisión reproducible sin modificar jamás el primer pronóstico.

    No crea revisiones después del inicio, ni registros redundantes. La referencia
    evaluada por validation.evaluate sigue siendo record['home_pct'] ORIGINAL.
    """
    original = locked_prediction(record)
    if original is None or not isinstance(recalculated, dict):
        return None
    if at >= parse_time(record['scheduled_at']):
        return latest_pre_match_revision(record)
    try:
        home, away = float(recalculated['home_pct']), float(recalculated['away_pct'])
    except (KeyError, ValueError, TypeError, OverflowError):
        return latest_pre_match_revision(record)
    if not (math.isfinite(home) and math.isfinite(away) and 0 <= home <= 100
            and 0 <= away <= 100 and abs(home + away - 100) <= 0.2):
        return latest_pre_match_revision(record)
    prior = latest_pre_match_revision(record)
    baseline = prior or original
    if abs(home - baseline['home_pct']) >= .1 or abs(away - baseline['away_pct']) >= .1:
        revision = {
            'home_pct': home, 'away_pct': away,
            'predicted_at': at.isoformat(),
            'model': str(recalculated.get('model') or original['model']),
            'reason': str(recalculated.get('reason') or 'Actualización de resultados anteriores.'),
            'source': 'Recalculado con resultados disponibles antes del inicio',
        }
        revisions = record.setdefault('revisions', [])
        if not isinstance(revisions, list):
            revisions = record['revisions'] = []
        revisions.append(revision)
        record['revisions'] = revisions[-12:]
    return latest_pre_match_revision(record)


def latest_pre_match_revision(record: dict) -> dict | None:
    """Leer la última revisión validada sin confundirla con el pronóstico original."""
    try:
        if not isinstance(record, dict):
            return None
        cutoff = parse_time(record['scheduled_at'])
        original_at = parse_time(record['predicted_at'])
        if original_at >= cutoff:
            return None
        valid = []
        for entry in record.get('revisions', []):
            if not isinstance(entry, dict):
                continue
            ts = parse_time(entry['predicted_at'])
            hp, ap = float(entry['home_pct']), float(entry['away_pct'])
            if original_at < ts < cutoff and math.isfinite(hp) and math.isfinite(ap) and (
                0 <= hp <= 100 and 0 <= ap <= 100 and abs(hp + ap - 100) <= .2
            ):
                valid.append({**entry, 'home_pct': hp, 'away_pct': ap})
        return sorted(valid, key=lambda x: x['predicted_at'])[-1] if valid else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def write_json_atomic(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)



def recent_meetings(game: dict, finished: list[dict], limit: int = 5) -> list[dict]:
    """Últimos cruces REALES anteriores a este partido, sin inventar encuentros."""
    ids = {game['home']['id'], game['away']['id']}
    matched = [g for g in finished if g['id'] != game['id']
               and {g['home']['id'], g['away']['id']} == ids
               and parse_time(g['datetime']) < parse_time(game['datetime'])]
    matched.sort(key=lambda g: g['datetime'], reverse=True)
    return [{'date': g['date'], 'home': g['home']['abbr'], 'away': g['away']['abbr'],
             'home_score': g['home_score'], 'away_score': g['away_score']}
            for g in matched[:limit]]


def public_history(history: dict, limit: int = 45) -> list[dict]:
    """Historial legible sin reescribir pronósticos; descarta predicciones tardías."""
    visible = []
    for game_id, record in history.get('predictions', {}).items():
        try:
            started = parse_time(record['scheduled_at'])
            forecast = parse_time(record['predicted_at'])
            home_pct = float(record['home_pct'])
            away_pct = float(record['away_pct'])
            if forecast >= started or not math.isfinite(home_pct) or not math.isfinite(away_pct):
                continue
            if not (0 <= home_pct <= 100 and 0 <= away_pct <= 100):
                continue
            if abs(home_pct + away_pct - 100) > 0.2:
                continue
            result = record.get('result')
            final = None
            if isinstance(result, dict) and result.get('winner') in ('home','away'):
                hs, aws = result.get('home_score'), result.get('away_score')
                if isinstance(hs, int) and isinstance(aws, int) and hs >= 0 and aws >= 0 and hs != aws:
                    final = {'home_score': hs, 'away_score': aws, 'winner': result['winner']}
            row = {'id': str(game_id), 'date': record['date'],
                   'scheduled_at': record['scheduled_at'],
                   'predicted_at': record['predicted_at'],
                   'home': record['home'], 'away': record['away'],
                   'home_pct': home_pct, 'away_pct': away_pct,
                   'model': record.get('model', 'sin versión'), 'result': final}
            baseline = record.get('elo_baseline_home_pct')
            if baseline is not None:
                value = float(baseline)
                if math.isfinite(value) and 0 <= value <= 100:
                    row['elo_baseline_home_pct'] = value
            revision = latest_pre_match_revision(record)
            if revision:
                row['revised_prediction'] = revision
            visible.append(row)
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    visible.sort(key=lambda row: (row['scheduled_at'], row['id']), reverse=True)
    return visible[:limit]



def archived_games(all_events: dict, history: dict, day: date, days: int = 7) -> list[dict]:
    """Calendario de días pasados: resultados verificados y predicciones reales guardadas.

    No inventa probabilidades retrospectivas. El historial NO cambia ni se
    recalcula con los resultados posteriores al inicio del juego.
    """
    begin = (day - timedelta(days=days)).isoformat()
    end = day.isoformat()
    records = history.get('predictions', {})
    archived = []
    for original in all_events.values():
        if not isinstance(original, dict) or not (begin <= str(original.get('date', '')) < end):
            continue
        # No cambiar la caché de eventos con propiedades de presentación.
        game = dict(original)
        game['historical'] = True
        record = records.get(str(game.get('id')))
        game['prediction'] = locked_prediction(record)
        game['revised_prediction'] = latest_pre_match_revision(record)
        # No inventar marcador final si no lo ha confirmado la fuente.
        if game.get('status') != 'post':
            game['home_score'] = None
            game['away_score'] = None
        archived.append(game)
    archived.sort(key=lambda g: (g['datetime'], g['id']))
    return archived


def refresh(today: date | None = None):
    now = datetime.now(timezone.utc)
    day = today or now.astimezone(ZONE).date()
    # Resultados verificados en caché incremental; evitar decenas de
    # solicitudes repetidas en cada ejecución programada.
    history = load_history()
    cached_events = load_cache(EVENT_CACHE, 'events')
    cutoff = (day - timedelta(days=45)).isoformat()
    all_events = {str(k): v for k, v in cached_events.items()
                  if isinstance(v, dict) and v.get('id')
                  and isinstance(v.get('date'), str) and v['date'] >= cutoff}
    lookback = 21 if not all_events else 5
    dates_to_fetch = {day - timedelta(days=i) for i in range(lookback + 1)}
    dates_to_fetch.update(day + timedelta(days=i) for i in range(3))
    for record in history['predictions'].values():
        if record.get('result') is not None:
            continue
        try:
            pending_day = date.fromisoformat(record['date'])
        except (ValueError, TypeError, KeyError):
            continue
        if 0 <= (day - pending_day).days <= 35:
            dates_to_fetch.add(pending_day)
    failed_days, schedule_errors = [], []
    for d in sorted(dates_to_fetch):
        try:
            payload = get_json('scoreboard', {'dates': d.strftime('%Y%m%d'), 'limit': '100'})
            if not isinstance(payload.get('events'), list):
                raise RuntimeError('Respuesta ESPN sin lista de partidos')
        except RuntimeError:
            if d >= day:
                schedule_errors.append(d.isoformat())
            else:
                failed_days.append(d.isoformat())
            continue
        for item in payload['events']:
            event = parse_event(item)
            if event:
                all_events[event['id']] = event
    if schedule_errors:
        # No sustituir la última agenda correcta por información parcial.
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
    box_cache = load_cache(BOX_CACHE, 'games')
    summaries = {}
    for gid, item in need_summaries.items():
        cached = box_cache.get(gid)
        if isinstance(cached, dict) and isinstance(cached.get('player_stats'), dict):
            summaries[gid] = cached
            continue
        try:
            raw = get_json('summary', {'event': gid}, tries=2)
            summary = {'player_stats': {
                item['home']['id']: stat_line(raw, item['home']['id']),
                item['away']['id']: stat_line(raw, item['away']['id'])}}
            summaries[gid] = summary
            box_cache[gid] = summary
        except RuntimeError:
            # No inventar jugadores cuando ESPN falle.
            pass
    teams = {}
    for tid, info in involved_teams.items():
        hist = team_histories[tid]
        last_date = local_day(hist[0]['datetime']) if hist else None
        ref_date = min(g['date'] for g in schedule if tid in (g['home']['id'], g['away']['id']))
        rest = (date.fromisoformat(ref_date) - date.fromisoformat(last_date)).days if last_date else None
        players = player_profiles(tid, hist, summaries)
        teams[tid] = {'id': tid, 'abbr': info['abbr'], 'name': info['name'],
                      'rest_days': rest,
                      'form': weighted_form(tid, hist),
                      'players': players, 'player_trend': player_trend(players)}
    for game in schedule:
        game['head_to_head'] = recent_meetings(game, finished)
        stored = history['predictions'].get(game['id'])
        frozen = locked_prediction(stored)
        future = parse_time(game['datetime']) > now
        before_tipoff = game['status'] == 'pre' and future
        ratings = elo_before(finished, game['datetime']) if before_tipoff else {}
        recalculated = predict_v2(game, teams, ratings) if before_tipoff else None
        if frozen:
            game['prediction'] = frozen  # Pronóstico original: no se altera.
            game['elo_baseline_home_pct'] = stored.get('elo_baseline_home_pct')
            revision = save_pre_match_revision(stored, recalculated, now) if before_tipoff else latest_pre_match_revision(stored)
            game['revised_prediction'] = revision
        elif before_tipoff:
            game['prediction'] = recalculated
            game['elo_baseline_home_pct'] = (
                elo_baseline_probability(game, ratings) if recalculated else None)
            game['revised_prediction'] = None
        else:
            game['prediction'] = None
            game['elo_baseline_home_pct'] = None
            game['revised_prediction'] = None
    # Análisis contextual sobre el porcentaje más reciente, sin tocar el original.
    for game in schedule:
        if game['prediction']:
            active = game.get('revised_prediction') or game['prediction']
            game['scouting'] = analyze_scouting({**game, 'prediction': active}, teams)
    # Titulares/estadísticas del partido: nunca inferir quintetos de la forma reciente.
    # La API no oficial puede no publicar alineaciones antes del salto inicial.
    for game in schedule:
        if game['date'] != day.isoformat():
            continue
        try:
            actual = get_json('summary', {'event': game['id']}, tries=1)
        except RuntimeError:
            continue
        lineups = {'home': [], 'away': []}
        for side in ('home', 'away'):
            for p in stat_line(actual, game[side]['id']):
                lineups[side].append({
                    'id': p['id'], 'name': p['name'],
                    'starter': p.get('starter') is True,
                    'game_pts': p['pts'] if game['status'] in ('in', 'post') else None
                })
        if lineups['home'] or lineups['away']:
            game['lineups'] = lineups
    # Contexto de lesiones, noticias y foros SOLO para partidos del día.
    # No modifica la probabilidad, que depende de la forma deportiva.
    daily_context = collect([g for g in schedule if g['date'] == day.isoformat()], teams)
    news_items = daily_context.get('news', []) if isinstance(daily_context, dict) else []
    news_updated_at = daily_context.get('news_updated_at') if isinstance(daily_context, dict) else None
    if not news_items:
        # Si FOX no responde, mantener el último feed bueno en lugar de borrar
        # los titulares ya publicados; la fecha visible conserva su antigüedad.
        try:
            previous = json.loads(OUT.read_text(encoding='utf-8'))
            news_items = previous.get('news', []) if isinstance(previous, dict) else []
            news_updated_at = previous.get('news_updated_at') if isinstance(previous, dict) else None
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            news_items = []
            news_updated_at = None
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
                'predicted_at': now.isoformat(), 'model': game['prediction']['model'],
                'reason': game['prediction'].get('reason', 'Pronóstico prepartido.'),
                'elo_baseline_home_pct': game['elo_baseline_home_pct'],
                'scheduled_at': game['datetime'], 'result': None}
    # Keep history files modest and predictable.
    if len(history['predictions']) > 800:
        history['predictions'] = dict(sorted(history['predictions'].items(),
                                           key=lambda p: p[1]['date'], reverse=True)[:800])
    metrics = evaluate(history['predictions'])
    # Siete fechas previas y agenda actual; registros viejos sin pronóstico
    # muestran solo el resultado real, nunca un porcentaje retrocalculado.
    archived = archived_games(all_events, history, day, days=7)
    snapshot = {
        'as_of': now.isoformat(), 'date': day.isoformat(), 'timezone': 'America/Santo_Domingo',
        'source': 'ESPN (endpoint no oficial, sin garantía de disponibilidad)',
        'source_url': 'https://www.espn.com/nba/scoreboard',
        'model': 'elo-forma10-v2 / probabilidades experimentales; contexto cualitativo separado',
        'games': archived + schedule, 'teams': teams,
        'news': news_items, 'news_source': daily_context.get('news_source', 'FOX Sports RSS') if isinstance(daily_context, dict) else 'FOX Sports RSS',
        'news_updated_at': news_updated_at,
        'archive_days': 7,
        'validation': metrics,
        'history_recent': public_history(history),
        'data_quality': {'history_partial': bool(failed_days),
                         'missing_historical_days': len(failed_days),
                         'cached_games': len(all_events),
                         'cached_player_boxes': len(box_cache)},
        'notes': ['No utiliza cuotas de apuestas',
                  'El historial de hasta 45 días se conserva progresivamente; primera recuperación potencialmente incompleta',
                  'Puntos anotados y recibidos por juego NO equivalen a rating por 100 posesiones',
                  'Lesiones disponibles como contexto no verificado; comprobar informe oficial',
                  'Foros y noticias no alteran automáticamente los porcentajes',
                  'Las probabilidades no están calibradas ni garantizan resultados',
                  'Revisiones prepartido se guardan aparte; las métricas evalúan el primer pronóstico',
                  'Se muestran 7 días históricos con marcadores verificados y predicciones originales si existían'],
    }
    all_events = {gid: e for gid, e in all_events.items() if e['date'] >= cutoff}
    box_cache = {gid: entry for gid, entry in box_cache.items() if gid in all_events}
    # GitHub publicará los cuatro ficheros en un mismo commit.
    write_json_atomic(OUT, snapshot)
    write_json_atomic(HISTORY, history)
    write_json_atomic(EVENT_CACHE, {'events': all_events})
    write_json_atomic(BOX_CACHE, {'games': box_cache})
    print(f"Updated {len(schedule)} games / {len(teams)} teams, "
          f"{len(summaries)} summaries, {len(failed_days)} missing historical dates; "
          f"{metrics['completed_predictions']} assessed predictions; date {day}")


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
