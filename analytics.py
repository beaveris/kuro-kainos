"""Planavimo rodikliai iš faktinių dienos stebėjimų (be kainų perkėlimo)."""
import math
import pandas as pd


def stability_report(data, days=14):
    data = data.copy()
    data['ts'] = pd.to_datetime(data['data'])
    end = data.ts.max()
    data['deviation'] = data.kaina - data.groupby('data').kaina.transform('mean')
    groups = data.groupby(['data', 'miestas'])
    size = groups.stotis_id.transform('nunique')
    rank = groups.kaina.rank(method='min')
    data['top10'] = (rank <= size.map(lambda n: math.ceil(n / 10))).where(size >= 10)
    data['cheapest'] = rank == 1
    current = data[data.ts >= end - pd.Timedelta(days=days - 1)] if days else data
    n_days = current.data.nunique()
    result = current.sort_values('ts').groupby(['stotis_id', 'imone', 'miestas']).agg(
        adresas=('adresas', 'last'), dienu=('data', 'nunique'),
        vid_kaina=('kaina', 'mean'), mediana=('kaina', 'median'),
        vid_nuokrypis=('deviation', 'mean'), median_deviation=('deviation', 'median'),
        pigiausia_pct=('cheapest', 'mean'), top10_pct=('top10', 'mean'),
        top10_days=('top10', 'count'),
    ).reset_index()
    result['coverage'] = result.dienu / max(n_days, 1) * 100
    result = result[result.coverage >= 60].copy()
    result[['pigiausia_pct', 'top10_pct']] *= 100
    result['change_ct'] = float('nan')
    # Vienodo ilgio 14 kalendorinių dienų langai, bent 60 % stebėjimų abiejuose.
    windows = []
    for offset in (0, 14):
        window = data[(data.ts <= end - pd.Timedelta(days=offset)) &
                      (data.ts >= end - pd.Timedelta(days=offset + 13))]
        stats = window.groupby('stotis_id').agg(value=('deviation', 'median'), n=('data', 'nunique'))
        stats = stats[stats.n >= max(3, math.ceil(window.data.nunique() * .6))]
        windows.append(stats.value)
    delta = (windows[0] - windows[1]) * 100
    result['change_ct'] = result.stotis_id.map(delta)
    return result.sort_values(['median_deviation', 'vid_nuokrypis']), n_days


def weekday_profile(prices):
    """Tik pilnos Pr–Pn savaitės; išvados kriterijai yra euristika, ne prognozė."""
    frame = prices.rename('price').to_frame()
    frame['ts'] = pd.to_datetime(frame.index)
    frame['day'] = frame.ts.dt.dayofweek
    frame['week'] = frame.ts.dt.to_period('W-SUN')
    frame = frame[frame.day < 5]
    matrix = frame.pivot_table(index='week', columns='day', values='price', aggfunc='mean')
    matrix = matrix.reindex(columns=range(5)).dropna()
    count = len(matrix)
    if not count:
        return {'weeks': 0, 'profile': pd.DataFrame(), 'reliable': False}
    centered = matrix.sub(matrix.mean(axis=1), axis=0) * 100
    profile = centered.agg(['mean', 'median']).T
    best = int(profile['median'].idxmin())
    # Lygiomis kainomis visa savaitė nesuteikia penkių „laimėjimų“.
    unique_wins = matrix.eq(matrix.min(axis=1), axis=0).sum(axis=1) == 1
    wins = int((matrix.idxmin(axis=1).eq(best) & unique_wins).sum())
    recent = centered.tail(max(3, count // 2)).median().idxmin()
    gap = float(profile['median'].nsmallest(2).iloc[1] - profile.loc[best, 'median'])
    reliable = count >= 6 and wins / count >= .6 and gap >= .5 and recent == best
    return {'weeks': count, 'profile': profile, 'best': best, 'wins': wins,
            'reliable': reliable, 'dates': frame[frame.week.isin(matrix.index)].index}
