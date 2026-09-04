"""SQLite : schéma §6, upsert idempotent, historique de prix.

L'historique de prix est la seule chose irrécupérable du projet — les prix de septembre 2026
ne se rattraperont pas en mars 2027. C'est le seul rôle de ce module en phase 1.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id                  INTEGER PRIMARY KEY,
    source              TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    url                 TEXT,
    first_seen          DATE,
    last_seen           DATE,
    is_active           BOOLEAN DEFAULT 1,

    project_name        TEXT,
    project_name_norm   TEXT,
    district            TEXT,
    address_raw         TEXT,
    lat                 REAL,
    lng                 REAL,
    nearest_station     TEXT,
    station_distance_m  INTEGER,

    price_thb           INTEGER,
    price_eur           INTEGER,
    bedrooms            INTEGER,
    bathrooms           INTEGER,
    area_sqm            REAL,
    floor               INTEGER,
    furnished           TEXT,
    min_lease_months    INTEGER,
    deposit_months      REAL,

    agent_name          TEXT,
    agent_contact       TEXT,
    title_raw           TEXT,
    description_raw     TEXT,
    lang                TEXT,
    photos              TEXT,

    dedup_group_id      INTEGER REFERENCES dedup_groups(id),
    score               REAL,
    scraped_at          TIMESTAMP,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY,
    listing_id  INTEGER NOT NULL REFERENCES listings(id),
    price_thb   INTEGER NOT NULL,
    observed_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS dedup_groups (
    id                   INTEGER PRIMARY KEY,
    canonical_listing_id INTEGER REFERENCES listings(id),
    created_at           TIMESTAMP,
    match_confidence     REAL
);

CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history(listing_id);
CREATE INDEX IF NOT EXISTS idx_listings_segment ON listings(bedrooms, district);
"""

# Colonnes qu'un scraper a le droit de remplir. Tout le reste est calculé plus tard.
FIELDS = (
    "url project_name district address_raw lat lng nearest_station station_distance_m "
    "price_thb price_eur bedrooms bathrooms area_sqm floor furnished min_lease_months "
    "deposit_months agent_name agent_contact title_raw description_raw lang photos"
).split()


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, source: str, rec: dict) -> str:
    """Insère ou met à jour une annonce. Renvoie 'new', 'price' ou 'seen'.

    Une ligne de price_history est écrite à la première vue puis à chaque changement de prix.
    Ré-exécuter la même passe deux fois ne crée ni doublon ni fausse variation (§12).
    """
    now, today = datetime.now().isoformat(timespec="seconds"), date.today().isoformat()
    sid = str(rec["source_id"])
    row = conn.execute(
        "SELECT id, price_thb FROM listings WHERE source = ? AND source_id = ?", (source, sid)
    ).fetchone()

    values = {k: rec.get(k) for k in FIELDS}

    if row is None:
        cols = ["source", "source_id", "first_seen", "last_seen", "scraped_at", *FIELDS]
        conn.execute(
            f"INSERT INTO listings ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [source, sid, today, today, now, *values.values()],
        )
        listing_id, outcome = conn.execute("SELECT last_insert_rowid()").fetchone()[0], "new"
    else:
        listing_id = row["id"]
        assignments = ", ".join(f"{k} = ?" for k in FIELDS)
        conn.execute(
            f"UPDATE listings SET {assignments}, last_seen = ?, scraped_at = ?, is_active = 1 "
            "WHERE id = ?",
            [*values.values(), today, now, listing_id],
        )
        outcome = "price" if row["price_thb"] != rec.get("price_thb") else "seen"

    if outcome in ("new", "price") and rec.get("price_thb") is not None:
        conn.execute(
            "INSERT INTO price_history (listing_id, price_thb, observed_at) VALUES (?, ?, ?)",
            (listing_id, rec["price_thb"], now),
        )
    return outcome


# ponytail: is_active reste à 1. La règle « absente de 3 crawls consécutifs » du §6 suppose
# un crawl exhaustif — or PropertyHub ne rend que la page 1 de chaque zone, donc une absence
# n'y prouve rien. À implémenter quand la pagination PropertyHub sera résolue, ou seulement
# pour les sources exhaustives.
