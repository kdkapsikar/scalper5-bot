"""Market data loaders. All return a UTC-indexed OHLCV DataFrame keyed by candle OPEN time."""
from __future__ import annotations

import time

import pandas as pd
import requests

OHLCV = ["open", "high", "low", "close", "volume"]
BINANCE_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]
BINANCE_FUTURES = "https://fapi.binance.com"


def _klines_to_df(rows: list) -> pd.DataFrame:
    cols = ["t", "open", "high", "low", "close", "volume", "ct", "qv", "n", "tb", "tq", "ig"]
    df = pd.DataFrame(rows, columns=cols)
    df["time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df.set_index("time")[OHLCV].astype(float)


def fetch_binance(symbol: str, interval: str = "5m", limit: int = 1000, futures: bool = False,
                  end_ms: int | None = None, timeout: int = 15) -> pd.DataFrame:
    params = {"symbol": symbol.upper(), "interval": interval, "limit": min(limit, 1000)}
    if end_ms:
        params["endTime"] = end_ms
    hosts = [BINANCE_FUTURES] if futures else BINANCE_HOSTS
    path = "/fapi/v1/klines" if futures else "/api/v3/klines"
    last_err: Exception | None = None
    for host in hosts:
        try:
            r = requests.get(host + path, params=params, timeout=timeout)
            r.raise_for_status()
            return _klines_to_df(r.json())
        except Exception as e:  # try next host
            last_err = e
    raise RuntimeError(f"Binance fetch failed for {symbol}: {last_err}")


def fetch_binance_history(symbol: str, days: int, interval: str = "5m", futures: bool = False) -> pd.DataFrame:
    need = days * 288  # 288 five-minute candles per day
    end = int(time.time() * 1000)
    frames: list[pd.DataFrame] = []
    got = 0
    while got < need:
        df = fetch_binance(symbol, interval, 1000, futures, end_ms=end)
        if df.empty:
            break
        frames.append(df)
        got += len(df)
        end = int(df.index[0].timestamp() * 1000) - 1
        time.sleep(0.2)
    out = pd.concat(frames[::-1])
    return out[~out.index.duplicated()].sort_index().tail(need)


def fetch_yfinance(ticker: str, period: str = "1mo", interval: str = "5m") -> pd.DataFrame:
    """Indian indices / equities, e.g. ^NSEI (Nifty 50), ^NSEBANK, RELIANCE.NS. 5m data: max 60 days."""
    import yfinance as yf

    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[OHLCV]
    idx = df.index
    df.index = idx.tz_localize("Asia/Kolkata").tz_convert("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return df.dropna().astype(float)


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next((c for c in ("time", "timestamp", "datetime", "date") if c in df.columns), None)
    if tcol is None:
        raise ValueError("CSV needs a time/timestamp/datetime/date column")
    if pd.api.types.is_numeric_dtype(df[tcol]):
        unit = "ms" if df[tcol].iloc[0] > 1e11 else "s"
        ts = pd.to_datetime(df[tcol], unit=unit, utc=True)
    else:
        ts = pd.to_datetime(df[tcol], utc=True)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df.index = ts
    return df[OHLCV].astype(float).sort_index()


def closed_only(df: pd.DataFrame, minutes: int = 5, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Drop the still-forming candle so signals only ever fire on a confirmed close."""
    now = now or pd.Timestamp.now(tz="UTC")
    return df[df.index + pd.Timedelta(minutes=minutes) <= now]
