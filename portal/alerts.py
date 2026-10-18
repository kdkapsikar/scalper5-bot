"""Alert bot page: start / stop the 5-minute bot and watch what it does."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from scalpbot import creds
from scalpbot import portal_tools as pt
from scalpbot.universe import GROUPS

from portal import ui
from portal.auth import require_admin
from portal.common import get_universe, strategy_rules

ui.eyebrow("Trade · local alerts")
st.title("Alert bot")
st.caption("Checks every selected instrument at each 5-minute candle close and sends an alert when all the rules line up. "
           "It runs in the background on this computer with your saved keys, so keep the computer awake and online. Alerts only; it never places orders.")

admin = require_admin()
my = creds.current() or creds.Creds()
universe, warns = get_universe()
pid = pt.bot_pid()

# --------------------------------------------------------------------------- status + controls
top = st.columns([1, 1, 2])
top[0].metric("Bot", "Running" if pid else "Stopped")
tg_ok = bool(my.TELEGRAM_BOT_TOKEN and my.TELEGRAM_CHAT_ID)
top[1].metric("Telegram", "On" if tg_ok else "Off")
if not tg_ok:
    top[2].info("Telegram is not set, so alerts appear only in the log below. Add it on the Connect page if you want them on your phone.")

with st.container(border=True):
    st.subheader("Settings")
    available = [g for g in GROUPS if any(i.group == g for i in universe)]
    c1, c2 = st.columns(2)
    groups = c1.multiselect("Watch these groups", available, default=available, key="bot_groups", disabled=bool(pid))
    names = [i.name for i in universe if i.group in groups]
    only = c2.multiselect("Or only these tickers (leave empty for the whole groups)", names, key="bot_only", disabled=bool(pid))
    c3, c4 = st.columns(2)
    cooldown = c3.number_input("Cooldown: minimum candles between two same-side alerts per ticker", 0, 60, 6, key="bot_cooldown",
                               disabled=bool(pid))
    dry = c4.checkbox("Practice mode: log only, no Telegram", value=not tg_ok, key="bot_dry", disabled=bool(pid))
    with st.expander("Strategy rules"):
        _, cli_off = strategy_rules(st, prefix="bot_")
    dema_mode = st.session_state.get("bot_dema_mode", "both")

    b1, b2, _ = st.columns([1, 1, 3])
    if not pid:
        if b1.button("Start bot", type="primary", key="bot_start", disabled=not groups):
            try:
                cmd = pt.bot_command(groups, dema_mode, cooldown, dry, cli_off, only)
                st.success(f"Bot started (process {pt.start_bot(cmd, pt.bot_env(my, admin.id))}). The first check runs at the next candle close.")
                st.rerun()
            except Exception as e:
                st.error(str(e))
    else:
        if b1.button("Stop bot", type="primary", key="bot_stop"):
            pt.stop_bot()
            st.rerun()
        st.caption("Stop the bot to change settings. Upstox tokens are re-read every cycle, so a fresh daily login needs no restart.")

# --------------------------------------------------------------------------- latest alerts
st.subheader("Latest alert per ticker")
sig_file = pt.STATE_DIR / "signals.json"
rows = []
if sig_file.exists():
    try:
        data = json.loads(sig_file.read_text())
        for name, v in data.items():
            t = pd.Timestamp(v["bar"]).tz_convert("Asia/Kolkata")
            rows.append({"Ticker": name, "Side": v["side"], "Candle opened (IST)": f"{t:%d %b %H:%M}", "_t": t})
    except Exception:
        pass
if rows:
    df = pd.DataFrame(rows).sort_values("_t", ascending=False).drop(columns="_t")
    st.dataframe(df, hide_index=True)
else:
    st.caption("No alerts yet.")


# --------------------------------------------------------------------------- live log
@st.fragment(run_every=10 if pid else None)
def live_log() -> None:
    st.subheader("Bot log")
    st.caption("Refreshes every 10 seconds while the bot runs. Lines starting with ALERT are signals.")
    text = pt.tail_log(80)
    st.code(text or "The bot has not been started yet.", language="text")


live_log()
