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
            # Las predicciones posteriores al salto inicial nunca se evalúan.
            if record.get("predicted_at") and record.get("scheduled_at"):
                from datetime import datetime
                start = datetime.fromisoformat(record["scheduled_at"].replace("Z", "+00:00"))
                forecast = datetime.fromisoformat(record["predicted_at"].replace("Z", "+00:00"))
                if forecast >= start:
                    continue
            p = float(record["home_pct"]) / 100.0
            if not math.isfinite(p) or not 0.0 <= p <= 1.0:
                continue
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
        y = 1.0 if result["winner"] == "home" else 0.0
        valid.append((p, y, record.get("model", "sin versión")))
    n = len(valid)
    empty = {"completed_predictions": 0, "brier_score": None,
             "baseline_50_brier": None, "favorite_accuracy_pct": None,
             "log_loss": None, "calibration": [], "calibration_by_model": {},
             "sample_warning": "Sin resultados suficientes", "by_model": {},
             "history_by_model": {},
             "elo_comparison": {"n": 0, "model_brier": None, "elo_brier": None},
             "elo_comparison_by_model": {}}
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
    # Rendimiento por versión: para cada partido se considera el pronóstico
    # original y la última revisión prepartido de cada versión distinta.
    model_rows = {}
    history_by_model = {}
    paired_by_model = {}
    for record in predictions.values():
        result = record.get("result")
        if not isinstance(result, dict) or result.get("winner") not in ("home", "away"):
            continue
        y = 1.0 if result["winner"] == "home" else 0.0
        candidates = []
        try:
            original_model = str(record.get("model", "sin versión"))
            original_p = float(record["home_pct"]) / 100.0
            original_at = record.get("predicted_at")
            scheduled_at = record.get("scheduled_at")
            from datetime import datetime
            start = (datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
                     if scheduled_at else None)
            if not math.isfinite(original_p) or not 0 <= original_p <= 1:
                continue
            if original_at and start:
                forecast = datetime.fromisoformat(original_at.replace("Z", "+00:00"))
                if forecast >= start:
                    continue
            candidates.append((original_model, original_p, original_at or ""))
            # Para cada versión, escoger solo su pronóstico prepartido más reciente.
            revisions = {}
            for entry in record.get("revisions", []):
                if not isinstance(entry, dict):
                    continue
                model = str(entry.get("model") or original_model)
                stamp = str(entry.get("predicted_at") or "")
                p = float(entry["home_pct"]) / 100.0
                if not stamp or not math.isfinite(p) or not 0 <= p <= 1:
                    continue
                if scheduled_at and datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= start:
                    continue
                if model not in revisions or stamp > revisions[model][1]:
                    revisions[model] = (p, stamp, entry.get("elo_baseline_home_pct"))
            for model, (p, stamp, baseline) in revisions.items():
                if model == original_model:
                    candidates = [row for row in candidates if row[0] != model]
                candidates.append((model, p, stamp))
                if baseline is None and model == original_model:
                    baseline = record.get("elo_baseline_home_pct")
                if baseline is not None:
                    q = float(baseline) / 100.0
                    if math.isfinite(q) and 0 <= q <= 1:
                        paired_by_model.setdefault(model, []).append((p, q, y))
            if original_model not in revisions and record.get("elo_baseline_home_pct") is not None:
                q = float(record["elo_baseline_home_pct"]) / 100.0
                if math.isfinite(q) and 0 <= q <= 1:
                    paired_by_model.setdefault(original_model, []).append((original_p, q, y))
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
        for model, p, stamp in candidates:
            model_rows.setdefault(model, []).append((p, y))
            history_by_model.setdefault(model, []).append({
                "scheduled_at": str(record.get("scheduled_at") or ""),
                "predicted_at": str(stamp or ""),
                "home_pct": round(p * 100, 1),
                "winner": result["winner"],
            })

    def calibration_for(rows):
        bins = []
        for lo in (0, 20, 40, 60, 80):
            chunk = [(p, y) for p, y in rows
                     if lo <= p*100 < lo+20 or (lo == 80 and p == 1)]
            if chunk:
                bins.append({"range": f"{lo}-{lo+20}%", "count": len(chunk),
                             "average_predicted_pct": round(100*sum(p for p,_ in chunk)/len(chunk), 1),
                             "actual_home_win_pct": round(100*sum(y for _,y in chunk)/len(chunk), 1)})
        return bins

    by_model, calibration_by_model = {}, {}
    for model, rows in sorted(model_rows.items()):
        by_model[model] = {
            "n": len(rows), "brier": brier(rows),
            "log_loss": round(-sum(y*math.log(max(1e-9,p)) +
                                   (1-y)*math.log(max(1e-9,1-p))
                                   for p,y in rows)/len(rows), 4),
            "favorite_accuracy_pct": round(100*sum((p>=.5)==bool(y) for p,y in rows)/len(rows), 1)
        }
        calibration_by_model[model] = calibration_for(rows)
    for rows in history_by_model.values():
        rows.sort(key=lambda item: item["scheduled_at"])
    elo_comparison_by_model = {
        model: {"n": len(rows),
                "model_brier": round(sum((p-y)**2 for p,_,y in rows)/len(rows), 4),
                "elo_brier": round(sum((q-y)**2 for _,q,y in rows)/len(rows), 4)}
        for model, rows in paired_by_model.items() if rows
    }

    # Comparación justa: exactamente los mismos partidos y pronósticos guardados
    # antes del inicio, nunca recalculados después del resultado.
    paired = []
    for record in predictions.values():
        result = record.get("result")
        if not isinstance(result, dict) or result.get("winner") not in ("home", "away"):
            continue
        if record.get("elo_baseline_home_pct") is None:
            continue
        try:
            if record.get("predicted_at") and record.get("scheduled_at"):
                from datetime import datetime
                if datetime.fromisoformat(record["predicted_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(record["scheduled_at"].replace("Z", "+00:00")):
                    continue
            main = float(record["home_pct"]) / 100
            elo = float(record["elo_baseline_home_pct"]) / 100
            if not math.isfinite(main) or not math.isfinite(elo) or not (0 <= main <= 1 and 0 <= elo <= 1):
                continue
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
        y = 1 if result["winner"] == "home" else 0
        paired.append((main, elo, y))
    comparison = {
        "n": len(paired),
        "model_brier": round(sum((p-y)**2 for p,_,y in paired)/len(paired), 4) if paired else None,
        "elo_brier": round(sum((q-y)**2 for _,q,y in paired)/len(paired), 4) if paired else None
    }
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
        "calibration_by_model": calibration_by_model,
        "by_model": by_model,
        "history_by_model": history_by_model,
        "elo_comparison": comparison,
        "elo_comparison_by_model": elo_comparison_by_model,
        "sample_warning": ("Muestra pequeña: no permite demostrar calibración."
                           if n < 50 else "Comparar con referencia; Brier no demuestra calibración por sí solo.")
    }
