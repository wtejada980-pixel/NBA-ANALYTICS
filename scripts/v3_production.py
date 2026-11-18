"""Pronosticador V3 activo; V2 ya no genera predicciones nuevas."""
from __future__ import annotations

import math
from pathlib import Path

from model_v3 import FEATURES, build_features, infer, load_seasons, train
from v3_dataset import STORE
from v3_shadow import REQUIRED, current_final_games, features_at

ACTIVE_MODEL = "logistic-v3-production"
TRAINING_SEASONS = (2022, 2023)


def fit_model(folder: Path = STORE):
    """Entrenar con las mismas temporadas usadas en la evaluación prospectiva V3."""
    seasons, coverage = load_seasons(folder)
    missing = [season for season in sorted(REQUIRED)
               if not isinstance(coverage.get(season), int)]
    if missing:
        raise RuntimeError("V3 no disponible: faltan temporadas completas " +
                           ", ".join(missing))
    rows = build_features(seasons, include_v2_proxy=False)
    fit = [row for row in rows if row.get("season_year") in TRAINING_SEASONS]
    if len(fit) < 100:
        raise RuntimeError("V3 no disponible: muestra de entrenamiento insuficiente")
    return train(fit), seasons


def current_rows(events):
    """Convertir solo marcadores finales confirmados de la temporada actual."""
    return current_final_games({"events": events})


def predict(game, model, feature_games, cutoff):
    """Crear una predicción V3 con datos que existían antes de la hora de corte."""
    home_id, away_id = str(game["home"]["id"]), str(game["away"]["id"])
    row = features_at(feature_games, home_id, away_id, cutoff)
    if row is None:
        return None
    probability = infer(model, row)
    if not math.isfinite(probability):
        return None
    home_pct = round(probability * 100, 1)
    away_pct = round(100 - home_pct, 1)
    favorite_sign = 1 if home_pct >= 50 else -1
    weights = model.get("weights", [])[1:]
    labels = {
        "elo_difference": "Elo previo",
        "margin_difference": "margen reciente",
        "win_rate_difference": "victorias recientes",
        "scoring_difference": "anotación reciente",
        "defense_difference": "defensa reciente",
        "rest_difference": "descanso",
    }
    contributions = []
    for i, feature in enumerate(FEATURES):
        scale = max(.1, float(model["std"][feature]))
        z = (float(row[feature]) - float(model["means"][feature])) / scale
        contribution = float(weights[i]) * z
        if favorite_sign * contribution > 0:
            contributions.append((favorite_sign * contribution, labels[feature]))
    contributions.sort(reverse=True)
    reasons = [name for _, name in contributions[:2]]
    reason = ("Ventaja V3 por " + " y ".join(reasons) + "."
              if reasons else "Pronóstico V3 equilibrado según la muestra disponible.")
    elo_delta = float(row["elo_difference"]) * 100
    elo_home_pct = 100 / (1 + 10 ** (-(elo_delta + 55) / 400))
    return {
        "home_pct": home_pct,
        "away_pct": away_pct,
        "model": ACTIVE_MODEL,
        "experimental": True,
        "calibrated": False,
        "reason": reason,
        "elo_baseline_home_pct": round(elo_home_pct, 1),
        "factors": {key: round(float(value), 4) for key, value in row.items()},
        "explanation": (
            "Regresión logística V3 basada en Elo y diferencias recientes de margen, "
            "victorias, anotación, defensa y descanso. Solo usa resultados previos."
        ),
    }
