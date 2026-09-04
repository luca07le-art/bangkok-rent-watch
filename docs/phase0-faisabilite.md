# Phase 0 — Note de faisabilité par source

Projet : bangkok-rent-watch · Date des sondages : 2026-09-01
Méthode : `curl` seul, User-Agent identifiable (`bangkok-rent-watch/0.1 (personal apartment search; <email>)`),
délai 2–4 s entre requêtes, ~25 requêtes au total. Aucun contournement, aucun navigateur headless.

---

## Verdict

| Source | Accès | Verdict |
|---|---|---|
| **PropertyHub** | JSON embarqué (Next.js SSR), 60 annonces/page | **Prioritaire** — la meilleure structure de données |
| **DDproperty** | HTML SSR + JSON-LD, 24/page, filtres et pagination par URL | **Prioritaire** — le plus gros volume, géoloc incluse |
| **Renthub** | JSON embarqué (Next.js SSR), 40/page | **À garder, modèle différent** — seule source avec bail court structuré |
| **FazWaz** | HTML statique, classes CSS stables | **Secondaire** — parsing HTML uniquement |
| **Hipflat** | Cloudflare, 403 sur tout, y compris `/robots.txt` | **Abandonner** |

Trois sources solides + une secondaire : le critère d'acceptation §12 (≥ 3 sources en fin de phase 1) est atteignable.

---

## L'ordre de préférence du §4 s'inverse

Le CDC classe « endpoint JSON interne » en premier choix. Sur les deux plus grosses sources, c'est
exactement ce que le `robots.txt` interdit :

- **DDproperty** interdit `/property-search-proxy`, `/en/property-search-proxy`, `/similar-listing`, `/*/schema.json` et plusieurs routes `ajax`.
- **FazWaz** interdit `/api/` et `/graphql`.

Mais les deux servent les données dans le HTML de la page de résultats, qui est autorisée. La bonne
méthode est donc une troisième voie, absente du CDC :

> **Extraire le JSON déjà embarqué dans une page HTML autorisée** — `<script id="__NEXT_DATA__">` ou
> `<script type="application/ld+json">`.

C'est aussi stable qu'un appel d'API et parfaitement conforme. **Playwright n'est nécessaire nulle
part** : la seule source qui l'exigerait est Hipflat, qui est abandonnée. À retirer des dépendances.

---

## Fiches par source

### PropertyHub — prioritaire

- URL de recherche : `https://propertyhub.in.th/en/condo-for-rent/bangkok` (200, `Allow: /` intégral)
- Payload : `__NEXT_DATA__ → props.pageProps.listings.listings` — **60 annonces/page**, `pagination.totalCount` = 141 752, 2 363 pages
- Champs liste : `id`, `project{name, nameEnglish, slug, address}`, `propertyType`, `title`,
  `price.forRent.monthly.price`, `roomInformation{numberOfBed, numberOfBath, roomArea, onFloor, roomType}`,
  `createdAt / updatedAt / refreshedAt`
- Champs fiche : `amenities{hasWasher, hasAir, hasInternet, hasFurniture, hasParking, hasPool, ...}` — couvre
  directement les critères équipements et meublé du §3 ; `nearbyZones` groupés par type avec **`distance` en
  mètres, `duration` et `lat/lng`** ; `images`, `detail` (HTML libre), `contactInformation`
- Correspondance directe avec le §6 : `refreshedAt` alimente `last_seen`, `project.slug` est un
  `project_name_norm` fourni par la source — meilleur point d'ancrage de dédup que la normalisation floue prévue au §7

**Point ouvert, à régler avant la phase 1 :** les paramètres d'URL (`?bedroom=2&maxPrice=50000&page=2`) sont
**ignorés** — la page SSR renvoie toujours la page 1 non filtrée. Le filtrage est fait côté client contre
`api.propertyhub.in.th` (pas de `robots.txt` sur ce sous-domaine, donc autorisé par défaut). Sans filtre,
141 752 annonces à 60/page sont inexploitables. Il faut soit trouver les vrais noms de paramètres, soit
appeler l'API. C'est le seul vrai reste à faire de la phase 0 (≈ 30 min d'inspection réseau).

### DDproperty — prioritaire

- URL : `https://www.ddproperty.com/en/property-for-rent?region_code=TH10&beds[]=2&baths[]=2&maxprice=50000&page=2`
- **Filtres et pagination fonctionnent par URL** (vérifié : `searchParams` du payload reflète bien
  `bedrooms:[2], bathrooms:[2], maxPrice:50000, page:2`)
- Volume : 20 251 annonces pour 2 chambres à Bangkok, **6 541** avec 2 sdb et ≤ 50 000 THB → 273 pages à 24/page
- Page de résultats, deux gisements :
  - `ld+json` → `ItemList` de 24 : `name`, `url`, `image`, `offers.price`, `priceCurrency`, type de bien
  - DOM, sélecteurs stables `da-id="listing-card-v2-*"` : `bedrooms`, `bathrooms`, `area`, `price`, `title`,
    `unit-type`, `psf`, `build-year`, `recency`, `agent-name`, `agency-name` — 24 occurrences de chacun
- Fiche annonce : accessible (200), à condition de **suivre les redirections** (les URL du `ld+json` renvoient
  un 308 vers un slug canonique) et de laisser passer un délai. Elle donne `lat/lng` de l'annonce, le statut
  meublé (« Fully furnished »), et surtout `nearestMRTs[]` avec code station, nom, ligne, **`distance.value` en
  mètres et `duration` de marche**
- Réserve : un 403 isolé sur une fiche lors du premier sondage, non reproduit ensuite. Traiter le 403 comme un
  429 (backoff), pas comme un blocage définitif

### Renthub — à garder, modèle de données différent

- URL : `https://www.renthub.in.th/en/apartment/<zone-slug>`, par ex. `bts-asok` — 40 résultats/page
- Payload : `__NEXT_DATA__ → props.pageProps.listings`
- **Le modèle n'est pas l'annonce mais l'immeuble** : `name`, `district`, `subdistrict`, `road`,
  `propertyType`, `distance` (mètres jusqu'à la station de la zone), `amenities`, et un prix en fourchette
  `price.monthly{minPrice, maxPrice}`. **Pas de `numberOfBed` ni de `numberOfBath` au niveau liste** — les
  types de chambres sont sur la fiche
- **Seule source à exposer le bail court de façon structurée :**
  `price.shortTerm{shortContract: bool, oneMonth{}, threeMonth{}, sixMonth{}}`
- Bonus : la page d'accueil embarque `zonesForTab.massTransitTab` — **187 zones de transport** avec `name`,
  `slug`, `stationCode`, ligne (`zoneSubType`), ordre sur la ligne et nombre d'annonces
- À noter : Renthub sert aussi un bloc `propertyhubListings` — les deux sites partagent de l'inventaire.
  La dédup Renthub↔PropertyHub se fera par identifiant, pas par similarité

### FazWaz — secondaire

- URL : `https://www.fazwaz.com/2-bedroom-property-for-rent/thailand/bangkok` — chemins SEO propres par nombre de chambres
- 58 193 annonces en location à Bangkok (titre de page)
- HTML statique, classes stables : `result-search__item`, `unit-name`, `location-unit` (sous-district,
  district, ville), `price-tag`, `unit-info__shot-description`, `wrap-icon-info` (chambres / sdb), lien fiche
  `/property-rent/...-u<id>`
- **Piège devise** : le prix affiché est localisé selon l'IP — le sondage depuis la France a renvoyé
  `€937/mo`. Le montant en THB n'apparaît que dans le texte de description (`Rent: THB 36,000/month`).
  Forcer la devise ou parser le THB dans la description, jamais le `price-tag`
- Pas de JSON exploitable : `ld+json` limité au bloc `Organization`, pas de `__NEXT_DATA__`

### Hipflat — abandonner

`https://www.hipflat.co.th/robots.txt` renvoie **403** avec une page de défi Cloudflare (« Just a moment... »).
Le fichier de politique lui-même est inaccessible : impossible de savoir ce qui est autorisé, donc rien ne l'est.
Le §5 tranche déjà le cas — « si une source bloque malgré ces précautions, elle est désactivée ». La contourner
demanderait un navigateur furtif, hors périmètre.

---

## Ce que la phase 0 change dans le CDC

**1. Le critère à 35 points n'existe presque pas dans les données.**
La durée de bail minimale est le critère le plus discriminant du projet et **aucune source sauf Renthub ne
l'expose comme champ**. Sur la fiche DDproperty inspectée, zéro occurrence de « minimum », « contract » ou
« ปี » : l'information n'est pas seulement non structurée, elle est souvent absente du texte. Le seul
`leaseTerm` trouvé dans le payload est un champ du formulaire de contact, pas une donnée d'annonce.

Conséquence : avec le barème actuel, la quasi-totalité des annonces tomberait dans « non précisé = 15 pts » et
l'axe à 35 points ne discriminerait plus rien — il deviendrait une constante. Trois options :

- extraire par regex sur `description_raw` à l'ingestion (`minimum \d+ (month|year)`, `\d+ year contract`,
  `short term`, `สัญญา \d+ ปี`) — quelques lignes, c'est là qu'est le signal quand il existe ;
- traiter « bail court disponible » comme un signal **positif rare** plutôt qu'un axe de notation : +35 quand
  Renthub le confirme ou que la regex trouve ≤ 6 mois, 0 sinon, sans pénaliser l'absence d'information ;
- accepter que ce soit une question à poser à l'agent, hors périmètre du scraper.

À trancher avant d'écrire `score.py`. Recommandation : regex à l'ingestion **et** barème sans pénalité pour
l'absence — sinon le classement final trie sur du bruit.

**2. La distance aux stations est offerte, le fichier du §13.2 est inutile.**
DDproperty fournit `nearestMRTs[]` avec distance en mètres et temps de marche par annonce ; PropertyHub
fournit `nearbyZones` avec distance et coordonnées ; Renthub fournit les 187 stations avec codes et lignes.
Overpass API n'est pas nécessaire — `data/bts_mrt_stations.json` peut être dérivé du payload d'accueil Renthub,
et `core/geo.py` se réduit à un repli pour les annonces sans station renseignée.

**3. Le volume impose un découpage du crawl.**
DDproperty filtré : 273 pages × 3,5 s ≈ 16 min pour une seule source. Le budget de 30 min du §12 est tenable à
trois sources **seulement si** le crawl est découpé par district ou par station et incrémental (ne re-parcourir
que les premières pages triées par date). Un balayage complet hebdomadaire de tout Bangkok ne tient pas.

**4. Le tri du §7 change de point d'appui.**
PropertyHub et Renthub fournissent tous deux un `slug` de projet normalisé par la source. La dédup
intra-source devient triviale, et `rapidfuzz` ne sert plus qu'au rapprochement inter-sources (DDproperty et
FazWaz vers ces slugs). Seuil à calibrer sur données réelles comme prévu, mais le périmètre se réduit beaucoup.

**5. Python n'est pas installé sur cette machine.**
Seul le raccourci Microsoft Store est présent (`python` renvoie « Python est introuvable »). Node est
disponible. Prérequis à installer avant la phase 1 : Python 3.11+ depuis python.org, pas depuis le Store.

---

## Réponses aux points à trancher (§13)

**Serviced apartments et hôtels longue durée — oui, et Renthub est la source qui répond à la question.**
C'est précisément son inventaire (immeubles d'appartements, `apartmentIsHotel`, `hotelListings`), et c'est la
seule source dont le modèle de prix contient nativement `oneMonth / threeMonth / sixMonth` et un drapeau
`shortContract`. Pour un séjour de 4 mois contre un marché à bail de 12 mois, c'est le gisement le plus
pertinent du projet — malgré un prix mensuel plus élevé. À quantifier dès les premiers crawls : part des
immeubles avec `shortContract: true` dans les zones BTS/MRT centrales.

**Fichier des stations — résolu**, voir point 2 ci-dessus. Pas d'Overpass.

**Annonces en thaï — à l'affichage, pas à l'ingestion.** Les trois sources prioritaires servent une version
anglaise (`/en/`), et PropertyHub porte `languages{en, th}`. Le volume réellement thaï-seulement sera faible.
Traduire à l'ingestion coûterait des appels API sur des milliers d'annonces dont aucune ne sera louable avant
avril 2027 ; traduire à la demande sur la short-list en coûte quelques dizaines.

---

## Recommandation de séquencement

La seule chose irréversible dans ce projet, c'est **l'historique de prix** : les prix de septembre 2026 ne
seront pas récupérables en mars 2027. Tout le reste — scoring, dédup, rapport HTML, diff quotidien — peut être
écrit en février 2027 contre des données déjà accumulées, et sera d'ailleurs meilleur écrit à ce moment-là,
puisque les seuils de dédup et les pondérations doivent être calibrés sur des données réelles qui n'existent
pas encore.

Séquencement proposé, contre celui du §11 :

1. **Maintenant** — résoudre le filtrage PropertyHub, puis un collecteur minimal : les deux sources
   prioritaires, écriture dans `listings` et `price_history`, cron hebdomadaire. Ni scoring, ni dédup, ni
   rapport. L'horloge tourne, elle commence à tourner.
2. **Janvier–février 2027** — dédup et scoring calibrés sur 4 mois de données réelles, seuils choisis en
   regardant les doublons effectivement observés plutôt qu'estimés.
3. **Mars 2027** — cadence quotidienne, diff, rapport HTML.

Ce qui est repoussé : `dedup.py`, `score.py`, `report_html.py`, `digest.py`, l'abstraction `scrapers/base.py`
(deux scrapers ne justifient pas encore une classe abstraite — la factoriser au troisième).
