"""Candle adapters for Upstox (NSE/BSE stocks, indices, MCX commodities) and CoinSwitch PRO (crypto futures).

Endpoints follow the brokers' public docs as read on 2026-10-16:
  Upstox     GET /v3/historical-candle/{key}/minutes/5/{to}/{from}   (past days)
             GET /v3/historical-candle/intraday/{key}/minutes/5      (today, needs Bearer token)
  CoinSwitch GET /trade/api/v2/futures/klines  (Ed25519-signed, exchange=EXCHANGE_2, interval in minutes)

These have only been exercised against mocked responses so far. Run `python -m scalpbot.check`
on your own machine with live keys before relying on them.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import quote, unquote_plus, urlencode

import pandas as pd
import requests

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
    """Token file wins over the env var so a daily refresh needs no restart."""
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


def fetch_upstox(instrument_key: str, days: int = 20, timeout: int = 20) -> pd.DataFrame:
    """5-minute candles: ~`days` calendar days of history plus today's intraday candles."""
    token = upstox_token()
    if not token:
        raise AuthExpired("no Upstox access token (run scripts/upstox_token.py or set UPSTOX_ACCESS_TOKEN)")
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    enc = quote(instrument_key, safe="")
    today = dt.datetime.now(IST).date()
    urls = [
        f"{UPSTOX_BASE}/v3/historical-candle/{enc}/minutes/5/{today}/{today - dt.timedelta(days=days)}",
        f"{UPSTOX_BASE}/v3/historical-candle/intraday/{enc}/minutes/5",
    ]
    frames = []
    for n, url in enumerate(urls):
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code in (401, 403):
            raise AuthExpired(f"Upstox rejected the token (HTTP {r.status_code}): {r.text[:160]}")
        if not r.ok:
            if n == 1 and r.status_code == 400:  # intraday has nothing on holidays / before the open
                log.warning("Upstox intraday returned 400 for %s: %s", instrument_key, r.text[:120])
                continue
            raise RuntimeError(f"Upstox HTTP {r.status_code} for {instrument_key}: {r.text[:200]}")
        frames.append(_parse_upstox((r.json().get("data") or {}).get("candles") or []))
    return _merge(*frames)


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


def _cs_throttle(min_gap: float = 2.1) -> None:
    """CoinSwitch klines allow 30 requests / 60 s."""
    wait = _cs_last_call[0] + min_gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _cs_last_call[0] = time.monotonic()


def _cs_headers(method: str, path_with_query: str) -> tuple[dict, str]:
    """Ed25519 signature over METHOD + url-decoded path?query + epoch_ms (per CoinSwitch auth docs)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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
    _cs_throttle()
    headers, decoded = _cs_headers("GET", "/trade/api/v2/futures/klines?" + urlencode(params))
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
    _CS_CACHE[sym] = df.tail(2 * n)
    return df.tail(n)
