"""Kuro kainų Lietuvos degalinėse žemėlapis ir ataskaitos.

Duomenų šaltinis: Lietuvos energetikos agentūra (ena.lt), atnaujinama kasdien.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

import history
from fuel_data import FUEL_TYPES
from geocode import load_cache

st.set_page_config(
    page_title="Kuro kainos Lietuvoje",
    page_icon="⛽",
    layout="wide",
)


@st.cache_data(ttl=3600, show_spinner="Atnaujinami duomenys iš ena.lt…")
def load_data() -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """Grąžina (naujausia data, tos dienos duomenys, visa istorija).

    Kas valandą patikrina, ar ENA nepaskelbė naujų dienų, ir jas parsisiunčia.
    """
    history.sync()
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
    return str(latest), df, hist


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


date, df, hist = load_data()
coords = load_coords()

st.title("⛽ Kuro kainos Lietuvoje")
stale_n = df.loc[df["senumas"] > 0, "stotis_id"].nunique()
st.caption(
    f"Duomenys: [Lietuvos energetikos agentūra](https://www.ena.lt/dk-visa-informacija/) · "
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
        default="95 benzinas",
    )
if not fuel:
    st.stop()

fdf = df[df["tipas"] == fuel].copy()
# Rinkos vidurkis skaičiuojamas nuo visos rinkos — filtrai jo nekeičia,
# kad nuokrypiai visada rodytų palyginimą su rinka.
market_avg = fdf["kaina"].mean()

network_counts = fdf["imone"].value_counts()
with col_net:
    networks = st.multiselect(
        "Degalinių tinklai",
        options=list(network_counts.index),
        format_func=lambda x: f"{x} ({network_counts[x]})",
        placeholder="Visi tinklai",
    )
if networks:
    fdf = fdf[fdf["imone"].isin(networks)]
    if fdf.empty:
        st.warning("Pasirinkti tinklai neturi šio tipo degalų.")
        st.stop()
fdf["nuokrypis"] = fdf["kaina"] - market_avg
fdf["nuokrypis_pct"] = fdf["nuokrypis"] / market_avg * 100

cheapest = fdf.loc[fdf["kaina"].idxmin()]
priciest = fdf.loc[fdf["kaina"].idxmax()]

with st.container(horizontal=True):
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


def station_card(sid: str) -> None:
    """Degalinės kortelė: šiandienos būklė, istorija ir savaitės dienų profilis."""
    sh = hist_fuel[hist_fuel["stotis_id"] == sid]
    if sh.empty:
        st.info("Ši degalinė neturi istorijos pasirinktam kuro tipui.")
        return
    last = sh[sh["data"] == sh["data"].max()].iloc[0]

    st.subheader(f"⛽ {last['imone']} — {last['adresas']}")

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
                "Šiandienos kaina"
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
        st.metric(
            "Vid. nuokrypis nuo rinkos",
            f"{sh_dev.mean() * 100:+.1f} ct/l",
            border=True,
            help="Per visą turimą istoriją",
        )
        st.metric(
            "Pigiausia savivaldybėje",
            f"{(cheapest_days['rank'] <= 1).mean() * 100:.0f} % dienų",
            border=True,
        )
        st.metric("Istorijos dienų", f"{sh['data'].nunique()}", border=True)

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
    own = sh_daily.to_frame("kaina")
    own["ts"] = pd.to_datetime(own.index.astype(str))
    iso = own["ts"].dt.isocalendar()
    own["savaite"] = iso["year"].astype(str) + "-" + iso["week"].astype(str)
    own["sav_vid"] = own.groupby("savaite")["kaina"].transform("mean")
    own["nuokrypis_ct"] = (own["kaina"] - own["sav_vid"]) * 100
    own["diena_nr"] = own["ts"].dt.dayofweek

    prof_own = own.groupby("diena_nr")["nuokrypis_ct"].agg(["mean", "count"])
    rez = (sh_dev * 100).to_frame("nuokrypis_ct")
    rez["diena_nr"] = pd.to_datetime(rez.index.astype(str)).dayofweek
    prof_rink = rez.groupby("diena_nr")["nuokrypis_ct"].mean()

    enough = len(prof_own) >= 4 and prof_own["count"].min() >= 5
    st.markdown("**Šios degalinės savaitės ritmas**")
    if not enough:
        st.caption("Per mažai istorijos savaitės tendencijai įvertinti.")
    else:
        amp_own = prof_own["mean"].max() - prof_own["mean"].min()
        # savo ritmo dalis, nepaaiškinama rinkos ritmu
        rink_centered = prof_rink - prof_rink.mean()
        amp_savas = rink_centered.max() - rink_centered.min()
        best = prof_own["mean"].idxmin()
        if amp_own < 1.5:
            st.markdown(
                "Šios degalinės kainos per savaitę beveik nesikeičia "
                f"(amplitudė {amp_own:.1f} ct/l) — diena čia nesvarbi."
            )
        else:
            source = (
                "tai daugiausia jos pačios akcija, ne rinkos banga"
                if amp_savas >= 0.6 * amp_own
                else "iš esmės ji juda kartu su visa rinka"
            )
            st.markdown(
                f"Šioje degalinėje istoriškai pigiausia "
                f"**{DAY_NAMES[best].lower()[:-2]}iais** — vidutiniškai "
                f"{prof_own.loc[best, 'mean']:+.1f} ct/l nuo jos savaitės "
                f"vidurkio; {source}."
            )

        both = pd.DataFrame({
            "diena_nr": prof_own.index,
            "Prieš savo savaitės vidurkį": prof_own["mean"],
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


tab_map, tab_cities, tab_stable, tab_trends, tab_all = st.tabs(
    [
        "🗺️ Žemėlapis",
        "🏙️ Pigiausios pagal miestą",
        "🏆 Pastoviai pigiausios",
        "📈 Tendencijos",
        "📋 Visos degalinės",
    ]
)

with tab_map:
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

        st.markdown(
            "🟢 pigiau nei rinkos vidurkis · 🟡 apie vidurkį · 🔴 brangiau "
            f"(vidurkis: **{market_avg:.3f} €/l**)"
        )
        map_event = st.pydeck_chart(
            pdk.Deck(
                map_style=None,
                initial_view_state=pdk.ViewState(
                    latitude=55.2, longitude=23.9, zoom=6.3
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
                        get_line_color=[255, 255, 255, 120],
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
            height=650,
            on_select="rerun",
            selection_mode="single-object",
            key="stations_map",
        )
        picked = map_event.selection.objects.get("stations", [])
        if picked:
            st.divider()
            station_card(picked[0]["stotis_id"])

with tab_cities:
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

with tab_stable:
    st.markdown(
        "Reitingas pagal **vidutinį nuokrypį nuo tos dienos rinkos vidurkio** "
        "per pasirinktą laikotarpį — vienadienės akcijos rezultato nenulemia. "
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

    shf = hist[hist["tipas"] == fuel].copy()
    if networks:
        shf = shf[shf["imone"].isin(networks)]
    if period:
        cutoff = pd.Timestamp(str(hist["data"].max())) - pd.Timedelta(days=period - 1)
        shf = shf[pd.to_datetime(shf["data"]) >= cutoff]

    n_days = shf["data"].nunique()
    # nuokrypis nuo VISOS rinkos dienos vidurkio (ne filtruotos)
    day_avg = (
        hist[hist["tipas"] == fuel].groupby("data")["kaina"].mean().rename("dienos_vid")
    )
    shf = shf.join(day_avg, on="data")
    shf["nuokrypis"] = shf["kaina"] - shf["dienos_vid"]
    shf["pigiausia_sav"] = (
        shf.groupby(["data", "miestas"])["kaina"].rank(method="min") <= 1
    )

    agg = (
        shf.groupby(["imone", "miestas", "adresas"])
        .agg(
            dienu=("data", "nunique"),
            vid_kaina=("kaina", "mean"),
            vid_nuokrypis=("nuokrypis", "mean"),
            pigiausia_pct=("pigiausia_sav", "mean"),
        )
        .reset_index()
    )
    agg = agg[agg["dienu"] >= 0.6 * n_days]
    agg["pigiausia_pct"] *= 100

    city_stable = st.selectbox(
        "Savivaldybė",
        ["Visos"] + sorted(agg["miestas"].unique()),
        key="stable_city",
    )
    if city_stable != "Visos":
        agg = agg[agg["miestas"] == city_stable]
    agg = agg.sort_values("vid_nuokrypis").head(30).reset_index(drop=True)
    agg.index += 1

    st.dataframe(
        agg,
        column_config={
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


with tab_trends:
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
    prev_wd = chg.index.to_series().shift(1).dt.dayofweek
    fri_mon = chg[(prev_wd == 4) & (chg.index.dayofweek == 0)].mean()
    mon_tue = chg[(prev_wd == 0) & (chg.index.dayofweek == 1)].mean()
    if amplitude < 1.5:
        st.markdown(
            f"**{FUEL_TYPES[fuel]}** ryškaus savaitės ciklo neturi "
            f"(amplitudė {amplitude:.1f} ct/l) — pilimo diena beveik nesvarbi. "
            "*(ENA skelbia tik darbo dienų kainas.)*"
        )
    else:
        st.markdown(
            f"**{FUEL_TYPES[fuel]}** kainos savaitės eigoje leidžiasi ir žemiausią "
            f"tašką pasiekia **savaitgalio–pirmadienio lange**: nuo penktadienio iki "
            f"pirmadienio jos nukrenta dar vidutiniškai **{fri_mon:+.1f} ct/l** "
            f"(savaitgalių ENA neskelbia, tad ar sekmadienis pigesnis už pirmadienį — "
            f"nematome). Brangiausia — **{worst['diena'].lower()[:-2]}į**: "
            f"pirmadienio–antradienio naktį kainos „perkraunamos“ "
            f"vidutiniškai **{mon_tue:+.1f} ct/l** šuoliu. "
            "*(ENA skelbia tik darbo dienų kainas.)*"
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

with tab_all:
    city = st.selectbox(
        "Savivaldybė",
        ["Visos"] + sorted(fdf["miestas"].unique()),
    )
    tdf = fdf if city == "Visos" else fdf[fdf["miestas"] == city]
    tdf = (
        tdf[
            ["imone", "miestas", "adresas", "kaina", "nuokrypis",
             "nuokrypis_pct", "data", "stotis_id"]
        ]
        .sort_values("kaina")
        .reset_index(drop=True)
    )
    st.caption("Pažymėk eilutę — apačioje atsivers degalinės kainų istorija.")
    selection = st.dataframe(
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
        station_card(tdf.iloc[selection.selection.rows[0]]["stotis_id"])
