"""HTTP poli : robots.txt vérifié, cache disque, délai aléatoire, backoff. §5 du cahier des charges.

Une seule requête à la fois par domaine — le Fetcher est séquentiel par construction.
"""
from __future__ import annotations

import hashlib
import random
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

DENY_ALL = ["User-agent: *", "Disallow: /"]


class RobotsDenied(Exception):
    """Le robots.txt de la source interdit cette URL."""


class Fetcher:
    def __init__(self, cfg: dict, cache_dir: Path):
        c = cfg["crawl"]
        self.ua = c["user_agent"]
        self.delay = (c["delay_min_s"], c["delay_max_s"])
        self.ttl = c["cache_ttl_hours"] * 3600
        self.retries = c["max_retries"]
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.ua
        self._robots: dict[str, RobotFileParser] = {}
        self._last_hit: dict[str, float] = {}

    def allowed(self, url: str) -> bool:
        host = urlsplit(url).netloc
        rp = self._robots.get(host)
        if rp is None:
            rp = RobotFileParser()
            rp.set_url(f"https://{host}/robots.txt")
            # On récupère le fichier nous-mêmes : rp.read() n'enverrait pas notre User-Agent.
            try:
                r = self.session.get(f"https://{host}/robots.txt", timeout=20)
                # Une source qui refuse de servir sa propre politique (Hipflat : 403 Cloudflare)
                # est traitée comme interdisant tout. On ne devine pas à sa place.
                rp.parse(r.text.splitlines() if r.ok else DENY_ALL)
            except requests.RequestException:
                rp.parse(DENY_ALL)
            self._robots[host] = rp
        return rp.can_fetch(self.ua, url)

    def get(self, url: str) -> str:
        if not self.allowed(url):
            raise RobotsDenied(url)

        cached = self.cache / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".html")
        if self.ttl and cached.exists() and time.time() - cached.stat().st_mtime < self.ttl:
            return cached.read_text("utf-8", errors="replace")

        host = urlsplit(url).netloc
        backoff = 5.0
        for attempt in range(1, self.retries + 1):
            pause = self._last_hit.get(host, 0.0) + random.uniform(*self.delay) - time.time()
            if pause > 0:
                time.sleep(pause)
            self._last_hit[host] = time.time()

            r = self.session.get(url, timeout=30)
            # 403 inclus : DDproperty en renvoie de façon transitoire quand on va trop vite.
            if r.status_code in (403, 429) or r.status_code >= 500:
                if attempt == self.retries:
                    break
                time.sleep(backoff)
                backoff *= 3
                continue
            r.raise_for_status()
            cached.write_text(r.text, "utf-8")
            return r.text

        raise RuntimeError(f"{url} : abandon après {self.retries} tentatives")
