"""Five-indicator confluence strategy for 5-minute scalping.

Triggers: (a) SMA 22 crosses SMA 33; (b) the 22/33 lines cross the 200 DEMA (see dema_cross_mode).
          Opposite triggers on the same candle cancel each other out.
Filters : Supertrend direction, 200 DEMA bias, RSI zone + direction, room to next pivot level.
Targets : next daily pivot level (P / R1-R3 / S1-S3) in the trade direction.
Stop    : ATR based (the backtester also trails with Supertrend).

All logic is vectorised so the live bot, the backtester and the tests share one code path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

PIVOT_COLS = ["S3", "S2", "S1", "P", "R1", "R2", "R3"]


@dataclass
class StrategyConfig:
    sma_fast: int = 22
    sma_slow: int = 33
    dema_len: int = 200
    rsi_len: int = 14
    # Tunable RSI zones. Longs: not overbought and rising. Shorts: not oversold and falling.
    rsi_long: tuple = (35.0, 62.0)
    rsi_short: tuple = (30.0, 60.0)
    st_atr_len: int = 10
    st_mult: float = 3.0
    atr_len: int = 14
    require_dema_bias: bool = True
    require_supertrend: bool = True
    require_rsi: bool = True
    require_pivot_room: bool = True
    min_room_atr: float = 0.5      # next pivot must be at least this many ATRs away
    stop_atr_mult: float = 1.5
    cross_lookback: int = 1        # accept a cross that happened within the last N candles
    # Second trigger: the SMA lines crossing the 200 DEMA.
    #   "off"  : disabled
    #   "fast" : the fast SMA (22) crossing the DEMA is the event
    #   "both" : either line crossing is the event, but only once BOTH lines sit on the new side of the DEMA
    dema_cross_mode: str = "both"
    dema_cross_lookback: int = 1   # accept a DEMA cross within the last N candles
    tz: str = "UTC"                # timezone that defines the "day" for pivot levels


# --------------------------------------------------------------------------- indicators
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def dema(s: pd.Series, n: int) -> pd.Series:
    e1 = ema(s, n)
    return 2 * e1 - ema(e1, n)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI."""
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    return out.where(loss != 0, 100.0)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def supertrend(df: pd.DataFrame, length: int = 10, mult: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """Return (supertrend line, direction) where direction is +1 (up/green) or -1 (down/red)."""
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy(float)
    a = atr(df, length).to_numpy(float)
    ub, lb = hl2 + mult * a, hl2 - mult * a
    close = df["close"].to_numpy(float)
    n = len(df)
    fub, flb = ub.copy(), lb.copy()
    direction = np.zeros(n, dtype=int)
    line = np.full(n, np.nan)
    valid = np.flatnonzero(~np.isnan(ub))
    if len(valid) == 0:
        return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)
    s = int(valid[0])
    direction[s], line[s] = 1, flb[s]
    for i in range(s + 1, n):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or close[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or close[i - 1] < flb[i - 1]) else flb[i - 1]
        if direction[i - 1] == 1 and close[i] < flb[i]:
            direction[i] = -1
        elif direction[i - 1] == -1 and close[i] > fub[i]:
            direction[i] = 1
        else:
            direction[i] = direction[i - 1]
        line[i] = flb[i] if direction[i] == 1 else fub[i]
    return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)


def daily_pivots(df: pd.DataFrame, tz: str = "UTC") -> pd.DataFrame:
    """Classic floor-trader pivots from the previous day's H/L/C, aligned to each intraday row."""
    idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
    day = idx.tz_convert(tz).normalize()
    g = df.groupby(day).agg(h=("high", "max"), l=("low", "min"), c=("close", "last"))
    prev = g.shift(1)
    p = (prev["h"] + prev["l"] + prev["c"]) / 3
    rng = prev["h"] - prev["l"]
    piv = pd.DataFrame(
        {
            "P": p,
            "R1": 2 * p - prev["l"],
            "S1": 2 * p - prev["h"],
            "R2": p + rng,
            "S2": p - rng,
            "R3": prev["h"] + 2 * (p - prev["l"]),
            "S3": prev["l"] - 2 * (prev["h"] - p),
        }
    )
    out = piv.reindex(day)
    out.index = df.index
    return out


# --------------------------------------------------------------------------- pipeline
def compute(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """Add all indicator columns to a copy of the OHLC frame."""
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"missing column: {col}")
    if len(df) < 300:
        raise ValueError(f"need at least 300 candles for indicator warm-up, got {len(df)}")
    d = df.sort_index().copy()
    d["sma_fast"] = sma(d["close"], cfg.sma_fast)
    d["sma_slow"] = sma(d["close"], cfg.sma_slow)
    d["dema"] = dema(d["close"], cfg.dema_len)
    d["rsi"] = rsi(d["close"], cfg.rsi_len)
    d["atr"] = atr(d, cfg.atr_len)
    d["st"], d["st_dir"] = supertrend(d, cfg.st_atr_len, cfg.st_mult)
    return d.join(daily_pivots(d, cfg.tz))


def _recent(s: pd.Series, n: int) -> pd.Series:
    """True if `s` was True on any of the last n candles (including this one)."""
    return s.astype(float).rolling(n, min_periods=1).max() > 0


DEMA_MODES = ("off", "fast", "both")


def add_signals(ind: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """Add boolean long_sig / short_sig plus stop and target columns."""
    d = ind.copy()
    close, f, s = d["close"], d["sma_fast"], d["sma_slow"]

    cross_up = (f > s) & (f.shift(1) <= s.shift(1))
    cross_dn = (f < s) & (f.shift(1) >= s.shift(1))
    lb = max(1, cfg.cross_lookback)
    if lb > 1:
        cross_up = (cross_up.astype(float).rolling(lb, min_periods=1).max() > 0) & (f > s)
        cross_dn = (cross_dn.astype(float).rolling(lb, min_periods=1).max() > 0) & (f < s)
    d["cross_up"], d["cross_dn"] = cross_up, cross_dn

    # ---- second trigger: 22/33 lines crossing the 200 DEMA (green = up through it, red = down through it)
    if cfg.dema_cross_mode not in DEMA_MODES:
        raise ValueError(f"dema_cross_mode must be one of {DEMA_MODES}, got {cfg.dema_cross_mode!r}")
    dm = d["dema"]
    if cfg.dema_cross_mode == "off":
        dema_up = dema_dn = pd.Series(False, index=d.index)
    else:
        f_up = (f > dm) & (f.shift(1) <= dm.shift(1))
        f_dn = (f < dm) & (f.shift(1) >= dm.shift(1))
        if cfg.dema_cross_mode == "fast":
            ev_up, ev_dn = f_up, f_dn
            state_up, state_dn = f > dm, f < dm
        else:
            s_up = (s > dm) & (s.shift(1) <= dm.shift(1))
            s_dn = (s < dm) & (s.shift(1) >= dm.shift(1))
            ev_up, ev_dn = f_up | s_up, f_dn | s_dn
            state_up, state_dn = (f > dm) & (s > dm), (f < dm) & (s < dm)
        n2 = max(1, cfg.dema_cross_lookback)
        if n2 > 1:
            ev_up, ev_dn = _recent(ev_up, n2), _recent(ev_dn, n2)
        dema_up, dema_dn = ev_up & state_up, ev_dn & state_dn
    d["dema_up"], d["dema_dn"] = dema_up, dema_dn

    raw_long, raw_short = cross_up | dema_up, cross_dn | dema_dn
    conflict = raw_long & raw_short            # opposite triggers on one candle: stand aside
    raw_long, raw_short = raw_long & ~conflict, raw_short & ~conflict
    d["trigger"] = np.select(
        [raw_long.to_numpy() & cross_up.to_numpy() & dema_up.to_numpy(),
         raw_long.to_numpy() & dema_up.to_numpy(),
         raw_long.to_numpy() & cross_up.to_numpy(),
         raw_short.to_numpy() & cross_dn.to_numpy() & dema_dn.to_numpy(),
         raw_short.to_numpy() & dema_dn.to_numpy(),
         raw_short.to_numpy() & cross_dn.to_numpy()],
        ["SMA + DEMA cross", "200 DEMA cross", "SMA cross"] * 2,
        default="",
    )

    # nearest pivot level above / below price
    lv = d[PIVOT_COLS].to_numpy(float)
    c = close.to_numpy(float)[:, None]
    with np.errstate(invalid="ignore"):
        above = np.where(lv > c, lv, np.inf).min(axis=1)
        below = np.where(lv < c, lv, -np.inf).max(axis=1)
    above[np.isinf(above)] = np.nan
    below[np.isinf(below)] = np.nan
    d["next_up"], d["next_dn"] = above, below

    room = cfg.min_room_atr * d["atr"]
    d["l_st"] = d["st_dir"] == 1
    d["s_st"] = d["st_dir"] == -1
    d["l_dema"] = close > d["dema"]
    d["s_dema"] = close < d["dema"]
    d["l_rsi"] = d["rsi"].between(*cfg.rsi_long) & (d["rsi"] > d["rsi"].shift(1))
    d["s_rsi"] = d["rsi"].between(*cfg.rsi_short) & (d["rsi"] < d["rsi"].shift(1))
    d["l_room"] = (d["next_up"] - close) >= room
    d["s_room"] = (close - d["next_dn"]) >= room

    def gate(base: pd.Series, side: str) -> pd.Series:
        out = base
        out = out & (d[f"{side}_st"] | (not cfg.require_supertrend))
        out = out & (d[f"{side}_dema"] | (not cfg.require_dema_bias))
        out = out & (d[f"{side}_rsi"] | (not cfg.require_rsi))
        out = out & (d[f"{side}_room"] | (not cfg.require_pivot_room))
        return out

    d["long_sig"] = gate(raw_long, "l")
    d["short_sig"] = gate(raw_short, "s")
    d["long_stop"] = close - cfg.stop_atr_mult * d["atr"]
    d["short_stop"] = close + cfg.stop_atr_mult * d["atr"]
    d["long_tp"], d["short_tp"] = d["next_up"], d["next_dn"]
    return d


# --------------------------------------------------------------------------- live helpers
@dataclass
class Signal:
    side: str  # "LONG" | "SHORT"
    bar_open: pd.Timestamp
    price: float
    stop: float
    target: Optional[float]
    rsi: float
    atr: float
    above_dema: bool
    st_up: bool
    trigger: str = ""


def latest_signal(d: pd.DataFrame) -> Optional[Signal]:
    """Signal on the most recent *closed* candle, if any. Caller must drop the forming candle."""
    r = d.iloc[-1]
    if bool(r["long_sig"]):
        side, stop, tp = "LONG", r["long_stop"], r["long_tp"]
    elif bool(r["short_sig"]):
        side, stop, tp = "SHORT", r["short_stop"], r["short_tp"]
    else:
        return None
    return Signal(
        side=side,
        bar_open=d.index[-1],
        price=float(r["close"]),
        stop=float(stop),
        target=None if pd.isna(tp) else float(tp),
        rsi=float(r["rsi"]),
        atr=float(r["atr"]),
        above_dema=bool(r["close"] > r["dema"]),
        st_up=bool(r["st_dir"] == 1),
        trigger=str(r["trigger"]),
    )


def fmt(x: float) -> str:
    return f"{x:,.2f}" if abs(x) >= 100 else f"{x:,.4f}"


def status_line(d: pd.DataFrame) -> str:
    r = d.iloc[-1]
    trend = "22>33" if r["sma_fast"] > r["sma_slow"] else "22<33"
    return (
        f"candle={d.index[-1]:%Y-%m-%d %H:%M}Z close={fmt(r['close'])} {trend} "
        f"st={'UP' if r['st_dir'] == 1 else 'DOWN'} rsi={r['rsi']:.1f} "
        f"dema={'above' if r['close'] > r['dema'] else 'below'} "
        f"signal={'LONG' if r['long_sig'] else 'SHORT' if r['short_sig'] else 'none'}"
    )
