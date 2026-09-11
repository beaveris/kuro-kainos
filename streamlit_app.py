"""Kuro kainų Lietuvos degalinėse žemėlapis ir ataskaitos.

Duomenų šaltinis: Lietuvos energetikos agentūra (ena.lt), atnaujinama kasdien.
"""

from __future__ import annotations

import altair as alt
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
import pandas as pd
import pydeck as pdk
import streamlit as st

import history
from analytics import stability_report, weekday_profile
from fuel_data import FUEL_TYPES
from geocode import load_cache

st.set_page_config(
    page_title="Kuro kainos Lietuvoje",
    page_icon="⛽",
    layout="wide",
)


@st.cache_data(ttl=3600, show_spinner="Atnaujinami duomenys iš ena.lt…")
def load_data() -> tuple[str, pd.DataFrame, pd.DataFrame, bool, str]:
    """Grąžina (naujausia data, tos dienos duomenys, visa istorija).

    Kas valandą patikrina, ar ENA nepaskelbė naujų dienų, ir jas parsisiunčia.
    """
    update_failed = False
    try:
        history.sync()
    except Exception:
        logging.getLogger(__name__).exception("Nepavyko atnaujinti ENA duomenų")
        update_failed = True
    hist = history.load_history()
    if hist.empty:
        raise RuntimeError("Nepavyko parsisiųsti duomenų iš ena.lt")
    latest = hist["data"].max()
    # Dalis tinklų kai kuriomis dienomis duomenų nepateikia — kad degalinės
    # „neišnyktų“, imame paskutinę žinomą kiekvienos kainą (iki 7 d. senumo)
    # ir pažymime jos datą.
    recent = hist[hist["data"].map(lambda d: (latest - d).days <= 7)]
    df = (
        recent.sort_values("data")
        .drop_duplicates(subset=["stotis_id", "tipas"], keep="last")
        .reset_index(drop=True)
    )
    df["senumas"] = df["data"].map(lambda d: (latest - d).days)
    checked_at = datetime.now(ZoneInfo("Europe/Vilnius")).isoformat(timespec="minutes")
    return str(latest), df, hist, update_failed, checked_at


@st.cache_data(ttl=600)
def load_coords() -> pd.DataFrame:
    cache = load_cache()
    rows = [
        {"adresas": adresas, "lat": v["lat"], "lon": v["lon"]}
        for adresas, v in cache.items()
        if v
    ]
    return pd.DataFrame(rows, columns=["adresas", "lat", "lon"])


def deviation_color(pct: float) -> list[int]:
    """Spalva pagal nuokrypį nuo rinkos vidurkio: žalia (pigiau) → raudona (brangiau)."""
    # -5 % ir mažiau — sodri žalia; +5 % ir daugiau — sodri raudona
    t = max(-1.0, min(1.0, pct / 5.0))
    if t <= 0:
        # žalia → gelsva
        return [int(46 + (230 - 46) * (1 + t)), int(160 + (200 - 160) * (1 + t)), 60, 200]
    # gelsva → raudona
    return [int(230 + (220 - 230) * t), int(200 - 200 * t * 0.85), int(60 - 60 * t), 200]


try:
    date, df, hist, update_failed, checked_at = load_data()
except Exception:
    logging.getLogger(__name__).exception("Nepavyko įkelti kainų istorijos")
    st.error("Kainų šiuo metu nepavyko įkelti. Bandykite vėliau.")
    st.stop()
coords = load_coords()

st.title("⛽ Kuro kainos Lietuvoje")
st.caption(f"Atnaujinimą tikrinome {checked_at[11:16]} Lietuvos laiku ({checked_at[:10]}).")
with st.expander(f"Duomenų būklė · kainos {date}"):
    st.write(f"Paskutinis bandymas atnaujinti: **{checked_at.replace('T', ' ')}** (Lietuvos laikas).")
    st.write("Atnaujinimas nepavyko — rodoma išsaugota istorija." if update_failed else "ENA duomenys patikrinti.")
    current_ids = set(df.loc[df['senumas'] == 0, 'stotis_id'])
    old_ids = set(df.loc[df['senumas'] > 0, 'stotis_id'])
    with st.container(horizontal=True):
        st.metric("Pateikė naujausią dieną", len(current_ids), border=True)
        st.metric("Tik ankstesnės kainos", len(old_ids - current_ids), border=True)
        st.metric("Dalis kuro kainų senesnės", len(old_ids & current_ids), border=True)
    age = (datetime.now(ZoneInfo('Europe/Vilnius')).date() - pd.Timestamp(date).date()).days
    st.caption(f"Naujausia ataskaita prieš {age} kalendorines d. Nauja kaina nereiškia realaus laiko kainos: tai ENA dienos stebėjimas.")
    completeness = df.assign(nauja=df['senumas'].eq(0)).groupby('imone').agg(
        kainu=('tipas', 'size'), nauju=('nauja', 'sum'), paskutine=('data', 'max')
    ).reset_index()
    completeness['Naujų kainų, %'] = completeness.nauju / completeness.kainu * 100
    st.dataframe(completeness.rename(columns={'imone':'Tinklas','kainu':'Rodomų kainų','nauju':'Naujausios dienos kainų','paskutine':'Paskutinė data'}), hide_index=True)
    st.caption("Aprėptis skaičiuojama tarp paskutinės savaitės rodinyje esančių degalinių, ne visų Lietuvos degalinių registro.")
    if st.button('Tikrinti kainas dabar'):
        load_data.clear()
        st.rerun()
if update_failed:
    st.warning(
        f"Nepavyko gauti naujų ENA duomenų. Rodomos paskutinės išsaugotos "
        f"kainos ({date}); dabartinės kainos degalinėse gali skirtis."
    )
stale_n = df.loc[df["senumas"] > 0, "stotis_id"].nunique()
st.caption(
    f"Duomenys: [Lietuvos energetikos agentūra](https://www.ena.lt/dk-pr-pr-duomenys/) · "
    f"**{date}** · {df['stotis_id'].nunique()} degalinių"
    + (
        f" · iš jų {stale_n} tą dieną duomenų nepateikė — rodoma paskutinė "
        "žinoma kaina (žymima data)"
        if stale_n else ""
    )
)

col_fuel, col_net = st.columns([1, 2], vertical_alignment="bottom")
with col_fuel:
    fuel = st.segmented_control(
        "Degalų tipas",
        options=list(FUEL_TYPES),
        format_func=lambda x: FUEL_TYPES[x],
        default=st.query_params.get('fuel', '95 benzinas') if st.query_params.get('fuel', '95 benzinas') in FUEL_TYPES else '95 benzinas',
        key="fuel_choice",
    )
if not fuel:
    st.stop()

fdf = df[df["tipas"] == fuel].copy()
# Rinkos vidurkis skaičiuojamas nuo visos rinkos — filtrai jo nekeičia,
# kad nuokrypiai visada rodytų palyginimą su rinka.
market_avg = fdf.loc[fdf["senumas"] == 0, "kaina"].mean()
if pd.isna(market_avg):
    st.info("Naujausios dienos šio kuro kainų nėra. Pasirinkite kitą kuro tipą.")
    st.stop()
st.caption("Rinkos vidurkis: tik naujausios ataskaitos kainos, be ankstesnių dienų kainų.")

network_counts = fdf["imone"].value_counts()
with col_net:
    networks = st.multiselect(
        "Degalinių tinklai",
        options=list(network_counts.index),
        format_func=lambda x: f"{x} ({network_counts[x]})",
        placeholder="Visi tinklai",
        default=[n for n in st.query_params.get_all('network') if n in network_counts.index],
        key="network_choice",
    )
city_counts = df.groupby('miestas').stotis_id.nunique().sort_values(ascending=False)
global_cities = ['Visos', *city_counts.index]
saved_city = st.query_params.get('city', 'Visos')
global_city = st.selectbox('Mano savivaldybė', global_cities,
                           index=global_cities.index(saved_city) if saved_city in global_cities else 0,
                           key='global_city')
with st.popover('Vaizdas ir mano nuoroda'):
    compact = st.toggle('Kompaktiškas vaizdas telefonui', value=st.query_params.get('compact', '1') != '0', key='compact')
    params = {'fuel': fuel, 'network': networks, 'city': global_city}
    params['compact'] = '1' if compact else '0'
    preference_url = 'https://kuro-kainos-lt.streamlit.app/?' + urlencode(params, doseq=True)
    st.link_button('Atidaryti mano pasirinkimus', preference_url)
    st.code(preference_url, language=None)
    st.caption('Pridėkite šią nuorodą prie žymelių arba telefono pradžios ekrano. Ji atkurs kuro tipą, tinklus ir savivaldybę. Pasirinkimai saugomi nuorodoje, ne paskyroje.')
if networks:
    fdf = fdf[fdf["imone"].isin(networks)]
    if fdf.empty:
        st.warning("Pasirinkti tinklai neturi šio tipo degalų.")
        st.stop()
if global_city != 'Visos':
    fdf = fdf[fdf.miestas == global_city]
if fdf.empty:
    st.info('Pagal pasirinktą savivaldybę ir tinklus kainų nerasta. Pakeiskite filtrus.')
    st.stop()
fdf["nuokrypis"] = fdf["kaina"] - market_avg
fdf["nuokrypis_pct"] = fdf["nuokrypis"] / market_avg * 100

cheapest = fdf.loc[fdf["kaina"].idxmin()]
priciest = fdf.loc[fdf["kaina"].idxmax()]

st.caption(f"{len(fdf)} degalinių · rinkos vidurkis {market_avg:.3f} €/l · mažiausia rodoma kaina {cheapest['kaina']:.3f} €/l ({cheapest['data']})")
with st.expander('Kainų suvestinė', expanded=not compact):
    st.metric("Rinkos vidurkis", f"{market_avg:.3f} €/l", border=True)
    if networks:
        sel_avg = fdf["kaina"].mean()
        st.metric(
            "Pasirinktų tinklų vidurkis",
            f"{sel_avg:.3f} €/l",
            f"{(sel_avg - market_avg) / market_avg * 100:+.1f} % nuo rinkos",
            delta_color="inverse",
            border=True,
        )
    st.metric(
        "Pigiausia",
        f"{cheapest['kaina']:.3f} €/l",
        f"{cheapest['nuokrypis_pct']:+.1f} % nuo vidurkio",
        delta_color="inverse",
        border=True,
        help=f"{cheapest['imone']}, {cheapest['adresas']} ({cheapest['savivaldybe']})",
    )
    st.metric(
        "Brangiausia",
        f"{priciest['kaina']:.3f} €/l",
        f"{priciest['nuokrypis_pct']:+.1f} % nuo vidurkio",
        delta_color="inverse",
        border=True,
        help=f"{priciest['imone']}, {priciest['adresas']} ({priciest['savivaldybe']})",
    )
    st.metric("Degalinių su šiuo kuru", f"{len(fdf)}", border=True)

def trend_chart(data: pd.DataFrame, color_col: str, color_title: str | None = None):
    return (
        alt.Chart(data)
        .mark_line()
        .encode(
            x=alt.X("data:T", title="Data", axis=alt.Axis(format="%m-%d")),
            y=alt.Y(
                "kaina:Q",
                title="Kaina, €/l",
                scale=alt.Scale(zero=False),
                axis=alt.Axis(format=".2f"),
            ),
            color=alt.Color(f"{color_col}:N", title=color_title),
            tooltip=[
                alt.Tooltip("data:T", title="Data", format="%Y-%m-%d"),
                alt.Tooltip(color_col, title=color_title or " "),
                alt.Tooltip("kaina:Q", title="Kaina", format=".3f"),
            ],
        )
        .properties(height=340)
    )


DAY_NAMES = {
    0: "Pirmadienis", 1: "Antradienis", 2: "Trečiadienis",
    3: "Ketvirtadienis", 4: "Penktadienis", 5: "Šeštadienis", 6: "Sekmadienis",
}


def weekday_bar(weekday_df: pd.DataFrame, y_title: str):
    return (
        alt.Chart(weekday_df)
        .mark_bar()
        .encode(
            x=alt.X("diena:N", sort=list(DAY_NAMES.values()), title=None),
            y=alt.Y("nuokrypis_ct:Q", title=y_title),
            color=alt.condition(
                alt.datum.nuokrypis_ct < 0,
                alt.value("#2ea060"),
                alt.value("#dc4c4c"),
            ),
            tooltip=[
                alt.Tooltip("diena:N", title="Diena"),
                alt.Tooltip("nuokrypis_ct:Q", title="ct/l", format="+.2f"),
            ],
        )
        .properties(height=260)
    )


hist_fuel = hist[hist["tipas"] == fuel]
day_avg_all = hist_fuel.groupby("data")["kaina"].mean()


def city_options(data: pd.DataFrame) -> list[str]:
    """Savivaldybės didžiausių (pagal degalinių skaičių) tvarka, ne abėcėlės."""
    counts = data.groupby("miestas")["stotis_id"].nunique()
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return ["Visos"] + [name for name, _ in ranked]


def station_card(sid: str, context: str = "map") -> None:
    """Degalinės kortelė: šiandienos būklė, istorija ir savaitės dienų profilis."""
    sh = hist_fuel[hist_fuel["stotis_id"] == sid]
    if sh.empty:
        st.info("Ši degalinė neturi istorijos pasirinktam kuro tipui.")
        return
    last = sh[sh["data"] == sh["data"].max()].iloc[0]

    st.subheader(f"⛽ {last['imone']} — {last['adresas']}")
    # Adreso paieška navigacijoje saugesnė nei apytikslis pašto kodo taškas.
    destination = f"{last['imone']}, {last['adresas']}, {last['savivaldybe']}, Lietuva"
    with st.container(horizontal=True):
        st.link_button('Važiuoti su Google Maps', 'https://www.google.com/maps/dir/?' + urlencode({'api': 1, 'destination': destination}))
        st.link_button('Ieškoti Waze', 'https://www.waze.com/ul?' + urlencode({'q': destination, 'navigate': 'yes'}))
    st.caption('Navigacijoje patikrinkite pasirinktą degalinę. Rodoma kainos data gali skirtis nuo šiandienos.')

    sh_daily = sh.groupby("data")["kaina"].min()
    sh_dev = (sh_daily - day_avg_all).dropna()
    city_daily = (
        hist_fuel[hist_fuel["miestas"] == last["miestas"]]
        .groupby(["data", "stotis_id"])["kaina"].min().reset_index()
    )
    city_daily["rank"] = city_daily.groupby("data")["kaina"].rank(method="min")
    cheapest_days = city_daily[city_daily["stotis_id"] == sid]

    today_rows = fdf[fdf["stotis_id"] == sid]
    with st.container(horizontal=True):
        if not today_rows.empty:
            trow = today_rows.iloc[0]
            label = (
                f"Kaina ({trow['data']})"
                if trow.get("senumas", 0) == 0
                else f"Kaina ({trow['data']})"
            )
            st.metric(
                label,
                f"{trow['kaina']:.3f} €/l",
                f"{trow['nuokrypis_pct']:+.1f} % nuo rinkos",
                delta_color="inverse",
                border=True,
            )
        else:
            st.metric(
                f"Paskutinė kaina ({last['data']})",
                f"{last['kaina']:.3f} €/l",
                border=True,
            )
        if compact:
            st.caption(f"Per {sh['data'].nunique()} istorijos d.: vid. {sh_dev.mean() * 100:+.1f} ct/l nuo rinkos; pigiausia savivaldybėje {(cheapest_days['rank'] <= 1).mean() * 100:.0f} % stebėtų dienų.")
        else:
            st.metric("Vid. nuokrypis nuo rinkos", f"{sh_dev.mean() * 100:+.1f} ct/l", border=True)
            st.metric("Pigiausia savivaldybėje", f"{(cheapest_days['rank'] <= 1).mean() * 100:.0f} % dienų", border=True)
            st.metric("Istorijos dienų", f"{sh['data'].nunique()}", border=True)

    if not st.toggle('Rodyti kainų istoriją ir savaitės ritmą', key=f'details_{context}_{sid}'):
        return

    station_line = sh_daily.reset_index()
    station_line["serija"] = "Ši degalinė"
    market_line = day_avg_all.reset_index()
    market_line["serija"] = "Rinkos vidurkis"
    city_line = (
        hist_fuel[hist_fuel["miestas"] == last["miestas"]]
        .groupby("data")["kaina"].mean().reset_index()
    )
    city_line["serija"] = f"{last['miestas']} vidurkis"
    st.altair_chart(
        trend_chart(
            pd.concat([station_line, market_line, city_line], ignore_index=True),
            "serija",
            None,
        )
    )

    # Savaitės ritmas dviem pjūviais:
    # 1) degalinė prieš savo tos savaitės vidurkį — kada ČIA realiai pigiausia
    #    (kainų trendas susiprastina per savaitės centravimą);
    # 2) prieš tos dienos rinkos vidurkį — ar ritmas savas, ar tik rinkos aidas.
    rhythm = weekday_profile(sh_daily)
    prof_own = rhythm['profile']
    rez = (sh_dev.reindex(rhythm.get('dates', [])) * 100).to_frame("nuokrypis_ct")
    rez["diena_nr"] = pd.to_datetime(rez.index.astype(str)).dayofweek
    prof_rink = rez.groupby("diena_nr")["nuokrypis_ct"].mean()

    enough = rhythm['weeks'] >= 6
    st.markdown("**Šios degalinės savaitės ritmas**")
    if not enough:
        st.caption(f"Per mažai palyginamų savaičių: {rhythm['weeks']}. Reikia bent 6 pilnų Pr–Pn savaičių.")
    else:
        rink_centered = prof_rink - prof_rink.mean()
        best = rhythm['best']
        st.caption(f"Analizuota {rhythm['weeks']} pilnų savaičių. Diena „{DAY_NAMES[best]}“ buvo vienintelė pigiausia {rhythm['wins']} iš jų ({rhythm['wins'] / rhythm['weeks']:.0%}).")
        if not rhythm['reliable']:
            st.info('Aiškios, stabiliai pasikartojančios pigiausios dienos nėra. Grafikas rodo istorinius skirtumus, bet konkrečios dienos nerekomenduojame.')
        else:
            st.success(f"Pasikartojanti istoriškai pigiausia darbo diena: {DAY_NAMES[best]}. Medianinis nuokrypis nuo savo savaitės vidurkio: {prof_own.loc[best, 'median']:+.1f} ct/l.")
        st.caption('Tai aprašomoji taisyklė, ne statistinė garantija: ≥6 pilnos savaitės, ≥60 % vienareikšmių laimėjimų, bent 0,5 ct/l skirtumas nuo antros dienos ir ta pati geriausia diena naujesnėje istorijos pusėje. Savaitgalio kainų nematome; bendras kainų kritimas gali paveikti savaitės profilį.')

        both = pd.DataFrame({
            "diena_nr": prof_own.index,
            "Prieš savo savaitės vidurkį (mediana)": prof_own["median"],
            "Santykinai su rinka (centruota)": rink_centered,
        }).melt("diena_nr", var_name="serija", value_name="nuokrypis_ct")
        both["diena"] = both["diena_nr"].map(DAY_NAMES)
        st.altair_chart(
            alt.Chart(both)
            .mark_bar()
            .encode(
                x=alt.X("diena:N", sort=list(DAY_NAMES.values()), title=None),
                xOffset=alt.XOffset("serija:N"),
                y=alt.Y("nuokrypis_ct:Q", title="Nuokrypis, ct/l"),
                color=alt.Color(
                    "serija:N", title=None,
                    scale=alt.Scale(range=["#4c8bf5", "#b0b8c4"]),
                    legend=alt.Legend(orient="bottom"),
                ),
                tooltip=[
                    alt.Tooltip("diena:N", title="Diena"),
                    alt.Tooltip("serija:N", title=" "),
                    alt.Tooltip("nuokrypis_ct:Q", title="ct/l", format="+.2f"),
                ],
            )
            .properties(height=280)
        )


view = st.selectbox(
    'Ką norite peržiūrėti?',
    [
        "🗺️ Žemėlapis",
        "🏙️ Pigiausios pagal miestą",
        "🏆 Pastoviai pigiausios",
        "📈 Tendencijos",
        "📋 Visos degalinės",
    ], key='view',
)

if view == '🗺️ Žemėlapis':
    mdf = fdf.merge(coords, on="adresas", how="left")
    mapped = mdf.dropna(subset=["lat", "lon"]).copy()

    if mapped.empty:
        st.info(
            "Degalinių koordinatės dar nesugeneruotos. Paleiskite "
            "`python3 geocode.py` — adresai geokoduojami vieną kartą ir "
            "įsimenami `geocache.json` faile."
        )
    else:
        if len(mapped) < len(mdf):
            st.caption(
                f"Rodoma {len(mapped)} iš {len(mdf)} degalinių — likusioms dar "
                "nerastos koordinatės."
            )
        mapped["color"] = mapped["nuokrypis_pct"].map(deviation_color)
        # nepateikusių šiandien — blankesni taškai
        stale_mask = mapped["senumas"] > 0
        mapped.loc[stale_mask, "color"] = mapped.loc[stale_mask, "color"].map(
            lambda c: c[:3] + [110]
        )
        mapped["kaina_txt"] = mapped["kaina"].map("{:.3f} €/l".format)
        mapped.loc[stale_mask, "kaina_txt"] = (
            mapped.loc[stale_mask, "kaina_txt"]
            + " (" + mapped.loc[stale_mask, "data"].astype(str) + ")"
        )
        mapped["nuokrypis_txt"] = mapped["nuokrypis_pct"].map("{:+.1f} %".format)

        col_leg, col_style = st.columns([3, 1], vertical_alignment="center")
        with col_leg:
            st.markdown(
                "🟢 pigiau nei rinkos vidurkis · 🟡 apie vidurkį · 🔴 brangiau "
                f"(vidurkis: **{market_avg:.3f} €/l**)"
            )
        MAP_STYLES = {
            "Detalus": "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
            "Šviesus": "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
            "Tamsus": "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        }
        with col_style:
            map_style_name = st.selectbox(
                "Žemėlapio stilius",
                list(MAP_STYLES),
                label_visibility="collapsed",
                key="map_style",
            )
        dark_map = map_style_name == "Tamsus"
        map_event = st.pydeck_chart(
            pdk.Deck(
                map_style=MAP_STYLES[map_style_name],
                initial_view_state=pdk.ViewState(
                    latitude=float(mapped.lat.median()) if global_city != 'Visos' else 55.2,
                    longitude=float(mapped.lon.median()) if global_city != 'Visos' else 23.9,
                    zoom=10 if global_city != 'Visos' else (5.0 if compact else 6.3),
                ),
                layers=[
                    pdk.Layer(
                        "ScatterplotLayer",
                        id="stations",
                        data=mapped[
                            [
                                "lat", "lon", "color", "imone", "adresas",
                                "savivaldybe", "kaina_txt", "nuokrypis_txt",
                                "stotis_id",
                            ]
                        ],
                        get_position=["lon", "lat"],
                        get_fill_color="color",
                        get_radius=2500,
                        radius_min_pixels=4,
                        radius_max_pixels=18,
                        pickable=True,
                        stroked=True,
                        get_line_color=(
                            [255, 255, 255, 120] if dark_map else [60, 60, 60, 140]
                        ),
                        line_width_min_pixels=1,
                    )
                ],
                tooltip={
                    "html": (
                        "<b>{imone}</b><br/>{adresas}<br/>{savivaldybe}<br/>"
                        "Kaina: <b>{kaina_txt}</b> ({nuokrypis_txt} nuo vidurkio) "
                        "<br/><i>Spustelėk — pamatysi istoriją ir savaitės ritmą</i>"
                    )
                },
            ),
            height=420 if compact else 650,
            on_select="rerun",
            selection_mode="single-object",
            key="stations_map",
        )
        picked = map_event.selection.objects.get("stations", [])
        if picked:
            st.divider()
            station_card(picked[0]["stotis_id"])

if view == '🏙️ Pigiausios pagal miestą':
    grouped = fdf.groupby("miestas")
    city_report = grouped.apply(
        lambda g: pd.Series(
            {
                "degaliniu": len(g),
                "vidurkis": g["kaina"].mean(),
                "min_kaina": g["kaina"].min(),
                "imone": g.loc[g["kaina"].idxmin(), "imone"],
                "adresas": g.loc[g["kaina"].idxmin(), "adresas"],
            }
        ),
        include_groups=False,
    ).reset_index()
    city_report["vs_rinka_pct"] = (
        (city_report["min_kaina"] - market_avg) / market_avg * 100
    )
    city_report = city_report.sort_values("min_kaina")

    st.subheader(f"Pigiausia degalinė kiekvienoje savivaldybėje — {FUEL_TYPES[fuel]}")
    st.dataframe(
        city_report,
        column_config={
            "miestas": st.column_config.TextColumn("Savivaldybė", pinned=True),
            "degaliniu": st.column_config.NumberColumn("Degalinių", format="%d"),
            "vidurkis": st.column_config.NumberColumn(
                "Miesto vidurkis", format="%.3f €"
            ),
            "min_kaina": st.column_config.NumberColumn(
                "Pigiausia kaina", format="%.3f €"
            ),
            "imone": "Pigiausia degalinė",
            "adresas": "Adresas",
            "vs_rinka_pct": st.column_config.NumberColumn(
                "Nuo rinkos vidurkio", format="%+.1f %%"
            ),
        },
        hide_index=True,
        height=600,
    )

    st.subheader("Miestų vidurkiai, palyginti su rinkos vidurkiu")
    chart_df = city_report.copy()
    chart_df["vidurkio_nuokrypis_pct"] = (
        (chart_df["vidurkis"] - market_avg) / market_avg * 100
    )
    chart_df = chart_df.sort_values("vidurkio_nuokrypis_pct")
    st.bar_chart(
        chart_df,
        x="miestas",
        y="vidurkio_nuokrypis_pct",
        x_label="Savivaldybė",
        y_label="Vidutinės kainos nuokrypis nuo rinkos, %",
        horizontal=False,
        height=420,
    )

if view == '🏆 Pastoviai pigiausios':
    st.markdown(
        "Reitingas pagal **medianinį nuokrypį nuo tos dienos rinkos vidurkio** "
        "per pasirinktą laikotarpį — mediana mažiau jautri pavienėms akcijoms. "
        "Rodomos tik degalinės, teikusios duomenis bent 60 % laikotarpio dienų."
    )
    period = st.segmented_control(
        "Laikotarpis",
        options=[7, 14, 30, 0],
        format_func=lambda d: f"{d} d." if d else "Visa istorija",
        default=14,
        key="stable_period",
    )
    if period is None:
        st.stop()

    agg, n_days = stability_report(hist[hist['tipas'] == fuel], period)
    if networks:
        agg = agg[agg.imone.isin(networks)]
    if global_city != 'Visos':
        agg = agg[agg.miestas == global_city]
    st.caption('TOP 10 % skaičiuojamas savivaldybėje tarp bent 10 tą dieną kainą pateikusių degalinių; riba apvalinama aukštyn, vienodos kainos įtraukiamos kartu. Rodiklio vardiklis — tik palyginamos dienos.')
    st.caption('14 d. pokytis: paskutinių 14 kalendorinių dienų medianinio nuokrypio nuo rinkos skirtumas prieš ankstesnes 14 d. Neigiamas skaičius — santykinai atpigo. Reikia bent 60 % dienų ir bent 3 stebėjimų abiejuose languose.')
    agg = agg.head(30).reset_index(drop=True)
    agg.index += 1
    if agg.empty:
        st.info('Nepakanka duomenų reitingui pagal pasirinktus filtrus.')
    if compact:
        for rank, row in agg.iterrows():
            with st.expander(f"{rank}. {row.imone} · {row.median_deviation * 100:+.1f} ct/l"):
                st.write(row.adresas)
                st.write(f"Kainos mediana **{row.mediana:.3f} €/l** · aprėptis **{row.coverage:.0f} %** ({row.dienu}/{n_days} d.)")
                if pd.notna(row.top10_pct):
                    st.write(f"Tarp pigiausių 10 %: **{row.top10_pct:.0f} %** iš {row.top10_days} palyginamų dienų.")
                if pd.notna(row.change_ct):
                    st.write(f"14 d. nuokrypio pokytis: **{row.change_ct:+.2f} ct/l**.")
                if st.button('Degalinės kortelė', key=f'stable_open_{row.stotis_id}'):
                    st.session_state['stable_selected'] = row.stotis_id
        selected_stable = st.session_state.get('stable_selected')
        if selected_stable in set(agg.stotis_id):
            station_card(selected_stable, 'stable')
    st.expander('Pilna reitingo lentelė', expanded=not compact).dataframe(
        agg,
        column_config={
            "stotis_id": None,
            "mediana": st.column_config.NumberColumn('Kainos mediana', format='%.3f €'),
            "median_deviation": st.column_config.NumberColumn('Medianinis nuokrypis', format='%+.3f €'),
            "coverage": st.column_config.ProgressColumn('Duomenų aprėptis', min_value=0, max_value=100, format='%.0f %%'),
            "top10_pct": st.column_config.ProgressColumn('Dienų tarp pigiausių 10 %', min_value=0, max_value=100, format='%.0f %%'),
            "top10_days": st.column_config.NumberColumn('TOP 10 % palyginamų dienų', format='%d'),
            "change_ct": st.column_config.NumberColumn('14 d. pokytis prieš ankstesnes 14 d., ct/l', format='%+.2f'),
            "imone": st.column_config.TextColumn("Tinklas", pinned=True),
            "miestas": "Savivaldybė",
            "adresas": "Adresas",
            "dienu": st.column_config.NumberColumn(
                "Dienų", format="%d",
                help=f"Iš {n_days} laikotarpio dienų",
            ),
            "vid_kaina": st.column_config.NumberColumn(
                "Vid. kaina", format="%.3f €"
            ),
            "vid_nuokrypis": st.column_config.NumberColumn(
                "Vid. nuokrypis nuo rinkos", format="%+.3f €"
            ),
            "pigiausia_pct": st.column_config.ProgressColumn(
                "Dienų % pigiausia savivaldybėje",
                min_value=0, max_value=100, format="%.0f %%",
            ),
        },
        height=600,
    )


if view == '📈 Tendencijos':
    st.caption(
        f"Istorija: {hist['data'].min()} – {hist['data'].max()} "
        f"({hist['data'].nunique()} d.). Duomenys kaupiami kasdien."
    )

    st.subheader("Rinkos vidurkis pagal kuro tipą")
    all_avg = hist.groupby(["data", "tipas"])["kaina"].mean().reset_index()
    all_avg["tipas"] = all_avg["tipas"].map(FUEL_TYPES)
    st.altair_chart(trend_chart(all_avg, "tipas", "Kuro tipas"))

    hf = hist[hist["tipas"] == fuel]

    st.subheader(f"{FUEL_TYPES[fuel]}: kainų rėžiai dienomis")
    rng = hf.groupby("data")["kaina"].agg(["min", "mean", "max"]).reset_index()
    rng.columns = ["data", "Pigiausia", "Rinkos vidurkis", "Brangiausia"]
    rng = rng.melt("data", var_name="rodiklis", value_name="kaina")
    st.altair_chart(trend_chart(rng, "rodiklis", None))

    st.subheader("Kada pigiausia pilti?")
    wd = hf.groupby("data")["kaina"].mean().reset_index(name="dienos_vid")
    wd["data_ts"] = pd.to_datetime(wd["data"])
    wd["savaite"] = wd["data_ts"].dt.isocalendar().week.astype(str) + "-" + wd[
        "data_ts"
    ].dt.isocalendar().year.astype(str)
    wd["sav_vid"] = wd.groupby("savaite")["dienos_vid"].transform("mean")
    wd["nuokrypis_ct"] = (wd["dienos_vid"] - wd["sav_vid"]) * 100
    wd["diena_nr"] = wd["data_ts"].dt.dayofweek
    weekday = (
        wd.groupby("diena_nr")["nuokrypis_ct"].mean().reset_index()
    )
    weekday["diena"] = weekday["diena_nr"].map(DAY_NAMES)
    worst = weekday.loc[weekday["nuokrypis_ct"].idxmax()]
    amplitude = weekday["nuokrypis_ct"].max() - weekday["nuokrypis_ct"].min()
    # perėjimų analizė: kas vyksta tarp gretimų skelbimo dienų
    seq = wd.sort_values("data_ts").set_index("data_ts")["dienos_vid"]
    chg = (seq.diff() * 100).dropna()
    prev_wd = seq.index.to_series().shift(1).dt.dayofweek.reindex(chg.index)
    gap = seq.index.to_series().diff().dt.days.reindex(chg.index)
    fri_mon = chg[(prev_wd == 4) & (chg.index.dayofweek == 0) & (gap == 3)].mean()
    mon_tue = chg[(prev_wd == 0) & (chg.index.dayofweek == 1) & (gap == 1)].mean()
    if amplitude < 1.5:
        st.markdown(
            f"**{FUEL_TYPES[fuel]}** ryškaus savaitės ciklo neturi "
            f"(amplitudė {amplitude:.1f} ct/l) — pilimo diena beveik nesvarbi. "
            "*(ENA skelbia tik darbo dienų kainas.)*"
        )
    else:
        st.markdown(
            f"**{FUEL_TYPES[fuel]}**: didžiausias vidutinis nuokrypis nuo tos "
            f"savaitės vidurkio — **{worst['diena']}**. "
            f"Penktadienio–pirmadienio ataskaitų vidutinis pokytis: "
            f"**{fri_mon:+.1f} ct/l**, pirmadienio–antradienio: **{mon_tue:+.1f} ct/l**. "
            "Tai istoriniai stebėjimai, ne prognozė. Savaitgalio kainų ir tikslaus "
            "perkainojimo laiko šie duomenys neparodo."
        )
    st.altair_chart(weekday_bar(weekday, "Nuokrypis nuo savaitės vidurkio, ct/l"))

    if networks:
        st.subheader("Pasirinkti tinklai prieš rinką")
        net = (
            hf[hf["imone"].isin(networks)]
            .groupby(["data", "imone"])["kaina"]
            .mean()
            .reset_index()
        )
        market = hf.groupby("data")["kaina"].mean().reset_index()
        market["imone"] = "— Rinkos vidurkis"
        comb = pd.concat([net, market], ignore_index=True)
        st.altair_chart(trend_chart(comb, "imone", "Tinklas"))
    else:
        st.info(
            "Viršuje pasirinkus tinklus, čia matysite jų kainų dinamiką "
            "palyginti su rinkos vidurkiu."
        )

if view == '📋 Visos degalinės':
    city = global_city
    tdf = fdf if city == "Visos" else fdf[fdf["miestas"] == city]
    tdf = (
        tdf[
            ["imone", "miestas", "adresas", "kaina", "nuokrypis",
             "nuokrypis_pct", "data", "stotis_id"]
        ]
        .sort_values("kaina")
        .reset_index(drop=True)
    )
    station_labels = {r.stotis_id: f"{r.imone} · {r.adresas} · {r.kaina:.3f} €/l" for r in tdf.itertuples()}
    quick = st.selectbox('Atverti degalinės kortelę', [''] + list(tdf.stotis_id),
                         format_func=lambda sid: station_labels.get(sid, 'Pasirinkite degalinę…'),
                         key='quick_station')
    if quick:
        station_card(quick, 'quick')
    if compact:
        page = st.selectbox('Sąrašo puslapis', range(1, max(2, (len(tdf) + 7) // 8 + 1)), key='station_page')
        for row in tdf.iloc[(page - 1) * 8:page * 8].itertuples():
            with st.container(border=True):
                st.markdown(f"**{row.imone} · {row.kaina:.3f} €/l**")
                st.write(row.adresas)
                st.caption(f"Kainos data {row.data} · {row.nuokrypis * 100:+.1f} ct/l nuo rinkos")
                def select_station(sid):
                    st.session_state.quick_station = sid
                st.button('Atverti istoriją ir navigaciją', key=f'open_{row.stotis_id}',
                          on_click=select_station, args=(row.stotis_id,))
    st.caption("Pilnoje lentelėje galima rūšiuoti kainas ir pasirinkti eilutę.")
    selection = st.expander('Pilna degalinių lentelė', expanded=not compact).dataframe(
        tdf,
        column_config={
            "imone": st.column_config.TextColumn("Įmonė", pinned=True),
            "miestas": "Savivaldybė",
            "adresas": "Adresas",
            "kaina": st.column_config.NumberColumn("Kaina", format="%.3f €"),
            "nuokrypis": st.column_config.NumberColumn(
                "Nuo vidurkio", format="%+.3f €"
            ),
            "nuokrypis_pct": st.column_config.NumberColumn(
                "Nuo vidurkio, %", format="%+.1f %%"
            ),
            "data": st.column_config.DateColumn("Kainos data", format="MM-DD"),
            "stotis_id": None,
        },
        hide_index=True,
        height=430,
        on_select="rerun",
        selection_mode="single-row",
    )

    if selection.selection.rows:
        st.divider()
        station_card(tdf.iloc[selection.selection.rows[0]]["stotis_id"], 'table')
