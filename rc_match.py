"""Degalinių adresų sutapdinimas su oficialiu Adresų registru (Registrų centras).

Naudoja rc_adresai.csv.gz — jungtinę lentelę iš RC atvirų duomenų
(https://www.registrucentras.lt/atviri-duomenys-ir-statistika/adresu-registro-pirminiai-duomenys-raw-data):
1.13 mln pastatų su tiksliomis WGS84 koordinatėmis.

Paleidus kaip skriptą, visiems šiandienos ENA adresams bando rasti tikslų
atitikmenį registre ir įrašo koordinates į geocache.json su tikslumu
"registras" (aukščiausias prioritetas — perrašo Photon/Nominatim rezultatus).
Nesutapę adresai paliekami kaip buvę.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from geocode import load_cache, save_cache

RC_PATH = Path(__file__).parent / "rc_adresai.csv.gz"


def sav_to_rc(s: str) -> str:
    """ENA savivaldybės pavadinimas → registro forma.

    "Vilniaus m. sav." → "Vilniaus miesto", "Zarasų r. sav." → "Zarasų rajono",
    "Kalvarijos sav." → "Kalvarijos".
    """
    s = s.strip()
    if s.endswith(" m. sav."):
        return s[:-8] + " miesto"
    if s.endswith(" r. sav."):
        return s[:-8] + " rajono"
    if s.endswith(" sav."):
        return s[:-5]
    return s


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


_NR_RE = re.compile(r"^(.*?)[\s,]+(\d+\s*[a-zA-Z]?)$")


def parse_ena_address(adresas: str) -> tuple[str | None, str | None, str | None]:
    """Išskaido ENA adresą į (gyvenvietė, gatvė, nr).

    "Vilnius, Verkių g. 52, 09109" → ("vilnius", "verkių g.", "52")
    "Juodalaukių k. 2, 32104"      → ("juodalaukių k.", None, "2")
    """
    text = re.sub(r",?\s*\b\d{5}\b", "", adresas).strip(" ,")
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return None, None, None

    if len(parts) >= 2 and not re.search(r"\d", parts[0]):
        settlement = _norm(parts[0])
        rest = " ".join(parts[1:])
        m = _NR_RE.match(rest.strip())
        if m:
            return settlement, _norm(m.group(1)), _norm(m.group(2)).replace(" ", "")
        return settlement, _norm(rest), None

    m = _NR_RE.match(parts[0])
    if m:
        return _norm(m.group(1)), None, _norm(m.group(2)).replace(" ", "")
    return _norm(parts[0]), None, None


class RegistryMatcher:
    def __init__(self) -> None:
        df = pd.read_csv(RC_PATH, dtype=str)
        df["lat"] = df["lat"].astype(float)
        df["lon"] = df["lon"].astype(float)
        for c in ("sav", "gyv_v", "gyv_k", "gatve", "nr"):
            df[c] = df[c].fillna("").map(_norm)
        self.df = df
        self._by_sav: dict[str, dict] = {}

    def _index(self, sav: str) -> dict:
        """Indeksai vienai savivaldybei (kuriami pagal poreikį)."""
        if sav in self._by_sav:
            return self._by_sav[sav]
        sub = self.df[self.df["sav"] == sav]
        exact: dict[tuple, tuple] = {}
        street_pts: dict[tuple, list] = {}
        for r in sub.itertuples(index=False):
            pt = (r.lat, r.lon)
            # miestas + gatvė + nr
            exact.setdefault((r.gyv_v, r.gatve, r.nr), pt)
            # kaimas (linksniuota forma su tipu) + nr, be gatvės
            if not r.gatve:
                exact.setdefault((r.gyv_k, "", r.nr), pt)
            # kaimo forma + gatvė + nr (pvz. "traksėdžių k.", "klaipėdos g.", 60)
            exact.setdefault((r.gyv_k, r.gatve, r.nr), pt)
            nr_digits = re.sub(r"\D", "", r.nr)
            nr_int = int(nr_digits) if nr_digits else None
            street_pts.setdefault((r.gyv_v, r.gatve), []).append((nr_int, pt))
            street_pts.setdefault((r.gyv_k, r.gatve), []).append((nr_int, pt))
        idx = {"exact": exact, "street": street_pts}
        self._by_sav[sav] = idx
        return idx

    def match(self, adresas: str, savivaldybe: str) -> dict | None:
        sav = _norm(sav_to_rc(savivaldybe))
        idx = self._index(sav)
        settlement, street, nr = parse_ena_address(adresas)
        if settlement is None:
            return None

        # ENA duomenyse pasitaiko gatvių be tipo santrumpos ("Klaipėdos. 60") —
        # bandome ir su prirašytu "g."
        street_variants = []
        if street:
            street_variants.append(street)
            if not re.search(r"\b(g|pr|pl|al|a|tak|kel|sod)\.$", street):
                street_variants.append(street.rstrip(".") + " g.")

        if nr:
            for sv in street_variants or [""]:
                key = (settlement, sv, nr)
                if key in idx["exact"]:
                    lat, lon = idx["exact"][key]
                    return {"lat": lat, "lon": lon, "tikslumas": "registras"}

        # nr nesutapo — imame artimiausią tos gatvės numerį (geriau nei ilgos
        # gatvės vidurys)
        for sv in street_variants:
            houses = idx["street"].get((settlement, sv))
            if not houses:
                continue
            numbered = [(h_nr, p) for h_nr, p in houses if h_nr is not None]
            if nr and numbered:
                want = int(re.sub(r"\D", "", nr) or 0)
                _, (lat, lon) = min(
                    numbered, key=lambda x: abs(x[0] - want)
                )
            else:
                lat = sum(p[0] for _, p in houses) / len(houses)
                lon = sum(p[1] for _, p in houses) / len(houses)
            return {"lat": lat, "lon": lon, "tikslumas": "gatvė (registras)"}
        return None


if __name__ == "__main__":
    from collections import Counter

    from fuel_data import fetch_latest

    date, df = fetch_latest()
    stations = df[["adresas", "savivaldybe"]].drop_duplicates()
    print(f"{date}: {len(stations)} unikalių adresų")

    matcher = RegistryMatcher()
    cache = load_cache()
    stats: Counter = Counter()
    for r in stations.itertuples(index=False):
        result = matcher.match(r.adresas, r.savivaldybe)
        if result:
            cache[r.adresas] = result
            stats[result["tikslumas"]] += 1
        else:
            existing = cache.get(r.adresas)
            stats[
                f"liko: {(existing or {}).get('tikslumas', 'nerasta')}"
            ] += 1
    save_cache(cache)
    print("Rezultatai:", dict(stats.most_common()))
