"""NBA Analytics — modelo de pronóstico experimental v2.

Usa únicamente resultados anteriores al partido; nunca incluye cuotas ni datos
posteriores. Elo inicia en 1500 para la ventana recuperada (no Elo de temporada).
Los pesos son heurísticos, NO ajustados con un conjunto de validación.
"""
from __future__ import annotations
import math
from datetime import datetime


def _time(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _clip(n, low, high):
    return max(low, min(high, n))


def elo_before(games, cutoff):
    """Elo temporal hasta cutoff, excluyendo ese instante y cualquier partido futuro."""
    cutoff = _time(cutoff) if isinstance(cutoff, str) else cutoff
    ratings = {}
    ordered = sorted((g for g in games
                      if g.get("status") == "post" and g.get("home_score") is not None
                      and g.get("away_score") is not None and _time(g["datetime"]) < cutoff),
                     key=lambda g: (g["datetime"], g["id"]))
    for g in ordered:
        h, a = g["home"]["id"], g["away"]["id"]
        h_rating, a_rating = ratings.get(h, 1500.0), ratings.get(a, 1500.0)
        expectation = 1.0 / (1.0 + 10.0 ** ((a_rating - h_rating - 55.0) / 400.0))
        result = 1.0 if g["home_score"] > g["away_score"] else 0.0
        # No empates en partidos NBA completados; descartar datos imposibles.
        if g["home_score"] == g["away_score"]:
            continue
        score_margin = abs(g["home_score"] - g["away_score"])
        k = 18.0 * (1.0 + min(0.6, math.log1p(score_margin) / 6.0))
        adjustment = k * (result - expectation)
        ratings[h] = _clip(h_rating + adjustment, 1250, 1750)
        ratings[a] = _clip(a_rating - adjustment, 1250, 1750)
    return ratings


def _safe_number(n, default=0.0):
    try:
        n = float(n)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def predict(game, teams, elo=None):
    """Probabilidad preliminar. Datos escasos => abstención."""
    h = teams[game["home"]["id"]]
    a = teams[game["away"]["id"]]
    hf, af = h["form"], a["form"]
    n = min(int(hf.get("played") or 0), int(af.get("played") or 0))
    if n < 4:
        return None

    eh = (elo or {}).get(game["home"]["id"], 1500.0)
    ea = (elo or {}).get(game["away"]["id"], 1500.0)
    elo_component = 0.045 * _clip(eh - ea, -300, 300)

    hm = _safe_number(hf.get("margin"))
    am = _safe_number(af.get("margin"))
    margin_component = 0.22 * _clip(hm - am, -35, 35)
    win_component = 2.4 * (_safe_number(hf.get("win_rate"), .5) -
                           _safe_number(af.get("win_rate"), .5))

    # Puntos por partido y puntos recibidos; NO son ratings por posesión.
    # Usar el diferencial de expectativas en cada extremo, con peso moderado.
    hp = _safe_number(hf.get("points_for"), 110)
    ha = _safe_number(hf.get("points_against"), 110)
    ap = _safe_number(af.get("points_for"), 110)
    aa = _safe_number(af.get("points_against"), 110)
    score_component = 0.12 * _clip(((hp + aa) - (ap + ha)) / 2.0, -30, 30)

    hr = h.get("rest_days")
    ar = a.get("rest_days")
    rest_component = (-1.4 if hr == 1 else 0.0) + (1.4 if ar == 1 else 0.0)
    player_component = _clip(_safe_number(h.get("player_trend")) -
                             _safe_number(a.get("player_trend")), -1.2, 1.2)
    home_adv = 2.2
    components = {
        "home_advantage_points": home_adv,
        "elo_component": elo_component,
        "recent_margin_component": margin_component,
        "recent_wins_component": win_component,
        "scoring_component": score_component,
        "rest_component": rest_component,
        "player_component": player_component
    }
    expected_diff = sum(components.values())
    raw = 1.0 / (1.0 + math.exp(-_clip(expected_diff, -45, 45) / 12.0))
    # Prudencia por muestras pequeñas y por no disponer de calibración histórica.
    shrink = 0.65 + 0.35 * min(n, 10) / 10.0
    home_p = _clip(.5 + (raw - .5) * shrink, .14, .86)
    home_pct = round(home_p * 100, 1)
    fav_sign = 1 if home_pct >= 50 else -1
    labels = {
        "recent_margin_component": "mejor margen de puntos reciente",
        "elo_component": "mejor rendimiento ante sus rivales",
        "scoring_component": "mejor balance de anotación",
        "recent_wins_component": "más victorias recientes",
        "rest_component": "mayor descanso",
        "player_component": "mejor tendencia de jugadores",
        "home_advantage_points": "ventaja de localía",
    }
    # Solo mencionar factores realmente favorables al equipo elegido.
    favorable = sorted(
        ((fav_sign * value, name) for name, value in components.items()
         if fav_sign * value >= (0.5 if name != "player_component" else 0.35)),
        reverse=True
    )
    leading = [labels[name] for _, name in favorable[:2]]
    if home_pct == 50.0:
        reason = "Encuentro equilibrado; sin favorito claro."
    elif not leading:
        reason = "Encuentro equilibrado; ventaja estadística pequeña."
    elif len(leading) == 1:
        reason = "Ventaja por " + leading[0] + "."
    else:
        reason = "Ventaja por " + leading[0] + " y " + leading[1] + "."
    return {
        "home_pct": home_pct,
        "reason": reason,
        "away_pct": round(100.0 - home_pct, 1),
        "model": "elo-forma10-v2",
        "experimental": True,
        "calibrated": False,
        "sample_games_per_team_min": n,
        "confidence": "baja" if n < 6 else "limitada",
        "factors": {key: round(value, 2) for key, value in components.items()},
        "elo": {"home": round(eh), "away": round(ea)},
        "explanation": (
            "Pronóstico experimental basado en Elo temporal, forma de hasta 10 juegos, "
            "anotación, puntos recibidos, descanso y tendencia de jugadores. "
            "No se ajusta automáticamente por rumores, lesiones o sentimiento de aficionados."
        ),
    }
