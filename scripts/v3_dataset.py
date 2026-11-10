"""V3: extracción histórica NBA (ESPN no oficial), reproducible y reanudable.

Solo guarda marcadores FINALES y juegos de temporada regular/playoffs cuyo
tipo de temporada ESPN esté confirmado. Sin probabilidades retrospectivas.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "v3"
API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
USER_AGENT = "NBAAnalyticsHistoricalStudy/1.0 (GitHub Pages; bounded retrieval)"
SEASONS = {"2022-23": 2022, "2023-24": 2023, "2024-25": 2024, "2025-26": 2025}


def parse_final(raw):
    """Rechazar estado no final, empate, marcador ausente o temporada no verificada."""
    try:
        if raw["status"]["type"]["state"] != "post":
            return None
        season = raw.get("season") or {}
        stage = int(season["type"])
        if stage not in (2, 3):
            return None
        participants = raw["competitions"][0]["competitors"]
        h = next(p for p in participants if p["homeAway"] == "home")
        a = next(p for p in participants if p["homeAway"] == "away")
        hs, aws = int(h["score"]), int(a["score"])
        if not 0 <= hs <= 250 or not 0 <= aws <= 250 or hs == aws:
            return None
        stamp = raw["date"]
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        year = int(season["year"])
        if year < 2000:
            return None
        home, away = str(h["team"]["id"]), str(a["team"]["id"])
        if not home or not away or home == away:
            return None
        return {"id": str(raw["id"]), "datetime": dt.astimezone(timezone.utc).isoformat(),
                "date": dt.date().isoformat(), "season_year": year, "stage": stage,
                "home_id": home, "away_id": away, "home_score": hs, "away_score": aws}
    except (KeyError, ValueError, TypeError, IndexError, StopIteration, OverflowError):
        return None


def season_days(year):
    current, end = date(year, 10, 1), date(year + 1, 6, 30)
    while current <= end:
        yield current
        current += timedelta(days=1)


def get_events(day):
    params = urlencode({"dates": day.strftime("%Y%m%d"), "limit": "100"})
    request = Request(API + "?" + params,
                      headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last = None
    for attempt in range(2):
        try:
            with urlopen(request, timeout=15) as response:
                data = json.load(response)
            if not isinstance(data, dict) or not isinstance(data.get("events"), list):
                raise RuntimeError("ESPN scoreboard malformed")
            return data["events"]
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
            last = exc
            if not attempt:
                time.sleep(1)
    raise RuntimeError(str(last))


def backfill(season, pause=0.25):
    if season not in SEASONS:
        raise ValueError("Temporada no permitida")
    STORE.mkdir(parents=True, exist_ok=True)
    file = STORE / ("games-" + season + ".json")
    try:
        existing = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    if existing.get("season") != season:
        existing = {}
    checked = set(existing.get("checked_dates") or [])
    stored = {g["id"]: g for g in existing.get("games", [])
              if isinstance(g, dict) and g.get("id")}
    failed = []
    for i, day in enumerate(season_days(SEASONS[season])):
        stamp = day.isoformat()
        if stamp in checked:
            continue
        try:
            events = get_events(day)
        except RuntimeError:
            failed.append(stamp)
            continue
        for raw in events:
            row = parse_final(raw)
            if row and row["season_year"] == SEASONS[season]:
                stored[row["id"]] = row
        checked.add(stamp)
        if (i + 1) % 30 == 0:
            print(f"{season}: consultados {len(checked)} días; finales {len(stored)}", flush=True)
        time.sleep(max(0, pause))
    total = len(list(season_days(SEASONS[season])))
    data = {
        "schema": 1, "season": season, "source": "ESPN scoreboard, API no oficial",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "checked_dates": sorted(checked), "failed_dates": failed,
        "complete": len(checked) == total,
        "games": sorted(stored.values(), key=lambda g: (g["datetime"], g["id"])),
    }
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{season}: {len(data['games'])} juegos finales confirmados, "
          f"{len(checked)}/{total} fechas; faltantes {len(failed)}; complete={data['complete']}")
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", choices=list(SEASONS), required=True)
    parser.add_argument("--pause", type=float, default=.25)
    args = parser.parse_args()
    backfill(args.season, args.pause)


if __name__ == "__main__":
    main()
