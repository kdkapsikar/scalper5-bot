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
    cfg = StrategyConfig(require_dema_bias=False, require_supertrend=False, require_rsi=False, require_pivot_room=False)
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


def test_closed_only_drops_forming_candle():
    df = make_df(10)
    now = df.index[-1] + pd.Timedelta(minutes=2)  # last candle still forming
    assert closed_only(df, 5, now).index[-1] == df.index[-2]


def test_seconds_to_next_close():
    t = pd.Timestamp("2026-10-15 18:22:30", tz="UTC").timestamp()
    assert seconds_to_next_close(t, 5, 5.0) == pytest.approx(155.0)
