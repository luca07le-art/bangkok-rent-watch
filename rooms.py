"""Serviced apartments : les logements de 2 chambres et plus des résidences Renthub.

La liste Renthub décrit des immeubles (cf. scrapers/renthub.py) : la fiche donne, par type de
logement, la surface, le loyer et les paliers de bail court. Chaque type de 2 chambres et plus
devient une annonce de la source `renthub-room`, filtrable comme les autres.

Le loyer retenu est celui d'un séjour de 4 mois : le palier 3 mois s'il existe, sinon le loyer
mensuel bas. C'est le prix que paieraient les locataires, pas celui d'un bail d'un an.

Les résidences dont le haut de fourchette n'atteint pas `min_price_thb` n'ont pas de 2 chambres :
inutile d'ouvrir leur fiche. ~250 fiches par semaine, ~15 min.

    py rooms.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
import yaml

import store
from fetch import Fetcher, RobotsDenied
from scrapers.renthub import CDN, NEXT_DATA

ROOT = Path(__file__).parent
SOURCE = "renthub-room"
BEDS = {"TWO": 2, "THREE": 3, "FOUR": 4}
HIGH = re.compile(r"-(\d+) THB/mois")  # haut de fourchette, gardé dans title_raw par le scraper


def parse(html: str, building: dict) -> list[dict]:
    m = NEXT_DATA.search(html)
    listing = json.loads(m.group(1))["props"]["pageProps"].get("listing") if m else None
    if not listing:
        return []
    deposit = ((listing.get("fee") or {}).get("deposit") or {}).get("month")
    out = []
    for room in listing.get("rooms") or []:
        beds = BEDS.get((room.get("roomType") or "").split("_")[0])
        price = room.get("price") or {}
        monthly = (price.get("monthly") or {}).get("minPrice")
        if not beds or not monthly:
            continue
        short = price.get("shortTerm") or {}
        tiers = [(n, short.get(k)) for n, k in ((1, "oneMonth"), (3, "threeMonth"), (6, "sixMonth")) if short.get(k)]
        size = room.get("minSize")
        out.append({
            **building,
            "source_id": f"{listing['id']}-{room['roomType']}-{size}",
            "title_raw": f"{listing.get('name')} — {beds} ch {size} m², bail long {monthly} ฿"
                         + "".join(f", {n} mois {p} ฿" for n, p in tiers),
            "price_thb": short.get("threeMonth") or monthly,
            "bedrooms": beds,
            "bathrooms": None,  # Renthub ne le donne pas par type de logement
            "area_sqm": size,
            "min_lease_months": tiers[0][0] if tiers else None,
            "deposit_months": deposit,
            "description_raw": listing.get("description"),
            "photos": CDN + listing["coverPicture"] if listing.get("coverPicture") else building.get("photos"),
        })
    return out


def todo(conn, cfg: dict) -> list[dict]:
    s = cfg["sources"]["renthub"]
    since = (date.today() - timedelta(days=21)).isoformat()
    rows = conn.execute(
        "SELECT url, project_name, district, address_raw, nearest_station, station_distance_m, photos, "
        "title_raw, price_thb FROM listings WHERE source = 'renthub' AND last_seen >= ? AND price_thb <= ? "
        "ORDER BY last_seen DESC",
        (since, cfg["budget_max_eur"] * cfg["eur_thb_rate"]),
    ).fetchall()
    out = []
    for r in rows:
        m = HIGH.search(r["title_raw"] or "")
        if (int(m.group(1)) if m else r["price_thb"]) >= s["rooms_min_price_thb"]:
            out.append({k: r[k] for k in ("url", "project_name", "district", "address_raw",
                                          "nearest_station", "station_distance_m", "photos")})
    return out[: s["rooms_max_per_run"]]


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
    fetcher = Fetcher(cfg, ROOT / "data" / "cache")
    conn = store.connect(ROOT / "data" / "listings.db")
    pending = todo(conn, cfg)
    print(f"\n=== résidences Renthub : {len(pending)} fiches à lire")
    tally: dict[str, int] = {}
    for building in pending:
        try:
            recs = parse(fetcher.get(building["url"], keep=False), building)
        except RobotsDenied:
            print("  robots.txt interdit les fiches — arrêt")
            break
        except requests.HTTPError:
            continue  # résidence retirée
        except Exception as exc:
            print(f"  échec {building['url']} : {exc}")
            continue
        for rec in recs:
            rec["price_eur"] = round(rec["price_thb"] / cfg["eur_thb_rate"])
            outcome = store.upsert(conn, SOURCE, rec)
            tally[outcome] = tally.get(outcome, 0) + 1
        conn.commit()
    print(f"logements 2 ch+ : {tally}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
