"""On-demand scanner and single-ticker status. Shared by the CLI and the Streamlit app.

    python -m scalpbot.scan                            # scan the whole universe, list what satisfies the rules
    python -m scalpbot.scan --ticker "RELIANCE FUT"    # status of one ticker with the full checklist
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .brokers import AuthExpired
from .strategy import StrategyConfig, add_signals, compute, fmt
from .watchlist import Instrument, fetch_candles, make_config

CANDLE_MIN = 5
STALE_AFTER_MIN = 12          # last closed candle older than this => market closed / feed stalled
IST = "Asia/Kolkata"
ICON = {"LONG": "🟢 LONG", "SHORT": "🔴 SHORT", "BLOCKED": "🟡 BLOCKED"}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True

    @property
    def passed(self) -> bool:
        return self.ok or not self.required


@dataclass
class Result:
    name: str
    group: str = ""
    source: str = ""
    status: str = "NONE"                 # LONG | SHORT | BLOCKED | NONE | STALE | ERROR
    side: str = ""                       # LONG / SHORT for signals and blocked setups
    stale: bool = False
    error: str = ""
    last_candle: Optional[pd.Timestamp] = None     # open time of the last closed candle (UTC)
    age: Optional[int] = None                      # closed candles since the signal (0 = latest closed candle)
    signal_close: Optional[pd.Timestamp] = None    # close time of the signal candle (UTC)
    trigger: str = ""
    price: Optional[float] = None                  # latest close
    signal_price: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    rsi: Optional[float] = None
    st_up: Optional[bool] = None
    above_dema: Optional[bool] = None
    blocked_by: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)     # {"LONG": [Check], "SHORT": [Check]} on the latest candle
    snapshot: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- helpers
def _f(x) -> Optional[float]:
    return None if x is None or pd.isna(x) else float(x)


def _since(mask: pd.Series) -> Optional[int]:
    """Closed candles since the last True in `mask` (0 = latest candle); None if never."""
    idx = np.flatnonzero(mask.to_numpy(dtype=bool))
    return None if len(idx) == 0 else int(len(mask) - 1 - idx[-1])


def _event(up: pd.Series, dn: pd.Series) -> Optional[tuple]:
    u, d = _since(up), _since(dn)
    if u is None and d is None:
        return None
    if d is None or (u is not None and u <= d):
        return "up", u
    return "down", d


def _ago(n: int) -> str:
    return "on the latest closed candle" if n == 0 else f"{n} candle{'s' if n != 1 else ''} ago"


def checks_for(row: pd.Series, cfg: StrategyConfig, side: str) -> list[Check]:
    """Which conditions hold on this candle, for a LONG or a SHORT setup."""
    long_ = side == "LONG"
    p = "l" if long_ else "s"
    close, dema, rsi = float(row["close"]), row["dema"], row["rsi"]
    trig_now = bool(row["raw_long"] if long_ else row["raw_short"])
    nxt = _f(row["next_up"] if long_ else row["next_dn"])
    zone = cfg.rsi_long if long_ else cfg.rsi_short
    pct = (close / dema - 1) * 100 if pd.notna(dema) and dema else float("nan")
    return [
        Check("Trigger on this candle", trig_now,
              str(row["trigger"]) if trig_now else "no SMA or 200 DEMA cross on this candle"),
        Check("Supertrend " + ("up" if long_ else "down"), bool(row[f"{p}_st"]),
              "Supertrend is " + ("up" if row["st_dir"] == 1 else "down"), cfg.require_supertrend),
        Check("Price " + ("above" if long_ else "below") + " 200 DEMA", bool(row[f"{p}_dema"]),
              f"close {fmt(close)} vs DEMA {fmt(float(dema))} ({pct:+.2f}%)", cfg.require_dema_bias),
        Check(f"RSI {zone[0]:.0f}-{zone[1]:.0f} and {'rising' if long_ else 'falling'}", bool(row[f"{p}_rsi"]),
              f"RSI {rsi:.1f}", cfg.require_rsi),
        Check("Room to next pivot", bool(row[f"{p}_room"]),
              f"next level {fmt(nxt)}" if nxt is not None else "no pivot level in that direction",
              cfg.require_pivot_room),
    ]


def checks_frame(checks: list[Check]) -> pd.DataFrame:
    rows = []
    for c in checks:
        mark = "✅" if c.ok else ("➖ filter off" if not c.required else "❌")
        rows.append({"Condition": c.name, "Status": mark, "Detail": c.detail})
    return pd.DataFrame(rows)


def _snapshot(ind: pd.DataFrame) -> dict:
    last = ind.iloc[-1]
    f, s = float(last["sma_fast"]), float(last["sma_slow"])
    snap = {"22 vs 33 SMA": f"22 {'above' if f > s else 'below'} 33 ({(f / s - 1) * 100:+.2f}%)" if s else "n/a"}
    ev = _event(ind["cross_up"], ind["cross_dn"])
    snap["Last SMA 22/33 cross"] = f"{ev[0]}, {_ago(ev[1])}" if ev else "none in the loaded history"
    ev = _event(ind["dema_up"], ind["dema_dn"])
    snap["Last 200 DEMA cross"] = f"{ev[0]}, {_ago(ev[1])}" if ev else "none in the loaded history"
    ev = _event(ind["long_sig"], ind["short_sig"])
    if ev:
        row = ind.iloc[-1 - ev[1]]
        snap["Last full signal"] = f"{'LONG' if ev[0] == 'up' else 'SHORT'}, {_ago(ev[1])} ({row['trigger']})"
    else:
        snap["Last full signal"] = "none in the loaded history"
    levels = [f"{k} {fmt(float(last[k]))}" for k in ("S2", "S1", "P", "R1", "R2") if pd.notna(last[k])]
    snap["Pivot levels"] = " | ".join(levels) if levels else "n/a"
    snap["ATR (14)"] = fmt(float(last["atr"]))
    return snap


# --------------------------------------------------------------------------- analysis of one instrument
def analyse(ind: pd.DataFrame, inst: Instrument, cfg: StrategyConfig, lookback: int = 3,
            ignore_stale: bool = False, now: Optional[pd.Timestamp] = None) -> Result:
    """Turn an indicator frame (from add_signals) into a Result for the last `lookback` closed candles."""
    now = now or pd.Timestamp.now(tz="UTC")
    last, last_open = ind.iloc[-1], ind.index[-1]
    age_min = (now - (last_open + pd.Timedelta(minutes=CANDLE_MIN))).total_seconds() / 60
    r = Result(name=inst.name, group=inst.group, source=inst.source, last_candle=last_open,
               price=_f(last["close"]), rsi=_f(last["rsi"]), st_up=bool(last["st_dir"] == 1),
               above_dema=bool(last["close"] > last["dema"]), stale=age_min > STALE_AFTER_MIN)
    r.checks = {"LONG": checks_for(last, cfg, "LONG"), "SHORT": checks_for(last, cfg, "SHORT")}
    r.snapshot = _snapshot(ind)
    if r.stale and not ignore_stale:
        r.status = "STALE"
        return r

    n = len(ind)
    win = ind.iloc[-max(1, min(lookback, n)):]

    def fill(row_idx, side: str) -> pd.Series:
        row = ind.loc[row_idx]
        r.side, r.age = side, n - 1 - ind.index.get_loc(row_idx)
        r.signal_close = row_idx + pd.Timedelta(minutes=CANDLE_MIN)
        r.trigger, r.signal_price = str(row["trigger"]), _f(row["close"])
        k = "long" if side == "LONG" else "short"
        r.stop, r.target = _f(row[f"{k}_stop"]), _f(row[f"{k}_tp"])
        return row

    sig = win[win["long_sig"] | win["short_sig"]]
    if not sig.empty:
        idx = sig.index[-1]
        side = "LONG" if bool(sig.iloc[-1]["long_sig"]) else "SHORT"
        fill(idx, side)
        r.status = side
        return r
    blk = win[win["raw_long"] | win["raw_short"]]
    if not blk.empty:
        idx = blk.index[-1]
        side = "LONG" if bool(blk.iloc[-1]["raw_long"]) else "SHORT"
        row = fill(idx, side)
        r.status = "BLOCKED"
        r.blocked_by = [c.name for c in checks_for(row, cfg, side) if not c.passed]
    return r


def run_one(inst: Instrument, flags: dict, lookback: int = 3, ignore_stale: bool = False,
            candles: int = 1000, now: Optional[pd.Timestamp] = None):
    """Fetch, compute and analyse one instrument. Returns (Result, indicator frame or None, config or None)."""
    base = dict(name=inst.name, group=inst.group, source=inst.source)
    try:
        cfg = make_config(inst, flags)
        df = fetch_candles(inst, candles)
        if df.empty:
            raise RuntimeError("no closed candles returned")
        ind = add_signals(compute(df, cfg), cfg)
    except AuthExpired as e:
        return Result(**base, status="ERROR", error=f"login/token problem: {e}"), None, None
    except Exception as e:
        return Result(**base, status="ERROR", error=str(e)[:200] or type(e).__name__), None, None
    return analyse(ind, inst, cfg, lookback, ignore_stale, now), ind, cfg


def scan(insts: list[Instrument], flags: dict, lookback: int = 3, ignore_stale: bool = False,
         workers: int = 4, progress: Optional[Callable[[int, int], None]] = None,
         candles: int = 1000) -> list[Result]:
    """Scan many instruments in parallel. One failing instrument never stops the rest."""
    auth_failed: dict[str, str] = {}

    def work(inst: Instrument) -> Result:
        if inst.source in auth_failed:       # login already rejected this scan: don't hammer the broker
            return Result(name=inst.name, group=inst.group, source=inst.source, status="ERROR",
                          error=auth_failed[inst.source])
        res, _, _ = run_one(inst, flags, lookback, ignore_stale, candles)
        if res.status == "ERROR" and res.error.startswith("login/token"):
            auth_failed.setdefault(inst.source, res.error)
        return res

    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(insts) or 1))) as ex:
        futs = [ex.submit(work, i) for i in insts]
        for k, fu in enumerate(futs, 1):
            results.append(fu.result())
            if progress:
                progress(k, len(insts))
    return results


# --------------------------------------------------------------------------- presentation helpers
def _rnd(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x, 4 if abs(x) < 100 else 2)


def to_frame(results: list[Result], statuses=("LONG", "SHORT")) -> pd.DataFrame:
    rows = []
    for r in results:
        if r.status not in statuses:
            continue
        when = r.signal_close.tz_convert(IST).strftime("%d %b %H:%M") if r.signal_close is not None else ""
        row = {
            "Ticker": r.name, "Group": r.group,
            "Signal": ICON[r.status] if r.status != "BLOCKED" else f"🟡 {r.side} (blocked)",
            "Trigger": r.trigger, "Candles ago": r.age, "Candle close (IST)": when,
            "Price": _rnd(r.signal_price), "Stop": _rnd(r.stop), "Target": _rnd(r.target),
            "RSI": None if r.rsi is None else round(r.rsi, 1),
            "Supertrend": "up" if r.st_up else "down", "200 DEMA": "above" if r.above_dema else "below",
        }
        if "BLOCKED" in statuses:
            row["Blocked by"] = ", ".join(r.blocked_by)
        rows.append(row)
    df = pd.DataFrame(rows)
    return df.sort_values(["Candles ago", "Ticker"], kind="stable").reset_index(drop=True) if not df.empty else df


def headline(res: Result, lookback: int) -> str:
    if res.status == "ERROR":
        return f"Error: {res.error}"
    if res.status == "STALE":
        return "Market closed or no fresh candles."
    if res.status in ("LONG", "SHORT", "BLOCKED"):
        t = res.signal_close.tz_convert(IST)
        when = f"{_ago(res.age)} (closed {t:%H:%M} IST)"
        if res.status == "BLOCKED":
            return f"🟡 {res.side} trigger ({res.trigger}) {when}, but blocked by: {', '.join(res.blocked_by)}"
        return f"{ICON[res.status]} signal ({res.trigger}) {when}"
    return f"No signal in the last {lookback} closed candle{'s' if lookback != 1 else ''}."


# --------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    from .universe import GROUPS, build_universe

    p = argparse.ArgumentParser(description="Scan the universe, or show the status of one ticker")
    p.add_argument("--watchlist", default=os.getenv("SCALP_WATCHLIST", "watchlist.yaml"))
    p.add_argument("--groups", help=f"comma-separated subset of: {', '.join(GROUPS)}")
    p.add_argument("--ticker", help="show the full status of one ticker (exact name, e.g. 'NIFTY FUT')")
    p.add_argument("--lookback", type=int, default=3, help="look back this many closed candles for a signal")
    p.add_argument("--show-blocked", action="store_true", help="also list triggers blocked by a filter")
    p.add_argument("--include-closed", action="store_true", help="include markets that are closed (last session)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--dema-cross", choices=["off", "fast", "both"], default="both")
    p.add_argument("--no-dema", action="store_true")
    p.add_argument("--no-supertrend", action="store_true")
    p.add_argument("--no-rsi", action="store_true")
    p.add_argument("--no-room", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level="WARNING", format="%(levelname)s %(message)s")

    flags: dict = {"dema_cross_mode": a.dema_cross}
    for attr, key in (("no_dema", "require_dema_bias"), ("no_supertrend", "require_supertrend"),
                      ("no_rsi", "require_rsi"), ("no_room", "require_pivot_room")):
        if getattr(a, attr):
            flags[key] = False

    insts, warns = build_universe(a.watchlist)
    for w in warns:
        print(f"! {w}")
    if a.groups:
        wanted = {g.strip().lower() for g in a.groups.split(",")}
        insts = [i for i in insts if i.group.lower() in wanted]

    if a.ticker:
        match = [i for i in insts if i.name.lower() == a.ticker.lower()] or \
                [i for i in insts if a.ticker.lower() in i.name.lower()]
        if len(match) != 1:
            print(f"Ticker '{a.ticker}' matched {len(match)} instruments."
                  + (" Candidates: " + ", ".join(i.name for i in match[:15]) if match else ""))
            return 2
        res, _, _ = run_one(match[0], flags, a.lookback, ignore_stale=True)
        print(f"\n{res.name} ({res.group})\n{headline(res, a.lookback)}")
        if res.status != "ERROR":
            if res.stale:
                print("! last closed candle is old: market looks closed, showing the last session")
            for side in ("LONG", "SHORT"):
                print(f"\n{side} checklist on the latest closed candle:")
                print(checks_frame(res.checks[side]).to_string(index=False))
            print()
            for k, v in res.snapshot.items():
                print(f"{k:>22}: {v}")
        return 0 if res.status != "ERROR" else 1

    def cb(done, total):
        print(f"\rscanning {done}/{total}", end="", file=sys.stderr, flush=True)

    results = scan(insts, flags, a.lookback, a.include_closed, a.workers, cb)
    print(file=sys.stderr)
    from collections import Counter
    c = Counter(r.status for r in results)
    print(f"Scanned {len(results)}: {c['LONG']} long, {c['SHORT']} short, {c['BLOCKED']} blocked, "
          f"{c['STALE']} market closed, {c['ERROR']} errors (look-back {a.lookback} candles)\n")
    shown = to_frame(results, ("LONG", "SHORT", "BLOCKED") if a.show_blocked else ("LONG", "SHORT"))
    print(shown.to_string(index=False) if not shown.empty else "No instrument satisfies all conditions.")
    errs = [r for r in results if r.status == "ERROR"]
    if errs:
        print(f"\nErrors ({len(errs)}), first few:")
        for r in errs[:8]:
            print(f"  {r.name}: {r.error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
