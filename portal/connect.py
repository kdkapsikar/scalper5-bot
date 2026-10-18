"""Connect page: each user saves their own keys, does the daily Upstox login, and tests everything."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from scalpbot import creds
from scalpbot import portal_tools as pt
from scalpbot.brokers import clear_candle_caches, clear_instrument_cache

from portal import ui
from portal.auth import accounts, current_user, hosted, portal_url
from portal.common import get_universe

acc = accounts()
user = current_user()
my = creds.current() or creds.Creds()
saved_at = acc.key_saved_at(user.id)

ui.eyebrow("Setup · your broker accounts")
st.title("Connect")
st.caption("Connect **your own** Upstox and CoinSwitch accounts. Keys are encrypted before they are stored and are only "
           "used to fetch market data for your pages; they are never shown again. The portal operator holds the "
           "encryption key, so use keys that can't withdraw funds. Leave a box empty to keep what is already saved.")

msg = st.session_state.pop("conn_msg", None)
if msg:
    (st.success if msg[0] == "success" else st.error)(msg[1])


def _save(values: dict) -> None:
    saved = acc.save_keys(user.id, values)
    if saved:
        clear_candle_caches()
        st.session_state["conn_msg"] = ("success", f"Saved: {', '.join(saved)}")
    else:
        st.session_state["conn_msg"] = ("error", "Nothing to save.")
    st.rerun()


# --------------------------------------------------------------------------- status
tok_at = saved_at.get("UPSTOX_ACCESS_TOKEN")
age = (dt.datetime.now(dt.timezone.utc) - tok_at).total_seconds() / 3600 if tok_at and my.UPSTOX_ACCESS_TOKEN else None
c = st.columns(4)
c[0].metric("Upstox token", "Saved" if my.UPSTOX_ACCESS_TOKEN else "Missing",
            help="Upstox tokens expire every day. Log in again each trading morning.")
c[1].metric("Token age", "-" if age is None else f"{age:.1f} h")
c[2].metric("CoinSwitch keys", "Saved" if my.COINSWITCH_API_KEY and my.COINSWITCH_SECRET_KEY else "Missing")
c[3].metric("Telegram", "Saved" if my.TELEGRAM_BOT_TOKEN and my.TELEGRAM_CHAT_ID else "Not set",
            help="Optional: only used by the Alert bot on a local install.")
if age is not None and age > 20:
    st.warning("Your Upstox token is more than 20 hours old and has probably expired. Log in again below.")

tabs = ["1 · Upstox (India)", "2 · CoinSwitch (crypto)", "3 · Test connections"]
if not hosted():
    tabs.insert(2, "Telegram (optional)")
tab = dict(zip(tabs, st.tabs(tabs)))

# --------------------------------------------------------------------------- Upstox
with tab["1 · Upstox (India)"]:
    st.subheader("Step 1: your Upstox app (one time)")
    st.caption("Create an app on the Upstox developer site under your own Upstox account. Register this exact redirect "
               f"URI there: `{portal_url()}`. Then the login below finishes by itself.")
    with st.form("up_keys"):
        a = st.text_input("API key", type="password", placeholder="saved" if my.UPSTOX_API_KEY else "", key="up_key")
        b = st.text_input("API secret", type="password", placeholder="saved" if my.UPSTOX_API_SECRET else "", key="up_secret")
        r = st.text_input("Redirect URI", value=my.UPSTOX_REDIRECT_URI or portal_url(), key="up_redirect")
        if st.form_submit_button("Save Upstox app details", type="primary"):
            _save({"UPSTOX_API_KEY": a, "UPSTOX_API_SECRET": b, "UPSTOX_REDIRECT_URI": r})

    st.subheader("Step 2: today's login (every trading morning)")
    if my.UPSTOX_API_KEY and my.UPSTOX_REDIRECT_URI:
        if st.button("Prepare Upstox login", key="up_prepare") or st.session_state.get("up_url"):
            if "up_url" not in st.session_state:
                st.session_state["up_url"] = pt.upstox_login_url(my.UPSTOX_API_KEY, my.UPSTOX_REDIRECT_URI,
                                                                 acc.new_login_state(user.id))
            st.link_button("Log in to Upstox", st.session_state["up_url"], type="primary")
            st.caption("The link works once and for 15 minutes. After you log in, Upstox sends you back here and the "
                       "token is saved to your account. If you land on a different page, paste its address below.")
    else:
        st.info("Save your Upstox API key and redirect URI first.")
    with st.form("up_code"):
        pasted = st.text_input("Paste the code, or the whole address you landed on", key="up_code_text")
        if st.form_submit_button("Finish login"):
            try:
                token = pt.upstox_get_token(pasted, my.UPSTOX_API_KEY, my.UPSTOX_API_SECRET, my.UPSTOX_REDIRECT_URI)
                acc.save_keys(user.id, {"UPSTOX_ACCESS_TOKEN": token})
                acc.log("upstox_login", user.email)
                st.session_state.pop("up_url", None)
                clear_candle_caches()
                st.session_state["conn_msg"] = ("success", pt.saved_message())
                st.rerun()
            except Exception as e:
                st.error(str(e))
    with st.expander("Advanced: paste an access token you already have"):
        with st.form("up_tok"):
            t = st.text_input("Access token", type="password", key="up_token")
            if st.form_submit_button("Save token"):
                _save({"UPSTOX_ACCESS_TOKEN": t})

# --------------------------------------------------------------------------- CoinSwitch
with tab["2 · CoinSwitch (crypto)"]:
    if hosted():
        st.caption("Create the key on CoinSwitch PRO with no withdrawal rights. This portal runs on a shared cloud server "
                   "whose address changes, so an IP-restricted key will be rejected. This tool only reads candles.")
    else:
        st.caption("Create the key on CoinSwitch PRO. Restrict it to this computer's IP and, if offered, give it no "
                   "withdrawal rights. This tool only reads candles; it never places orders.")
    with st.form("cs_keys"):
        a = st.text_input("API key", type="password", placeholder="saved" if my.COINSWITCH_API_KEY else "", key="cs_key")
        b = st.text_input("Secret key (hex)", type="password", placeholder="saved" if my.COINSWITCH_SECRET_KEY else "",
                          key="cs_secret")
        if st.form_submit_button("Save CoinSwitch keys", type="primary"):
            _save({"COINSWITCH_API_KEY": a, "COINSWITCH_SECRET_KEY": b})

# --------------------------------------------------------------------------- Telegram (local alert bot only)
if "Telegram (optional)" in tab:
    with tab["Telegram (optional)"]:
        st.caption("Used by the Alert bot on this computer. Create a bot with @BotFather, send it any message, then open "
                   "`https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat id.")
        with st.form("tg"):
            a = st.text_input("Bot token", type="password", placeholder="saved" if my.TELEGRAM_BOT_TOKEN else "", key="tg_token")
            b = st.text_input("Chat id", value=my.TELEGRAM_CHAT_ID, key="tg_chat")
            if st.form_submit_button("Save Telegram settings", type="primary"):
                _save({"TELEGRAM_BOT_TOKEN": a, "TELEGRAM_CHAT_ID": b})
        if st.button("Send a test message", key="tg_test"):
            try:
                st.success(pt.telegram_test(my.TELEGRAM_BOT_TOKEN, my.TELEGRAM_CHAT_ID))
            except Exception as e:
                st.error(str(e))

# --------------------------------------------------------------------------- tests
with tab["3 · Test connections"]:
    st.caption("Fetches real candles for a sample (3 per group) or for every instrument, and shows what came back. "
               "Check that PAXGUSDT and XAUUSDT appear and are OK. NSE futures show 'market closed' outside trading hours.")
    universe, warns = get_universe()
    for w in warns:
        st.warning(w)
    c1, c2 = st.columns([1, 3])
    scope = c2.radio("What to test", ["Sample (3 per group)", "Everything"], horizontal=True, key="test_scope")
    if c1.button("Run connection test", type="primary", key="run_test"):
        clear_instrument_cache()
        insts = universe if scope == "Everything" else pt.sample_per_group(universe)
        with st.spinner(f"Testing {len(insts)} instruments..."):
            st.session_state["test_result"] = pt.check_instruments(insts)
    res = st.session_state.get("test_result")
    if res is not None:
        ok = res["Status"].str.startswith("OK").sum()
        st.write(f"**{ok} of {len(res)} OK**")
        st.dataframe(res, hide_index=True)
        if (res["Status"].str.startswith("LOGIN")).any():
            st.warning("Some instruments need a login: complete step 1 and 2 on the Upstox tab or add the CoinSwitch keys.")

    with st.expander("Remove saved keys"):
        which = st.multiselect("Keys to remove", [k for k in creds.FIELDS if k in saved_at], key="rm_keys")
        if st.button("Remove", key="rm_btn") and which:
            acc.remove_keys(user.id, which)
            clear_candle_caches()
            st.session_state["conn_msg"] = ("success", f"Removed: {', '.join(which)}")
            st.rerun()
