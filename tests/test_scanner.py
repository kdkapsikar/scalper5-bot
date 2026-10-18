"""Universe building, scan/analysis logic, the CLI and the Streamlit app (run headless with AppTest)."""
import re
import zlib
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scalpbot import scan as sc
from scalpbot import universe
from scalpbot.brokers import AuthExpired
from scalpbot.chart import make_chart
from scalpbot.strategy import StrategyConfig, add_signals, compute
from scalpbot.universe import build_universe, pick_futures
from scalpbot.watchlist import Instrument
from test_strategy import LOOSE, make_df

TODAY = date(2026, 10, 16)
ROOT = Path(__file__).resolve().parent.parent


def ms(d):
    return int(pd.Timestamp(d, tz="Asia/Kolkata").timestamp() * 1000)


def fut(sym, expiry, key, utype="EQUITY", seg="NSE_FO"):
    return {"segment": seg, "instrument_type": "FUT", "underlying_symbol": sym, "underlying_type": utype,
            "expiry": ms(expiry), "instrument_key": key, "trading_symbol": f"{sym} FUT"}


NSE_ROWS = [
    fut("NIFTY", "2026-10-27", "NSE_FO|1", "INDEX"), fut("NIFTY", "2026-11-24", "NSE_FO|2", "INDEX"),
    fut("BANKNIFTY", "2026-10-27", "NSE_FO|3", "INDEX"),
    fut("RELIANCE", "2026-09-29", "NSE_FO|9"), fut("RELIANCE", "2026-10-27", "NSE_FO|4"),
    fut("RELIANCE", "2026-11-24", "NSE_FO|5"), fut("TCS", "2026-10-27", "NSE_FO|6"),
    {"segment": "NSE_FO", "instrument_type": "CE", "underlying_symbol": "NIFTY", "expiry": ms("2026-10-27"),
     "instrument_key": "NSE_FO|opt"},
    {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "RELIANCE", "instrument_key": "NSE_EQ|INE"},
]
MCX_ROWS = [fut("GOLDM", "2026-12-04", "MCX_FO|1", "COMMODITY", "MCX_FO")]
CRYPTO = ["BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUUSDT"]


# --------------------------------------------------------------------------- universe
def test_pick_futures_nearest_and_roll():
    p = pick_futures(NSE_ROWS, TODAY)
    assert {k: v["instrument_key"] for k, v in p.items()} == {
        "NIFTY": "NSE_FO|1", "BANKNIFTY": "NSE_FO|3", "RELIANCE": "NSE_FO|4", "TCS": "NSE_FO|6"}   # no options/cash/expired
    r = pick_futures(NSE_ROWS, TODAY, roll_days=15)
    assert r["NIFTY"]["instrument_key"] == "NSE_FO|2" and r["RELIANCE"]["instrument_key"] == "NSE_FO|5"
    assert r["TCS"]["instrument_key"] == "NSE_FO|6" and r["BANKNIFTY"]["instrument_key"] == "NSE_FO|3"  # no later month


def test_build_universe_groups_cache_and_warnings(monkeypatch, tmp_path):
    loads = []
    monkeypatch.setattr(universe, "_load_instruments", lambda ex: loads.append(ex) or (NSE_ROWS if ex == "NSE" else MCX_ROWS))
    y = tmp_path / "w.yaml"
    y.write_text("universe:\n  mcx: [GOLDM, NOPE]\ninstruments:\n  - {name: X, source: binance, symbol: BTCUSDT}\n")
    insts, warns = build_universe(str(y), today=TODAY, state_dir=str(tmp_path))
    assert [i.name for i in insts] == ["BANKNIFTY FUT", "NIFTY FUT", "RELIANCE FUT", "TCS FUT", "GOLDM FUT", *CRYPTO, "X"]
    groups = {i.name: i.group for i in insts}
    assert groups["NIFTY FUT"] == groups["BANKNIFTY FUT"] == "Index futures"
    assert groups["RELIANCE FUT"] == "Stock futures" and groups["GOLDM FUT"] == "MCX futures"
    assert groups["BTCUSDT"] == "Crypto" and groups["X"] == "Custom"
    assert next(i for i in insts if i.name == "NIFTY FUT").instrument_key == "NSE_FO|1"
    assert any("NOPE" in w for w in warns)
    assert loads == ["NSE", "MCX"]
    insts2, warns2 = build_universe(str(y), today=TODAY, state_dir=str(tmp_path))     # served from today's cache
    assert loads == ["NSE", "MCX"] and [i.name for i in insts2] == [i.name for i in insts] and any("NOPE" in w for w in warns2)
    build_universe(str(y), today=date(2026, 10, 17), state_dir=str(tmp_path))          # next day: reloads
    assert loads == ["NSE", "MCX", "NSE", "MCX"]


def test_build_universe_only_exclude_and_toggles(monkeypatch, tmp_path):
    monkeypatch.setattr(universe, "_load_instruments", lambda ex: NSE_ROWS)
    y = tmp_path / "w.yaml"
    y.write_text("universe:\n  only: [RELIANCE]\n  exclude: [BANKNIFTY]\n  crypto: [BTCUSDT]\n")
    insts, _ = build_universe(str(y), today=TODAY, state_dir=str(tmp_path))
    assert [i.name for i in insts] == ["NIFTY FUT", "RELIANCE FUT", "BTCUSDT"]
    y.write_text("universe:\n  stock_futures: false\n  crypto: []\n")
    insts, _ = build_universe(str(y), today=TODAY, state_dir=str(tmp_path))
    assert [i.name for i in insts] == ["BANKNIFTY FUT", "NIFTY FUT"]


def test_build_universe_survives_upstox_outage(monkeypatch, tmp_path):
    def boom(ex):
        raise RuntimeError("offline")

    monkeypatch.setattr(universe, "_load_instruments", boom)
    y = tmp_path / "w.yaml"
    y.write_text("universe: {}\n")
    insts, warns = build_universe(str(y), today=TODAY, state_dir=str(tmp_path))
    assert [i.name for i in insts] == CRYPTO
    assert warns and "Upstox" in warns[0]


# --------------------------------------------------------------------------- analysis
def _frame(fast, slow, dema, cfg):
    ind = compute(make_df(), cfg)
    i = np.arange(len(ind))
    ind["sma_fast"], ind["sma_slow"], ind["dema"] = fast(i), slow(i), dema
    return add_signals(ind, cfg)


INST = Instrument(name="TEST FUT", source="upstox", instrument_key="k", group="Stock futures")
LOOSE_CFG = StrategyConfig(**LOOSE)


def _signal_frame(slow_at):
    f = lambda i: np.where(i < slow_at - 1, 98.0, 103.0)    # 22 crosses the DEMA, 33 follows one candle later
    s = lambda i: np.where(i < slow_at, 97.0, 101.0)
    return _frame(f, s, 100.0, LOOSE_CFG)


def _now(ind):
    return ind.index[-1] + pd.Timedelta(minutes=5, seconds=30)


def test_analyse_long_on_latest_candle():
    ind = _signal_frame(2999)
    r = sc.analyse(ind, INST, LOOSE_CFG, 3, now=_now(ind))
    assert (r.status, r.side, r.age, r.trigger, r.stale) == ("LONG", "LONG", 0, "200 DEMA cross", False)
    assert r.stop < r.signal_price and r.signal_close == ind.index[-1] + pd.Timedelta(minutes=5)
    assert set(r.checks) == {"LONG", "SHORT"} and len(r.checks["LONG"]) == 5
    assert "latest closed candle" in sc.headline(r, 3)


def test_analyse_lookback_window_and_age():
    ind = _signal_frame(2997)                        # signal is 2 candles old
    r = sc.analyse(ind, INST, LOOSE_CFG, 3, now=_now(ind))
    assert (r.status, r.age) == ("LONG", 2) and "2 candles ago" in sc.headline(r, 3)
    assert sc.analyse(ind, INST, LOOSE_CFG, 2, now=_now(ind)).status == "NONE"       # outside a 2-candle window


def test_analyse_blocked_names_the_failing_filter():
    cfg = StrategyConfig()                           # all filters on
    f = lambda i: np.where(i < 2998, 998.0, 1003.0)
    s = lambda i: np.where(i < 2999, 997.0, 1001.0)
    ind = _frame(f, s, 1000.0, cfg)                  # price ~100 is far below a 1000 DEMA
    r = sc.analyse(ind, INST, cfg, 3, now=_now(ind))
    assert r.status == "BLOCKED" and r.side == "LONG"
    assert any("200 DEMA" in b for b in r.blocked_by)
    assert "blocked by" in sc.headline(r, 3)


def test_analyse_stale_market():
    ind = _signal_frame(2999)
    late = ind.index[-1] + pd.Timedelta(hours=5)
    assert sc.analyse(ind, INST, LOOSE_CFG, 3, now=late).status == "STALE"
    r = sc.analyse(ind, INST, LOOSE_CFG, 3, ignore_stale=True, now=late)
    assert r.status == "LONG" and r.stale and r.snapshot["Last full signal"].startswith("LONG")


def test_to_frame_and_checks_frame():
    ind = _signal_frame(2999)
    r = sc.analyse(ind, INST, LOOSE_CFG, 3, now=_now(ind))
    df = sc.to_frame([r, sc.Result(name="Z", status="NONE")])
    assert list(df["Ticker"]) == ["TEST FUT"] and df.loc[0, "Signal"] == "🟢 LONG" and df.loc[0, "Candles ago"] == 0
    cf = sc.checks_frame(r.checks["LONG"])
    assert list(cf.columns) == ["Condition", "Status", "Detail"] and cf["Status"].iloc[0] == "✅"
    off = StrategyConfig(require_rsi=False)
    row = ind.iloc[-1]
    assert any(c.name.startswith("RSI") and not c.required for c in sc.checks_for(row, off, "LONG"))


def _recent_frame(seed_name: str, n=1200):
    df = make_df(n, seed=zlib.crc32(seed_name.encode()) % 1000)
    end = pd.Timestamp.now(tz="UTC").floor("5min") - pd.Timedelta(minutes=5)     # last closed candle
    df.index = pd.date_range(end=end, periods=n, freq="5min", tz="UTC")
    return df


def test_scan_isolates_failures(monkeypatch):
    insts = [Instrument(name="OK1", source="coinswitch", symbol="A", group="Crypto"),
             Instrument(name="UP1", source="upstox", instrument_key="k1", group="Stock futures"),
             Instrument(name="UP2", source="upstox", instrument_key="k2", group="Stock futures"),
             Instrument(name="BAD", source="coinswitch", symbol="B", group="Crypto"),
             Instrument(name="SHORTHIST", source="coinswitch", symbol="C", group="Crypto")]

    def fake(inst, n=1000):
        if inst.source == "upstox":
            raise AuthExpired("token expired")
        if inst.name == "BAD":
            raise RuntimeError("symbol not found")
        if inst.name == "SHORTHIST":
            return _recent_frame("x", 100)
        return _recent_frame(inst.name)

    monkeypatch.setattr(sc, "fetch_candles", fake)
    seen = []
    res = sc.scan(insts, {}, 3, workers=1, progress=lambda d, t: seen.append((d, t)))
    by = {r.name: r for r in res}
    assert by["OK1"].status in ("LONG", "SHORT", "BLOCKED", "NONE")
    assert by["UP1"].status == by["UP2"].status == "ERROR" and "login" in by["UP1"].error
    assert "symbol not found" in by["BAD"].error and "300 candles" in by["SHORTHIST"].error
    assert seen[-1] == (5, 5)


def test_cli_scan_and_ticker(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SCALP_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(universe, "_load_instruments", lambda ex: NSE_ROWS)
    monkeypatch.setattr(sc, "fetch_candles", lambda inst, n=1000: _recent_frame(inst.name))
    y = tmp_path / "w.yaml"
    y.write_text("universe:\n  crypto: [BTCUSDT]\n")
    assert sc.main(["--watchlist", str(y), "--no-dema", "--no-supertrend", "--no-rsi", "--no-room"]) == 0
    out = capsys.readouterr().out
    assert "Scanned 5:" in out
    assert sc.main(["--watchlist", str(y), "--ticker", "BTCUSDT"]) == 0
    out = capsys.readouterr().out
    assert "LONG checklist" in out and "SHORT checklist" in out and "Pivot levels" in out
    assert sc.main(["--watchlist", str(y), "--ticker", "NOPE"]) == 2


def test_check_command_samples_each_group(monkeypatch, tmp_path, capsys):
    from scalpbot import check
    monkeypatch.setenv("SCALP_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(universe, "_load_instruments", lambda ex: NSE_ROWS)
    fetched = []

    def fake(inst, n=1000):
        fetched.append(inst.name)
        if inst.name == "TCS FUT":
            raise AuthExpired("token expired")
        return _recent_frame(inst.name)

    monkeypatch.setattr(check, "fetch_candles", fake)
    y = tmp_path / "w.yaml"
    y.write_text("universe:\n  crypto: [BTCUSDT, ETHUSDT, PAXGUSDT, XAUUSDT]\n")
    assert check.main(["--watchlist", str(y), "--sample", "2"]) == 1          # TCS FUT is among the 2 stock futures sampled
    out = capsys.readouterr().out
    assert fetched.count("BTCUSDT") == 1 and "XAUUSDT" not in fetched         # only 2 crypto sampled
    assert check.main(["--watchlist", str(y), "--all"]) == 1
    assert "TCS FUT" in fetched and "AUTH: token expired" in capsys.readouterr().out


def test_chart_builds():
    ind = _signal_frame(2999)
    fig = make_chart(ind, "TEST", n=120)
    names = {t.name for t in fig.data}
    assert {"Price", "SMA 22", "SMA 33", "200 DEMA", "Long signal"} <= names


# --------------------------------------------------------------------------- the app, run headless
@pytest.fixture
def app(monkeypatch, tmp_path, portal_db):
    pytest.importorskip("streamlit")
    pytest.importorskip("plotly")
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    st.cache_data.clear()
    monkeypatch.setenv("SCALP_WATCHLIST", str(ROOT / "watchlist.yaml"))
    monkeypatch.setenv("SCALP_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(universe, "_load_instruments", lambda ex: NSE_ROWS if ex == "NSE" else MCX_ROWS)

    def fake(inst, n=1000):
        if inst.source == "coinswitch":
            raise AuthExpired("keys missing")
        return _recent_frame(inst.name)

    monkeypatch.setattr(sc, "fetch_candles", fake)
    from tests.conftest import make_user, sign_in
    user = make_user(portal_db, keys={"UPSTOX_ACCESS_TOKEN": "test-token"})   # "connected": opens on the Scanner
    return sign_in(AppTest.from_file(str(ROOT / "app.py"), default_timeout=120), user)


def test_app_scan_all_mode(app):
    app.run()
    assert not app.exception
    assert app.radio(key="mode").value == "Scan all"
    assert set(app.multiselect(key="groups").value) == {"Index futures", "Stock futures", "Crypto"}
    app.button(key="run_scan").click().run()
    assert not app.exception
    m = {re.sub(r":\w+\[(.*)\]", r"\1", x.label): x.value for x in app.metric}   # labels may carry colour markup
    assert m["Scanned"] == "8"                       # 2 index + 2 stock futures + 4 crypto
    assert m["Errors"] == "4"                        # crypto keys are "missing" in this fake
    assert int(m["Long"]) + int(m["Short"]) + int(m["Blocked"]) + int(m["Closed / delayed"]) + 4 <= 8


def test_app_universe_filter_and_single_ticker(app):
    app.run()
    app.multiselect(key="groups").set_value(["Index futures"]).run()
    app.button(key="run_scan").click().run()
    assert {x.label: x.value for x in app.metric}["Scanned"] == "2"
    app.radio(key="mode").set_value("Single ticker").run()
    assert not app.exception
    assert app.selectbox(key="ticker").options == ["BANKNIFTY FUT", "NIFTY FUT"]
    app.selectbox(key="ticker").select("NIFTY FUT").run()
    assert not app.exception
    assert len(app.dataframe) >= 2                   # LONG and SHORT checklists
    assert any("NIFTY FUT" in s.value for s in app.subheader)


def test_app_single_ticker_error_is_shown(app):
    app.run()
    app.radio(key="mode").set_value("Single ticker").run()
    app.selectbox(key="ticker").select("BTCUSDT").run()
    assert not app.exception
    assert any("keys missing" in e.value for e in app.error)


def test_stale_crypto_is_a_data_delay_not_a_closed_market():
    now = pd.Timestamp("2026-10-18 14:34", tz="UTC")
    last_open = pd.Timestamp("2026-10-18 13:55", tz="UTC")              # candle ended 14:00 -> 34 min old
    btc = sc.Result(name="BTCUSDT", group="Crypto", source="coinswitch", status="STALE", stale=True, last_candle=last_open)
    nifty = sc.Result(name="NIFTY FUT", group="Index futures", source="upstox", status="STALE", stale=True,
                      last_candle=last_open)
    assert sc.always_open(btc) and not sc.always_open(nifty)
    assert sc.data_age_min(btc, now) == pytest.approx(34)
    t = sc.stale_text(btc, now)
    assert t.startswith("Data delayed") and "34 min" in t and "not a closed market" in t
    assert sc.stale_text(nifty, now).startswith("Market closed")
