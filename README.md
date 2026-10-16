# scalp5-bot

5-minute scalping signals for **Indian index and F&O stock futures** (via Upstox) and **BTC, ETH, PAXG and XAUUSDT** futures (via CoinSwitch PRO). Two ways to use it:

1. **Scanner app** (`streamlit run app.py`): pick a mode in the sidebar.
   - **Scan all**: scans every instrument and lists the ones satisfying all the rules right now.
   - **Single ticker**: choose one from a dropdown (type to search) and see its full status: signal, a LONG and a SHORT checklist showing which conditions pass, a chart, and the last SMA/DEMA crosses.
2. **Alert bot** (`python -m scalpbot.bot`): runs continuously, wakes at every 5-minute candle close, checks the whole universe and sends Telegram/console alerts.

> **Analysis and alerts only.** Nothing here places orders. Nothing here is financial advice; backtest and paper-trade before risking money.
>
> **Status:** the logic, parsing, scanner, app (including headless browser checks) and bot loop are tested against faked broker responses. The Upstox and CoinSwitch adapters have **not yet been run against live accounts**. Do the setup steps below, starting with `python -m scalpbot.check`, before trusting anything.

## Strategy

| # | Tool | Role |
|---|------|------|
| 1 | SMA 22 / SMA 33 | **Trigger**: 22 crossing above 33 = long, below = short |
| 2 | 22/33 lines vs 200 DEMA | **Second trigger**: lines rising above the DEMA = long, going down through it = short |
| 3 | 200 DEMA | Bias filter (long above, short below) |
| 4 | RSI (14) | Zone + slope filter (long: 35-62 and rising, short: 30-60 and falling; tunable) |
| 5 | Daily pivots (P, R1-R3, S1-S3) | Next level in trade direction = target; needs min room (0.5 ATR) |
| 6 | Supertrend (10, 3) | Direction filter and trailing exit |

Stop = 1.5 x ATR. The DEMA trigger has three modes: `fast` (the 22 line crossing is the event), `both` (default: either line crossing is the event, but the signal fires only once both lines are on the new side), `off`. If the two triggers point opposite ways on one candle, nothing fires. Every filter can be switched off in the app's "Strategy rules" panel or with `--no-dema`, `--no-supertrend`, `--no-rsi`, `--no-room`.

## What it watches (the universe)

Defined in the `universe:` section of `watchlist.yaml`:

| Group | Source | Contents |
|---|---|---|
| Index futures | Upstox | NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 (nearest expiry) |
| Stock futures | Upstox | every NSE F&O stock future (nearest expiry) |
| Crypto | CoinSwitch PRO | BTCUSDT, ETHUSDT, PAXGUSDT, XAUUSDT futures |
| MCX futures | Upstox | optional, e.g. `mcx: [GOLDM, SILVERM, CRUDEOIL]` (off by default) |
| Custom | any | hand-picked entries under `instruments:` |

Upstox's instrument list is downloaded once a day, so futures roll to the next expiry on their own (set `roll_days` to switch a few days before expiry). Use `only:` / `exclude:` to trim the stock futures, for example `only: [RELIANCE, TCS, SBIN]`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # fill in the keys below
```

1. **CoinSwitch keys:** create an API key on CoinSwitch PRO, restricted to your IP and, if offered, with no withdrawal rights. Put `COINSWITCH_API_KEY` and `COINSWITCH_SECRET_KEY` (hex) in `.env`.
2. **Upstox login:** put `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_REDIRECT_URI` in `.env`, then `python scripts/upstox_token.py` (prints the login URL) and `python scripts/upstox_token.py --code <code from the redirect URL>`. Upstox tokens expire daily: repeat each trading morning. The app and bot re-read the token file, and the bot sends a Telegram alert when the token is rejected.
3. **Verify:** `python -m scalpbot.check` fetches 3 sample instruments per group (`--all` for everything) and shows candle counts, last candle time and any login or symbol errors. Confirm `PAXGUSDT` and `XAUUSDT` exist on CoinSwitch futures and that the Upstox futures resolve.

## 1. The scanner app

```bash
streamlit run app.py
```

Sidebar: **Mode**, **Universe** (tick which groups), **Strategy rules** (DEMA trigger mode and each filter), **Look back** (a signal fires on a candle close, so the scan also reports signals from the last N closed candles, default 3, so you don't miss one by opening the app late), and **Include closed markets** (to review the last session, e.g. at night).

- **Scan all:** press **Run scan**. You get counts (long, short, blocked, market closed, errors), a table of everything satisfying all conditions (ticker, signal, trigger, candles ago, close time, price, stop, target, RSI) with CSV download, an optional **near-misses** table (a trigger fired but a filter blocked it, with the blocking filter named), and a picker to open any result in detail. A full F&O scan takes a minute or two; run it again after the next 5-minute close.
- **Single ticker:** choose from the dropdown; the page shows the headline status, key metrics, the LONG and SHORT checklists, the chart (candles, SMA 22/33, 200 DEMA, Supertrend, pivots, signal markers) and the latest cross times. **Refresh** re-fetches.

There is also a command-line version: `python -m scalpbot.scan` (scan all), `python -m scalpbot.scan --ticker "RELIANCE FUT"` (one ticker), with `--groups`, `--lookback`, `--show-blocked`, `--include-closed`.

## 2. The alert bot

```bash
python -m scalpbot.bot                                   # whole universe
python -m scalpbot.bot --groups "Index futures,Crypto"   # subset of groups
python -m scalpbot.bot --only "NIFTY FUT,BTCUSDT"        # specific names
python -m scalpbot.bot --once --dry-run                  # single console pass
```

Signals fire only on a **closed** candle, are de-duplicated per instrument across restarts (`.state/signals.json`) and respect a cooldown (`--cooldown`, default 6 candles). Fetching runs in parallel (`--workers`). If more than 6 signals fire on one candle (a volatile open), you get one digest message instead of a flood. One broken feed never blocks the others: one warning after three failed checks, one alert per broker for login problems, a recovery note, and a "still alive" note every 6 hours. Instruments whose market is closed are skipped automatically.

### Telegram setup
1. Message `@BotFather`, run `/newbot`, copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` into `TELEGRAM_CHAT_ID`.

### Keep it running
- **Docker (VPS or home server):** `docker compose up -d --build` (restarts after crashes and reboots; `.state/` is mounted so alert history and the Upstox token survive).
- **Linux/macOS boot:** `crontab -e` and add `@reboot cd /path/scalp5-bot && .venv/bin/python -m scalpbot.bot >> bot.log 2>&1`.
- **Windows login:** Task Scheduler, trigger "At log on", action `python -m scalpbot.bot`, start in the repo folder.
- GitHub Actions cron is **not** suitable for 5-minute checks (best-effort scheduling, often delayed).

## Backtest

```bash
python -m scalpbot.backtest --source binance --symbol BTCUSDT --days 60      # public crypto data, no keys
python -m scalpbot.backtest --source yfinance --symbol ^NSEI --days 59        # delayed NSE data
python -m scalpbot.backtest --csv data/my_5m.csv --tz Asia/Kolkata            # columns: time,open,high,low,close,volume
```

Add `--dema-cross off|fast|both` to compare trigger modes. Entry is at the next candle's open; fees 5 bps and slippage 2 bps per side by default (`--fee-bps`, `--slippage-bps`); when stop and target fall in one candle the stop is assumed hit first. The summary includes a win rate per trigger. Judge profit factor, average win vs average loss and drawdown over 100+ trades, per session, and check on data you did not tune on. A backtest on the actual Upstox and CoinSwitch feeds is the natural next addition.

## TradingView

`pine/scalp5_confluence.pine` mirrors the rules as a Pine v5 strategy (paste into the Pine editor, add to a 5m chart, *Create Alert > Any alert() function call*). It has not been compiled on TradingView by the author of this repo, so compare a few signals against the Python output first.

## Notes and limits

- Pivot "day" is Asia/Kolkata for Upstox and UTC for CoinSwitch (override with `tz:` on a custom entry).
- Upstox rate limits: the adapter uses one global limiter (`UPSTOX_MAX_RPS`, default 5 per second), retries on HTTP 429, and caches each contract's history for the day so a cycle only re-fetches today's candles.
- CoinSwitch klines are limited to 30 requests per 60 s; the adapter backfills once, then fetches only new candles.
- Instrument-file field names (`underlying_symbol`, `underlying_type`, `expiry`) follow Upstox's documentation; if futures don't appear, `python -m scalpbot.check` shows a warning.
- Each instrument needs about 300+ candles for the 200 DEMA; about 20 days of history is loaded for Upstox.

## Develop

```bash
pip install pytest && python -m pytest -q
```

CI runs the tests on every push (`.github/workflows/ci.yml`).
