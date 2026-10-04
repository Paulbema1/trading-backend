"""
Calendrier économique historique (USD) construit depuis FRED - RECHERCHE UNIQUEMENT.

Écrit calendar.parquet dans le dossier de données du backtest ; le moteur
(src/backtest/engine.py) le charge déjà tout seul, aucun fichier de src/ n'est modifié.
FRED donne la DATE de publication ; l'heure est celle habituelle (heure de New York,
convertie en UTC en tenant compte de l'heure d'été).
"""
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

API = "https://api.stlouisfed.org/fred"
START = "2019-12-01"

# (nom FRED en minuscules, titre affiché, heure locale New York)
WANTED = [
    ("employment situation", "Non-Farm Payrolls", (8, 30)),
    ("consumer price index", "CPI", (8, 30)),
    ("producer price index", "PPI", (8, 30)),
    ("gross domestic product", "GDP", (8, 30)),
    ("advance monthly sales for retail and food services", "Retail Sales", (8, 30)),
    ("personal income and outlays", "Personal Income and Outlays (PCE)", (8, 30)),
    ("fomc press release", "FOMC", (14, 0)),
]


def _get(path, key, **params):
    params.update({"api_key": key, "file_type": "json"})
    r = requests.get(f"{API}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _all_releases(key):
    out, offset = [], 0
    while True:
        data = _get("releases", key, limit=1000, offset=offset)
        batch = data.get("releases", [])
        out.extend(batch)
        if len(batch) < 1000:
            return out
        offset += 1000


def _release_dates(key, release_id):
    out, offset = [], 0
    while True:
        data = _get("release/dates", key, release_id=release_id, limit=10000,
                    offset=offset, sort_order="asc")
        batch = [d["date"] for d in data.get("release_dates", [])]
        out.extend(batch)
        if len(batch) < 10000:
            return out
        offset += 10000


def build_calendar_parquet(base_dir):
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY manquante (secret GitHub non transmis).")
    ny, utc = ZoneInfo("America/New_York"), ZoneInfo("UTC")
    today = date.today().isoformat()
    releases = _all_releases(key)
    rows = []
    for fragment, title, (hh, mm) in WANTED:
        matches = [r for r in releases if r["name"].lower() == fragment]
        if not matches:
            matches = [r for r in releases if r["name"].lower().startswith(fragment)]
        if not matches:
            print(f"[calendrier] AUCUNE release FRED trouvée pour : {fragment}")
            continue
        for r in matches:
            n = 0
            for d in _release_dates(key, r["id"]):
                if d < START or d > today:
                    continue
                local = datetime.fromisoformat(d).replace(hour=hh, minute=mm, tzinfo=ny)
                rows.append({"datetime": local.astimezone(utc), "currency": "USD",
                             "impact": "High", "title": title})
                n += 1
            print(f"[calendrier] {title} <- FRED #{r['id']} « {r['name']} » : {n} événements")
    if not rows:
        raise RuntimeError("Aucun événement récupéré depuis FRED.")
    df = pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)
    path = Path(base_dir) / "calendar.parquet"
    df.to_parquet(path, index=False)
    print(f"[calendrier] {len(df)} événements écrits dans {path}")
    return path
