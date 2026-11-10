"""V3 en paralelo: jamás modifica el V2 activo ni retro-inventa picks auditables.

- Retrospectiva: evaluación diagnóstica, NO se cuenta como pronóstico publicado.
- Prospectiva: única estimación V3 congelada ANTES del partido y evaluable luego.
- Cada ejemplo V3 se genera solo con partidos ya finalizados en DÍAS anteriores
  al momento en que se registró la predicción V2 o al momento de cálculo.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from model_v3 import (_form, _sigmoid, build_features, train, infer, metrics,
                      load_seasons, FEATURES)
from v3_dataset import STORE

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "history.json"
CACHE = ROOT / "data" / "events-cache.json"
SHADOW = STORE / "shadow.json"
REQUIRED = {"2022-23", "2023-24", "2024-25", "2025-26"}


def _timestamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Hora sin zona")
    return dt.astimezone(timezone.utc)


def _percent(entry):
    try:
        p = float(entry["home_pct"])
        q = float(entry["away_pct"])
        if math.isfinite(p) and math.isfinite(q) and 0 <= p <= 100 and 0 <= q <= 100 and abs(p+q-100) < .2:
            return p
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return None


def current_final_games(cache):
    rows = []
    for event in cache.get("events", {}).values():
        try:
            if event["status"] != "post" or event["datetime"] < "2026-10-20":
                continue
            h, a = int(event["home_score"]), int(event["away_score"])
            if h < 0 or a < 0 or h == a:
                continue
            when = _timestamp(event["datetime"])
            rows.append({
                "id": str(event["id"]), "date": when.date().isoformat(),
                "datetime": when.isoformat(), "season_year": 2026,
                "home_id": str(event["home"]["id"]), "away_id": str(event["away"]["id"]),
                "home_score": h, "away_score": a,
            })
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return rows


def features_at(events, home, away, cutoff):
    """Foto conservadora: descartar resultados del día UTC del registro."""
    day = _timestamp(cutoff).date()
    earlier = sorted((g for g in events if
                      datetime.fromisoformat(g["datetime"].replace("Z", "+00:00")).date() < day),
                     key=lambda r: (r["datetime"],r["id"]))
    hf, af = _form(str(home), earlier, day), _form(str(away), earlier, day)
    if min(hf["n"], af["n"]) < 4:
        return None
    ratings = {}
    for g in earlier:
        h, a = g["home_id"], g["away_id"]
        eh, ea = ratings.get(h,1500.), ratings.get(a,1500.)
        expected = _sigmoid(math.log(10.)*(eh-ea+55.)/400.)
        y = int(g["home_score"] > g["away_score"])
        delta = 22.*(y-expected)
        ratings[h],ratings[a] = eh+delta,ea-delta
    ehome, eaway = ratings.get(str(home),1500.),ratings.get(str(away),1500.)
    row = {
        "elo_difference": (ehome-eaway)/100.,
        "margin_difference": (hf["margin"]-af["margin"])/10.,
        "win_rate_difference": hf["win"]-af["win"],
        "scoring_difference": (hf["scored"]-af["scored"])/10.,
        "defense_difference": (af["allowed"]-hf["allowed"])/10.,
        "rest_difference": (hf["rest"]-af["rest"])/4.,
    }
    assert set(row) == set(FEATURES)
    return row


def summarize_pairs(entries, field):
    paired = [(e[field]/100., int(e["winner"] == "home")) for e in entries]
    return metrics(paired)


def build_report(history, cache, seasons, previous=None, now=None):
    now = now or datetime.now(timezone.utc)
    all_games = sorted(seasons + current_final_games(cache),
                       key=lambda g: (g["date"],g["datetime"],g["id"]))
    training = build_features(seasons)
    fit = [r for r in training if r["season_year"] in (2022,2023)]
    if len(fit) < 100:
        raise ValueError("No hay datos de entrenamiento suficientes")
    model = train(fit)
    # Incluir también encuentros futuros. Una búsqueda limitada a finales
    # impediría guardar CUALQUIER pronóstico V3 realmente prospectivo.
    games_by_id = {}
    for event in cache.get("events", {}).values():
        try:
            if event["status"] not in ("pre", "in", "post"):
                continue
            games_by_id[str(event["id"])] = {
                "home_id": str(event["home"]["id"]),
                "away_id": str(event["away"]["id"]),
            }
        except (KeyError, TypeError):
            continue
    records = history.get("predictions", {})
    existing = (previous or {}).get("forecasts", {})
    forecast_map = dict(existing) if isinstance(existing,dict) else {}
    retro = []
    for gid, record in records.items():
        try:
            pct = _percent(record)
            cutoff = _timestamp(record["predicted_at"])
            tipoff = _timestamp(record["scheduled_at"])
            game = games_by_id.get(str(gid))
            if pct is None or cutoff >= tipoff or game is None:
                continue
            features = features_at(all_games,game["home_id"],game["away_id"],cutoff)
            if features is None:
                continue
            v3 = round(infer(model,features)*100,1)
            result = record.get("result")
            if isinstance(result,dict) and result.get("winner") in ("home","away"):
                retro.append({"id":gid,"v2_original_home_pct":pct,
                              "v3_retrospective_home_pct":v3,
                              "winner":result["winner"]})
            # Solo nuevos registros prospectivos creados con el partido pendiente.
            # No usar resultados posteriores para una predicción supuestamente antigua.
            if str(gid) not in forecast_map and result is None and now < tipoff:
                live_features = features_at(all_games,game["home_id"],game["away_id"],now.isoformat())
                if live_features is None:
                    continue
                forecast_map[str(gid)] = {
                    "scheduled_at":record["scheduled_at"],
                    "predicted_at":now.isoformat(),
                    "v3_home_pct":round(infer(model,live_features)*100,1),
                    "v2_original_home_pct":pct,
                    "model":"logistic-v3-shadow",
                }
        except (KeyError,TypeError,ValueError,OverflowError):
            continue
    settled=[]
    for gid,f in forecast_map.items():
        record=records.get(gid,{})
        result=record.get("result")
        try:
            if result and result.get("winner") in ("home","away") and (
                _timestamp(f["predicted_at"]) < _timestamp(f["scheduled_at"])):
                settled.append({"id":gid,"winner":result["winner"],
                               "v2_original_home_pct":float(f["v2_original_home_pct"]),
                               "v3_home_pct":float(f["v3_home_pct"])})
        except (KeyError,ValueError,TypeError):
            pass
    return {
        "schema":1,"as_of":now.isoformat(),
        "status":"shadow_not_production","training_seasons":[2022,2023],
        "historical_seasons_loaded":sorted({g["season_year"] for g in seasons}),
        "warning":"La comparación retrospectiva V3 no es un pronóstico registrado antes del partido; "
                  "sirve solo como diagnóstico. La comparación prospectiva incluye únicamente "
                  "pronósticos V3 realmente congelados antes del inicio. ESPN 2026 en caché "
                  "carece de clasificación de temporada confirmada.",
        "retrospective":{"n":len(retro),"v2_original":summarize_pairs(retro,"v2_original_home_pct"),
                         "v3_reconstructed":summarize_pairs(retro,"v3_retrospective_home_pct"),
                         "games":retro},
        "prospective":{"n":len(settled),"v2_original":summarize_pairs(settled,"v2_original_home_pct"),
                       "v3_shadow":summarize_pairs(settled,"v3_home_pct")},
        "forecasts":forecast_map,
    }


def main():
    coverage = {}
    for season in REQUIRED:
        path = STORE/("games-"+season+".json")
        try:
            doc=json.loads(path.read_text(encoding="utf-8"))
            coverage[season] = doc.get("complete") is True
        except (OSError,ValueError):
            coverage[season] = False
    if not all(coverage.values()):
        print("V3 shadow: historial incompleto; sin generar pronósticos.",coverage)
        return
    seasons, check = load_seasons()
    if len(seasons) < 3000:
        print("V3 shadow: 3000 partidos históricos no disponibles")
        return
    history=json.loads(HISTORY.read_text(encoding="utf-8"))
    cache=json.loads(CACHE.read_text(encoding="utf-8"))
    try:
        previous=json.loads(SHADOW.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        previous=None
    report=build_report(history,cache,seasons,previous=previous)
    SHADOW.parent.mkdir(parents=True,exist_ok=True)
    SHADOW.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Comparación V2/V3:",report["retrospective"]["n"],
          "retrospectivos,",report["prospective"]["n"],"prospectivos verificados;" ,
          len(report["forecasts"]),"pronósticos V3 prepartido guardados.")


if __name__ == "__main__":
    main()
