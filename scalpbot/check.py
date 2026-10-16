"""Connectivity check: fetch instruments once and report what came back.

    python -m scalpbot.check                  # 3 sample instruments from each group (quick)
    python -m scalpbot.check --all            # every instrument in the universe
    python -m scalpbot.check --only BTCUSDT,XAUUSDT

Run this first on your own machine with live keys. Exit code is non-zero if any instrument fails.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

import pandas as pd

from .bot import CANDLE_MIN, DISPLAY_TZ
from .brokers import AuthExpired, clear_instrument_cache
from .universe import GROUPS, build_universe
from .watchlist import fetch_candles


def main(argv=None) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    p = argparse.ArgumentParser(description="Check broker connectivity for the universe")
    p.add_argument("--watchlist", default=os.getenv("SCALP_WATCHLIST", "watchlist.yaml"))
    p.add_argument("--only", help="comma-separated instrument names")
    p.add_argument("--groups", help=f"comma-separated subset of: {', '.join(GROUPS)}")
    p.add_argument("--all", action="store_true", help="check every instrument instead of 3 per group")
    p.add_argument("--sample", type=int, default=3, help="instruments per group when not using --all")
    p.add_argument("--candles", type=int, default=1000)
    a = p.parse_args(argv)
    logging.basicConfig(level="WARNING", format="%(levelname)s %(message)s")

    insts, warns = build_universe(a.watchlist)
    for w in warns:
        print(f"! {w}")
    if a.groups:
        wanted = {g.strip().lower() for g in a.groups.split(",")}
        insts = [i for i in insts if i.group.lower() in wanted]
    if a.only:
        wanted_names = {s.strip() for s in a.only.split(",")}
        insts = [i for i in insts if i.name in wanted_names]
    elif not a.all:
        seen: dict[str, int] = {}
        sample = []
        for i in insts:
            seen[i.group] = seen.get(i.group, 0) + 1
            if seen[i.group] <= a.sample:
                sample.append(i)
        insts = sample
    print(f"Universe: {len(insts)} instruments to check\n")
    failures = 0
    print(f"{'instrument':<18}{'group':<15}{'candles':>8}  last closed candle (IST)   status")
    for inst in insts:
        try:
            df = fetch_candles(inst, a.candles)
            if df.empty:
                raise RuntimeError("no closed candles returned")
            last = df.index[-1]
            age = (pd.Timestamp.now(tz="UTC") - (last + pd.Timedelta(minutes=CANDLE_MIN))).total_seconds() / 60
            note = "OK" if len(df) >= 300 else f"OK but only {len(df)} candles (indicators need ~300+)"
            if age > 12:
                note += f"  [{age / 60:.1f}h old: market closed?]" if age > 120 else f"  [{age:.0f} min old]"
            print(f"{inst.name:<18}{inst.group:<15}{len(df):>8}  {last.tz_convert(DISPLAY_TZ):%Y-%m-%d %H:%M}"
                  f"          {note}")
        except AuthExpired as e:
            failures += 1
            print(f"{inst.name:<18}{inst.group:<15}{'-':>8}  {'-':<24}   AUTH: {e}")
        except Exception as e:
            failures += 1
            print(f"{inst.name:<18}{inst.group:<15}{'-':>8}  {'-':<24}   FAIL: {str(e)[:160]}")
    clear_instrument_cache()
    print(f"\n{len(insts) - failures}/{len(insts)} instruments OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
