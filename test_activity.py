import pandas as pd
from activity import conservative_activity_qualifies


def make_intraday(days, bars_per_day=5):
    rows=[]
    for d in days:
        for i in range(bars_per_day):
            rows.append((pd.Timestamp(d)+pd.Timedelta(hours=9, minutes=i*5), 100))
    df=pd.DataFrame(rows, columns=['DateTime','Volume']).set_index('DateTime')
    return df


def test_activity_passes_with_five_positive_bars_each_day():
    days=pd.bdate_range('2026-07-01', periods=20)
    df=make_intraday(days, 5)
    ok, details=conservative_activity_qualifies(df, list(days), days[-1], 5, 20)
    assert ok
    assert details['minimum_nonempty_bars'] == 5


def test_activity_rejects_day_with_four_bars():
    days=pd.bdate_range('2026-07-01', periods=20)
    df=make_intraday(days, 5)
    bad=days[8].normalize()
    mask=~((df.index.normalize()==bad) & (df.groupby(df.index.normalize()).cumcount()==4))
    df=df[mask]
    ok, details=conservative_activity_qualifies(df, list(days), days[-1], 5, 20)
    assert not ok
    assert details['minimum_nonempty_bars'] == 4


def test_activity_rejects_missing_day():
    days=pd.bdate_range('2026-07-01', periods=20)
    df=make_intraday(days[:-1], 5)
    ok, details=conservative_activity_qualifies(df, list(days), days[-1], 5, 20)
    assert not ok
    assert details['missing_days'] == 1
