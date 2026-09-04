"""Renthub — Next.js, JSON dans la page. robots.txt autorise tout, 40 résultats par page.

Renthub n'est pas là pour le volume : c'est la seule source qui expose la durée de bail de
façon structurée (`price.shortTerm.shortContract` et les paliers 1 / 3 / 6 mois). Pour un
séjour de quatre mois face à un marché à bail de douze, c'est l'information la plus décisive
du projet — et 12 immeubles sur 40 l'annoncent rien que sur la zone Asok.

Elle donne aussi `distance`, la distance en mètres jusqu'à la station de la zone : c'est le
seul remplissage de `station_distance_m`, à 0 % chez les deux autres sources.

Attention au modèle de données : **une entrée est un immeuble, pas un logement**. Il n'y a ni
nombre de chambres, ni surface au niveau de la liste — ils sont sur la fiche, par type de
chambre. Le prix est une fourchette ; on stocke le bas de fourchette, qui est le seul montant
comparable au loyer d'une annonce unitaire.
"""
from __future__ import annotations

import json
import re

# Zones indépendantes les unes des autres : une zone vide ne dit rien des suivantes.
STOP_ON_EMPTY = False

BASE = "https://www.renthub.in.th/en/apartment/"
BUILDING = "https://www.renthub.in.th/en/"
CDN = "https://bcdn.renthub.in.th"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

# Du plus court au plus long : on retient le palier le plus court réellement proposé.
PALIERS = (("oneMonth", 1), ("threeMonth", 3), ("sixMonth", 6))


def urls(cfg: dict):
    s = cfg["sources"]["renthub"]
    for zone in s["zones"]:
        for page in range(1, s["max_pages_per_zone"] + 1):
            yield BASE + zone if page == 1 else f"{BASE}{zone}/{page}"


def _bail_min(price: dict) -> int | None:
    """Durée de bail minimale annoncée, en mois. None = non précisé (le cas courant).

    L'absence n'est pas un « bail long » : c'est une absence. Elle ne doit pas être
    confondue avec un 12 explicite, sinon le filtre trierait sur du bruit — c'est
    exactement l'écueil relevé en phase 0 sur l'axe à 35 points du barème.
    """
    st = price.get("shortTerm") or {}
    if not st.get("shortContract"):
        return None
    for cle, mois in PALIERS:
        if (st.get(cle) or {}).get("shortContract"):
            return mois
    return 1  # shortContract vrai sans palier détaillé : au moins du court terme


def parse(html: str) -> list[dict]:
    m = NEXT_DATA.search(html)
    if not m:
        return []
    page = json.loads(m.group(1))["props"]["pageProps"]
    # Un slug de zone inconnu ne renvoie ni 404 ni page vide : Renthub sert sa page
    # d'accueil, où `listings` est un dict de blocs éditoriaux et `zone` vaut null.
    # Itérer dessus donnerait des chaînes. On la traite comme une zone vide.
    if not isinstance(page.get("listings"), list):
        return []

    zone = page.get("zone") or {}
    # La zone EST la station : c'est ce à quoi `distance` se rapporte.
    station = zone.get("name") if isinstance(zone, dict) else None

    out = []
    for item in page.get("listings") or []:
        price = item.get("price") or {}
        mensuel = price.get("monthly") or {}
        # Bas de fourchette : le seul montant comparable à une annonce unitaire. Le haut
        # est conservé dans le titre pour que l'écart reste visible à l'œil.
        bas, haut = mensuel.get("minPrice"), mensuel.get("maxPrice")
        if not bas:
            continue  # immeuble sans prix mensuel : rien à comparer, rien à historiser

        adresse = " ".join(
            str(item[k]) for k in ("houseNumber", "street", "road") if item.get(k)
        )
        out.append(
            {
                "source_id": item["id"],
                "url": BUILDING + item["slug"],
                "project_name": item.get("name"),
                "title_raw": f"{item.get('name')} — {bas}-{haut} THB/mois"
                if haut and haut != bas
                else item.get("name"),
                "address_raw": adresse or None,
                "district": item.get("district"),
                "price_thb": bas,
                "nearest_station": station,
                "station_distance_m": item.get("distance"),
                "min_lease_months": _bail_min(price),
                "photos": CDN + item["coverPicture"] if item.get("coverPicture") else None,
                "lang": "en",
            }
        )
    return out


# ponytail: ni chambres ni surface — elles n'existent que sur la fiche immeuble, une requête
# de plus par bâtiment. Conséquence assumée : ces entrées ne passent pas les filtres
# chambres/sdb de la page, qui ne les montre donc que si l'on demande le bail court.
