"""Orchestrateur. Une passe = chaque source active, page par page, dans listings.db.

Phase 1 : on collecte et on historise les prix. Ni dédup, ni scoring, ni rapport — ils seront
écrits en février 2027 contre des données réelles (cf. docs/phase0-faisabilite.md).
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

import store
from fetch import Fetcher, RobotsDenied
from scrapers import ddproperty, propertyhub

ROOT = Path(__file__).parent
SCRAPERS = {"ddproperty": ddproperty, "propertyhub": propertyhub}


def run_source(name: str, scraper, cfg: dict, fetcher: Fetcher, conn) -> Counter:
    tally = Counter()
    for url in scraper.urls(cfg):
        try:
            html = fetcher.get(url)
        except RobotsDenied:
            print(f"  robots.txt interdit {url} — source arrêtée")
            break
        except Exception as exc:  # réseau, 429 persistant, page absente
            print(f"  échec {url} : {exc}")
            tally["erreur"] += 1
            continue

        records = scraper.parse(html)
        if not records:
            print(f"  0 annonce sur {url} — fin de pagination ou zone inconnue")
            tally["vide"] += 1
            continue

        for rec in records:
            if rec.get("price_thb"):
                rec["price_eur"] = round(rec["price_thb"] / cfg["eur_thb_rate"])
            tally[store.upsert(conn, name, rec)] += 1
        conn.commit()  # une page = une transaction : une interruption ne perd qu'une page
        print(f"  {url.rsplit('/', 1)[-1][:60]} : {len(records)} annonces")
    return tally


def main() -> int:
    print(f"\n===== passe du {datetime.now():%Y-%m-%d %H:%M} =====")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
    fetcher = Fetcher(cfg, ROOT / "data" / "cache")
    conn = store.connect(ROOT / "data" / "listings.db")

    total = Counter()
    for name, scraper in SCRAPERS.items():
        if not cfg["sources"].get(name, {}).get("enabled"):
            continue
        print(f"\n=== {name}")
        total.update(run_source(name, scraper, cfg, fetcher, conn))

    print(
        f"\n{total['new']} nouvelles, {total['price']} changements de prix, "
        f"{total['seen']} inchangées, {total['erreur']} erreurs"
    )
    rows = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    prices = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    print(f"base : {rows} annonces, {prices} relevés de prix")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
