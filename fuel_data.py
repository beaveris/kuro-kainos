"""Degalų kainų duomenų parsisiuntimas iš Lietuvos energetikos agentūros (ena.lt).

ENA kasdien skelbia degalų kainas kaip Excel failus SharePoint'e.
Šis modulis suranda naujausią failą, jį parsisiunčia ir išparsina.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pandas as pd
import requests
from bs4 import BeautifulSoup

ENA_PAGE_URL = "https://www.ena.lt/dk-pr-pr-duomenys/"
# Ankstesnė ENA svetainės struktūra (iki 2026-07-27) šiuos duomenis skelbė
# adresu dk-visa-informacija/ — po pertvarkos puslapis perkeltas į tris
# atskirus adresus: dk-zemelapis/ (žemėlapis), dk-irankis/ (stebėsenos
# įrankis) ir aukščiau nurodytą dk-pr-pr-duomenys/ (pranešimai ir pradiniai
# duomenys — mums reikalingos SharePoint nuorodos).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

COLUMNS = ["imone", "savivaldybe", "adresas", "tipas", "kaina", "data"]

FUEL_TYPES = {
    "95 benzinas": "95 benzinas",
    "Dyzelinas": "Dyzelinas",
    "SND": "SND (dujos)",
}


@dataclass
class DailyLink:
    date: str  # YYYY-MM-DD
    url: str


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHAREPOINT_RE = re.compile(r"sharepoint\.com")


def _links_from_tables(html: str) -> dict[str, str]:
    """Struktūrinis parseris (nuo 2026-07-27 svetainės pertvarkos).

    Kiekvienas mėnuo — lentelė, eilutės trejetais: datų eilutė (Pr–Pn),
    „Pranešimas" eilutė, „Kainos" eilutė. Nuorodos šiame formate title
    atributo nebeturi — data nustatoma pagal stulpelio poziciją.
    """
    soup = BeautifulSoup(html, "html.parser")
    links: dict[str, str] = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for i in range(0, len(rows) - 2, 3):
            date_cells = rows[i].find_all("td")
            kainos_cells = rows[i + 2].find_all("td")
            if len(date_cells) != len(kainos_cells):
                continue
            for date_td, kainos_td in zip(date_cells, kainos_cells):
                date = date_td.get_text(strip=True)
                if not _DATE_RE.match(date):
                    continue
                a = kainos_td.find("a", href=_SHAREPOINT_RE)
                if a and a.get("href"):
                    links[date] = a["href"]
    return links


def _links_from_title_attr(html: str) -> dict[str, str]:
    """Senasis parseris (iki 2026-07-27): nuorodos su title="Degalų kainos ...".

    Paliktas kaip atsarginis variantas, jei ENA vėl pakeistų formatą.
    """
    pattern = re.compile(
        r'href="(https://ltenergagen\.sharepoint\.com/[^"]+)"[^>]*'
        r'title="Degalų kainos (\d{4}-\d{2}-\d{2})"'
        r'|title="Degalų kainos (\d{4}-\d{2}-\d{2})"[^>]*'
        r'href="(https://ltenergagen\.sharepoint\.com/[^"]+)"'
    )
    links = {}
    for m in pattern.finditer(html):
        url = m.group(1) or m.group(4)
        date = m.group(2) or m.group(3)
        links[date] = url
    return links


def list_daily_links() -> list[DailyLink]:
    """Iš ENA puslapio ištraukia visų dienų Excel failų nuorodas."""
    s = _session()
    html = s.get(ENA_PAGE_URL, timeout=30).text
    links = _links_from_tables(html)
    links.update(_links_from_title_attr(html))  # papildo, jei kur liko title
    if not links:
        raise RuntimeError(
            f"ENA puslapyje ({ENA_PAGE_URL}) nerasta nė vienos kainų nuorodos "
            "— tikriausiai svetainės struktūra vėl pasikeitė."
        )
    return sorted(
        (DailyLink(date=d, url=u.replace("&amp;", "&")) for d, u in links.items()),
        key=lambda x: x.date,
    )


def download_daily_xlsx(link: DailyLink) -> bytes:
    """Parsisiunčia dienos Excel failą (SharePoint reikalauja slapukų sesijos)."""
    s = _session()
    sep = "&" if "?" in link.url else "?"
    resp = s.get(f"{link.url}{sep}download=1", timeout=60, allow_redirects=True)
    resp.raise_for_status()
    if not resp.content.startswith(b"PK"):
        raise RuntimeError(
            f"Nepavyko parsisiųsti {link.date} failo: gautas ne Excel turinys"
        )
    return resp.content


def parse_daily_xlsx(content: bytes) -> pd.DataFrame:
    """Išparsina dienos kainų lentelę į DataFrame.

    Palaiko abu ENA formatus: naująjį ilgą (nuo 2026-06-11; eilutė = degalinė
    + kuro tipas) ir senąjį platų (kainos stulpeliuose, eilutė = degalinė).
    """
    raw = pd.read_excel(io.BytesIO(content), sheet_name=0, header=None)
    header_idx = raw.index[raw[0].astype(str).str.strip() == "Įmonė"]
    if len(header_idx) > 0:
        df = raw.iloc[header_idx[0] + 1 :, :6].copy()
        df.columns = COLUMNS
    else:
        df = _parse_wide_format(raw)
    df = df.dropna(subset=["imone", "kaina"])
    df["kaina"] = pd.to_numeric(df["kaina"], errors="coerce")
    df = df.dropna(subset=["kaina"])
    for col in ("imone", "savivaldybe", "adresas", "tipas"):
        df[col] = df[col].astype(str).str.strip()
    df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.date
    df["miestas"] = df["savivaldybe"].str.replace(r"\s*sav\.$", "", regex=True)
    return df.reset_index(drop=True)


def _parse_wide_format(raw: pd.DataFrame) -> pd.DataFrame:
    """Senasis formatas: Data | Įmonė | Savivaldybė | Vieta | 95 | Dyzelinas | SND."""
    header_idx = raw.index[raw[0].astype(str).str.strip() == "Data"]
    if len(header_idx) == 0:
        raise RuntimeError("Neatpažintas failo formatas (nei 'Įmonė', nei 'Data')")
    h = header_idx[0]
    fuel_names = [str(raw.iloc[h, c]).strip() for c in (4, 5, 6)]
    df = raw.iloc[h + 1 :, :7].copy()
    df.columns = ["data", "imone", "savivaldybe", "adresas", *fuel_names]
    df = df.dropna(subset=["imone"])
    long = df.melt(
        id_vars=["data", "imone", "savivaldybe", "adresas"],
        value_vars=fuel_names,
        var_name="tipas",
        value_name="kaina",
    )
    return long[COLUMNS]


def fetch_latest() -> tuple[str, pd.DataFrame]:
    """Grąžina (data, DataFrame) naujausios dienos kainoms."""
    links = list_daily_links()
    if not links:
        raise RuntimeError("ENA puslapyje nerasta kainų failų nuorodų")
    # Retais atvejais naujausias failas dar gali būti nepasiekiamas — bandome
    # nuo naujausio atgal.
    last_err: Exception | None = None
    for link in reversed(links[-5:]):
        try:
            return link.date, parse_daily_xlsx(download_daily_xlsx(link))
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"Nepavyko parsisiųsti nė vieno failo: {last_err}")


if __name__ == "__main__":
    date, df = fetch_latest()
    print(f"Data: {date}, eilučių: {len(df)}")
    print(df.head())
