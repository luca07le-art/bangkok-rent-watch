"""Fiche annonce PropertyHub : description, bail court, caution, station la plus proche.

La page liste ne sert rien de tout cela (cf. scrapers/propertyhub.py) : une requête par annonce,
une seule fois. Seulement le segment utile (2 ch / 2 sdb, dans le budget, vue récemment), sinon
la première passe coûterait 23 000 requêtes.

Bail court = PropertyHub publie un prix par palier (`monthly1/3/6`) quand le bailleur l'accepte.
`min_lease_months` reçoit le plus petit palier proposé ; c'est ce que filtre « Bail court » du rapport.

    py details.py
"""
from __future__ import annotations

import json

import sys
from datetime import date, timedelta
from pathlib import Path

import requests
import yaml

import store
from fetch import Fetcher, RobotsDenied
from scrapers.propertyhub import NEXT_DATA

ROOT = Path(__file__).parent


def parse(html: str) -> dict | None:
    m = NEXT_DATA.search(html)
    listing = json.loads(m.group(1))["props"]["pageProps"].get("listing") if m else None
    if not listing:
        return None  # annonce retirée : PropertyHub redirige vers le projet ou l'accueil
    rent = (listing.get("price") or {}).get("forRent") or {}
    tiers = [n for n in (1, 3, 6) if (rent.get(f"monthly{n}") or {}).get("price")]
    deposit = (rent.get("deposit") or {}).get("month")
    transit = ((listing.get("nearbyZones") or {}).get("MASS_TRANSIT") or [{}])[0]
    return {
        "description_raw": listing.get("detail") or "",  # "" = fiche lue, pas de texte : ne pas relire
        "min_lease_months": tiers[0] if tiers else None,
        "deposit_months": deposit,
        "nearest_station": transit.get("name"),
        "station_distance_m": transit.get("distance"),
    }


def todo(conn, cfg: dict) -> list[tuple[int, str]]:
    budget = cfg["budget_max_eur"] * cfg["eur_thb_rate"]
    since = (date.today() - timedelta(days=21)).isoformat()
    return conn.execute(
        "SELECT id, url FROM listings WHERE source = 'propertyhub' AND description_raw IS NULL "
        "AND bedrooms >= ? AND bathrooms >= ? AND price_thb <= ? AND last_seen >= ? "
        "ORDER BY last_seen DESC LIMIT ?",
        (cfg["bedrooms_min"], cfg["bathrooms_min"], budget, since,
         cfg["sources"]["propertyhub"]["details_max_per_run"]),
    ).fetchall()


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
    fetcher = Fetcher(cfg, ROOT / "data" / "cache")
    conn = store.connect(ROOT / "data" / "listings.db")  # crée gone_on sur les bases anciennes
    pending = todo(conn, cfg)
    print(f"\n=== fiches PropertyHub : {len(pending)} à lire")
    short = gone = 0
    for i, (lid, url) in enumerate(pending, 1):
        try:
            d = parse(fetcher.get(url, keep=False))
        except RobotsDenied:
            print("  robots.txt interdit les fiches — arrêt")
            break
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in (404, 410):
                continue  # erreur passagère : retentée la semaine suivante
            d = None
        except Exception as exc:  # réseau : retentée la semaine suivante
            print(f"  échec {url} : {exc}")
            continue
        if d is None:
            gone += 1
            # Marquée lue pour ne pas la redemander, et disparue : c'est « loué » dans le rapport.
            d = {"description_raw": "", "gone_on": date.today().isoformat()}
        conn.execute(
            f"UPDATE listings SET {', '.join(f'{k} = ?' for k in d)} WHERE id = ?", [*d.values(), lid]
        )
        conn.commit()
        short += bool(d.get("min_lease_months"))
        if i % 100 == 0:
            print(f"  {i}/{len(pending)} — {short} bails courts")
    print(f"{short} bails courts, {gone} annonces retirées")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
