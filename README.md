# scalp5-bot

5-minute scalping signals for **Indian index and F&O stock futures** (via Upstox), **BTC, ETH, PAXG and XAUUSDT** futures (via CoinSwitch PRO) and **XAUUSD from OANDA** (optional), with a Bull / Bear market mood and the **Bull & Bear** assistant.

Built like wardwatch: a **React** web app on **GitHub Pages** ([`web/`](web/)), a **FastAPI** service on **Render**
([`api/`](api/)) and **Neon** Postgres. The trading engine is plain Python ([`scalpbot/`](scalpbot/)) and is shared by the
API and the command-line tools.

```
Browser ── GitHub Pages: web/ (React, Vite, Tailwind)  ─┐
                                                        │ HTTPS + Bearer token
Render: api/ (FastAPI) ── scalpbot/ (signals, brokers) ─┘── Neon (accounts, encrypted keys, sessions)
```

Everyone **signs in** first. People create an account, an admin approves it, and each person connects **their own** Upstox and CoinSwitch accounts (keys are encrypted per user).

| Page | Who | What you do there |
|------|-----|-------------------|
| **Connect** | everyone | Save your own Upstox and CoinSwitch keys, do the daily Upstox login, run a connection test |
| **Scanner** | everyone | **Scan all**: everything satisfying the rules now. **Single ticker**: one instrument's status, checklists and an interactive chart |
| **Market mood** 🐂🐻 | everyone | Bull / Bear read of Indian futures and of crypto, with the reasons behind it |
| **Backtest** | everyone | Replay the rules on a ticker's recent history and compare the three 200 DEMA trigger modes |
| **My account** | everyone | Change your password |
| **Users** | admins | Approve or reject sign-ups, disable / re-enable, make admin, delete, and the activity log |
| **Bull & Bear** 🐂🐻 | everyone, every page | Floating chat assistant (bottom-right): market mood, live signals, any ticker's status, indicator explanations, connection check |

The command-line tools (`python -m scalpbot.scan`, `.bot`, `.check`, `.backtest`) still work too; the 5-minute Telegram
**alert bot** runs from the command line or Docker (see below).

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
| Forex & metals | OANDA (optional) | `oanda: [XAU_USD]` = **XAUUSD (OANDA)**, the same spot-gold prices as TradingView's OANDA:XAUUSD. Add more OANDA instruments, e.g. `XAG_USD`, `EUR_USD`. Shown only to people who connected OANDA |
| MCX futures | Upstox | optional, e.g. `mcx: [GOLDM, SILVERM, CRUDEOIL]` (off by default) |
| Custom | any | hand-picked entries under `instruments:` |

Upstox's instrument list is downloaded once a day, so futures roll to the next expiry on their own (set `roll_days` to switch a few days before expiry). Use `only:` / `exclude:` to trim the stock futures, for example `only: [RELIANCE, TCS, SBIN]`.

## Run it on your computer

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000               # the API
cd web && npm install && npm run dev                     # the web app at http://localhost:5173 (proxies /api to :8000)
```

Or double-click `start.command` on a Mac: it builds the web app once and serves everything at http://localhost:8000.

**Create an account.** On a local install the first account becomes the admin (or list your email in `ADMIN_EMAILS`).
Accounts, roles, sessions and encrypted keys live in `.state/portal.db`; the encryption key is created at
`.state/master.key` (both git-ignored). Then open **Connect**:

1. **Upstox:** create an app on the Upstox developer site and register the redirect URI shown on the page
   (`APP_URL` + `/upstox/callback`, e.g. `http://localhost:5173/upstox/callback`). Save the API key, secret and redirect
   URI, then *Log in to Upstox*; you come back to the app and the token is saved to your account. Tokens expire daily:
   repeat each trading morning.
2. **CoinSwitch:** save the API key and secret (no withdrawal rights if offered).
3. **OANDA** (optional, for XAUUSD): in OANDA's hub open *Manage API Access*, generate a personal access token and save it
   with the matching account type (a free **practice** account works for prices).
4. **Test connections:** fetches real candles and shows what came back. Confirm `PAXGUSDT` and `XAUUSDT` are OK.

The API never uses keys from the server's `.env`; those are only for the command-line tools.

## Hosting (GitHub Pages + Render + Neon)

1. **Database:** create a free Neon project in AWS Singapore (`ap-southeast-1`, next to Render) and copy its *direct*
   connection string (ends in `?sslmode=require`).
2. **Master key:** run `python -m scalpbot.accounts --new-master-key` and keep a copy somewhere safe.
3. **API on Render:** *New > Blueprint*, pick this repo ([`render.yaml`](render.yaml)), then fill in `DATABASE_URL`,
   `SCALP_MASTER_KEY` and `ADMIN_EMAILS`. `CORS_ORIGINS` and `APP_URL` are set in `render.yaml` for
   `https://kdkapsikar.github.io/scalper5-bot`; change them for another address.
4. **Web app on GitHub Pages:** repo **Settings > Pages > Source: GitHub Actions**.
   [`.github/workflows/pages.yml`](.github/workflows/pages.yml) builds `web/` on every push that touches it and points it
   at `https://scalp5-portal.onrender.com` (set the Actions variable `API_URL` for another address). Free GitHub plans
   publish Pages from public repos only.
5. **First admin:** sign up with an email in `ADMIN_EMAILS`. Share the Pages address; new sign-ups wait under **Users**.
6. **Upstox:** everyone registers `https://kdkapsikar.github.io/scalper5-bot/upstox/callback` as their Upstox app's
   redirect URI.

The pages load instantly from GitHub. On Render's free plan the API sleeps after ~15 idle minutes, so the first data
request after a pause takes ~30-60 s (the app shows "Waking the server up…", and the home page starts waking it).
[`.github/workflows/keepalive.yml`](.github/workflows/keepalive.yml) pings it every 10 minutes on weekdays 08:30-16:30
IST (about 180 of the free plan's 750 hours a month). Slow work (a full scan, the full-breadth mood, a connection
test) runs as a background job that the page polls, so the screen stays responsive.

Security notes: sign-in returns an opaque token (only its sha256 is stored) kept in the browser and sent as
`Authorization: Bearer`; sessions last 7 days from last use and are revoked by signing out, a password change,
disabling or deleting the user. Five wrong passwords lock an account for 15 minutes. CoinSwitch keys can't be
IP-restricted on Render (its address changes); Upstox rate limits are per user. The admin can't see anyone's keys,
but whoever holds both the database and `SCALP_MASTER_KEY` could decrypt them; the Connect page tells users this.

## 1. The scanner page

Controls: **Scan all / Single ticker**, **Universe** (tick which groups), **Strategy rules** (DEMA trigger mode and each filter), **Look back** (a signal fires on a candle close, so the scan also reports signals from the last N closed candles, default 3, so you don't miss one by opening the app late), and **Include closed markets** (to review the last session, e.g. at night).

- **Scan all:** press **Run scan**. You get counts (long, short, blocked, market closed, errors), a table of everything satisfying all conditions (ticker, signal, trigger, candles ago, close time, price, stop, target, RSI) with CSV download, an optional **near-misses** table (a trigger fired but a filter blocked it, with the blocking filter named), and a click on any row opens it in detail. A full F&O scan takes a minute or two; run it again after the next 5-minute close.
- **Single ticker:** type to search; the page shows the headline status, key metrics, the LONG and SHORT checklists, an interactive chart (candles, SMA 22/33, 200 DEMA, Supertrend, pivots, signal markers; times in IST) and the latest cross times. **Refresh** re-fetches.

There is also a command-line version: `python -m scalpbot.scan` (scan all), `python -m scalpbot.scan --ticker "RELIANCE FUT"` (one ticker), with `--groups`, `--lookback`, `--show-blocked`, `--include-closed`.

## Market mood (Bull 🐂 / Bear 🐻)

The **Market mood** page scores Indian futures and crypto separately from -100 (strong bear) to +100 (strong bull), using the scanner's own indicators:

| Weight | Component | Bullish end |
|---|---|---|
| 30% | 200 DEMA breadth | every instrument closes above its 200 DEMA |
| 20% | Supertrend breadth | every Supertrend points up |
| 15% | SMA 22/33 breadth | every SMA 22 is above its SMA 33 |
| 20% | Leader (NIFTY FUT, BTCUSDT) | above the DEMA, Supertrend up, 22 above 33 |
| 10% | Median RSI | 70 or more |
| 5% | Fresh signals | only LONG signals in the last 3 candles |

Labels: 40+ Strong Bull, 15+ Bull, -15 to 15 Neutral, -15 or lower Bear, -40 or lower Strong Bear. *Quick* uses index futures and crypto; *Full* adds every F&O stock future for a proper Indian breadth reading (a minute or two). It describes the market right now; it is not a forecast.

## Bull & Bear, the assistant

Two mascots float at the bottom-right of every signed-in page, like eNagarparishad's मदतनीस: **Bull** (green scarf,
upbeat) and **Bear** (red scarf, cautious). Whichever matches the current market mood stands in front, and the bubble
greets you with it. *Ask Bull & Bear* opens the chat:

| Menu chip | What you get |
|---|---|
| 🐂🐻 Market mood | India and crypto labels and scores, the main reasons, and a caveat from the other mascot |
| ⚡ Live signals | LONG / SHORT setups on index futures and crypto in the last 3 closed candles, with stop and target, plus near-misses |
| 🔎 Check a ticker | Price, 200 DEMA side, Supertrend, SMA 22/33, RSI and any signal for one instrument |
| 📚 Explain | SMA, 200 DEMA, Supertrend, RSI, pivots, ATR stops, the mood score, fees and slippage, blocked setups |
| 🔌 My connections | Whether your Upstox token is fresh and your CoinSwitch keys are saved |

Or just type: *nifty*, *how is banknifty*, *btc*, *gold*, *any signals?*, *what is rsi*. It reads **your own** broker
data (cached per 5-minute candle), describes what the rules see and never places orders or gives advice. Code:
[scalpbot/assistant.py](scalpbot/assistant.py) (the logic), [api/account.py](api/account.py) (`POST /api/assistant`) and
[web/src/components/Assistant.jsx](web/src/components/Assistant.jsx) (chat window and the animated SVG mascots).

## 2. The alert bot

It needs an always-on machine (your computer or a small server); keys come from `.env`:

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

- Pivot "day" is Asia/Kolkata for Upstox, UTC for CoinSwitch and Europe/Athens for OANDA (its midnight is the forex day's 17:00 New York close, give or take an hour in the weeks between US and EU clock changes); override with `tz:` on a custom entry.
- Upstox rate limits: the adapter uses one global limiter (`UPSTOX_MAX_RPS`, default 5 per second), retries on HTTP 429, and caches each contract's history for the day so a cycle only re-fetches today's candles.
- CoinSwitch klines are limited to 30 requests per 60 s; the adapter backfills once, then fetches only new candles.
- CoinSwitch publishes 5-minute candles in batches, so its candle history runs about 7-37 minutes behind the live
  market (measured October 2026). Its futures carry Bybit's prices (identical closes and volume), so the adapter fills
  the missing recent candles from Bybit's public real-time API, with Binance USDT-M futures as a backup. Filled
  candles are never cached (CoinSwitch's own replace them once published) and the Scanner and Connect test say when
  they were used. `SCALP_CRYPTO_FILL=off` disables it; if every source is behind, crypto shows **data delayed**
  (crypto never "closes").
- Instrument-file field names (`underlying_symbol`, `underlying_type`, `expiry`) follow Upstox's documentation; if futures don't appear, `python -m scalpbot.check` shows a warning.
- Each instrument needs about 300+ candles for the 200 DEMA; about 20 days of history is loaded for Upstox.

## Develop

```bash
pip install pytest && python -m pytest -q
```

CI runs the tests on every push (`.github/workflows/ci.yml`).
