# scalp5-bot

5-minute scalping signals from a five-indicator confluence, with a bot that wakes on **every 5-minute candle close**, checks the rules, and alerts you (console + optional Telegram). Includes a backtester and a matching TradingView Pine Script.

> **Alert-only.** The bot never places orders. Nothing here is financial advice; backtest and paper-trade before risking money.

## Strategy

| # | Tool | Role |
|---|------|------|
| 1 | SMA 22 / SMA 33 | **Trigger**: 22 crossing above 33 = long, below = short |
| 2 | 200 DEMA | Bias filter (long above, short below); also a pullback target |
| 3 | RSI (14) | Zone + slope filter (long: 35-62 and rising, short: 30-60 and falling; tunable) |
| 4 | Daily pivots (P, R1-R3, S1-S3) | Next level in trade direction = target; needs min room (0.5 ATR) |
| 5 | Supertrend (10, 3) | Direction filter and trailing exit |

Stop = 1.5 x ATR. Exits in the backtester: stop, pivot target, Supertrend flip, opposite signal. Every filter can be switched off (`--no-dema`, `--no-supertrend`, `--no-rsi`, `--no-room`). RSI zones, ATR multiples and indicator lengths live in `StrategyConfig` (`scalpbot/strategy.py`).

## Quick start

```bash
git clone <your-repo-url> && cd scalp5-bot
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # add Telegram token/chat id (optional)

python -m scalpbot.bot --once --dry-run                # single check, console only
python -m scalpbot.bot --source binance --symbol BTCUSDT
python -m scalpbot.bot --source yfinance --symbol ^NSEI --tz Asia/Kolkata   # Nifty 50
python -m scalpbot.bot --source yfinance --symbol ^NSEBANK --tz Asia/Kolkata
```

Each cycle logs one status line (close, 22/33 state, Supertrend, RSI, DEMA side, signal). Signals fire only on a **closed** candle, are de-duplicated across restarts (`.state/`), and respect a cooldown (`--cooldown`, default 6 candles). If three checks fail in a row you get a Telegram warning, and another when the feed recovers. Outside market hours (stale candles) signal checks are skipped.

### Telegram setup
1. Message `@BotFather`, run `/newbot`, copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` into `TELEGRAM_CHAT_ID`.

## Keep it running (starts on login / boot)

The bot only checks while it is running, so run it somewhere that stays on.

- **Docker (recommended, VPS or home server):** `docker compose up -d --build`. `restart: unless-stopped` brings it back after crashes and reboots.
- **Linux/macOS login or boot:** `crontab -e` and add `@reboot cd /path/scalp5-bot && .venv/bin/python -m scalpbot.bot >> bot.log 2>&1`.
- **Windows login:** Task Scheduler, trigger "At log on", action `python -m scalpbot.bot`, start in the repo folder.
- GitHub Actions cron is **not** suitable for 5-minute checks: schedules are best-effort and often delayed. If you must, use `--once` in a scheduled workflow, but expect late alerts.

## Backtest

```bash
python -m scalpbot.backtest --source binance --symbol BTCUSDT --days 30
python -m scalpbot.backtest --source yfinance --symbol ^NSEI --days 30
python -m scalpbot.backtest --csv data/my_5m.csv --tz Asia/Kolkata   # columns: time,open,high,low,close,volume
```

Entry is at the next candle's open, fees 5 bps and slippage 2 bps per side by default (`--fee-bps`, `--slippage-bps`), and when stop and target fall in one candle the stop is assumed hit first. Check win rate, average win vs average loss, profit factor and drawdown **per session** (Indian open, midday, close) before trusting any setting.

## TradingView

`pine/scalp5_confluence.pine` mirrors the rules as a Pine v5 strategy: paste it into the Pine editor, add it to a 5m chart, and use *Create Alert > Any alert() function call* for chart alerts. It has not been compiled on TradingView by the author of this repo, so compare a few signals against the Python output first.

## Notes and limits

- Binance candles are a proxy for CoinSwitch prices; levels differ slightly. Use `--futures` for USDT-M futures candles. Binance may be geo-restricted in some regions.
- yfinance 5-minute data is delayed and limited to about 60 days; fine for alerts and testing, not for execution-grade data.
- Pivot "day" follows `--tz` (UTC for crypto, Asia/Kolkata for NSE).
- The 200 DEMA needs history; the bot pulls 1000 candles per check.

## Develop

```bash
pip install pytest && pytest -q
```

CI runs the tests on every push (`.github/workflows/ci.yml`).
