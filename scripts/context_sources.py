"""Complementos del reporte diario: noticias, bajas y conversaciones públicas.

Los artículos y opiniones NO modifican la probabilidad numérica del modelo.
Reddit requiere credenciales OAuth autorizadas y se omite si no están disponibles.
Todas las fuentes opcionales fallan de manera segura sin bloquear partidos.
"""
from __future__ import annotations
import base64
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
NBA_REPORT = "https://official.nba.com/nba-injury-report-2026-27-season/"
UA = "NBAAnalyticsDaily/2.0 (personal noncommercial research; no trading)"
STATUS = {
    "out": "Fuera", "doubtful": "Dudoso", "questionable": "Cuestionable",
    "probable": "Probable", "day-to-day": "Día a día", "active": "Disponible"
}

def request_bytes(url, headers=None, data=None, timeout=9):
    h = {"User-Agent": UA, "Accept": "application/json, application/atom+xml, application/rss+xml, */*"}
    h.update(headers or {})
    req = Request(url, headers=h, data=data)
    with urlopen(req, timeout=timeout) as response:
        return response.read(600_000)

def injuries_for_team(tid, request=request_bytes):
    """Extrae datos publicados; ausencia de entradas NO equivale a sano."""
    try:
        import json
        data = json.loads(request(f"{ESPN}/teams/{quote(str(tid), safe='')}/injuries"))
        entries = data.get("injuries") or []
        out = []
        if isinstance(entries, dict):
            entries = [entries]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            athlete = entry.get("athlete") or {}
            if not isinstance(athlete, dict):
                continue
            info = entry.get("details") or {}
            injury = entry.get("injuries") or []
            if isinstance(injury, list) and injury and isinstance(injury[0], dict):
                info = injury[0]
            if not isinstance(info, dict):
                info = {}
            status = (info.get("status") or entry.get("status") or entry.get("type") or "")
            if isinstance(status, dict):
                status = status.get("name") or status.get("description") or ""
            status = str(status).strip()
            if not status:
                continue
            nm = athlete.get("displayName") or athlete.get("fullName")
            if not nm:
                continue
            reason = info.get("detail") or info.get("description") or ""
            out.append({"player": str(nm), "status": STATUS.get(status.lower(), status),
                        "reason": str(reason)[:150], "source": f"https://www.espn.com/nba/team/injuries/_/name/{tid}"})
        return out[:12], "ESPN (consulta complementaria)"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError):
        return [], "No verificado"

def feed_titles(xml_bytes, max_items=4):
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    result = []
    for item in root.findall(".//item")[:max_items]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        if title and link.startswith("https://"):
            result.append({"title": title[:160], "url": link, "published": published})
    return result

def news_for_game(game, request=request_bytes):
    teams = [game["away"]["name"], game["home"]["name"]]
    query = f'"{teams[0]}" "{teams[1]}" NBA when:2d'
    url = "https://news.google.com/rss/search?" + urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    try:
        return feed_titles(request(url), 4)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return []

def reddit_token(request=request_bytes):
    """Acceso API solo si el usuario autorizó la aplicación y puso secretos en GitHub."""
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    if not (client_id and secret):
        return ""
    import json
    encoded = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    payload = urlencode({"grant_type": "client_credentials"}).encode()
    try:
        raw = request("https://www.reddit.com/api/v1/access_token",
                      {"Authorization": "Basic " + encoded,
                       "Content-Type": "application/x-www-form-urlencoded",
                       "User-Agent": os.getenv("REDDIT_USER_AGENT", UA)},
                      data=payload, timeout=10)
        return json.loads(raw).get("access_token", "")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError):
        return ""

def forum_for_game(game, token, request=request_bytes):
    away = game["away"].get("name", "").split()[-1]
    home = game["home"].get("name", "").split()[-1]
    term = away + " " + home
    link = "https://www.reddit.com/r/nba/search/?" + urlencode({"q": term, "restrict_sr": "1", "sort": "new", "t": "day"})
    result = {"status": "No conectado", "discussion_url": link, "posts": [], "count": 0}
    if not token:
        return result
    query = {"q": f"{away} {home}", "restrict_sr": "1", "sort": "new", "t": "day", "limit": "12"}
    url = "https://oauth.reddit.com/r/nba/search?" + urlencode(query)
    try:
        import json
        raw = request(url, {"Authorization": "Bearer " + token,
                            "User-Agent": os.getenv("REDDIT_USER_AGENT", UA)})
        data = json.loads(raw)
        posts = []
        for child in data.get("data", {}).get("children", []):
            p = child.get("data") or {}
            title = str(p.get("title") or "").strip()
            path = str(p.get("permalink") or "")
            if not title or not path.startswith("/r/"):
                continue
            # No guardar nombres de autores, cuerpos ni comentarios de Reddit.
            posts.append({"title": title[:140], "url": "https://www.reddit.com" + path})
            if len(posts) >= 4:
                break
        result.update({"status": "Recopilado", "posts": posts, "count": len(posts)})
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError):
        result["status"] = "No disponible"
    return result

def collect(games, teams, get_injuries=injuries_for_team, get_news=news_for_game,
            get_forum=forum_for_game, get_token=reddit_token):
    """Obtener contexto UNA vez por equipo y partido. Sin inventar ausencias."""
    injury_cache = {}
    token = get_token()
    for game in games:
        if game.get("status") != "pre":
            continue
        for side in ("home", "away"):
            tid = game[side]["id"]
            if tid not in injury_cache:
                injury_cache[tid] = get_injuries(tid)
        game["context"] = {
            "injuries": {side: {"items": injury_cache[game[side]["id"]][0],
                                  "source": injury_cache[game[side]["id"]][1]}
                         for side in ("home", "away")},
            "official_injury_report": NBA_REPORT,
            "news": get_news(game),
            "forum": get_forum(game, token),
            "analysis_notes": [
                "Noticias y foros son contexto, no una encuesta representativa.",
                "Las lesiones se muestran como reportes; deben confirmarse cerca del salto inicial.",
                "El modelo numérico aún NO ajusta por lesiones ni opiniones, para evitar certeza falsa."
            ],
            "context_updated_at": datetime.now(timezone.utc).isoformat()
        }
    return games
