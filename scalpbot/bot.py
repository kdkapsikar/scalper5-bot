"""Live signal bot: wakes at every 5-minute candle close, evaluates the strategy, alerts on signals.

    python -m scalpbot.bot --source binance --symbol BTCUSDT
    python -m scalpbot.bot --source yfinance --symbol ^NSEI --tz Asia/Kolkata
    python -m scalpbot.bot --once --dry-run          # single check, console only

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

from .data import closed_only, fetch_binance, fetch_yfinance
from .strategy import Signal, StrategyConfig, add_signals, compute, fmt, latest_signal, status_line

log = logging.getLogger("scalpbot")
CANDLE_MIN = 5
DISPLAY_TZ = "Asia/Kolkata"
STALE_AFTER_MIN = 12  # last closed candle older than this => market closed / feed stalled


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
    """Remembers the last alert so restarts / repeated cycles never double-alert."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.data: dict = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except Exception:
                self.data = {}

    def is_duplicate(self, sig: Signal, cooldown_bars: int) -> bool:
        last_bar, last_side = self.data.get("bar"), self.data.get("side")
        if not last_bar:
            return False
        gap = (sig.bar_open - pd.Timestamp(last_bar)) / pd.Timedelta(minutes=CANDLE_MIN)
        return gap <= 0 or (last_side == sig.side and gap < cooldown_bars)

    def record(self, sig: Signal) -> None:
        self.data = {"bar": sig.bar_open.isoformat(), "side": sig.side}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data))


def format_signal(sig: Signal, symbol: str) -> str:
    close_time = (sig.bar_open + pd.Timedelta(minutes=CANDLE_MIN)).tz_convert(DISPLAY_TZ)
    icon = "🟢 LONG" if sig.side == "LONG" else "🔴 SHORT"
    tgt = fmt(sig.target) if sig.target is not None else "n/a"
    return (
        f"{icon}  {symbol}  5m\n"
        f"Candle close: {close_time:%Y-%m-%d %H:%M} IST\n"
        f"Price: {fmt(sig.price)}\n"
        f"Stop: {fmt(sig.stop)}   Target (next pivot): {tgt}\n"
        f"RSI {sig.rsi:.1f} | Supertrend {'up' if sig.st_up else 'down'} | "
        f"{'above' if sig.above_dema else 'below'} 200 DEMA\n"
        f"Alert only. Not financial advice."
    )


def build_config(args: argparse.Namespace) -> StrategyConfig:
    tz = args.tz or ("Asia/Kolkata" if args.source == "yfinance" else "UTC")
    return StrategyConfig(
        tz=tz,
        require_dema_bias=not args.no_dema,
        require_supertrend=not args.no_supertrend,
        require_rsi=not args.no_rsi,
        require_pivot_room=not args.no_room,
        cross_lookback=args.cross_lookback,
    )


def get_candles(args: argparse.Namespace) -> pd.DataFrame:
    if args.source == "binance":
        df = fetch_binance(args.symbol, "5m", args.candles, futures=args.futures)
    else:
        df = fetch_yfinance(args.symbol, period=args.period).tail(args.candles)
    return closed_only(df, CANDLE_MIN)


# --------------------------------------------------------------------------- one cycle
def run_cycle(args: argparse.Namespace, cfg: StrategyConfig, state: State, notifier: Notifier) -> None:
    df = get_candles(args)
    if df.empty:
        raise RuntimeError("no closed candles returned")
    age_min = (pd.Timestamp.now(tz="UTC") - (df.index[-1] + pd.Timedelta(minutes=CANDLE_MIN))).total_seconds() / 60
    ind = add_signals(compute(df, cfg), cfg)
    log.info(status_line(ind))
    if age_min > STALE_AFTER_MIN:
        log.info("Last closed candle is %.0f min old: market closed or feed stalled, skipping signal check", age_min)
        return
    sig = latest_signal(ind)
    if sig is None:
        return
    if state.is_duplicate(sig, args.cooldown):
        log.info("Signal %s suppressed (duplicate / cooldown)", sig.side)
        return
    notifier.send(format_signal(sig, args.symbol))
    state.record(sig)


# --------------------------------------------------------------------------- entry point
def parse_args(argv=None) -> argparse.Namespace:
    env = os.getenv
    p = argparse.ArgumentParser(description="5-minute confluence scalping signal bot (alert only)")
    p.add_argument("--source", choices=["binance", "yfinance"], default=env("SCALP_SOURCE", "binance"))
    p.add_argument("--symbol", default=env("SCALP_SYMBOL", "BTCUSDT"),
                   help="BTCUSDT / ETHUSDT (binance) or ^NSEI / ^NSEBANK / RELIANCE.NS (yfinance)")
    p.add_argument("--futures", action="store_true", help="use Binance USDT-M futures candles")
    p.add_argument("--tz", default=env("SCALP_TZ"), help="timezone that defines the pivot 'day'")
    p.add_argument("--candles", type=int, default=1000, help="history length used for indicators")
    p.add_argument("--period", default="1mo", help="yfinance lookback period")
    p.add_argument("--delay", type=float, default=5.0, help="seconds to wait after candle close before fetching")
    p.add_argument("--cooldown", type=int, default=6, help="min candles between same-side alerts")
    p.add_argument("--cross-lookback", type=int, default=1)
    p.add_argument("--no-dema", action="store_true", help="don't require 200 DEMA bias")
    p.add_argument("--no-supertrend", action="store_true")
    p.add_argument("--no-rsi", action="store_true")
    p.add_argument("--no-room", action="store_true", help="don't require room to next pivot")
    p.add_argument("--state-file", default=env("SCALP_STATE", ".state/last_signal.json"))
    p.add_argument("--once", action="store_true", help="run a single check and exit")
    p.add_argument("--dry-run", action="store_true", help="console only, no Telegram")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv=None) -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s")
    cfg = build_config(args)
    notifier, state = Notifier(args.dry_run), State(args.state_file)

    stop = threading.Event()
    for sig_name in ("SIGINT", "SIGTERM"):
        if hasattr(os_signal, sig_name):
            os_signal.signal(getattr(os_signal, sig_name), lambda *_: stop.set())

    log.info("Bot started: %s %s 5m (pivot tz=%s)", args.source, args.symbol, cfg.tz)
    if not args.once:
        notifier.send(f"✅ scalp5-bot started: {args.symbol} 5m ({args.source}). Checking every 5-minute candle close.")

    fails, alerted_down = 0, False
    while not stop.is_set():
        try:
            run_cycle(args, cfg, state, notifier)
            if alerted_down:
                notifier.send("✅ scalp5-bot data feed recovered.")
            fails, alerted_down = 0, False
        except Exception as e:
            fails += 1
            log.exception("Cycle failed (%d in a row): %s", fails, e)
            if fails >= 3 and not alerted_down:
                notifier.send(f"⚠️ scalp5-bot: {fails} failed checks in a row: {e}")
                alerted_down = True
        if args.once:
            break
        wait = seconds_to_next_close(time.time(), CANDLE_MIN, args.delay)
        log.info("Next check in %.0fs", wait)
        stop.wait(wait)
    log.info("Bot stopped")


if __name__ == "__main__":
    main()
