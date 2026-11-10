"""V3 experimental: features solo de resultados anteriores, entrenamiento cronológico.

No se publica ninguna predicción en producción hasta revisión explícita.
Solo Python stdlib: regresión logística regularizada y comparador Elo.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data" / "v3"
FEATURES = ("elo_difference", "margin_difference", "win_rate_difference",
            "scoring_difference", "rest_difference")
MODEL_NAME = "logistic-v3-experimental"


def _day(event):
    return date.fromisoformat(event["date"])


def _sigmoid(value):
    value = max(-35., min(35., value))
    return 1. / (1. + math.exp(-value))


def _brier(pairs):
    return sum((p-y) ** 2 for p, y in pairs) / len(pairs) if pairs else None


def _log_loss(pairs):
    return -sum(y * math.log(max(1e-10, p)) +
                (1-y) * math.log(max(1e-10, 1-p)) for p, y in pairs) / len(pairs) if pairs else None


def metrics(pairs):
    if not pairs:
        return {"n": 0, "brier": None, "log_loss": None, "winner_accuracy_pct": None}
    return {
        "n": len(pairs),
        "brier": round(_brier(pairs), 5),
        "log_loss": round(_log_loss(pairs), 5),
        "winner_accuracy_pct": round(100 * sum((p >= .5) == bool(y) for p, y in pairs)/len(pairs), 1),
    }


def _form(team, completed, current_day, count=10):
    # Conservative day-level cutoff: never use same-day games to predict.
    relevant = [g for g in completed if _day(g) < current_day and
                (g["home_id"] == team or g["away_id"] == team)]
    rows = relevant[-count:]
    if not rows:
        return {"n": 0, "margin": 0., "win": .5, "scoring": 0., "rest": 3.}
    margins = [(g["home_score"] - g["away_score"]) *
               (1 if g["home_id"] == team else -1) for g in rows]
    rest = max(0, min(7, (current_day - _day(rows[-1])).days - 1))
    return {"n": len(rows), "margin": sum(margins)/len(rows),
            "win": sum(m > 0 for m in margins)/len(rows),
            "scoring": sum(margins)/len(rows),
            "rest": rest}


def build_features(events, min_previous=4):
    """Elo y forma calculados antes de cada día; grupos del mismo día no se filtran."""
    clean = sorted(events, key=lambda x: (x["date"], x["datetime"], x["id"]))
    seen_ids = set()
    completed, ratings, rows = [], {}, []
    i = 0
    while i < len(clean):
        current = _day(clean[i])
        batch = []
        while i < len(clean) and _day(clean[i]) == current:
            g = clean[i]
            i += 1
            if g["id"] in seen_ids:
                raise ValueError("Evento duplicado: " + g["id"])
            seen_ids.add(g["id"])
            if g["home_id"] == g["away_id"] or g["home_score"] == g["away_score"]:
                raise ValueError("Marcador o equipos inválidos")
            batch.append(g)
        for g in batch:
            h, a = g["home_id"], g["away_id"]
            hf, af = _form(h, completed, current), _form(a, completed, current)
            if min(hf["n"], af["n"]) < min_previous:
                continue
            eh, ea = ratings.get(h, 1500.), ratings.get(a, 1500.)
            elo_prob = _sigmoid(math.log(10.) * (eh-ea+55.)/400.)
            row = {
                "id": g["id"], "date": g["date"], "season_year": g["season_year"],
                "y": 1 if g["home_score"] > g["away_score"] else 0,
                "elo_probability": round(elo_prob, 8),
                "elo_difference": (eh-ea)/100.,
                "margin_difference": (hf["margin"]-af["margin"])/10.,
                "win_rate_difference": hf["win"]-af["win"],
                "scoring_difference": (hf["scoring"]-af["scoring"])/10.,
                "rest_difference": (hf["rest"]-af["rest"])/4.,
            }
            rows.append(row)
        # Solo después de construir todos los ejemplos del día añadimos sus resultados.
        for g in batch:
            h, a = g["home_id"], g["away_id"]
            eh, ea = ratings.get(h, 1500.), ratings.get(a, 1500.)
            expected = _sigmoid(math.log(10.) * (eh-ea+55.)/400.)
            y = 1 if g["home_score"] > g["away_score"] else 0
            change = 22. * (y-expected)
            ratings[h], ratings[a] = eh+change, ea-change
            completed.append(g)
    return rows


def train(rows, epochs=1200, learn_rate=.06, ridge=.025):
    if len(rows) < 100:
        raise ValueError("Muestra insuficiente para entrenar V3")
    means = {k: sum(r[k] for r in rows)/len(rows) for k in FEATURES}
    std = {k: max(.1, (sum((r[k]-means[k])**2 for r in rows)/len(rows))**.5)
           for k in FEATURES}
    x = [[1.] + [(r[k]-means[k])/std[k] for k in FEATURES] for r in rows]
    y = [r["y"] for r in rows]
    w = [0.] * (len(FEATURES)+1)
    for _ in range(epochs):
        grad = [0.] * len(w)
        for values, label in zip(x, y):
            delta = _sigmoid(sum(v*ww for v, ww in zip(values, w))) - label
            for j, value in enumerate(values):
                grad[j] += delta * value
        n = len(rows)
        for j in range(len(w)):
            penalty = ridge*w[j] if j else 0
            w[j] -= learn_rate * (grad[j]/n + penalty)
    return {"name": MODEL_NAME, "feature_names": list(FEATURES),
            "means": means, "std": std, "weights": [round(v, 10) for v in w],
            "n_train": len(rows)}


def infer(model, row):
    if model.get("feature_names") != list(FEATURES):
        raise ValueError("Esquema de atributos incompatible")
    values = [1.] + [(row[k]-model["means"][k])/model["std"][k] for k in FEATURES]
    return _sigmoid(sum(v*w for v, w in zip(values, model["weights"])))


def load_seasons(folder=FOLDER):
    items, coverage = [], {}
    for path in sorted(folder.glob("games-????-??.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        season = d.get("season")
        if not d.get("complete") or len(d.get("checked_dates", [])) < 240:
            coverage[season or path.name] = "incomplete"
            continue
        coverage[season] = len(d["games"])
        items.extend(d["games"])
    return items, coverage


def evaluate(folder=FOLDER):
    games, coverage = load_seasons(folder)
    rows = build_features(games)
    seasons = sorted({r["season_year"] for r in rows})
    report = {"version": MODEL_NAME, "status": "insufficient_history",
              "source": "ESPN (API no oficial)", "coverage": coverage,
              "games": len(games), "usable_rows": len(rows), "seasons": seasons,
              "published": False, "validated_advantage": False,
              "message": "Sin suficientes temporadas completas para prueba cronológica."}
    if len(seasons) < 3:
        return report, None
    train_rows = [r for r in rows if r["season_year"] < seasons[-2]]
    valid_rows = [r for r in rows if r["season_year"] == seasons[-2]]
    test_rows = [r for r in rows if r["season_year"] == seasons[-1]]
    if min(len(train_rows), len(valid_rows), len(test_rows)) < 100:
        report["message"] = "Se requieren 100+ partidos en cada tramo independiente."
        return report, None
    model = train(train_rows)
    def audit(part):
        pairs = [(infer(model, r), r["y"]) for r in part]
        elo = [(r["elo_probability"], r["y"]) for r in part]
        return {"v3": metrics(pairs), "elo": metrics(elo)}
    report["segments"] = {
        "train": {"seasons": seasons[:-2], "n": len(train_rows)},
        "validation": {"season": seasons[-2], **audit(valid_rows)},
        "test": {"season": seasons[-1], **audit(test_rows)},
    }
    report["status"] = "evaluated_not_published"
    # Test no se usa para ajustar pesos; comparación solo después de entrenar.
    val = report["segments"]["validation"]
    tst = report["segments"]["test"]
    report["validated_advantage"] = (
        val["v3"]["brier"] + .005 < val["elo"]["brier"] and
        tst["v3"]["brier"] + .005 < tst["elo"]["brier"]
    )
    report["message"] = ("V3 supera Elo en evaluación temporal, requiere revisión humana."
                         if report["validated_advantage"] else
                         "No hay evidencia suficiente para reemplazar V2.")
    return report, model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=FOLDER)
    args = parser.parse_args()
    report, model = evaluate(args.data_dir)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    (args.data_dir / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if model is not None:
        (args.data_dir / "candidate.json").write_text(
            json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
