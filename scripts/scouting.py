"""Análisis comparativo prepartido; NO altera el modelo ni calcula hándicaps.

Todos los valores provienen de partidos anteriores a la fecha del encuentro.
Los porcentajes son una referencia histórica congelada, no se recalculan aquí.
"""
from __future__ import annotations

import math


def _stats(teams, team):
    info = teams.get(str(team.get("id")), {})
    form = info.get("form", {})
    return {
        "games": int(form.get("played") or 0),
        "wins": int(form.get("wins") or 0),
        "margin": _number(form.get("margin")),
        "for": _number(form.get("points_for")),
        "against": _number(form.get("points_against")),
        "rest": info.get("rest_days"),
    }


def _number(value):
    if value is None:
        return None
    try:
        result = float(value)
        return round(result, 1) if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def analyze(game, teams):
    """Un diagnóstico cualitativo, independiente de predicciones o resultados en vivo."""
    pred = game.get("prediction") or {}
    hp, ap = _number(pred.get("home_pct")), _number(pred.get("away_pct"))
    if hp is None or ap is None or not (0 <= hp <= 100 and 0 <= ap <= 100):
        return None
    if abs(hp + ap - 100) > 0.2:
        return None
    away, home = game["away"], game["home"]
    hform, aform = _stats(teams, home), _stats(teams, away)
    fav = "home" if hp > ap else "away" if ap > hp else None
    if fav is None:
        classification = "Sin favorito"
        lead = 50.0
    else:
        lead = max(hp, ap)
        classification = ("Partido muy cerrado" if lead < 58
                          else "Ventaja moderada" if lead < 68
                          else "Favorito estadístico")
    favorite = game[fav]["name"] if fav else None
    opposing = game["away" if fav == "home" else "home"]["name"] if fav else None
    fav_stats = hform if fav == "home" else aform
    opp_stats = aform if fav == "home" else hform
    observations = []
    if lead < 58:
        observations.append("Diferencia de probabilidades pequeña: no hay una ventaja sólida.")
    if fav and min(fav_stats["games"], opp_stats["games"]) >= 4:
        if fav_stats["margin"] is not None and opp_stats["margin"] is not None:
            if fav_stats["margin"] + 4 < opp_stats["margin"]:
                observations.append("Alerta: el rival tiene un mejor margen de puntos reciente.")
        if fav_stats["games"] and opp_stats["games"]:
            if (opp_stats["wins"] / opp_stats["games"] -
                    fav_stats["wins"] / fav_stats["games"] >= 0.2):
                observations.append("Alerta: el rival tiene mayor porcentaje de victorias recientes.")
    if fav and isinstance(fav_stats["rest"], int) and isinstance(opp_stats["rest"], int):
        if fav_stats["rest"] < opp_stats["rest"]:
            observations.append("El favorito llega con menos días de descanso registrado.")
    if not observations:
        observations.append("Sin alertas cuantitativas adicionales en la forma reciente disponible.")
    return {
        "version": "contexto-v1",
        "favorite": favorite,
        "opponent": opposing,
        "favorite_pct_original": lead,
        "classification": classification,
        "observations": observations[:4],
        "home_form": hform,
        "away_form": aform,
        "scope": "Análisis descriptivo, no una nueva probabilidad ni un pronóstico de hándicap.",
    }
