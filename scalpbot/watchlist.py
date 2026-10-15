"""Watchlist loading, per-instrument strategy config, and the source dispatcher."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import pandas as pd
import yaml

from .brokers import SEGMENT_FILE, fetch_coinswitch, fetch_upstox, resolve_upstox
from .data import closed_only, fetch_binance, fetch_yfinance
from .strategy import StrategyConfig

SOURCES = {"upstox", "coinswitch", "binance", "yfinance"}
DEFAULT_TZ = {"upstox": "Asia/Kolkata", "yfinance": "Asia/Kolkata", "coinswitch": "UTC", "binance": "UTC"}


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
    raw = data.get("instruments")
    if not raw:
        raise ValueError(f"{path}: no 'instruments' list found")
    out, seen = [], set()
    for i, item in enumerate(raw, 1):
        if "name" not in item or "source" not in item:
            raise ValueError(f"{path}: instrument #{i} needs 'name' and 'source'")
        inst = Instrument(**item)
        inst.validate()
        if inst.name in seen:
            raise ValueError(f"{path}: duplicate instrument name '{inst.name}'")
        seen.add(inst.name)
        out.append(inst)
    return out


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
    elif inst.source == "binance":
        df = fetch_binance(inst.symbol, "5m", n)
    else:
        df = fetch_yfinance(inst.symbol)
    return closed_only(df, 5).tail(n)
