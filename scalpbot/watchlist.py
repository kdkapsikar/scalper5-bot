"""Watchlist loading, per-instrument strategy config, and the source dispatcher."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import pandas as pd
import yaml

from .brokers import SEGMENT_FILE, fetch_coinswitch, fetch_spot_index, fetch_upstox, resolve_upstox
from .data import closed_only, fetch_binance, fetch_yfinance
from .strategy import StrategyConfig

SOURCES = {"upstox", "coinswitch", "spotindex", "binance", "yfinance"}
# Pivot "day": IST for NSE, UTC for crypto. Spot gold's trading day ends 17:00 New York; Europe/Athens midnight
# (UTC+2/+3) is the usual forex stand-in for that (off by an hour in the weeks between US and EU clock changes).
DEFAULT_TZ = {"upstox": "Asia/Kolkata", "yfinance": "Asia/Kolkata", "coinswitch": "UTC", "binance": "UTC",
              "spotindex": "Europe/Athens"}


@dataclass
class Instrument:
    name: str
    source: str
    symbol: str = ""          # coinswitch/binance/yfinance symbol, or Upstox trading symbol
    instrument_key: str = ""  # Upstox, e.g. "NSE_INDEX|Nifty 50"
    segment: str = ""         # Upstox: NSE_EQ, NSE_INDEX, MCX_FO, ...
    underlying: str = ""      # Upstox MCX futures: GOLDM, SILVERM, CRUDEOIL, ...
    tz: str = ""              # override the pivot "day" timezone
    params: dict = field(default_factory=dict)  # StrategyConfig overrides for this instrument
    group: str = ""           # "Index futures", "Stock futures", "MCX futures", "Crypto" or "Custom"

    def validate(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"{self.name}: unknown source '{self.source}' (use {sorted(SOURCES)})")
        if self.source == "upstox":
            ok = self.instrument_key or (self.segment and (self.symbol or self.underlying))
            if not ok:
                raise ValueError(f"{self.name}: upstox needs instrument_key, or segment + symbol/underlying")
            if self.segment and self.segment not in SEGMENT_FILE:
                raise ValueError(f"{self.name}: unknown Upstox segment '{self.segment}'")
        elif not self.symbol:
            raise ValueError(f"{self.name}: {self.source} needs a symbol")


def load_watchlist(path: str) -> list[Instrument]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    raw = data.get("instruments") or []
    if not raw and "universe" not in data:
        raise ValueError(f"{path}: needs an 'instruments' list or a 'universe' section")
    out, seen = [], set()
    for i, item in enumerate(raw, 1):
        if "name" not in item or "source" not in item:
            raise ValueError(f"{path}: instrument #{i} needs 'name' and 'source'")
        inst = Instrument(**item)
        inst.validate()
        inst.group = inst.group or "Custom"
        if inst.name in seen:
            raise ValueError(f"{path}: duplicate instrument name '{inst.name}'")
        seen.add(inst.name)
        out.append(inst)
    return out


UNIVERSE_DEFAULTS = {
    "index_futures": True,      # NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 (nearest expiry)
    "stock_futures": True,      # every NSE F&O stock (nearest expiry)
    "mcx": [],                  # MCX underlyings to add, e.g. [GOLDM, SILVERM, CRUDEOIL]
    "crypto": ["BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUUSDT"],   # CoinSwitch PRO futures symbols
    "spot_gold": True,          # XAUUSD (spot): spot gold from the Bybit/Binance index price, no account needed
    "roll_days": 0,             # switch to next month this many days before expiry (0 = nearest expiry)
    "only": [],                 # restrict stock futures to these underlyings (empty = all)
    "exclude": [],              # underlyings to skip
}


def load_universe_config(path: str) -> dict | None:
    """The `universe:` section of the watchlist with defaults filled in, or None if the file has none."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    if "universe" not in data:
        return None
    u = data["universe"] or {}
    if not isinstance(u, dict):
        raise ValueError(f"{path}: 'universe' must be a mapping")
    unknown = set(u) - set(UNIVERSE_DEFAULTS)
    if unknown:
        raise ValueError(f"{path}: unknown universe option(s) {sorted(unknown)}; allowed: {sorted(UNIVERSE_DEFAULTS)}")
    conf = {**UNIVERSE_DEFAULTS, **u}
    for k in ("mcx", "crypto", "only", "exclude"):
        conf[k] = [str(x).strip() for x in (conf[k] or []) if str(x).strip()]
    conf["roll_days"] = int(conf["roll_days"] or 0)
    conf["index_futures"], conf["stock_futures"] = bool(conf["index_futures"]), bool(conf["stock_futures"])
    conf["spot_gold"] = bool(conf["spot_gold"])
    return conf


def make_config(inst: Instrument, flags: dict | None = None) -> StrategyConfig:
    """Global CLI flags first, then the instrument's own `params` on top."""
    params = {**(flags or {}), **inst.params}
    valid = {f.name for f in fields(StrategyConfig)} - {"tz"}
    unknown = set(params) - valid
    if unknown:
        raise ValueError(f"{inst.name}: unknown strategy parameter(s) {sorted(unknown)}")
    for k in ("rsi_long", "rsi_short"):
        if k in params:
            params[k] = tuple(params[k])
    return StrategyConfig(tz=inst.tz or DEFAULT_TZ[inst.source], **params)


def fetch_candles(inst: Instrument, n: int = 1000) -> pd.DataFrame:
    """Closed 5-minute candles only (the forming candle is dropped)."""
    if inst.source == "upstox":
        df = fetch_upstox(resolve_upstox(inst))
    elif inst.source == "coinswitch":
        df = fetch_coinswitch(inst.symbol, n)
    elif inst.source == "spotindex":
        df = fetch_spot_index(inst.symbol, n)
    elif inst.source == "binance":
        df = fetch_binance(inst.symbol, "5m", n)
    else:
        df = fetch_yfinance(inst.symbol)
    return closed_only(df, 5).tail(n)
