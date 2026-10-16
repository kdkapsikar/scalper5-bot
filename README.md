# scalp5-bot

5-minute scalping signals from a five-indicator confluence, run across a **watchlist** of Indian stocks, indices and MCX commodities (via **Upstox**) and crypto futures (via **CoinSwitch PRO**). The bot wakes at **every 5-minute candle close**, checks each instrument, and alerts you on console and, optionally, Telegram. Includes a backtester and a matching TradingView Pine Script.

> **Alert-only.** The bot never places orders. Nothing here is financial advice; backtest and paper-trade before risking money.
>
> **Status:** logic, parsing and plumbing are unit-tested against faked broker responses. The Upstox and CoinSwitch adapters have **not yet been run against live accounts**. Do step 3 of the quick start before trusting anything.

## Strategy

| # | Tool | Role |
|---|------|------|
| 1 | SMA 22 / SMA 33 | **Trigger**: 22 crossing above 33 = long, below = short |
| 2 | 200 DEMA | Bias filter (long above, short below); also a pullback target |
| 3 | RSI (14) | Zone + slope filter (long: 35-62 and rising, short: 30-60 and falling; tunable) |
| 4 | Daily pivots (P, R1-R3, S1-S3) | Next level in trade direction = target; needs min room (0.5 ATR) |
| 5 | Supertrend (10, 3) | Direction filter and trailing exit |
| 6 | 22/33 lines vs 200 DEMA | **Second trigger**: lines crossing up through the DEMA = long, down through it = short |

The DEMA trigger has three modes (`--dema-cross off|fast|both`, or `dema_cross_mode` in a watchlist entry's `params:`). `fast`: the 22 line crossing the DEMA is the event. `both` (default): either line crossing is the event, but the signal fires only once both lines sit on the new side of the DEMA. The alert and the backtest label each signal's trigger (`SMA cross`, `200 DEMA cross`, or `SMA + DEMA cross`) so you can compare how each performs; the backtest prints a per-trigger win rate. If the two triggers point opposite ways on the same candle, the bot stands aside.

Stop = 1.5 x ATR. Backtester exits: stop, pivot target, Supertrend flip, opposite signal. Every filter can be switched off (`--no-dema`, `--no-supertrend`, `--no-rsi`, `--no-room`), and any instrument can override settings with `params:` in `watchlist.yaml` (gold, crypto and index futures rarely want identical RSI zones).

## Quick start

```bash
git clone <your-repo-url> && cd scalp5-bot
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # fill in the keys below
```

1. **CoinSwitch keys** (BTC, ETH, PAXG): create an API key on CoinSwitch PRO, restrict it to your server's IP and, if offered, to no withdrawal rights. Put `COINSWITCH_API_KEY` and `COINSWITCH_SECRET_KEY` (hex) in `.env`.
2. **Upstox login** (stocks, indices, MCX): put `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_REDIRECT_URI` in `.env`, then
   `python scripts/upstox_token.py` (prints the login URL) and `python scripts/upstox_token.py --code <code from redirect URL>`. The token is saved to `.state/upstox_token.txt`. Upstox tokens expire daily, so repeat each trading morning; the bot re-reads the file every cycle and sends a Telegram alert when the token is rejected.
3. **Verify connectivity:** `python -m scalpbot.check` fetches every instrument once and reports candle counts, last candle time and any auth or symbol errors. Fix those first (for example, confirm `PAXGUSDT` is listed on CoinSwitch futures and the MCX `underlying` names resolve).
4. **Run:** `python -m scalpbot.bot` (or `--only "NIFTY 50,BTC"`, `--once --dry-run` for a single console pass).

Edit `watchlist.yaml` to add or remove instruments. Upstox entries can use an `instrument_key`, a `segment` + `symbol` (resolved from Upstox's instrument file), or `segment: MCX_FO` + `underlying` (nearest unexpired future, re-resolved daily so it rolls). CoinSwitch entries use futures symbols such as `BTCUSDT`.

Each cycle logs one status line per instrument. Signals fire only on a **closed** candle, are de-duplicated per instrument across restarts (`.state/signals.json`), and respect a cooldown (`--cooldown`, default 6 candles). One broken feed never blocks the others: you get a single Telegram warning after three failed checks in a row, one alert per broker for login problems, a recovery note, and a "still alive" note every 6 hours (`--heartbeat-hours`). Instruments whose market is closed are skipped automatically (stale candle check).

### Telegram setup
1. Message `@BotFather`, run `/newbot`, copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` into `TELEGRAM_CHAT_ID`.

## Keep it running (starts on login / boot)

- **Docker (recommended, VPS or home server):** `docker compose up -d --build`. `restart: unless-stopped` brings it back after crashes and reboots; `.state/` is mounted so alert history and the Upstox token survive restarts.
- **Linux/macOS boot:** `crontab -e` and add `@reboot cd /path/scalp5-bot && .venv/bin/python -m scalpbot.bot >> bot.log 2>&1`.
- **Windows login:** Task Scheduler, trigger "At log on", action `python -m scalpbot.bot`, start in the repo folder.
- GitHub Actions cron is **not** suitable for 5-minute checks (best-effort scheduling, often delayed).

## Backtest

```bash
python -m scalpbot.backtest --source binance --symbol BTCUSDT --days 30      # public crypto data, no keys
python -m scalpbot.backtest --source yfinance --symbol ^NSEI --days 30        # delayed NSE data
python -m scalpbot.backtest --csv data/my_5m.csv --tz Asia/Kolkata            # columns: time,open,high,low,close,volume
```

Entry is at the next candle's open; fees 5 bps and slippage 2 bps per side by default (`--fee-bps`, `--slippage-bps`); when stop and target fall in one candle the stop is assumed hit first. Judge win rate, average win vs average loss, profit factor and drawdown **per session** (Indian open, midday, close) before trusting any setting. A broker-fed backtest (Upstox/CoinSwitch history through the same adapters) is the natural next addition.

## TradingView

`pine/scalp5_confluence.pine` mirrors the rules as a Pine v5 strategy: paste it into the Pine editor, add it to a 5m chart, and use *Create Alert > Any alert() function call*. It has not been compiled on TradingView by the author of this repo, so compare a few signals against the Python output first.

## Notes and limits

- Pivot "day" follows each instrument's timezone: Asia/Kolkata for Upstox, UTC for CoinSwitch (override with `tz:` in the watchlist). MCX trades into the late evening, so check that the pivot day suits the contract.
- CoinSwitch klines are rate-limited to 30 requests per 60 s; the adapter backfills once, then fetches only new candles and throttles itself.
- Upstox historical 5-minute data is limited to one month per request; the adapter pulls about 20 calendar days plus today's intraday candles.
- The 200 DEMA needs history; each instrument needs roughly 300+ candles.
- `binance` and `yfinance` sources still work as `source:` values in the watchlist for testing without broker keys.

## Develop

```bash
pip install pytest && python -m pytest -q
```

CI runs the tests on every push (`.github/workflows/ci.yml`).
