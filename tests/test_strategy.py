import numpy as np
import pandas as pd
import pytest

from scalpbot.backtest import backtest, summarize
from scalpbot.bot import seconds_to_next_close
from scalpbot.data import closed_only
from scalpbot.strategy import StrategyConfig, add_signals, compute, daily_pivots, latest_signal


def make_df(n=3000, seed=1):
    rng = np.random.default_rng(seed)
    drift = np.sin(np.linspace(0, 12 * np.pi, n)) * 0.0004
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.0015, n)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.0008, n)) * close
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + spread,
            "low": np.minimum(open_, close) - spread,
            "close": close,
            "volume": 1.0,
        },
        index=idx,
    )


def test_indicators_sane():
    d = compute(make_df(), StrategyConfig())
    tail = d.iloc[400:]
    assert tail["rsi"].between(0, 100).all()
    assert set(tail["st_dir"].unique()) <= {-1, 1}
    assert tail[["sma_fast", "sma_slow", "dema", "atr", "st"]].notna().all().all()


def test_too_few_candles_rejected():
    with pytest.raises(ValueError):
        compute(make_df(100), StrategyConfig())


def test_pivot_math():
    idx = pd.date_range("2026-01-01", periods=576, freq="5min", tz="UTC")
    df = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}, index=idx)
    df.iloc[10, df.columns.get_loc("high")] = 110.0
    df.iloc[20, df.columns.get_loc("low")] = 90.0
    piv = daily_pivots(df)
    assert piv.iloc[:288].isna().all().all()          # no previous day yet
    day2 = piv.iloc[300]
    assert day2["P"] == pytest.approx(100.0)
    assert day2["R1"] == pytest.approx(110.0)
    assert day2["S1"] == pytest.approx(90.0)


def test_unfiltered_signals_equal_crosses():
    cfg = StrategyConfig(require_dema_bias=False, require_supertrend=False, require_rsi=False,
                         require_pivot_room=False, dema_cross_mode="off")
    d = add_signals(compute(make_df(), cfg), cfg)
    assert d["cross_up"].sum() > 5
    assert d["long_sig"].sum() == d["cross_up"].sum()
    assert d["short_sig"].sum() == d["cross_dn"].sum()
    assert not (d["long_sig"] & d["short_sig"]).any()


def test_filters_only_remove_signals():
    loose = StrategyConfig(require_dema_bias=False, require_supertrend=False, require_rsi=False, require_pivot_room=False)
    strict = StrategyConfig()
    df = make_df()
    a = add_signals(compute(df, loose), loose)
    b = add_signals(compute(df, strict), strict)
    assert (b["long_sig"] & ~a["long_sig"]).sum() == 0
    assert b["long_sig"].sum() <= a["long_sig"].sum()


def test_latest_signal_fields():
    cfg = StrategyConfig(require_dema_bias=False, require_supertrend=False, require_rsi=False, require_pivot_room=False)
    d = add_signals(compute(make_df(), cfg), cfg)
    hit = d.index[d["long_sig"] | d["short_sig"]][-1]
    sig = latest_signal(d.loc[:hit])
    assert sig is not None and sig.side in ("LONG", "SHORT")
    assert (sig.stop < sig.price) == (sig.side == "LONG")


def test_backtest_runs_and_is_consistent():
    cfg = StrategyConfig(require_dema_bias=False)
    trades = backtest(make_df(), cfg)
    stats = summarize(trades)
    assert stats["trades"] == len(trades) > 0
    assert (trades["exit_time"] >= trades["entry_time"]).all()
    assert set(trades["side"]) <= {"LONG", "SHORT"}
    assert trades["trigger"].isin({"SMA cross", "200 DEMA cross", "SMA + DEMA cross"}).all()
    assert "by_trigger" in stats


def test_closed_only_drops_forming_candle():
    df = make_df(10)
    now = df.index[-1] + pd.Timedelta(minutes=2)  # last candle still forming
    assert closed_only(df, 5, now).index[-1] == df.index[-2]


def test_seconds_to_next_close():
    t = pd.Timestamp("2026-10-15 18:22:30", tz="UTC").timestamp()
    assert seconds_to_next_close(t, 5, 5.0) == pytest.approx(155.0)


# --------------------------------------------------------------------------- 200 DEMA cross trigger
LOOSE = dict(require_dema_bias=False, require_supertrend=False, require_rsi=False, require_pivot_room=False)


def _with_lines(fast, slow, dema=100.0, **kw):
    """Real frame with the SMA / DEMA columns replaced by hand-made lines, then signals."""
    cfg = StrategyConfig(**LOOSE, **kw)
    ind = compute(make_df(), cfg)
    i = np.arange(len(ind))
    ind["sma_fast"], ind["sma_slow"], ind["dema"] = fast(i), slow(i), dema
    return add_signals(ind, cfg)


def _rows(series):
    return list(np.flatnonzero(series.to_numpy()))


def test_dema_cross_up_long_modes():
    f = lambda i: np.where(i < 500, 98.0, 103.0)   # 22 crosses up through the DEMA at row 500
    s = lambda i: np.where(i < 502, 97.0, 101.0)   # 33 follows at row 502 (22 stays above 33: no SMA cross)
    d = _with_lines(f, s, dema_cross_mode="both")
    assert _rows(d["long_sig"]) == [502]            # fires when BOTH lines are above
    assert d["trigger"].iloc[502] == "200 DEMA cross"
    assert not d["short_sig"].any() and not d["cross_up"].any() and not d["cross_dn"].any()
    assert _rows(_with_lines(f, s, dema_cross_mode="fast")["long_sig"]) == [500]
    assert not _with_lines(f, s, dema_cross_mode="off")["long_sig"].any()


def test_dema_cross_down_short():
    f = lambda i: np.where(i < 600, 102.0, 97.0)
    s = lambda i: np.where(i < 602, 103.0, 98.0)
    d = _with_lines(f, s, dema_cross_mode="both")
    assert _rows(d["short_sig"]) == [602]
    assert d["trigger"].iloc[602] == "200 DEMA cross"
    assert not d["long_sig"].any()
    assert _rows(_with_lines(f, s, dema_cross_mode="fast")["short_sig"]) == [600]


def test_trigger_label_when_both_fire():
    f = lambda i: np.where(i < 500, 98.0, 103.0)
    s = lambda i: np.where(i < 500, 99.0, 101.0)    # 22 crosses 33 AND both cross the DEMA on row 500
    d = _with_lines(f, s, dema_cross_mode="both")
    assert _rows(d["long_sig"]) == [500]
    assert d["trigger"].iloc[500] == "SMA + DEMA cross"


def test_conflicting_triggers_cancel():
    f = lambda i: np.where(i < 700, 101.0, 99.0)
    s = lambda i: np.where(i < 700, 102.0, 98.0)    # SMA cross up and DEMA cross down on the same candle
    d = _with_lines(f, s, dema_cross_mode="both")
    assert d["cross_up"].iloc[700] and d["dema_dn"].iloc[700]
    assert not d["long_sig"].any() and not d["short_sig"].any()


def test_invalid_dema_mode_rejected():
    cfg = StrategyConfig(dema_cross_mode="sideways")
    with pytest.raises(ValueError):
        add_signals(compute(make_df(), StrategyConfig()), cfg)
