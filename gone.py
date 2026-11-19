"""Annonces louées : revérifie chaque semaine la fiche PropertyHub des annonces de la shortlist.

Une fiche qui ne sert plus l'annonce (PropertyHub redirige vers le projet ou l'accueil) : louée ou
retirée, `gone_on` reçoit la date. Le rapport l'affiche « louée » et ne la montre plus qu'en favori.
Une annonce revue ensuite dans un crawl redevient disponible (store.upsert efface gone_on).

Shortlist = ce qu'on mettrait en favori : 2 ch / 2 sdb, ≥ area_min_sqm, dans le budget, vue depuis
6 semaines, immeuble haut de gamme (standing ≥ standing_min) ou récent. ~260 fiches, ~15 min.
Les résidences Renthub sont vérifiées par rooms.py, qui lit déjà leur fiche chaque semaine.
DDproperty ne l'est pas : ses fiches répondent 403 à tout client hors navigateur.

    py gone.py
"""
from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests
import yaml

import details
import projects
import store
from fetch import Fetcher, RobotsDenied

ROOT = Path(__file__).parent


def standing(conn) -> dict[tuple, float]:
    """€/m² médian de l'immeuble ÷ celui de son quartier, comme STANDING dans report.html."""
    by_district, by_building = defaultdict(list), defaultdict(list)
    for district, name, eur, area in conn.execute(
        "SELECT district, COALESCE(project_name, title_raw), price_eur, area_sqm FROM listings "
        "WHERE area_sqm > 0 AND price_eur > 0 AND district IS NOT NULL"
    ):
        by_district[district].append(eur / area)
        if name:
            by_building[(district, name.strip().lower())].append(eur / area)
    med = {d: statistics.median(v) for d, v in by_district.items() if len(v) >= 10}
    return {k: statistics.median(v) / med[k[0]] for k, v in by_building.items() if len(v) >= 3 and k[0] in med}


def todo(conn, cfg: dict) -> list[tuple[int, str]]:
    stand = standing(conn)
    years = {k: y for k, y in conn.execute("SELECT name_key, completed_year FROM projects") if y}
    recent = date.today().year - cfg["recent_max_age_years"]
    rows = conn.execute(
        "SELECT id, url, district, COALESCE(project_name, title_raw) FROM listings "
        "WHERE source = 'propertyhub' AND gone_on IS NULL AND description_raw IS NOT NULL "
        "AND bedrooms >= ? AND bathrooms >= ? AND area_sqm >= ? AND price_thb <= ? AND last_seen >= ?",
        (cfg["bedrooms_min"], cfg["bathrooms_min"], cfg["area_min_sqm"],
         cfg["budget_max_eur"] * cfg["eur_thb_rate"], (date.today() - timedelta(weeks=6)).isoformat()),
    )
    return [
        (lid, url) for lid, url, district, name in rows
        if stand.get((district, (name or "").strip().lower()), 0) >= cfg["standing_min"]
        or years.get(projects.key(name or ""), 0) >= recent
    ]


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
    fetcher = Fetcher(cfg, ROOT / "data" / "cache")
    conn = store.connect(ROOT / "data" / "listings.db")
    pending = todo(conn, cfg)
    print(f"\n=== shortlist : {len(pending)} fiches à revérifier")
    gone = 0
    for lid, url in pending:
        try:
            alive = details.parse(fetcher.get(url, keep=False)) is not None
        except RobotsDenied:
            print("  robots.txt interdit les fiches — arrêt")
            break
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in (404, 410):
                continue  # erreur passagère : rien ne prouve que l'annonce a disparu
            alive = False
        except Exception as exc:
            print(f"  échec {url} : {exc}")
            continue
        if not alive:
            conn.execute("UPDATE listings SET gone_on = ? WHERE id = ?", (date.today().isoformat(), lid))
            conn.commit()
            gone += 1
    print(f"{gone} annonces louées ou retirées")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
