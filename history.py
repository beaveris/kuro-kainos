"""Kainų istorijos kaupimas: po vieną CSV failą kiekvienai dienai data/ kataloge.

ENA puslapyje laikomas visų dienų archyvas, tad bet kada galima parsisiųsti
trūkstamas dienas — sync() atsisiunčia tik tas, kurių dar neturime.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from fuel_data import COLUMNS, download_daily_xlsx, list_daily_links, parse_daily_xlsx

DATA_DIR = Path(__file__).parent / "data"


def _day_path(date: str) -> Path:
    return DATA_DIR / f"kainos_{date}.csv"


def stored_dates() -> set[str]:
    if not DATA_DIR.exists():
        return set()
    return {p.stem.replace("kainos_", "") for p in DATA_DIR.glob("kainos_*.csv")}


def sync(progress_cb=None, refresh_last: int = 2) -> list[str]:
    """Parsisiunčia trūkstamas dienas. Grąžina naujai išsaugotų datų sąrašą.

    ENA dienos failas pildosi visą dieną (degalinės duomenis pateikia
    skirtingu metu), todėl paskutinės `refresh_last` jau turimos dienos
    parsisiunčiamos iš naujo ir perrašomos, jei ENA versija ne mažesnė.
    """
    DATA_DIR.mkdir(exist_ok=True)
    have = stored_dates()
    links = list_daily_links()
    refresh = {l.date for l in links if l.date in have}
    refresh = set(sorted(refresh)[-refresh_last:]) if refresh_last else set()
    todo = [l for l in links if l.date not in have or l.date in refresh]
    saved = []
    for i, link in enumerate(todo):
        try:
            df = parse_daily_xlsx(download_daily_xlsx(link))
        except Exception:  # noqa: BLE001 — viena nepavykusi diena nestabdo kitų
            continue
        path = _day_path(link.date)
        new_csv = df[COLUMNS].to_csv(index=False)
        if link.date in have:
            old_csv = path.read_text()
            old_rows = old_csv.count("\n") - 1
            if new_csv == old_csv or len(df) < old_rows:
                continue  # nepasikeitė arba ENA versija trumpesnė
            saved.append(f"{link.date} (atnaujinta: {old_rows} → {len(df)} eil.)")
        else:
            saved.append(link.date)
        path.write_text(new_csv)
        if progress_cb:
            progress_cb(i + 1, len(todo), link.date)
    return saved


# Teisinės formos, bendriniai ir geografiniai žodžiai, nesvarbūs tapatybei
_STOP_TOKENS = {
    "uab", "ab", "iį", "mb", "kb", "tūb", "všį", "žūb",
    "žemės", "ūkio", "bendrovė", "prekybos", "komercinė", "įmonė", "imone",
    "lietuva", "lt", "baltics", "retail",
}


def _name_tokens(name: str) -> frozenset[str]:
    s = re.sub(r"\(.*?\)", " ", str(name).lower())  # be franšizės skliaustuose
    s = re.sub(r"[^\w]+", " ", s, flags=re.UNICODE)
    return frozenset(t for t in s.split() if t not in _STOP_TOKENS)


def _unify_company_names(df: pd.DataFrame) -> pd.DataFrame:
    """Suvienodina įmonių pavadinimus tarp senojo ir naujojo ENA formato.

    Senuose failuose "Viada", "Circle K", "Lašų ŽŪB"; naujuose —
    "UAB Viada LT", "UAB Circle K Lietuva", "Lašų žemės ūkio bendrovė".
    Kanonas — naujausios dienos rašyba; senas vardas priskiriamas, jei jo
    reikšminių žodžių aibė sutampa su vieninteliu kanoniniu kandidatu
    (poaibio tikslumu).
    """
    canon_names = df.loc[df["data"] == df["data"].max(), "imone"].unique()
    canon_tokens = {c: _name_tokens(c) for c in canon_names}

    mapping: dict[str, str] = {}
    for name in df["imone"].unique():
        if name in canon_tokens:
            continue
        toks = _name_tokens(name)
        if not toks:
            continue
        candidates = [
            c for c, ct in canon_tokens.items()
            if ct and (toks <= ct or ct <= toks)
        ]
        if len(candidates) == 1:
            mapping[name] = candidates[0]
    if mapping:
        df["imone"] = df["imone"].replace(mapping)
    return df


def _station_key(adresas: str) -> str:
    """Formato nepriklausomas degalinės raktas.

    Senuose ENA failuose "Palijoniškio g. 1, Utena", naujuose —
    "Utena, Palijoniškio g. 1, 28241": žodžių aibė be pašto kodo sutampa.
    """
    s = re.sub(r"\b\d{5}\b", " ", str(adresas).lower())
    return " ".join(sorted(t for t in re.split(r"[^\w]+", s) if t))


def load_history() -> pd.DataFrame:
    """Sujungia visas išsaugotas dienas į vieną DataFrame."""
    files = sorted(DATA_DIR.glob("kainos_*.csv")) if DATA_DIR.exists() else []
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    df["data"] = pd.to_datetime(df["data"]).dt.date
    df["miestas"] = df["savivaldybe"].str.replace(r"\s*sav\.$", "", regex=True)
    df["stotis_id"] = df["adresas"].map(
        {a: _station_key(a) for a in df["adresas"].unique()}
    )
    # Senuose failuose pasitaiko pavienių kitos datos eilučių — dienos su vos
    # keliais įrašais nėra tikros ataskaitos, jos iškraipytų statistiką.
    counts = df.groupby("data").size()
    df = df[df["data"].isin(counts[counts >= 100].index)]
    return _unify_company_names(df.reset_index(drop=True))


if __name__ == "__main__":
    saved = sync(lambda i, n, d: print(f"[{i}/{n}] {d}", flush=True))
    print(f"Nauju dienų: {len(saved)}")
    df = load_history()
    if not df.empty:
        print(f"Istorija: {df['data'].nunique()} d., {len(df)} eilučių, "
              f"{df['data'].min()} – {df['data'].max()}")
