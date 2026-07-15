"""Kasdienis atnaujinimas: parsisiunčia trūkstamas dienas ir geokoduoja
naujų degalinių adresus (pirma per Adresų registrą, likusius — per Photon).

Paleidžiama ranka arba per launchd (žr. README).
"""

from __future__ import annotations

import history
from geocode import PRECISE, geocode_stations, load_cache, save_cache


def main() -> None:
    saved = history.sync(lambda i, n, d: print(f"[{i}/{n}] {d}", flush=True))
    print(f"Naujų dienų: {len(saved)}")

    df = history.load_history()
    if df.empty:
        return
    latest = df[df["data"] == df["data"].max()]
    stations = latest[["adresas", "savivaldybe"]].drop_duplicates()
    cache = load_cache()
    new = stations[~stations["adresas"].isin(cache.keys())]
    if new.empty:
        print("Naujų adresų nėra.")
        return

    print(f"Naujų adresų: {len(new)} — bandome Adresų registrą")
    try:
        from rc_match import RegistryMatcher

        matcher = RegistryMatcher()
        for r in new.itertuples(index=False):
            result = matcher.match(r.adresas, r.savivaldybe)
            if result:
                cache[r.adresas] = result
        save_cache(cache)
    except FileNotFoundError:
        print("rc_adresai.csv.gz nerastas — praleidžiama")

    cache = load_cache()
    left = [
        (r.adresas, r.savivaldybe)
        for r in new.itertuples(index=False)
        if not cache.get(r.adresas)
    ]
    if left:
        print(f"Per Photon geokoduojama: {len(left)}")
        geocode_stations(left, lambda i, n, a: print(f"[{i}/{n}] {a}", flush=True))

    ok = sum(
        1 for r in new.itertuples(index=False)
        if (load_cache().get(r.adresas) or {}).get("tikslumas")
    )
    print(f"Geokoduota naujų: {ok}/{len(new)}")


if __name__ == "__main__":
    main()
