"""Vérification minimale : parsing des deux sources sur fixtures réelles + idempotence du store.

    python tests/test_pipeline.py

Les fixtures sont de vraies pages récupérées le 2026-09-01. Si un site change sa structure,
c'est ici que ça casse — pas silencieusement en base.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import store  # noqa: E402
from scrapers import ddproperty, propertyhub, renthub  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def test_ddproperty():
    recs = ddproperty.parse((FIXTURES / "ddproperty_search.html").read_text("utf-8"))
    assert len(recs) >= 15, f"trop peu de cartes trouvées : {len(recs)}"
    for r in recs:
        assert r["source_id"].isdigit(), r["source_id"]
        assert r["url"].startswith("https://www.ddproperty.com/"), r["url"]
        assert 1_000 < r["price_thb"] <= 200_000, r["price_thb"]
        # La recherche est filtrée sur 2 chambres / 2 sdb : la carte doit le confirmer.
        assert r["bedrooms"] == 2 and r["bathrooms"] == 2, r
        assert r["area_sqm"] and r["area_sqm"] > 10, r["area_sqm"]
        assert r["district"], r["address_raw"]
    # La photo de l'annonce, jamais celle de l'agent (`/agent/` sur le même CDN).
    photos = [r["photos"] for r in recs if r["photos"]]
    assert len(photos) >= len(recs) * 0.8, f"{len(photos)}/{len(recs)} annonces avec photo"
    assert all("/listing/" in p for p in photos), photos[:2]
    print(f"ddproperty : {len(recs)} annonces, districts {sorted({r['district'] for r in recs})[:4]}...")


def test_propertyhub():
    recs = propertyhub.parse((FIXTURES / "propertyhub_zone.html").read_text("utf-8"))
    assert len(recs) == 60, f"60 annonces attendues par page de zone, {len(recs)} trouvées"
    for r in recs:
        assert str(r["source_id"]).isdigit()
        assert r["url"].startswith("https://propertyhub.in.th/en/listings/")
        assert isinstance(r["price_thb"], int) and r["price_thb"] > 0, r["price_thb"]
        assert r["bedrooms"] is not None and r["bathrooms"] is not None, r
        assert r["photos"].startswith("https://bcdn.propertyhub.in.th/pictures/"), r["photos"]
    # Le district vient de `project.address` ; il doit être écrit comme chez DDproperty,
    # sinon les médianes par district du §8 comptent deux fois le même quartier.
    districts = {r["district"] for r in recs if r["district"]}
    assert len(districts) >= 5, districts
    assert not any(d.endswith("Bangkok") for d in districts), districts
    print(f"propertyhub : {len(recs)} annonces, {min(r['price_thb'] for r in recs)}–"
          f"{max(r['price_thb'] for r in recs)} THB, districts {sorted(districts)[:3]}...")


def test_renthub():
    recs = renthub.parse((FIXTURES / "renthub_zone.html").read_text("utf-8"))
    assert len(recs) >= 30, f"40 immeubles par page de zone, {len(recs)} parsés"
    for r in recs:
        assert r["url"].startswith("https://www.renthub.in.th/en/"), r["url"]
        assert r["price_thb"] > 0, r["price_thb"]
        assert r["nearest_station"], r
        # La distance à la station est la raison d'être de cette source : elle remplit une
        # colonne que les deux autres laissent vide. Si elle disparaît, le test doit tomber.
        assert isinstance(r["station_distance_m"], int), r["station_distance_m"]

    # Le bail court est l'autre raison d'être : sans lui, activer Renthub n'a pas de sens.
    court = [r for r in recs if r["min_lease_months"]]
    assert court, "aucun bail court trouvé — le champ shortTerm a dû changer de forme"
    assert all(r["min_lease_months"] in (1, 3, 6) for r in court), court[:2]
    # Un immeuble sans bail court doit rester à None, jamais à 12 : l'absence n'est pas une
    # durée, et la confondre ferait trier le classement sur du bruit.
    assert all(r["min_lease_months"] is None for r in recs if r not in court)
    print(f"renthub : {len(recs)} immeubles, {len(court)} à bail court, "
          f"stations {sorted({r['nearest_station'] for r in recs})[:2]}")


def test_renthub_slug_inconnu():
    """Un slug de zone invalide renvoie la page d'accueil, pas une erreur : `listings` y est
    un dict. Le parser doit rendre une liste vide, jamais planter — c'est ce qui avait
    interrompu la passe du 2026-09-04 après 350 pages déjà collectées."""
    accueil = '<script id="__NEXT_DATA__">' + json.dumps(
        {"props": {"pageProps": {"listings": {"highlightListings": [{"id": "1"}]}, "zone": None}}}
    ) + "</script>"
    assert renthub.parse(accueil) == []


def test_propertyhub_page_without_data():
    assert propertyhub.parse("<html>page d'erreur</html>") == []


def test_store_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    rec = {"source_id": "42", "url": "https://x/42", "price_thb": 40000, "bedrooms": 2}

    assert store.upsert(conn, "ddproperty", rec) == "new"
    assert store.upsert(conn, "ddproperty", rec) == "seen"      # rejouer ne duplique pas
    assert store.upsert(conn, "ddproperty", {**rec, "price_thb": 38000}) == "price"
    assert store.upsert(conn, "ddproperty", {**rec, "price_thb": 38000}) == "seen"

    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
    # Un relevé à la première vue, un au changement de prix. Pas un de plus.
    prices = [r[0] for r in conn.execute("SELECT price_thb FROM price_history ORDER BY id")]
    assert prices == [40000, 38000], prices

    # Même source_id chez une autre source = une autre annonce.
    assert store.upsert(conn, "propertyhub", rec) == "new"
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 2
    print("store : upsert idempotent, historique de prix correct")


def test_report_build():
    """La page générée doit contenir un JSON relisable, pas les jetons du gabarit."""
    import json
    import re

    import report

    html, meta, with_photo = report.build()
    assert "__DATA__" not in html and "__META__" not in html, "jeton non remplacé"

    data = json.loads(re.search(r"const DATA = (\[.*?\]);\n", html, re.S).group(1))
    assert len(data) == meta["total"], (len(data), meta["total"])
    assert all(r["price_thb"] and r["url"] for r in data), "annonce sans prix ni URL servie"
    # Un relevé unique n'est pas un historique : `prices` ne doit exister qu'au-delà.
    assert all(len(r["prices"]) > 1 for r in data if "prices" in r)
    assert 0 <= with_photo <= len(data)
    print(f"report : {len(data)} annonces sérialisées, {round(len(html.encode()) / 1024)} Ko")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("\nok")
