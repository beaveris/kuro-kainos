# ⛽ Kuro kainos Lietuvoje

Streamlit aplikacija, rodanti kasdienes degalų kainas Lietuvos degalinėse:
žemėlapis, pigiausios degalinės pagal savivaldybę ir kainų palyginimas su
rinkos vidurkiu.

Duomenų šaltinis: [Lietuvos energetikos agentūra](https://www.ena.lt/dk-visa-informacija/)
(atnaujinama kasdien darbo dienomis).

## Paleidimas

```bash
pip install -r requirements.txt

# Atsiradus naujoms degalinėms — koordinačių atnaujinimas žemėlapiui.
# Pagrindinis šaltinis: oficialus Adresų registras (rc_adresai.csv.gz),
# atsarginis: Photon/Nominatim geokoderiai. Rezultatai įsimenami
# geocache.json faile:
python3 geocode.py     # nauji adresai per Photon/Nominatim
python3 rc_match.py    # tikslios Adresų registro koordinatės (prioritetas)

streamlit run streamlit_app.py
```

## Talpinimas internete (Streamlit Community Cloud)

Aplikacija talpinama nemokamai: GitHub repo + [share.streamlit.io](https://share.streamlit.io).
Duomenis kasdien atnaujina GitHub Actions (`.github/workflows/update.yml`):
darbo dienomis 13:00 ir 19:30 LT parsiunčia naują ENA failą, geokoduoja
naujas degalines ir įcommitina į repo — Streamlit Cloud persikrauna
automatiškai. Rankinis paleidimas: repo skiltis Actions → „Atnaujinti kuro
kainas" → Run workflow.

Diegimas: share.streamlit.io → Sign in with GitHub → New app →
pasirinkti šį repo, branch `main`, failą `streamlit_app.py` → Deploy.
Norint riboti prieigą: App settings → Sharing → „Only specific people
can view this app" ir suvesti žiūrovų el. paštus.

## Istorija ir automatinis atnaujinimas (lokaliai)

Kainų istorija kaupiama `data/` kataloge (po CSV kiekvienai dienai; ENA
archyvas siekia 2026-04-08). Aplikacija pati parsisiunčia trūkstamas dienas
kas valandą, o visiškai automatiškai tai daro launchd užduotis:

- `~/Library/LaunchAgents/lt.kuro-kainos.update.plist` — kasdien 12:30 ir
  18:30 paleidžia `update_history.py` (naujos dienos + naujų degalinių
  geokodavimas). Žurnalas: `update.log`.
- Įjungimas: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/lt.kuro-kainos.update.plist`
- Išjungimas: `launchctl bootout gui/$(id -u)/lt.kuro-kainos.update`

## Failai

- `streamlit_app.py` — pagrindinė aplikacija
- `fuel_data.py` — duomenų parsisiuntimas iš ena.lt (SharePoint xlsx)
- `rc_match.py` — adresų sutapdinimas su oficialiu Adresų registru
- `rc_adresai.csv.gz` — Adresų registro pastatai su koordinatėmis (1.13 mln;
  šaltinis: registrucentras.lt atviri duomenys, `adr_stat_lr.csv` +
  `adr_gra_adresai_LT.zip` + gatvių/gyvenviečių žodynai)
- `geocode.py` — atsarginis geokodavimas per Photon/Nominatim (OSM)
- `geocache.json` — koordinačių talpykla (generuojama automatiškai)
