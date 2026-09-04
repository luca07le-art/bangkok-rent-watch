"""Génère index.html : le gabarit report.html avec les annonces injectées.

Un seul fichier autonome, sans serveur ni base côté lecteur — 3600 annonces tiennent en ~1 Mo,
et GitHub Pages le sert gzippé. Aucun moteur de template : un `.replace()` suffit pour une page,
et le gabarit reste un vrai fichier .html éditable.

    py report.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).parent

# Les colonnes servies au navigateur. `min_lease_months` et `station_distance_m` ne sont
# remplies que par Renthub : nulles ailleurs, et c'est justement ce qui les rend utiles.
# Restent à 0 % — donc absentes d'ici — lat/lng, meublé, dépôt, agent et description :
# elles n'existent que sur les fiches annonces, une requête par annonce (phase 2).
QUERY = """
SELECT l.id, l.url, l.source, l.district, l.first_seen, l.last_seen,
       l.price_thb, l.price_eur, l.bedrooms, l.bathrooms, l.area_sqm, l.floor, l.photos,
       l.min_lease_months, l.nearest_station, l.station_distance_m,
       COALESCE(l.project_name, l.title_raw) AS name
FROM listings l
WHERE l.price_thb IS NOT NULL
"""


def build() -> tuple[str, dict, int]:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
    conn = sqlite3.connect(ROOT / "data" / "listings.db")
    conn.row_factory = sqlite3.Row

    # Un seul balayage de l'historique plutôt qu'une requête par annonce.
    history: dict[int, list] = {}
    for lid, price, obs in conn.execute(
        "SELECT listing_id, price_thb, observed_at FROM price_history ORDER BY listing_id, id"
    ):
        history.setdefault(lid, []).append([obs[:10], price])

    listings = []
    for row in conn.execute(QUERY):
        rec = {k: v for k, v in dict(row).items() if v is not None and k != "id"}
        prices = history.get(row["id"], [])
        if len(prices) > 1:  # un seul relevé n'est pas un historique : on ne l'envoie pas
            rec["prices"] = prices
        listings.append(rec)

    span = conn.execute("SELECT MIN(first_seen), MAX(last_seen) FROM listings").fetchone()
    conn.close()

    meta = {
        "total": len(listings),
        "first": span[0],
        "last": span[1],
        "generated": date.today().isoformat(),
        "rate": cfg["eur_thb_rate"],
        # Les curseurs démarrent sur les critères réels du config, pas sur des valeurs
        # arbitraires. Le budget est en euros — la devise dans laquelle le loyer est payé —
        # et `rate` sert à afficher l'équivalent en bahts sous le curseur.
        "budget_max_eur": cfg["budget_max_eur"],
        "area_min": cfg["area_min_sqm"],
    }
    html = (ROOT / "report.html").read_text("utf-8")
    for token, value in (("__DATA__", listings), ("__META__", meta)):
        if token not in html:
            raise SystemExit(f"gabarit report.html : jeton {token} introuvable")
        html = html.replace(token, json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return html, meta, sum(1 for r in listings if r.get("photos"))


def main() -> int:
    html, meta, with_photo = build()
    out = ROOT / "index.html"
    out.write_text(html, "utf-8")
    print(
        f"{out.name} : {meta['total']} annonces, {with_photo} avec photo, "
        f"{round(len(html.encode()) / 1024)} Ko"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
