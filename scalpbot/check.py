"""Connectivity check: fetch every watchlist instrument once and report what came back.

    python -m scalpbot.check                 # whole watchlist.yaml
    python -m scalpbot.check --only BTC,PAXG

Run this first on your own machine with live keys. Exit code is non-zero if any instrument fails.
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from .brokers import AuthExpired, clear_instrument_cache
from .bot import CANDLE_MIN, DISPLAY_TZ
from .watchlist import fetch_candles, load_watchlist


def main(argv=None) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    p = argparse.ArgumentParser(description="Check broker connectivity for every watchlist instrument")
    p.add_argument("--watchlist", default="watchlist.yaml")
    p.add_argument("--only")
    p.add_argument("--candles", type=int, default=1000)
    a = p.parse_args(argv)
    logging.basicConfig(level="WARNING", format="%(levelname)s %(message)s")

    insts = load_watchlist(a.watchlist)
    if a.only:
        wanted = {s.strip() for s in a.only.split(",")}
        insts = [i for i in insts if i.name in wanted]
    failures = 0
    print(f"{'instrument':<18}{'source':<11}{'candles':>8}  last closed candle (IST)      status")
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
            print(f"{inst.name:<18}{inst.source:<11}{len(df):>8}  {last.tz_convert(DISPLAY_TZ):%Y-%m-%d %H:%M}"
                  f"             {note}")
        except AuthExpired as e:
            failures += 1
            print(f"{inst.name:<18}{inst.source:<11}{'-':>8}  {'-':<28}  AUTH: {e}")
        except Exception as e:
            failures += 1
            print(f"{inst.name:<18}{inst.source:<11}{'-':>8}  {'-':<28}  FAIL: {str(e)[:160]}")
    clear_instrument_cache()
    print(f"\n{len(insts) - failures}/{len(insts)} instruments OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
