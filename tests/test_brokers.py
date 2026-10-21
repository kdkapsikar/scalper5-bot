"""Offline tests: broker HTTP is faked, so these check our request building, parsing and plumbing,
not the live services."""
import json
import time
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scalpbot import bot, brokers
from scalpbot.strategy import add_signals, compute, latest_signal
from scalpbot.watchlist import Instrument, load_universe_config, load_watchlist, make_config
from test_strategy import make_df


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    brokers.clear_candle_caches()
    monkeypatch.setenv("UPSTOX_MAX_RPS", "1000")   # no throttle sleeps in tests
    yield


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status
        self.ok = status < 400
        self.text = json.dumps(payload)

    def json(self):
        return self._p

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


# --------------------------------------------------------------------------- CoinSwitch
@pytest.fixture
def cs_keys(monkeypatch):
    sk = Ed25519PrivateKey.generate()
    raw = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setenv("COINSWITCH_API_KEY", pub.hex())
    monkeypatch.setenv("COINSWITCH_SECRET_KEY", raw.hex())
    monkeypatch.setattr(brokers, "_cs_throttle", lambda *a, **k: None)
    brokers._CS_CACHE.clear()
    return sk.public_key()


def test_coinswitch_signature_matches_docs(cs_keys, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1719905777.483)
    headers, decoded = brokers._cs_headers("get", "/trade/api/v2/orders?open=true&exchanges=coinswitchx%2Cc2c1")
    assert decoded == "/trade/api/v2/orders?open=true&exchanges=coinswitchx,c2c1"
    assert headers["X-AUTH-EPOCH"] == "1719905777483"
    msg = b"GET/trade/api/v2/orders?open=true&exchanges=coinswitchx,c2c11719905777483"
    cs_keys.verify(bytes.fromhex(headers["X-AUTH-SIGNATURE"]), msg)  # raises if wrong


def test_coinswitch_missing_keys(monkeypatch):
    monkeypatch.delenv("COINSWITCH_API_KEY", raising=False)
    with pytest.raises(brokers.AuthExpired):
        brokers._cs_headers("GET", "/x")


def _fake_cs_server(monkeypatch, calls, total=3000):
    end = pd.Timestamp.now(tz="UTC").floor("5min")
    idx = pd.date_range(end=end, periods=total, freq="5min")
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.normal(0, 0.1, total))

    def fake_get(url, headers=None, timeout=None):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        assert urlparse(url).path == "/trade/api/v2/futures/klines"
        assert q["exchange"] == "EXCHANGE_2" and q["interval"] == "5" and q["symbol"] == "BTCUSDT"
        assert {"X-AUTH-APIKEY", "X-AUTH-SIGNATURE", "X-AUTH-EPOCH"} <= set(headers)
        calls.append(q)
        s, e, lim = int(q["start_time"]), int(q["end_time"]), int(q["limit"])
        rows = []
        for t, c in zip(idx, close):
            ms = int(t.timestamp() * 1000)
            if s <= ms <= e:
                rows.append({"o": str(c), "h": str(c + 0.2), "l": str(c - 0.2), "c": str(c + 0.05),
                             "symbol": "BTCUSDT", "close_time": str(ms + 299999), "volume": "5",
                             "start_time": str(ms), "interval": "5"})
        return FakeResp({"data": rows[-lim:]})

    monkeypatch.setattr(brokers.requests, "get", fake_get)


def test_coinswitch_backfill_then_incremental(cs_keys, monkeypatch):
    calls = []
    _fake_cs_server(monkeypatch, calls)
    df = brokers.fetch_coinswitch("btcusdt", n=800)
    assert len(df) == 800 and df.index.is_monotonic_increasing and df.index.is_unique
    assert (df.index[1:] - df.index[:-1] == pd.Timedelta(minutes=5)).all()
    assert len(calls) == 2                      # 2 x 500-candle windows
    calls.clear()
    df2 = brokers.fetch_coinswitch("BTCUSDT", n=800)
    assert len(calls) == 1                      # only the new tail is requested
    assert len(df2) == 800 and df2.index[-1] == df.index[-1]


def test_coinswitch_auth_error(cs_keys, monkeypatch):
    monkeypatch.setattr(brokers.requests, "get", lambda *a, **k: FakeResp({"message": "bad key"}, 401))
    with pytest.raises(brokers.AuthExpired):
        brokers.fetch_coinswitch("BTCUSDT")


# --------------------------------------------------------------------------- Upstox
def _ist(ts: pd.Timestamp) -> str:
    return ts.tz_convert("Asia/Kolkata").isoformat()


def test_upstox_merge_and_url(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSTOX_TOKEN_FILE", str(tmp_path / "none.txt"))
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "tok123")
    base = pd.Timestamp("2026-10-14 09:15", tz="Asia/Kolkata")
    hist_idx = [base + pd.Timedelta(minutes=5 * i) for i in range(10)]
    intra_idx = hist_idx[8:] + [base + pd.Timedelta(minutes=5 * i) for i in range(10, 13)]
    row = lambda t, c: [_ist(t), c, c + 1, c - 1, c + 0.5, 1000, 0]
    urls = []

    def fake_get(url, headers=None, timeout=None):
        urls.append(url)
        assert headers["Authorization"] == "Bearer tok123"
        if "/intraday/" in url:   # newest first, like Upstox's sample
            return FakeResp({"status": "success", "data": {"candles": [row(t, 200.0) for t in intra_idx][::-1]}})
        return FakeResp({"status": "success", "data": {"candles": [row(t, 100.0) for t in hist_idx][::-1]}})

    monkeypatch.setattr(brokers.requests, "get", fake_get)
    df = brokers.fetch_upstox("NSE_INDEX|Nifty 50")
    assert "NSE_INDEX%7CNifty%2050" in urls[0] and urls[0].split("/minutes/5/")[1].count("/") == 1
    assert urls[1].endswith("/intraday/NSE_INDEX%7CNifty%2050/minutes/5")
    assert len(df) == 13 and df.index.is_monotonic_increasing and df.index.tz is not None
    assert df.iloc[8]["close"] == 200.5      # overlap: intraday value wins
    assert df.iloc[0]["close"] == 100.5
    assert df.index[0] == hist_idx[0].tz_convert("UTC")


def test_upstox_auth_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSTOX_TOKEN_FILE", str(tmp_path / "none.txt"))
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    with pytest.raises(brokers.AuthExpired):
        brokers.fetch_upstox("NSE_EQ|INE002A01018")
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "expired")
    monkeypatch.setattr(brokers.requests, "get", lambda *a, **k: FakeResp({"status": "error"}, 401))
    with pytest.raises(brokers.AuthExpired):
        brokers.fetch_upstox("NSE_EQ|INE002A01018")


def test_upstox_token_file_wins(monkeypatch, tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("from-file\n")
    monkeypatch.setenv("UPSTOX_TOKEN_FILE", str(f))
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "from-env")
    assert brokers.upstox_token() == "from-file"


def test_resolve_mcx_nearest_future_and_daily_cache(monkeypatch, tmp_path):
    now_ms = time.time() * 1000
    day = 86_400_000
    instruments = [
        {"segment": "MCX_FO", "instrument_type": "FUT", "underlying_symbol": "GOLDM", "instrument_key": "MCX_FO|old", "expiry": now_ms - 5 * day},
        {"segment": "MCX_FO", "instrument_type": "FUT", "underlying_symbol": "GOLDM", "instrument_key": "MCX_FO|far", "expiry": now_ms + 60 * day},
        {"segment": "MCX_FO", "instrument_type": "FUT", "underlying_symbol": "GOLDM", "instrument_key": "MCX_FO|near", "expiry": now_ms + 20 * day},
        {"segment": "MCX_FO", "instrument_type": "FUT", "underlying_symbol": "GOLD", "instrument_key": "MCX_FO|big", "expiry": now_ms + 10 * day},
        {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "RELIANCE", "instrument_key": "NSE_EQ|INE002A01018"},
    ]
    loads = []
    monkeypatch.setattr(brokers, "_load_instruments", lambda ex: loads.append(ex) or instruments)
    cache = str(tmp_path / "instr.json")
    gold = Instrument(name="GOLD MINI", source="upstox", segment="MCX_FO", underlying="GOLDM")
    assert brokers.resolve_upstox(gold, cache) == "MCX_FO|near"
    assert brokers.resolve_upstox(gold, cache) == "MCX_FO|near"
    assert loads == ["MCX"]                      # second call served from today's cache
    rel = Instrument(name="REL", source="upstox", segment="NSE_EQ", symbol="reliance")
    assert brokers.resolve_upstox(rel, cache) == "NSE_EQ|INE002A01018"
    missing = Instrument(name="X", source="upstox", segment="NSE_EQ", symbol="NOPE")
    with pytest.raises(ValueError):
        brokers.resolve_upstox(missing, cache)
    direct = Instrument(name="N", source="upstox", instrument_key="NSE_INDEX|Nifty 50")
    assert brokers.resolve_upstox(direct, cache) == "NSE_INDEX|Nifty 50"


# --------------------------------------------------------------------------- watchlist
def test_default_watchlist_is_valid():
    conf = load_universe_config("watchlist.yaml")
    assert conf["crypto"] == ["BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUUSDT"]
    assert conf["index_futures"] and conf["stock_futures"] and conf["mcx"] == ["GOLD", "GOLDM", "SILVER", "SILVERM", "CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "COPPER", "ZINC", "ALUMINIUM", "LEAD"]
    assert load_watchlist("watchlist.yaml") == []     # no hand-picked extras by default


def test_universe_config_validation(tmp_path):
    f = tmp_path / "w.yaml"
    f.write_text("universe:\n  stock_futurez: true\n")
    with pytest.raises(ValueError, match="unknown universe"):
        load_universe_config(str(f))
    f.write_text("instruments:\n  - {name: A, source: binance, symbol: X}\n")
    assert load_universe_config(str(f)) is None


def test_watchlist_validation(tmp_path):
    def load(text):
        f = tmp_path / "w.yaml"
        f.write_text(text)
        return load_watchlist(str(f))

    with pytest.raises(ValueError, match="needs"):
        load("instruments:\n  - {name: A, source: upstox}\n")
    with pytest.raises(ValueError, match="unknown source"):
        load("instruments:\n  - {name: A, source: zerodha, symbol: X}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load("instruments:\n  - {name: A, source: coinswitch, symbol: X}\n  - {name: A, source: coinswitch, symbol: Y}\n")
    with pytest.raises(ValueError, match="segment"):
        load("instruments:\n  - {name: A, source: upstox, segment: NOPE, symbol: X}\n")


def test_per_instrument_params_override():
    inst = Instrument(name="PAXG", source="coinswitch", symbol="PAXGUSDT",
                      params={"rsi_long": [40, 70], "min_room_atr": 0.8})
    cfg = make_config(inst, {"require_rsi": False, "min_room_atr": 0.3})
    assert cfg.rsi_long == (40, 70) and cfg.min_room_atr == 0.8 and cfg.require_rsi is False
    assert cfg.tz == "UTC"
    assert make_config(Instrument(name="N", source="upstox", instrument_key="k")).tz == "Asia/Kolkata"
    with pytest.raises(ValueError, match="unknown strategy"):
        make_config(Instrument(name="B", source="coinswitch", symbol="X", params={"bogus": 1}))


# --------------------------------------------------------------------------- bot loop
class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


LOOSE = {"require_dema_bias": False, "require_supertrend": False, "require_rsi": False, "require_pivot_room": False}


def _fresh_signal_df():
    from scalpbot.strategy import StrategyConfig, add_signals, compute
    cfg = StrategyConfig(**LOOSE)
    df = make_df(3000, seed=3)
    ind = add_signals(compute(df, cfg), cfg)
    hit = ind.index[ind["long_sig"] | ind["short_sig"]][-1]
    df = df.loc[:hit]
    target = pd.Timestamp.now(tz="UTC").floor("5min") - pd.Timedelta(minutes=5)
    df.index = df.index + (target - df.index[-1])
    return df


def test_run_all_isolates_failures_alerts_once_and_dedupes(monkeypatch, tmp_path):
    good = _fresh_signal_df()
    insts = [Instrument(name="GOOD", source="coinswitch", symbol="G"),
             Instrument(name="BROKEN", source="binance", symbol="B"),
             Instrument(name="NIFTY", source="upstox", instrument_key="NSE_INDEX|Nifty 50"),
             Instrument(name="STOCK", source="upstox", instrument_key="NSE_EQ|X")]

    def fake_fetch(inst, n=1000):
        if inst.name == "GOOD":
            return good
        if inst.source == "upstox":
            raise brokers.AuthExpired("token expired")
        raise RuntimeError("feed down")

    monkeypatch.setattr(bot, "fetch_candles", fake_fetch)
    args = bot.parse_args(["--dry-run", "--state-file", str(tmp_path / "s.json")])
    state, notifier, health = bot.State(args.state_file), FakeNotifier(), bot.Health()

    res = bot.run_all(insts, args, LOOSE, state, notifier, health)
    assert res == {"GOOD": "alert", "BROKEN": "FAIL", "NIFTY": "FAIL", "STOCK": "FAIL"}
    assert sum("GOOD" in m for m in notifier.sent) == 1
    assert sum("rejected our credentials" in m for m in notifier.sent) == 1   # one auth alert for the whole source

    res = bot.run_all(insts, args, LOOSE, state, notifier, health)
    assert res["GOOD"] == "duplicate"
    assert sum("GOOD" in m for m in notifier.sent) == 1                        # no second alert
    assert sum("rejected our credentials" in m for m in notifier.sent) == 1   # still just one

    bot.run_all(insts, args, LOOSE, state, notifier, health)                   # BROKEN fails a 3rd time
    assert sum("BROKEN failed 3 checks" in m for m in notifier.sent) == 1
    bot.run_all(insts, args, LOOSE, state, notifier, health)
    assert sum("BROKEN failed" in m for m in notifier.sent) == 1               # no repeat spam

    # state survives a restart
    cfg = make_config(insts[0], LOOSE)
    sig = latest_signal(add_signals(compute(good, cfg), cfg))
    assert bot.State(args.state_file).is_duplicate("GOOD", sig, 6)


def test_recovery_message(monkeypatch, tmp_path):
    good = _fresh_signal_df()
    inst = Instrument(name="FLAKY", source="binance", symbol="F")
    mode = {"fail": True}

    def fake_fetch(i, n=1000):
        if mode["fail"]:
            raise RuntimeError("down")
        return good

    monkeypatch.setattr(bot, "fetch_candles", fake_fetch)
    args = bot.parse_args(["--dry-run", "--state-file", str(tmp_path / "s.json")])
    state, notifier, health = bot.State(args.state_file), FakeNotifier(), bot.Health()
    for _ in range(3):
        bot.run_all([inst], args, LOOSE, state, notifier, health)
    mode["fail"] = False
    bot.run_all([inst], args, LOOSE, state, notifier, health)
    assert any("recovered" in m for m in notifier.sent)


def test_many_signals_become_one_digest(monkeypatch, tmp_path):
    good = _fresh_signal_df()
    insts = [Instrument(name=f"STK{i} FUT", source="binance", symbol=f"S{i}") for i in range(10)]
    monkeypatch.setattr(bot, "fetch_candles", lambda inst, n=1000: good)
    args = bot.parse_args(["--dry-run", "--state-file", str(tmp_path / "s.json")])
    notifier = FakeNotifier()
    res = bot.run_all(insts, args, LOOSE, bot.State(args.state_file), notifier, bot.Health())
    assert list(res.values()) == ["alert"] * 10
    assert len(notifier.sent) == 1 and "10 signals" in notifier.sent[0] and "STK9 FUT" in notifier.sent[0]


def test_upstox_history_is_cached_for_the_day(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSTOX_TOKEN_FILE", str(tmp_path / "none.txt"))
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "tok")
    base = pd.Timestamp.now(tz="Asia/Kolkata").floor("5min") - pd.Timedelta(minutes=50)
    rows = [[_ist(base + pd.Timedelta(minutes=5 * i)), 100.0, 101.0, 99.0, 100.5, 10, 0] for i in range(5)][::-1]
    urls = []

    def fake_get(url, headers=None, timeout=None):
        urls.append(url)
        return FakeResp({"status": "success", "data": {"candles": rows}})

    monkeypatch.setattr(brokers.requests, "get", fake_get)
    for _ in range(3):
        df = brokers.fetch_upstox("NSE_FO|1")
    assert len(df) == 5
    assert sum("/intraday/" not in u for u in urls) == 1      # history fetched once
    assert sum("/intraday/" in u for u in urls) == 3          # today's candles every time


def test_upstox_retries_on_rate_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSTOX_TOKEN_FILE", str(tmp_path / "none.txt"))
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(brokers.time, "sleep", lambda s: None)
    base = pd.Timestamp.now(tz="Asia/Kolkata").floor("5min") - pd.Timedelta(minutes=10)
    rows = [[_ist(base), 100.0, 101.0, 99.0, 100.5, 10, 0]]
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return FakeResp({}, 429) if calls["n"] == 1 else FakeResp({"data": {"candles": rows}})

    monkeypatch.setattr(brokers.requests, "get", fake_get)
    assert len(brokers.fetch_upstox("NSE_FO|2")) == 1
    assert calls["n"] == 3        # 429 then success for history, then intraday


# --------------------------------------------------------------------------- crypto gap fill (CoinSwitch is behind)
class _Resp:
    def __init__(self, js, ok=True):
        self._js, self.ok, self.status_code = js, ok, 200 if ok else 503

    def json(self):
        return self._js

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("HTTP 503")


def _cs_frame(last_open: "pd.Timestamp", n: int = 20) -> "pd.DataFrame":
    idx = pd.date_range(end=last_open, periods=n, freq="5min")
    return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}, index=idx)


def _bybit_rows(start: "pd.Timestamp", k: int) -> list:
    # Bybit lists newest first: [start ms, open, high, low, close, volume, turnover]
    return [[str(int((start + pd.Timedelta(minutes=5 * i)).timestamp() * 1000)), "3", "4", "2", "3.5", "7", "0"]
            for i in range(k)][::-1]


def test_fill_recent_appends_missing_candles_from_bybit(monkeypatch):
    from scalpbot import brokers as b
    now = pd.Timestamp("2026-10-18 14:49:00", tz="UTC")
    df = _cs_frame(pd.Timestamp("2026-10-18 14:25", tz="UTC"))      # CoinSwitch stops at 14:25 (24 min behind)
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen.update(url=url, params=params)
        return _Resp({"retCode": 0, "result": {"list": _bybit_rows(pd.Timestamp("2026-10-18 14:30", tz="UTC"), 4)}})

    monkeypatch.setattr(b.requests, "get", fake_get)
    monkeypatch.delenv("SCALP_CRYPTO_FILL", raising=False)                     # default order: bybit, then binance
    out = b.fill_recent("BTCUSDT", df, int(now.timestamp() * 1000))
    assert "api.bybit.com/v5/market/kline" in seen["url"] and seen["params"]["category"] == "linear"
    assert out.index[-1] == pd.Timestamp("2026-10-18 14:45", tz="UTC")          # 14:30, 14:35, 14:40 closed + forming
    assert out.loc["2026-10-18 14:25+00:00", "close"] == 1.5                     # CoinSwitch's own candles untouched
    assert b.FILL_INFO["BTCUSDT"] == {"candles": 3, "provider": "bybit", "at": b.FILL_INFO["BTCUSDT"]["at"]}


def test_fill_recent_falls_back_to_binance_then_gives_up_quietly(monkeypatch):
    from scalpbot import brokers as b
    now = pd.Timestamp("2026-10-18 14:49:00", tz="UTC")
    df = _cs_frame(pd.Timestamp("2026-10-18 14:25", tz="UTC"))
    start = int(pd.Timestamp("2026-10-18 14:30", tz="UTC").timestamp() * 1000)

    def fake_get(url, params=None, timeout=None):
        if "bybit" in url or "bytick" in url:
            return _Resp({}, ok=False)                                            # e.g. blocked in this region
        return _Resp([[start + 300000 * i, "3", "4", "2", "3.5", "7"] for i in range(4)])

    monkeypatch.setattr(b.requests, "get", fake_get)
    monkeypatch.setenv("SCALP_CRYPTO_FILL", "bybit,binance")
    out = b.fill_recent("ETHUSDT", df, int(now.timestamp() * 1000))
    assert b.FILL_INFO["ETHUSDT"]["provider"] == "binance" and len(out) == len(df) + 4

    monkeypatch.setattr(b.requests, "get", lambda *a, **k: _Resp({}, ok=False))   # everything down
    out = b.fill_recent("ETHUSDT", df, int(now.timestamp() * 1000))
    assert out.equals(df) and "ETHUSDT" not in b.FILL_INFO


def test_fill_recent_skips_when_fresh_or_disabled(monkeypatch):
    from scalpbot import brokers as b
    calls = []
    monkeypatch.setattr(b.requests, "get", lambda *a, **k: calls.append(1))
    monkeypatch.setenv("SCALP_CRYPTO_FILL", "bybit,binance")
    df = _cs_frame(pd.Timestamp("2026-10-18 14:40", tz="UTC"))
    assert b.fill_recent("BTCUSDT", df, int(pd.Timestamp("2026-10-18 14:47", tz="UTC").timestamp() * 1000)) is df
    monkeypatch.setenv("SCALP_CRYPTO_FILL", "off")
    assert b.fill_recent("BTCUSDT", df, int(pd.Timestamp("2026-10-18 15:47", tz="UTC").timestamp() * 1000)) is df
    assert calls == []


# --------------------------------------------------------------------------- OANDA (forex & metals)
def _oanda_candles(n=3, complete_last=False):
    t0 = pd.Timestamp("2026-10-21 03:00", tz="UTC")
    out = []
    for i in range(n):
        p = 4120 + i
        out.append({"time": (t0 + pd.Timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
                    "volume": 10 + i, "complete": complete_last or i < n - 1,
                    "mid": {"o": f"{p}.10", "h": f"{p + 1}.50", "l": f"{p - 1}.25", "c": f"{p}.75"}})
    return out


def test_fetch_oanda_parses_candles_with_the_users_token(monkeypatch):
    from scalpbot import brokers as b
    from scalpbot import creds as cr
    seen = {}

    class R:
        ok, status_code = True, 200
        def json(self): return {"instrument": "XAU_USD", "granularity": "M5", "candles": _oanda_candles(3)}

    def fake_get(url, headers=None, params=None, timeout=None):
        seen.update(url=url, headers=headers, params=params)
        return R()

    monkeypatch.setattr(b.requests, "get", fake_get)
    cr.activate(cr.Creds(OANDA_API_TOKEN="TOK", OANDA_ENV="live"))
    df = b.fetch_oanda("XAU_USD", 500)
    assert seen["url"] == "https://api-fxtrade.oanda.com/v3/instruments/XAU_USD/candles"
    assert seen["headers"]["Authorization"] == "Bearer TOK"
    assert seen["params"]["granularity"] == "M5" and seen["params"]["price"] == "M" and seen["params"]["count"] == 501
    assert list(df.columns) == ["open", "high", "low", "close", "volume"] and len(df) == 3
    assert df.index[0] == pd.Timestamp("2026-10-21 03:00", tz="UTC") and df["close"].iloc[-1] == 4122.75

    cr.activate(cr.Creds(OANDA_API_TOKEN="TOK"))                    # no environment chosen: practice
    b.fetch_oanda("XAU_USD", 10)
    assert seen["url"].startswith("https://api-fxpractice.oanda.com/")


def test_fetch_oanda_errors(monkeypatch):
    from scalpbot import brokers as b
    from scalpbot import creds as cr
    cr.activate(cr.Creds())
    with pytest.raises(b.AuthExpired, match="no OANDA API token"):
        b.fetch_oanda("XAU_USD")

    class R:
        ok, status_code, text = False, 401, "Insufficient authorization"

    monkeypatch.setattr(b.requests, "get", lambda *a, **k: R())
    cr.activate(cr.Creds(OANDA_API_TOKEN="BAD"))
    with pytest.raises(b.AuthExpired, match="practice"):
        b.fetch_oanda("XAU_USD")


def test_fetch_candles_routes_oanda_and_drops_the_forming_candle(monkeypatch):
    from scalpbot import watchlist as wl
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("5min"), periods=5, freq="5min")
    frame = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0}, index=idx)
    monkeypatch.setattr(wl, "fetch_oanda", lambda sym, n: frame)
    inst = wl.Instrument(name="XAUUSD (OANDA)", source="oanda", symbol="XAU_USD", group="Forex & metals")
    inst.validate()
    out = wl.fetch_candles(inst, 100)
    assert len(out) == 4 and out.index[-1] == idx[-2]                # the still-forming candle is not used
    assert wl.make_config(inst).tz == "Europe/Athens"


# --------------------------------------------------------------------------- XAUUSD (spot) from the spot-gold index
def test_metals_session_matches_oandas_hours():
    from scalpbot.brokers import in_metals_session
    ny = lambda s: pd.Timestamp(s, tz="America/New_York").tz_convert("UTC")
    cases = {
        "2026-10-20 12:00": True,    # Tuesday midday
        "2026-10-20 16:55": True,    # last candle before the daily break
        "2026-10-20 17:00": False,   # daily break 17:00-18:00
        "2026-10-20 17:55": False,
        "2026-10-20 18:00": True,    # reopens
        "2026-10-23 16:55": True,    # Friday, last candle of the week
        "2026-10-23 17:00": False,   # weekend starts
        "2026-10-24 12:00": False,   # Saturday
        "2026-10-25 17:55": False,   # Sunday before the open
        "2026-10-25 18:00": True,    # Sunday open
    }
    idx = pd.DatetimeIndex([ny(k) for k in cases])
    assert list(in_metals_session(idx)) == list(cases.values())


def test_fetch_spot_index_pages_filters_and_falls_back(monkeypatch):
    from scalpbot import brokers as b
    end = pd.Timestamp("2026-10-21 10:00", tz="UTC")

    def rows(last, k):                                       # newest-first like Bybit; [start ms, o, h, l, c]
        return [[str(int((last - pd.Timedelta(minutes=5 * i)).timestamp() * 1000)), "4100", "4102", "4099", "4101"]
                for i in range(k)]

    calls = []

    class R:
        def __init__(self, js, ok=True): self._js, self.ok = js, ok
        def json(self): return self._js
        def raise_for_status(self):
            if not self.ok: raise RuntimeError("HTTP 403")

    def bybit_ok(url, params=None, timeout=None):
        calls.append(params["end"])
        last = pd.Timestamp(int(params["end"]), unit="ms", tz="UTC").floor("5min")
        return R({"retCode": 0, "result": {"list": rows(last, params["limit"])}})

    monkeypatch.setattr(b.time, "time", lambda: end.timestamp())
    monkeypatch.setattr(b.requests, "get", bybit_ok)
    df = b.fetch_spot_index("XAUUSDT", 1500)
    assert len(calls) >= 2 and calls[1] < calls[0]          # paged back in time
    assert len(df) == 1501 and df["volume"].eq(0).all()
    assert b.in_metals_session(df.index).all()              # no weekend / daily-break candles left

    def bybit_down_binance_ok(url, params=None, timeout=None):
        if "bybit" in url:
            return R({}, ok=False)
        last = pd.Timestamp(int(params["endTime"]), unit="ms", tz="UTC").floor("5min")
        return R([[int(r[0]), *r[1:]] for r in rows(last, params["limit"])])

    monkeypatch.setattr(b.requests, "get", bybit_down_binance_ok)
    assert len(b.fetch_spot_index("XAUUSDT", 200)) == 201

    monkeypatch.setattr(b.requests, "get", lambda *a, **k: R({}, ok=False))
    with pytest.raises(RuntimeError, match="Spot gold index unavailable"):
        b.fetch_spot_index("XAUUSDT", 200)
