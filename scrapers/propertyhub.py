"""PropertyHub — Next.js : les annonces sont déjà en JSON dans la page (`__NEXT_DATA__`).

robots.txt autorise tout le site. 60 annonces par page, structure la plus propre des cinq sources.
Le filtrage reste côté client, mais la pagination se fait par segment d'URL (cf. urls()).
"""
from __future__ import annotations

import json
import re

# Chaque URL est une zone independante : une zone vide (slug inconnu) ne dit rien des
# suivantes, on continue.
STOP_ON_EMPTY = False

BASE = "https://propertyhub.in.th/en/condo-for-rent/"
LISTING = "https://propertyhub.in.th/en/listings/"
CDN = "https://bcdn.propertyhub.in.th"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def urls(cfg: dict):
    """Une URL par page et par zone.

    La pagination passe par un SEGMENT d'URL (`/bangkok/2`), pas par `?page=2` — ce dernier
    est silencieusement ignore et rend toujours la page 1. C'est ce qui avait fait conclure
    en phase 0 que la pagination etait purement cliente.

    Les pages se recouvrent : les annonces `sponsorPackage` sont reinjectees a chaque page
    (32 communes entre la page 3 et la page 50, toutes sponsorisees). `store.upsert` les
    dedoublonne, le cout est en bande passante, pas en donnees fausses.
    """
    s = cfg["sources"]["propertyhub"]
    for zone in s["zones"]:
        for page in range(1, s["max_pages_per_zone"] + 1):
            yield BASE + zone if page == 1 else f"{BASE}{zone}/{page}"


def parse(html: str) -> list[dict]:
    m = NEXT_DATA.search(html)
    if not m:
        return []  # zone inconnue ou page d'erreur : le collecteur le signalera
    page = json.loads(m.group(1))["props"]["pageProps"]
    out = []
    for item in page.get("listings", {}).get("listings", []):
        project = item.get("project") or {}
        room = item.get("roomInformation") or {}
        monthly = ((item.get("price") or {}).get("forRent") or {}).get("monthly") or {}
        floor = room.get("onFloor")
        # `project.address` vaut « Khlong Toei Bangkok » : le district en est la tête.
        # Vérifié sur 1066/1069 adresses, et 19 des 23 districts obtenus sont écrits
        # exactement comme chez DDproperty — les médianes par district restent comparables.
        address = project.get("address") or ""
        district = address.rsplit(" Bangkok", 1)[0] if address.endswith(" Bangkok") else None

        out.append(
            {
                "source_id": item["id"],
                "url": LISTING + item["slug"],
                "title_raw": item.get("title"),
                "project_name": project.get("nameEnglish") or project.get("name"),
                "address_raw": project.get("address"),
                "district": district,
                "price_thb": monthly.get("price"),
                "bedrooms": room.get("numberOfBed"),
                "bathrooms": room.get("numberOfBath"),
                "area_sqm": room.get("roomArea"),
                "floor": int(floor) if str(floor).isdigit() else None,
                # `detail` n'est jamais servi dans le payload de liste (0/60 sur fixture,
                # 0 % sur 1866 lignes en base) : il n'existe que sur la fiche annonce.
                "photos": CDN + item["coverPicture"] if item.get("coverPicture") else None,
                "lang": "en",
            }
        )
    return out

