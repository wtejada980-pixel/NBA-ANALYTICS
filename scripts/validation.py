"""Métricas auditables de pronósticos guardados antes del salto inicial."""
from __future__ import annotations
import math


def evaluate(predictions):
    """Brier binario (0-1), aciertos del favorito y confiabilidad por intervalos."""
    valid = []
    for record in predictions.values():
        result = record.get("result")
        if not isinstance(result, dict) or result.get("winner") not in ("home", "away"):
            continue
        try:
            p = float(record["home_pct"]) / 100.0
            if not math.isfinite(p) or not 0.0 <= p <= 1.0:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        y = 1.0 if result["winner"] == "home" else 0.0
        valid.append((p, y, record.get("model", "sin versión")))
    n = len(valid)
    empty = {"completed_predictions": 0, "brier_score": None,
             "baseline_50_brier": None, "favorite_accuracy_pct": None,
             "log_loss": None, "calibration": [], "sample_warning": "Sin resultados suficientes",
             "by_model": {}}
    if not n:
        return empty

    def brier(rows):
        return round(sum((p-y)**2 for p,y,*_ in rows)/len(rows), 4)

    bins = []
    for lo in (0, 20, 40, 60, 80):
        rows = [(p, y) for p,y,_ in valid if lo <= p*100 < lo+20 or (lo == 80 and p == 1)]
        if not rows:
            continue
        bins.append({"range": f"{lo}-{lo+20}%",
                     "count": len(rows),
                     "average_predicted_pct": round(100*sum(p for p,_ in rows)/len(rows), 1),
                     "actual_home_win_pct": round(100*sum(y for _,y in rows)/len(rows), 1)})
    groups = {}
    for p, y, model in valid:
        groups.setdefault(str(model), []).append((p,y))
    by_model = {key: {"n": len(rows), "brier": brier(rows)}
                for key, rows in sorted(groups.items())}
    accuracy = sum((p>=.5) == bool(y) for p,y,_ in valid) / n
    log_loss = -sum(y*math.log(max(1e-9,p)) +
                    (1-y)*math.log(max(1e-9,1-p)) for p,y,_ in valid)/n
    return {
        "completed_predictions": n,
        "brier_score": brier(valid),
        "baseline_50_brier": 0.25,
        "favorite_accuracy_pct": round(accuracy*100, 1),
        "log_loss": round(log_loss, 4),
        "calibration": bins,
        "by_model": by_model,
        "sample_warning": ("Muestra pequeña: no permite demostrar calibración."
                           if n < 50 else "Comparar con referencia; Brier no demuestra calibración por sí solo.")
    }
