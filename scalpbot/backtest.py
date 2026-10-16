"""Bar-by-bar backtester using the same signal code as the live bot.

    python -m scalpbot.backtest --source binance --symbol BTCUSDT --days 30
    python -m scalpbot.backtest --csv data/nifty_5m.csv --tz Asia/Kolkata

Assumptions: enter at the OPEN of the candle after the signal; exit on stop, pivot target,
Supertrend flip, or opposite signal; if stop and target are both inside one candle the stop wins.
Returns are per trade, un-leveraged, after fees and slippage.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .data import fetch_binance_history, fetch_yfinance, load_csv
from .strategy import StrategyConfig, add_signals, compute


def backtest(df: pd.DataFrame, cfg: StrategyConfig, fee_bps: float = 5.0, slippage_bps: float = 2.0) -> pd.DataFrame:
    d = add_signals(compute(df, cfg), cfg)
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    st_dir = d["st_dir"].to_numpy()
    trig = d["trigger"].to_numpy()
    long_sig, short_sig = d["long_sig"].to_numpy(), d["short_sig"].to_numpy()
    arrs = {k: d[k].to_numpy(float) for k in ("long_stop", "long_tp", "short_stop", "short_tp")}
    cost = 2 * (fee_bps + slippage_bps) / 1e4
    trades: list[dict] = []
    pos = None  # dict(side, entry, stop, tp, i)

    def close_trade(i: int, price: float, reason: str) -> None:
        nonlocal pos
        ret = pos["side"] * (price - pos["entry"]) / pos["entry"] - cost
        trades.append({"entry_time": d.index[pos["i"]], "exit_time": d.index[i], "side": "LONG" if pos["side"] == 1 else "SHORT",
                       "entry": pos["entry"], "exit": price, "ret": ret, "reason": reason, "bars": i - pos["i"],
                       "trigger": pos["trig"]})
        pos = None

    for i in range(1, len(d)):
        if pos and ((pos["side"] == 1 and short_sig[i - 1]) or (pos["side"] == -1 and long_sig[i - 1])):
            close_trade(i, o[i], "opposite")
        if pos is None and (long_sig[i - 1] or short_sig[i - 1]):
            side = 1 if long_sig[i - 1] else -1
            k = "long" if side == 1 else "short"
            pos = {"side": side, "entry": o[i], "stop": arrs[f"{k}_stop"][i - 1], "tp": arrs[f"{k}_tp"][i - 1], "i": i,
                   "trig": trig[i - 1]}
        if pos is None:
            continue
        if pos["side"] == 1:
            if l[i] <= pos["stop"]:
                close_trade(i, min(o[i], pos["stop"]), "stop")
            elif not np.isnan(pos["tp"]) and h[i] >= pos["tp"]:
                close_trade(i, max(o[i], pos["tp"]), "target")
            elif st_dir[i] == -1:
                close_trade(i, c[i], "supertrend")
        else:
            if h[i] >= pos["stop"]:
                close_trade(i, max(o[i], pos["stop"]), "stop")
            elif not np.isnan(pos["tp"]) and l[i] <= pos["tp"]:
                close_trade(i, min(o[i], pos["tp"]), "target")
            elif st_dir[i] == 1:
                close_trade(i, c[i], "supertrend")
    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0}
    r = trades["ret"]
    wins, losses = r[r > 0], r[r <= 0]
    equity = (1 + r).cumprod()
    return {
        "trades": len(r),
        "win_rate_%": round(100 * len(wins) / len(r), 1),
        "avg_win_%": round(100 * wins.mean(), 3) if len(wins) else 0.0,
        "avg_loss_%": round(100 * losses.mean(), 3) if len(losses) else 0.0,
        "profit_factor": round(wins.sum() / abs(losses.sum()), 2) if losses.sum() != 0 else float("inf"),
        "total_return_%": round(100 * (equity.iloc[-1] - 1), 2),
        "max_drawdown_%": round(100 * (equity / equity.cummax() - 1).min(), 2),
        "by_exit": trades["reason"].value_counts().to_dict(),
        "by_trigger": {t: {"trades": int(len(g)), "win_%": round(float(100 * (g["ret"] > 0).mean()), 1),
                           "avg_%": round(float(100 * g["ret"].mean()), 3)} for t, g in trades.groupby("trigger")},
    }


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Backtest the 5-minute confluence strategy")
    p.add_argument("--source", choices=["binance", "yfinance"], default="binance")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--csv", help="use a local CSV instead (time,open,high,low,close,volume)")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--futures", action="store_true")
    p.add_argument("--tz", default=None)
    p.add_argument("--fee-bps", type=float, default=5.0, help="per side")
    p.add_argument("--slippage-bps", type=float, default=2.0, help="per side")
    p.add_argument("--dema-cross", choices=["off", "fast", "both"], default="both",
                   help="200 DEMA cross trigger mode")
    p.add_argument("--out", default="trades.csv")
    a = p.parse_args(argv)

    if a.csv:
        df = load_csv(a.csv)
    elif a.source == "binance":
        df = fetch_binance_history(a.symbol, a.days, futures=a.futures)
    else:
        df = fetch_yfinance(a.symbol, period=f"{min(a.days, 59)}d")
    cfg = StrategyConfig(tz=a.tz or ("Asia/Kolkata" if a.source == "yfinance" and not a.csv else "UTC"),
                         dema_cross_mode=a.dema_cross)
    trades = backtest(df, cfg, a.fee_bps, a.slippage_bps)
    print(f"Candles: {len(df)}  ({df.index[0]} -> {df.index[-1]})")
    for k, v in summarize(trades).items():
        print(f"{k:>16}: {v}")
    if not trades.empty:
        trades.to_csv(a.out, index=False)
        print(f"Trades saved to {a.out}")


if __name__ == "__main__":
    main()
