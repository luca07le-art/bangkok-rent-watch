"""PropertyHub — Next.js : les annonces sont déjà en JSON dans la page (`__NEXT_DATA__`).

robots.txt autorise tout le site. 60 annonces par page, structure la plus propre des cinq sources.
Le filtrage et la pagination sont côté client : on interroge donc une zone par station.
"""
from __future__ import annotations

import json
import re

BASE = "https://propertyhub.in.th/en/condo-for-rent/"
LISTING = "https://propertyhub.in.th/en/listings/"
CDN = "https://bcdn.propertyhub.in.th"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def urls(cfg: dict):
    for zone in cfg["sources"]["propertyhub"]["zones"]:
        yield BASE + zone


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

