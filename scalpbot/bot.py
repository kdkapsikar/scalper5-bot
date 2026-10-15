"""Live signal bot: wakes at every 5-minute candle close, checks every watchlist instrument, alerts on signals.

    python -m scalpbot.bot                       # uses watchlist.yaml
    python -m scalpbot.bot --only "NIFTY 50,BTC" # subset
    python -m scalpbot.bot --source binance --symbol BTCUSDT   # quick single instrument
    python -m scalpbot.bot --once --dry-run      # one pass, console only

The bot is ALERT-ONLY: it never places orders.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal as os_signal
import threading
import time
from pathlib import Path

import pandas as pd
import requests

from .brokers import AuthExpired, clear_instrument_cache
from .strategy import Signal, add_signals, compute, fmt, latest_signal, status_line
from .watchlist import SOURCES, Instrument, fetch_candles, load_watchlist, make_config

log = logging.getLogger("scalpbot")
CANDLE_MIN = 5
DISPLAY_TZ = "Asia/Kolkata"
STALE_AFTER_MIN = 12   # last closed candle older than this => market closed / feed stalled
FAILS_BEFORE_ALERT = 3


# --------------------------------------------------------------------------- helpers
def seconds_to_next_close(now_ts: float, minutes: int = CANDLE_MIN, delay: float = 5.0) -> float:
    step = minutes * 60
    return max(0.0, (now_ts // step + 1) * step + delay - now_ts)


class Notifier:
    def __init__(self, dry_run: bool):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.telegram = bool(self.token and self.chat_id) and not dry_run
        if not self.telegram:
            log.info("Telegram disabled (dry-run or TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set): console only")

    def send(self, text: str) -> None:
        log.info("ALERT\n%s", text)
        if not self.telegram:
            return
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text},
                timeout=10,
            )
            r.raise_for_status()
        except Exception as e:
            log.warning("Telegram send failed: %s", e)


class State:
    """Remembers the last alert per instrument so restarts / repeated cycles never double-alert."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.data: dict = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except Exception:
                self.data = {}

    def is_duplicate(self, name: str, sig: Signal, cooldown_bars: int) -> bool:
        last = self.data.get(name)
        if not last:
            return False
        gap = (sig.bar_open - pd.Timestamp(last["bar"])) / pd.Timedelta(minutes=CANDLE_MIN)
        return gap <= 0 or (last["side"] == sig.side and gap < cooldown_bars)

    def record(self, name: str, sig: Signal) -> None:
        self.data[name] = {"bar": sig.bar_open.isoformat(), "side": sig.side}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data))


class Health:
    """Tracks consecutive failures so one broken feed alerts once, not every 5 minutes."""

    def __init__(self):
        self.fails: dict[str, int] = {}
        self.alerted: set[str] = set()
        self.auth_alerted: set[str] = set()


def format_signal(name: str, sig: Signal) -> str:
    close_time = (sig.bar_open + pd.Timedelta(minutes=CANDLE_MIN)).tz_convert(DISPLAY_TZ)
    icon = "🟢 LONG" if sig.side == "LONG" else "🔴 SHORT"
    tgt = fmt(sig.target) if sig.target is not None else "n/a"
    return (
        f"{icon}  {name}  5m\n"
        f"Candle close: {close_time:%Y-%m-%d %H:%M} IST\n"
        f"Price: {fmt(sig.price)}\n"
        f"Stop: {fmt(sig.stop)}   Target (next pivot): {tgt}\n"
        f"RSI {sig.rsi:.1f} | Supertrend {'up' if sig.st_up else 'down'} | "
        f"{'above' if sig.above_dema else 'below'} 200 DEMA\n"
        f"Alert only. Not financial advice."
    )


def flags_from(args: argparse.Namespace) -> dict:
    f: dict = {}
    if args.no_dema:
        f["require_dema_bias"] = False
    if args.no_supertrend:
        f["require_supertrend"] = False
    if args.no_rsi:
        f["require_rsi"] = False
    if args.no_room:
        f["require_pivot_room"] = False
    if args.cross_lookback != 1:
        f["cross_lookback"] = args.cross_lookback
    return f


def fetch_fresh(inst: Instrument, n: int) -> pd.DataFrame:
    """Fetch closed candles; if the just-closed candle is not published yet, retry briefly."""
    expected = pd.Timestamp.now(tz="UTC").floor(f"{CANDLE_MIN}min") - pd.Timedelta(minutes=CANDLE_MIN)
    df = fetch_candles(inst, n)
    for _ in range(3):
        if df.empty:
            raise RuntimeError("no closed candles returned")
        lag = expected - df.index[-1]
        if lag <= pd.Timedelta(0) or lag > pd.Timedelta(minutes=CANDLE_MIN):
            break  # up to date, or more than one candle behind (market closed): retrying won't help
        time.sleep(3)
        df = fetch_candles(inst, n)
    if df.empty:
        raise RuntimeError("no closed candles returned")
    return df


# --------------------------------------------------------------------------- one instrument, one cycle
def run_instrument(inst: Instrument, args, flags: dict, state: State, notifier: Notifier) -> str:
    cfg = make_config(inst, flags)
    df = fetch_fresh(inst, args.candles)
    age_min = (pd.Timestamp.now(tz="UTC") - (df.index[-1] + pd.Timedelta(minutes=CANDLE_MIN))).total_seconds() / 60
    ind = add_signals(compute(df, cfg), cfg)
    log.info("%-16s %s", inst.name, status_line(ind))
    if age_min > STALE_AFTER_MIN:
        log.info("%-16s last closed candle is %.0f min old: market closed or feed stalled, skipping", inst.name, age_min)
        return "stale"
    sig = latest_signal(ind)
    if sig is None:
        return "none"
    if state.is_duplicate(inst.name, sig, args.cooldown):
        log.info("%-16s %s suppressed (duplicate / cooldown)", inst.name, sig.side)
        return "duplicate"
    notifier.send(format_signal(inst.name, sig))
    state.record(inst.name, sig)
    return "alert"


def run_all(insts: list[Instrument], args, flags: dict, state: State, notifier: Notifier, health: Health) -> dict:
    """One pass over the watchlist. A failing instrument never blocks the others."""
    results: dict[str, str] = {}
    auth_failed: set[str] = set()
    for inst in insts:
        if inst.source in auth_failed:
            results[inst.name] = "FAIL"
            continue
        try:
            results[inst.name] = run_instrument(inst, args, flags, state, notifier)
            health.fails[inst.name] = 0
            health.auth_alerted.discard(inst.source)
            if inst.name in health.alerted:
                health.alerted.discard(inst.name)
                notifier.send(f"✅ {inst.name}: data feed recovered.")
        except AuthExpired as e:
            auth_failed.add(inst.source)
            results[inst.name] = "FAIL"
            log.error("%s: %s login/token problem: %s", inst.name, inst.source, e)
            if inst.source not in health.auth_alerted:
                health.auth_alerted.add(inst.source)
                hint = " Run scripts/upstox_token.py to log in again." if inst.source == "upstox" else ""
                notifier.send(f"🔑 scalp5-bot: {inst.source} rejected our credentials ({e}).{hint}")
        except Exception as e:
            n = health.fails.get(inst.name, 0) + 1
            health.fails[inst.name] = n
            results[inst.name] = "FAIL"
            log.exception("%s: cycle failed (%d in a row): %s", inst.name, n, e)
            if n >= FAILS_BEFORE_ALERT and inst.name not in health.alerted:
                health.alerted.add(inst.name)
                notifier.send(f"⚠️ scalp5-bot: {inst.name} failed {n} checks in a row: {e}")
    clear_instrument_cache()
    return results


# --------------------------------------------------------------------------- entry point
def parse_args(argv=None) -> argparse.Namespace:
    env = os.getenv
    p = argparse.ArgumentParser(description="5-minute confluence scalping signal bot (alert only)")
    p.add_argument("--watchlist", default=env("SCALP_WATCHLIST", "watchlist.yaml"))
    p.add_argument("--only", help="comma-separated instrument names from the watchlist")
    p.add_argument("--source", choices=sorted(SOURCES), help="quick single instrument (with --symbol)")
    p.add_argument("--symbol", help="symbol for --source, e.g. BTCUSDT or ^NSEI")
    p.add_argument("--candles", type=int, default=1000, help="history length used for indicators")
    p.add_argument("--delay", type=float, default=5.0, help="seconds to wait after candle close before fetching")
    p.add_argument("--cooldown", type=int, default=6, help="min candles between same-side alerts per instrument")
    p.add_argument("--cross-lookback", type=int, default=1)
    p.add_argument("--no-dema", action="store_true", help="don't require 200 DEMA bias")
    p.add_argument("--no-supertrend", action="store_true")
    p.add_argument("--no-rsi", action="store_true")
    p.add_argument("--no-room", action="store_true", help="don't require room to next pivot")
    p.add_argument("--state-file", default=env("SCALP_STATE", ".state/signals.json"))
    p.add_argument("--heartbeat-hours", type=float, default=6.0, help="'still alive' Telegram note interval, 0 = off")
    p.add_argument("--once", action="store_true", help="run a single pass and exit")
    p.add_argument("--dry-run", action="store_true", help="console only, no Telegram")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def build_instruments(args) -> list[Instrument]:
    if args.symbol:
        return [Instrument(name=args.symbol, source=args.source or "binance", symbol=args.symbol)]
    insts = load_watchlist(args.watchlist)
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        missing = wanted - {i.name for i in insts}
        if missing:
            raise SystemExit(f"--only: not in watchlist: {sorted(missing)}")
        insts = [i for i in insts if i.name in wanted]
    return insts


def main(argv=None) -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s")
    insts, flags = build_instruments(args), flags_from(args)
    for inst in insts:
        make_config(inst, flags)  # fail fast on bad parameters
    notifier, state, health = Notifier(args.dry_run), State(args.state_file), Health()

    stop = threading.Event()
    for sig_name in ("SIGINT", "SIGTERM"):
        if hasattr(os_signal, sig_name):
            os_signal.signal(getattr(os_signal, sig_name), lambda *_: stop.set())

    names = ", ".join(i.name for i in insts)
    log.info("Bot started: %d instruments (%s)", len(insts), names)
    if not args.once:
        notifier.send(f"✅ scalp5-bot started on {len(insts)} instruments: {names}. Checking at every 5-minute candle close.")

    last_beat = time.time()
    while not stop.is_set():
        results = run_all(insts, args, flags, state, notifier, health)
        if args.heartbeat_hours and time.time() - last_beat >= args.heartbeat_hours * 3600 and not args.once:
            bad = [n for n, r in results.items() if r == "FAIL"]
            notifier.send(f"🫀 scalp5-bot alive: {len(results) - len(bad)}/{len(results)} feeds OK"
                          + (f". Failing: {', '.join(bad)}" if bad else "."))
            last_beat = time.time()
        if args.once:
            break
        wait = seconds_to_next_close(time.time(), CANDLE_MIN, args.delay)
        log.info("Next check in %.0fs", wait)
        stop.wait(wait)
    log.info("Bot stopped")


if __name__ == "__main__":
    main()
