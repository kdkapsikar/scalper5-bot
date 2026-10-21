"""Candle adapters for Upstox (NSE/BSE stocks, indices, MCX commodities) and CoinSwitch PRO (crypto futures).

Endpoints follow the brokers' public docs as read on 2026-10-16 (OANDA 2026-10-21):
  Upstox     GET /v3/historical-candle/{key}/minutes/5/{to}/{from}   (past days)
             GET /v3/historical-candle/intraday/{key}/minutes/5      (today, needs Bearer token)
  CoinSwitch GET /trade/api/v2/futures/klines  (Ed25519-signed, exchange=EXCHANGE_2, interval in minutes)
  OANDA      GET /v3/instruments/{XAU_USD}/candles?granularity=M5&price=M   (Bearer API token; practice or live host)

These have only been exercised against mocked responses so far. Run `python -m scalpbot.check`
on your own machine with live keys before relying on them.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import quote, unquote_plus, urlencode

import pandas as pd
import requests

from . import creds
from .data import OHLCV

log = logging.getLogger("scalpbot.brokers")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CANDLE_MS = 300_000


class AuthExpired(RuntimeError):
    """Broker rejected our credentials or token (e.g. the Upstox daily token expired)."""


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=OHLCV, index=pd.DatetimeIndex([], tz="UTC"), dtype=float)


def _merge(*frames: pd.DataFrame) -> pd.DataFrame:
    parts = [f for f in frames if f is not None and not f.empty]
    if not parts:
        return _empty()
    df = pd.concat(parts)
    return df[~df.index.duplicated(keep="last")].sort_index()


# =========================================================================== Upstox
UPSTOX_BASE = "https://api.upstox.com"
UPSTOX_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{}.json.gz"
SEGMENT_FILE = {
    "NSE_EQ": "NSE", "NSE_INDEX": "NSE", "NSE_FO": "NSE",
    "BSE_EQ": "BSE", "BSE_INDEX": "BSE", "BSE_FO": "BSE",
    "MCX_FO": "MCX",
}
_INSTR_CACHE: dict[str, list] = {}


def upstox_token() -> str:
    """The signed-in portal user's token; otherwise the token file, which wins over the env var so a daily
    refresh needs no restart."""
    c = creds.current()
    if c is not None:
        return c.UPSTOX_ACCESS_TOKEN
    f = Path(os.getenv("UPSTOX_TOKEN_FILE", ".state/upstox_token.txt"))
    if f.exists():
        tok = f.read_text().strip()
        if tok:
            return tok
    return os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()


def _parse_upstox(rows: list) -> pd.DataFrame:
    if not rows:
        return _empty()
    df = pd.DataFrame([r[:6] for r in rows], columns=["time"] + OHLCV)
    if pd.api.types.is_numeric_dtype(df["time"]):
        unit = "ms" if df["time"].iloc[0] > 1e11 else "s"
        ts = pd.to_datetime(df["time"], unit=unit, utc=True)
    else:
        ts = pd.to_datetime(df["time"], utc=True)
    out = df[OHLCV].astype(float)
    out.index = pd.DatetimeIndex(ts)
    return out.sort_index()


_UP_HIST: dict[str, tuple[str, pd.DataFrame]] = {}   # instrument_key -> (date fetched, history frame)
_up_lock = threading.Lock()
_up_last = [0.0]


def clear_candle_caches() -> None:
    _UP_HIST.clear()
    _CS_CACHE.clear()


def _upstox_throttle() -> None:
    """One global limiter for all threads (UPSTOX_MAX_RPS requests per second, default 5)."""
    gap = 1.0 / max(0.1, float(os.getenv("UPSTOX_MAX_RPS", "5")))
    with _up_lock:
        wait = _up_last[0] + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _up_last[0] = time.monotonic()


def _upstox_get(url: str, headers: dict, timeout: int, key: str, tolerate_400: bool = False) -> list:
    r = None
    for attempt in range(4):
        _upstox_throttle()
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code == 429 and attempt < 3:   # rate limited: back off and retry
            time.sleep(1.5 * (attempt + 1))
            continue
        break
    if r.status_code in (401, 403):
        raise AuthExpired(f"Upstox rejected the token (HTTP {r.status_code}): {r.text[:160]}")
    if not r.ok:
        if tolerate_400 and r.status_code == 400:   # intraday has nothing on holidays / before the open
            log.warning("Upstox intraday returned 400 for %s: %s", key, r.text[:120])
            return []
        raise RuntimeError(f"Upstox HTTP {r.status_code} for {key}: {r.text[:200]}")
    return (r.json().get("data") or {}).get("candles") or []


def fetch_upstox(instrument_key: str, days: int = 20, timeout: int = 20) -> pd.DataFrame:
    """5-minute candles: ~`days` calendar days of history plus today's intraday candles."""
    token = upstox_token()
    if not token:
        raise AuthExpired("no Upstox access token (run scripts/upstox_token.py or set UPSTOX_ACCESS_TOKEN)")
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    enc = quote(instrument_key, safe="")
    today = dt.datetime.now(IST).date()
    hist_url = f"{UPSTOX_BASE}/v3/historical-candle/{enc}/minutes/5/{today}/{today - dt.timedelta(days=days)}"
    intra_url = f"{UPSTOX_BASE}/v3/historical-candle/intraday/{enc}/minutes/5"
    cached = _UP_HIST.get(instrument_key)
    if cached and cached[0] == today.isoformat():
        hist = cached[1]          # history does not change within the day: only today's candles are re-fetched
    else:
        hist = _parse_upstox(_upstox_get(hist_url, headers, timeout, instrument_key))
        _UP_HIST[instrument_key] = (today.isoformat(), hist)
    intra = _parse_upstox(_upstox_get(intra_url, headers, timeout, instrument_key, tolerate_400=True))
    return _merge(hist, intra)


def _to_ms(v) -> float:
    try:
        x = float(v)
        return x if x > 1e11 else x * 1000
    except (ValueError, TypeError):
        ts = pd.Timestamp(v)
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        return ts.timestamp() * 1000


def _load_instruments(exchange: str) -> list:
    if exchange not in _INSTR_CACHE:
        r = requests.get(UPSTOX_INSTRUMENTS_URL.format(exchange), timeout=90)
        r.raise_for_status()
        _INSTR_CACHE[exchange] = json.loads(gzip.decompress(r.content))
    return _INSTR_CACHE[exchange]


def clear_instrument_cache() -> None:
    _INSTR_CACHE.clear()


def resolve_upstox(inst, cache_path: str = ".state/instruments.json") -> str:
    """instrument_key for an Upstox watchlist entry.

    - explicit `instrument_key`            -> used as is
    - `segment` + `symbol`                 -> match trading_symbol (stocks, indices)
    - `segment: MCX_FO` + `underlying`     -> nearest unexpired future (re-resolved daily, so it rolls)
    """
    if inst.instrument_key:
        return inst.instrument_key
    cache_file = Path(cache_path)
    cache: dict = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text())
        except Exception:
            cache = {}
    ckey = f"{inst.name}|{inst.segment}|{inst.symbol or inst.underlying}"
    today = dt.datetime.now(IST).date().isoformat()
    hit = cache.get(ckey)
    if hit and hit.get("date") == today:
        return hit["key"]

    rows = [r for r in _load_instruments(SEGMENT_FILE[inst.segment]) if r.get("segment") == inst.segment]
    if inst.underlying:
        floor_ms = time.time() * 1000 - 86_400_000
        cands = [r for r in rows
                 if r.get("instrument_type") == "FUT"
                 and str(r.get("underlying_symbol", "")).upper() == inst.underlying.upper()
                 and _to_ms(r.get("expiry", 0)) >= floor_ms]
        cands.sort(key=lambda r: _to_ms(r["expiry"]))
    else:
        cands = [r for r in rows if str(r.get("trading_symbol", "")).upper() == inst.symbol.upper()]
        cands.sort(key=lambda r: r.get("instrument_type") not in ("EQ", "INDEX"))
    if not cands:
        raise ValueError(f"{inst.name}: no Upstox instrument matches {inst.segment} {inst.symbol or inst.underlying}")
    key = cands[0]["instrument_key"]
    log.info("%s resolved to %s (%s)", inst.name, key, cands[0].get("trading_symbol"))
    cache[ckey] = {"key": key, "date": today}
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache))
    return key


# =========================================================================== CoinSwitch
_CS_CACHE: dict[str, pd.DataFrame] = {}
_cs_last_call = [0.0]


def _cs_base() -> str:
    return os.getenv("COINSWITCH_BASE_URL", "https://coinswitch.co")


_cs_lock = threading.Lock()


def _cs_throttle(min_gap: float = 2.1) -> None:
    """CoinSwitch klines allow 30 requests / 60 s (shared by all threads)."""
    with _cs_lock:
        wait = _cs_last_call[0] + min_gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _cs_last_call[0] = time.monotonic()


def _cs_headers(method: str, path_with_query: str) -> tuple[dict, str]:
    """Ed25519 signature over METHOD + url-decoded path?query + epoch_ms (per CoinSwitch auth docs)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    c = creds.current()
    if c is not None:
        api, secret = c.COINSWITCH_API_KEY, c.COINSWITCH_SECRET_KEY
    else:
        api, secret = os.getenv("COINSWITCH_API_KEY", ""), os.getenv("COINSWITCH_SECRET_KEY", "")
    if not api or not secret:
        raise AuthExpired("COINSWITCH_API_KEY / COINSWITCH_SECRET_KEY not set")
    epoch = str(int(time.time() * 1000))
    decoded = unquote_plus(path_with_query)
    message = f"{method.upper()}{decoded}{epoch}".encode()
    sig = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(secret)).sign(message).hex()
    headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": api,
               "X-AUTH-SIGNATURE": sig, "X-AUTH-EPOCH": epoch}
    return headers, decoded


def _parse_cs(rows: list) -> pd.DataFrame:
    if not rows:
        return _empty()
    df = pd.DataFrame(rows)
    idx = pd.DatetimeIndex(pd.to_datetime(pd.to_numeric(df["start_time"]), unit="ms", utc=True))
    out = pd.DataFrame(
        {
            "open": df["o"].astype(float).to_numpy(),
            "high": df["h"].astype(float).to_numpy(),
            "low": df["l"].astype(float).to_numpy(),
            "close": df["c"].astype(float).to_numpy(),
            "volume": df["volume"].astype(float).to_numpy(),
        },
        index=idx,
    )
    return out.sort_index()


def _cs_klines(symbol: str, start_ms: int, end_ms: int, limit: int) -> pd.DataFrame:
    params = {"exchange": "EXCHANGE_2", "symbol": symbol, "interval": "5",
              "start_time": start_ms, "end_time": end_ms, "limit": limit}
    path = "/trade/api/v2/futures/klines?" + urlencode(params)
    _cs_headers("GET", path)            # fail fast on missing keys, before waiting on the shared limiter
    _cs_throttle()
    headers, decoded = _cs_headers("GET", path)
    r = requests.get(_cs_base() + decoded, headers=headers, timeout=20)
    if r.status_code in (401, 403):
        raise AuthExpired(f"CoinSwitch rejected the request (HTTP {r.status_code}): {r.text[:160]}")
    if not r.ok:
        raise RuntimeError(f"CoinSwitch HTTP {r.status_code} for {symbol}: {r.text[:200]}")
    return _parse_cs(r.json().get("data") or [])


def fetch_coinswitch(symbol: str, n: int = 1000, window: int = 500) -> pd.DataFrame:
    """5-minute futures candles. First call backfills `n` candles; later calls only fetch what is new."""
    sym = symbol.upper()
    now_ms = int(time.time() * 1000)
    cached = _CS_CACHE.get(sym)
    gap = None
    if cached is not None and len(cached) >= min(n, 300):
        last_ms = int(cached.index[-1].timestamp() * 1000)
        gap = (now_ms - last_ms) // CANDLE_MS
    if gap is not None and gap <= window - 30:
        new = _cs_klines(sym, last_ms - 12 * CANDLE_MS, now_ms, int(gap) + 30)
        df = _merge(cached, new)
    else:
        frames, end, got = [], now_ms, 0
        for _ in range(6):
            start = end - window * CANDLE_MS
            part = _cs_klines(sym, start, end, window)
            if part.empty:
                break
            frames.append(part)
            got += len(part)
            if got >= n:
                break
            end = start - 1
        if not frames:
            raise RuntimeError(f"CoinSwitch returned no candles for {sym}: check the symbol exists on EXCHANGE_2 futures")
        df = _merge(*frames)
    _CS_CACHE[sym] = df.tail(2 * n)          # CoinSwitch's own candles only: filled ones are never cached
    return fill_recent(sym, df).tail(n)


# =========================================================================== real-time gap fill for crypto
# CoinSwitch publishes 5-minute futures candles in batches, so its history runs 7-37 minutes behind the live market
# (measured 2026-10-18). Its EXCHANGE_2 futures carry Bybit's prices (identical closes and volume on every shared
# candle), so the missing recent candles are filled from Bybit's public, real-time kline API; Binance USDT-M futures
# is the backup (a few bps apart). Filled candles are never cached, so CoinSwitch's own replace them once published.
FILL_PROVIDERS = {
    "bybit": ("https://api.bybit.com", "https://api.bytick.com"),
    "binance": ("https://fapi.binance.com",),
}
FILL_INFO: dict[str, dict] = {}       # symbol -> {"candles": n, "provider": name, "at": epoch s}; read by the UI


def _fill_order() -> list[str]:
    raw = os.getenv("SCALP_CRYPTO_FILL", "bybit,binance").strip().lower()
    return [] if raw in ("", "off", "none", "0") else [x.strip() for x in raw.split(",") if x.strip() in FILL_PROVIDERS]


def _public_klines(provider: str, symbol: str, start_ms: int, limit: int) -> pd.DataFrame:
    for host in FILL_PROVIDERS[provider]:
        try:
            if provider == "bybit":
                r = requests.get(host + "/v5/market/kline", timeout=6, params={
                    "category": "linear", "symbol": symbol, "interval": "5", "start": start_ms, "limit": limit})
                r.raise_for_status()
                js = r.json()
                if js.get("retCode") != 0:
                    raise RuntimeError(js.get("retMsg"))
                rows = [[int(x[0]), *map(float, x[1:6])] for x in js["result"]["list"]]
            else:
                r = requests.get(host + "/fapi/v1/klines", timeout=6, params={
                    "symbol": symbol, "interval": "5m", "startTime": start_ms, "limit": limit})
                r.raise_for_status()
                rows = [[int(x[0]), *map(float, x[1:6])] for x in r.json()]
            if not rows:
                return _empty()
            df = pd.DataFrame(rows, columns=["time"] + OHLCV)
            out = df[OHLCV]
            out.index = pd.DatetimeIndex(pd.to_datetime(df["time"], unit="ms", utc=True))
            return out.sort_index()
        except Exception as e:                      # next host / provider
            log.debug("%s %s klines failed on %s: %s", provider, symbol, host, e)
    raise RuntimeError(f"{provider} unreachable")


def fill_recent(symbol: str, df: pd.DataFrame, now_ms: int | None = None) -> pd.DataFrame:
    """Append the 5-minute candles CoinSwitch hasn't published yet (including the forming one, which callers drop)."""
    FILL_INFO.pop(symbol, None)
    if df.empty:
        return df
    now_ms = now_ms or int(time.time() * 1000)
    last_ms = int(df.index[-1].timestamp() * 1000)
    missing = (now_ms - last_ms) // CANDLE_MS          # candles after the last one CoinSwitch has (incl. forming)
    if missing < 2:                                    # only the forming candle is missing: nothing to fill
        return df
    for provider in _fill_order():
        try:
            new = _public_klines(provider, symbol, last_ms + CANDLE_MS, int(min(missing + 1, 200)))
        except Exception as e:
            log.info("Gap fill for %s via %s failed: %s", symbol, provider, e)
            continue
        new = new[new.index > df.index[-1]]
        if new.empty:
            continue
        closed = int(((new.index + pd.Timedelta(milliseconds=CANDLE_MS)) <= pd.Timestamp(now_ms, unit="ms", tz="UTC")).sum())
        FILL_INFO[symbol] = {"candles": closed, "provider": provider, "at": time.time()}
        return _merge(df, new)
    return df


# =========================================================================== OANDA (forex & metals, e.g. XAU_USD)
# The same prices as TradingView's OANDA:XAUUSD. Any OANDA account's personal API token works, including a free
# practice (demo) account; practice and live accounts use different hosts.
OANDA_HOSTS = {"practice": "https://api-fxpractice.oanda.com", "live": "https://api-fxtrade.oanda.com"}


def _oanda_auth() -> tuple[str, str]:
    c = creds.current()
    token = c.OANDA_API_TOKEN if c is not None else os.getenv("OANDA_API_TOKEN", "")
    env = (c.OANDA_ENV if c is not None else os.getenv("OANDA_ENV", "")) or "practice"
    if not token:
        raise AuthExpired("no OANDA API token (add it on the Connect page, or OANDA_API_TOKEN for the command line)")
    return token, OANDA_HOSTS.get(env.strip().lower(), OANDA_HOSTS["practice"])


def _parse_oanda(candles: list) -> pd.DataFrame:
    rows = [(c["time"], *(float(c["mid"][k]) for k in ("o", "h", "l", "c")), float(c.get("volume", 0)))
            for c in candles if c.get("mid")]
    if not rows:
        return _empty()
    df = pd.DataFrame(rows, columns=["time"] + OHLCV)
    out = df[OHLCV]
    out.index = pd.DatetimeIndex(pd.to_datetime(df["time"], utc=True, format="ISO8601"))
    return out.sort_index()


def fetch_oanda(instrument: str, n: int = 1000, timeout: int = 20) -> pd.DataFrame:
    """5-minute mid-price candles (the forming candle included; callers drop it)."""
    token, host = _oanda_auth()
    r = requests.get(f"{host}/v3/instruments/{quote(instrument.upper(), safe='')}/candles", timeout=timeout,
                     headers={"Authorization": f"Bearer {token}", "Accept-Datetime-Format": "RFC3339"},
                     params={"granularity": "M5", "price": "M", "count": min(max(n + 1, 2), 5000)})
    if r.status_code in (401, 403):
        raise AuthExpired(f"OANDA rejected the token (HTTP {r.status_code}). Check it, and whether it is a practice "
                          "or a live account token.")
    if not r.ok:
        raise RuntimeError(f"OANDA HTTP {r.status_code} for {instrument}: {r.text[:200]}")
    return _parse_oanda(r.json().get("candles") or [])
