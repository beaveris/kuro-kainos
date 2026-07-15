"""Degalinių adresų geokodavimas su talpykla.

Pagrindinis geokoderis — Photon (photon.komoot.io, OSM duomenys): gerai
supranta lietuviškus adresus su linksniuotais gyvenviečių vardais ir randa
pastatus namo tikslumu. Atsarginis — Nominatim struktūrinės užklausos,
tada pašto kodas, tada savivaldybės centras.

Talpykla saugoma geocache.json faile — kartą geokodavus adresą, jis
nebekvočiamas. Paleidus kaip skriptą, geokoduoja visus šiandienos
duomenų adresus; su --force pergeokoduoja ir netikslius (ne pastato/
gatvės lygio) įrašus.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).parent / "geocache.json"
PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "kuro-kainos-lt/1.0 (personal fuel price map)"

# Lietuvos ribos rezultatų patikrai
LT_BOUNDS = (53.85, 56.50, 20.85, 26.90)  # lat_min, lat_max, lon_min, lon_max

PRECISE = {"pastatas", "gatvė"}


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1))


def _in_lithuania(lat: float, lon: float) -> bool:
    return LT_BOUNDS[0] <= lat <= LT_BOUNDS[1] and LT_BOUNDS[2] <= lon <= LT_BOUNDS[3]


def _clean(adresas: str, savivaldybe: str) -> tuple[str, str, str | None]:
    """Grąžina (adresas be pašto kodo, savivaldybė be 'sav.', pašto kodas)."""
    postcode_m = re.search(r"\b(\d{5})\b", adresas)
    street = re.sub(r",?\s*\b\d{5}\b", "", adresas).strip(" ,")
    muni = re.sub(r"\s*sav\.$", "", savivaldybe).strip()
    return street, muni, postcode_m.group(1) if postcode_m else None


def _query_photon(q: str) -> tuple[float, float, str] | None:
    resp = requests.get(
        PHOTON_URL,
        params={"q": q, "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    feats = resp.json().get("features", [])
    if not feats:
        return None
    props = feats[0]["properties"]
    if props.get("countrycode") != "LT":
        return None
    lon, lat = feats[0]["geometry"]["coordinates"][:2]
    kind = props.get("type", "")
    precision = {"house": "pastatas", "street": "gatvė"}.get(kind, kind)
    return float(lat), float(lon), precision


def _query_nominatim(params: dict) -> tuple[float, float] | None:
    resp = requests.get(
        NOMINATIM_URL,
        params={"format": "json", "limit": 1, "countrycodes": "lt", **params},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    results = resp.json()
    if results:
        return float(results[0]["lat"]), float(results[0]["lon"])
    return None


def geocode_address(adresas: str, savivaldybe: str) -> dict | None:
    """Geokoduoja vieną adresą. Grąžina {lat, lon, tikslumas} arba None."""
    street, muni, postcode = _clean(adresas, savivaldybe)

    # 1) Photon: adresas + savivaldybė (be pašto kodo — duomenyse jų pasitaiko
    # klaidingų, o Photon miestą atpažįsta iš adreso teksto)
    for q in (f"{street}, {muni}", street):
        try:
            r = _query_photon(q)
        except requests.RequestException:
            time.sleep(2)
            r = None
        time.sleep(0.4)
        if r and _in_lithuania(r[0], r[1]) and r[2] in PRECISE:
            return {"lat": r[0], "lon": r[1], "tikslumas": r[2]}

    # 2) Nominatim struktūrinė užklausa: gatvė + miestas
    parts = [p.strip() for p in street.split(",")]
    if len(parts) >= 2:
        city, rest = parts[0], ", ".join(parts[1:])
        try:
            coords = _query_nominatim(
                {"street": rest, "city": city, "country": "Lithuania"}
            )
        except requests.RequestException:
            coords = None
        time.sleep(1.1)
        if coords and _in_lithuania(*coords):
            return {"lat": coords[0], "lon": coords[1], "tikslumas": "adresas"}

    # 3) Pašto kodas
    if postcode:
        try:
            coords = _query_nominatim({"q": f"{postcode}, Lietuva"})
        except requests.RequestException:
            coords = None
        time.sleep(1.1)
        if coords and _in_lithuania(*coords):
            return {"lat": coords[0], "lon": coords[1], "tikslumas": "pašto kodas"}

    # 4) Savivaldybės centras
    try:
        coords = _query_nominatim({"q": f"{muni}, Lietuva"})
    except requests.RequestException:
        coords = None
    time.sleep(1.1)
    if coords:
        return {"lat": coords[0], "lon": coords[1], "tikslumas": "savivaldybė"}
    return None


def geocode_stations(stations, progress_cb=None, force_imprecise=False) -> dict:
    """Geokoduoja degalinių sąrašą [(adresas, savivaldybe), ...] su talpykla."""
    cache = load_cache()

    def needs_work(adresas: str) -> bool:
        if adresas not in cache:
            return True
        entry = cache[adresas]
        if force_imprecise:
            return entry is None or entry.get("tikslumas") not in PRECISE
        return False

    todo = [(a, s) for a, s in stations if needs_work(a)]
    for i, (adresas, savivaldybe) in enumerate(todo):
        cache[adresas] = geocode_address(adresas, savivaldybe)
        if (i + 1) % 10 == 0 or i == len(todo) - 1:
            save_cache(cache)
        if progress_cb:
            progress_cb(i + 1, len(todo), adresas)
    save_cache(cache)
    return cache


if __name__ == "__main__":
    from fuel_data import fetch_latest

    force = "--force" in sys.argv
    date, df = fetch_latest()
    stations = list(
        df[["adresas", "savivaldybe"]].drop_duplicates().itertuples(index=False)
    )
    print(f"{date}: {len(stations)} unikalių adresų (force={force})")

    def progress(done, total, adresas):
        entry = load_cache().get(adresas) if done % 25 == 0 else None
        print(f"[{done}/{total}] {adresas}", flush=True)

    cache = geocode_stations(stations, progress, force_imprecise=force)
    from collections import Counter

    stats = Counter(
        (v or {}).get("tikslumas", "nerasta") for v in cache.values()
    )
    print("Tikslumo statistika:", dict(stats))
