"""Elegir la primera temporada histórica no recuperada completamente."""
import json
from pathlib import Path
from v3_dataset import SEASONS, STORE


def next_season(folder=STORE):
    for season in SEASONS:
        # El 2025-26 se deja como fuente opcional, no requisito básico.
        if season == "2025-26":
            continue
        path = Path(folder) / f"games-{season}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return season
        if data.get("season") != season or data.get("complete") is not True:
            return season
    return "none"


if __name__ == "__main__":
    print(next_season())
