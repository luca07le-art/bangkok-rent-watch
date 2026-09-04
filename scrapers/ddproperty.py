"""DDproperty — la page de résultats est autorisée par robots.txt et rendue côté serveur.

L'endpoint JSON interne (/property-search-proxy) est explicitement interdit par leur robots.txt :
on lit donc les cartes du HTML, où les sélecteurs `da-id="listing-card-v2-*"` sont stables.
Filtres et pagination passent par l'URL (vérifié en phase 0).
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

BASE = "https://www.ddproperty.com/en/property-for-rent"
DIGITS = re.compile(r"[\d.]+")


def urls(cfg: dict):
    s = cfg["sources"]["ddproperty"]
    for page in range(1, s["max_pages"] + 1):
        yield BASE + "?" + urlencode(
            {
                "region_code": s["region_code"],
                "listing_type": "rent",
                "beds[]": cfg["bedrooms_min"],
                "baths[]": cfg["bathrooms_min"],
                "page": page,
            }
        )


def _num(node, cast=int):
    """Premier nombre du texte d'un nœud : '฿45,000 /mo' -> 45000, '94 sqm' -> 94.0."""
    if node is None:
        return None
    m = DIGITS.search(node.get_text(" ", strip=True).replace(",", ""))
    return cast(m.group()) if m else None


def _photos(soup) -> dict[str, str]:
    """{source_id: url de photo}, depuis le ld+json.

    Le carrousel des cartes est monté en JS : le HTML servi ne contient que 7 photos sur 20.
    Le bloc `ld+json` en porte 20 sur 20, avec le même id d'annonce dans l'URL.
    """
    block = soup.select_one('script[type="application/ld+json"]')
    if not block:
        return {}
    try:
        graph = json.loads(block.string or "")["@graph"]
    except (ValueError, KeyError, TypeError):
        return {}
    out = {}
    for node in graph:
        if node.get("@type") != "ItemList":
            continue
        for el in node.get("itemListElement", []):
            item = el.get("item") or el
            ids = re.findall(r"(\d{6,})", item.get("url") or "")
            if ids and item.get("image"):
                out[ids[-1]] = item["image"]
    return out


def parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    photos = _photos(soup)
    out = []
    for card in soup.select("a.card-footer"):
        url = card.get("href") or ""
        ids = re.findall(r"(\d{6,})", url)
        if not ids:
            continue  # lien de projet ou de pub, pas une annonce

        address = card.select_one(".listing-address")
        address_raw = address.get_text(" ", strip=True) if address else None
        # '39 South Sathorn Road, Thung Maha Mek, Sathon, Bangkok' -> district 'Sathon'
        parts = [p.strip() for p in address_raw.split(",")] if address_raw else []
        district = parts[-2] if len(parts) >= 2 else None

        title = card.select_one('[da-id="listing-card-v2-title"]')
        out.append(
            {
                "source_id": ids[-1],
                "url": url,
                "title_raw": title.get_text(" ", strip=True) if title else None,
                # Le titre DDproperty est « <Projet>, Bangkok » : le projet en est la tête.
                "project_name": title.get_text(" ", strip=True).split(",")[0] if title else None,
                "address_raw": address_raw,
                "district": district,
                "price_thb": _num(card.select_one('[da-id="listing-card-v2-price"]')),
                "bedrooms": _num(card.select_one('[da-id="listing-card-v2-bedrooms"]')),
                "bathrooms": _num(card.select_one('[da-id="listing-card-v2-bathrooms"]')),
                "area_sqm": _num(card.select_one('[da-id="listing-card-v2-area"]'), float),
                "photos": photos.get(ids[-1]),
                "lang": "en",
            }
        )
    return out


# ponytail: on ne lit que la carte. lat/lng, station la plus proche (nearestMRTs, distance en
# mètres), statut meublé et description ne sont que sur la fiche annonce — une requête de plus
# par annonce, soit ~6500 requêtes. À faire seulement sur la short-list, en phase 2.
