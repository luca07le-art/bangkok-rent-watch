"""Année d'achèvement, piscine et salle de sport des immeubles, lues sur la page projet
PropertyHub (`completedYear`, `facilities.pool`, `facilities.fitness`).

Une requête par immeuble, une seule fois : rien de tout cela ne change, un immeuble déjà tenté n'est
plus jamais redemandé — même introuvable. La première passe coûte ~1700 requêtes (~1 h 40),
les suivantes quelques-unes, pour les immeubles apparus dans la semaine.

Le nom d'immeuble est la clé commune aux sources. PropertyHub donne le slug de sa page ;
pour un immeuble vu seulement sur DDproperty, on le déduit du nom, comme PropertyHub le fait
(« Venio Sukhumvit 10 » -> venio-sukhumvit-10). Raté = année inconnue, rien de plus.

    py projects.py
"""
from __future__ import annotations

import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import requests
import yaml

from fetch import Fetcher, RobotsDenied

ROOT = Path(__file__).parent
PAGE = "https://propertyhub.in.th/en/projects/"
# Dans le payload Next.js la clé est échappée : completedYear\":\"2018\"
YEAR = re.compile(r'completedYear\\?"\s*:\s*\\?"(\d{4})')
# Bloc `facilities` : une trentaine de booléens (pool, fitness, sauna, allowPet…).
FACILITY = r'\\?"{}\\?"\s*:\s*(true|false)'

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    name_key        TEXT PRIMARY KEY,   -- lower(trim(nom)), comme report.html
    slug            TEXT,
    completed_year  INTEGER,            -- NULL = page introuvable ou année absente
    pool            INTEGER,            -- 1/0, NULL = inconnu
    fitness         INTEGER,
    fetched_at      TIMESTAMP
);
"""


def key(name: str) -> str:
    return " ".join(name.split()).lower()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_year(html: str) -> int | None:
    m = YEAR.search(html)
    year = int(m.group(1)) if m else None
    return year if year and 1960 <= year <= datetime.now().year + 5 else None


def parse_facility(html: str, name: str) -> int | None:
    m = re.search(FACILITY.format(name), html)
    return int(m.group(1) == "true") if m else None


def todo(conn) -> dict[str, str]:
    """Immeubles à tenter -> slug. Le slug fourni par la source prime sur le slug deviné.

    Un immeuble non daté est retenté seulement si un slug différent apparaît : c'est le cas
    quand PropertyHub publie enfin le vrai slug d'un nom qu'on avait deviné de travers.
    """
    out: dict[str, str] = {}
    dated = {r[0] for r in conn.execute("SELECT name_key FROM projects WHERE completed_year IS NOT NULL")}
    tried = set(conn.execute("SELECT name_key, slug FROM projects"))
    rows = conn.execute(
        "SELECT project_name, project_name_norm FROM listings "
        "WHERE source != 'renthub' AND project_name IS NOT NULL "
        "ORDER BY project_name_norm IS NULL"  # les slugs connus d'abord, ils gagnent
    )
    for name, slug in rows:
        k, slug = key(name), slug or slugify(name)
        if k not in dated and k not in out and (k, slug) not in tried:
            out[k] = slug
    return out


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
    fetcher = Fetcher(cfg, ROOT / "data" / "cache")
    conn = sqlite3.connect(ROOT / "data" / "listings.db")
    conn.executescript(SCHEMA)

    pending = todo(conn)
    print(f"\n=== projets : {len(pending)} immeubles à dater")
    found = 0
    for i, (k, slug) in enumerate(pending.items(), 1):
        try:
            html = fetcher.get(PAGE + slug, keep=False)
        except RobotsDenied:
            print("  robots.txt interdit les pages projet — arrêt")
            break
        except requests.HTTPError:
            html = ""  # 404 : slug deviné faux, l'immeuble n'existe pas chez PropertyHub
        except Exception as exc:  # réseau : on ne marque pas, il sera retenté la semaine suivante
            print(f"  échec {slug} : {exc}")
            continue
        year = parse_year(html)
        conn.execute(
            "INSERT OR REPLACE INTO projects VALUES (?, ?, ?, ?, ?, ?)",
            (k, slug, year, parse_facility(html, "pool"), parse_facility(html, "fitness"),
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()  # un immeuble = une transaction : l'interruption ne perd rien
        found += year is not None
        if i % 100 == 0:
            print(f"  {i}/{len(pending)} — {found} années trouvées")

    total, dated = conn.execute("SELECT COUNT(*), COUNT(completed_year) FROM projects").fetchone()
    print(f"{found} années trouvées cette passe ; base : {dated}/{total} immeubles datés")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
