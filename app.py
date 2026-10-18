"""Scalp5 web portal.  Start it with:   streamlit run app.py

Everyone signs in first. Each person connects their own Upstox and CoinSwitch accounts; their keys are stored
encrypted and only used for their own pages. Admins also see the Admin page (users, approvals, audit log).
  Connect      save your keys, do the daily Upstox login, test the connections
  Scanner      Scan all (everything satisfying the rules now) or Single ticker (pick one from a dropdown)
  Market mood  Bull / Bear read of Indian futures and crypto
  Backtest     replay the rules on an instrument's recent history
  Alert bot    local installs only: start / stop the 5-minute alert bot (admins)
"""
from __future__ import annotations

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from scalpbot import creds
from scalpbot import portal_tools as pt
from scalpbot.brokers import clear_candle_caches

from portal import ui
from portal.assistant import launcher
from portal.auth import accounts, current_user, hosted, sign_out

creds.strict()                               # this process serves many users: never use the server's .env keys
st.set_page_config(page_title="Scalp5", page_icon=str(ui.ASSETS / "mark.svg"), layout="wide")
ui.apply_theme()

try:
    acc = accounts()
except Exception as e:      # database unreachable, master key missing, ...
    st.error(f"The portal could not open its accounts database: {e}")
    st.stop()

# --------------------------------------------------------------------------- Upstox login redirect
# Upstox sends people back to the portal address with ?code=...&state=...  The state was issued to one signed-in
# user, so the token is saved to that user even if this browser tab is a fresh, signed-out session.
qp = st.query_params
if "code" in qp and "state" in qp:
    code, state = qp.get("code"), qp.get("state")
    owner = acc.consume_login_state(state)
    if owner is None:
        st.session_state["conn_msg"] = ("error", "That Upstox login link has expired or was already used. "
                                                 "Start the login again from the Connect page.")
    else:
        c = acc.load_creds(owner.id)
        try:
            token = pt.upstox_get_token(code, c.UPSTOX_API_KEY, c.UPSTOX_API_SECRET, c.UPSTOX_REDIRECT_URI)
            acc.save_keys(owner.id, {"UPSTOX_ACCESS_TOKEN": token})
            acc.log("upstox_login", owner.email)
            clear_candle_caches()
            st.session_state["conn_msg"] = ("success", pt.saved_message())
        except Exception as e:
            st.session_state["conn_msg"] = ("error", str(e))
    st.session_state["auth_msg"] = st.session_state["conn_msg"]
    st.query_params.clear()

user = current_user()

# --------------------------------------------------------------------------- signed out: only the sign-in page
if user is None:
    creds.activate(creds.Creds())            # never fall back to keys in this server's environment
    st.navigation([st.Page("portal/login.py", title="Sign in", icon=":material/lock:", url_path="signin")], position="hidden").run()
    st.stop()

# --------------------------------------------------------------------------- signed in
st.session_state.pop("auth_msg", None)
my = acc.load_creds(user.id)
creds.activate(my)
up_ok = bool(my.UPSTOX_ACCESS_TOKEN)
if user.is_admin and not hosted() and my.UPSTOX_ACCESS_TOKEN and pt.bot_pid():
    tf = pt.bot_token_file(user.id)             # keep a running local bot on today's token
    if not tf.exists() or tf.read_text().strip() != my.UPSTOX_ACCESS_TOKEN:
        pt.write_token_file(my.UPSTOX_ACCESS_TOKEN, tf)
cs_ok = bool(my.COINSWITCH_API_KEY and my.COINSWITCH_SECRET_KEY)

connect = st.Page("portal/connect.py", title="Connect", icon=":material/link:", url_path="connect")
scanner = st.Page("portal/scanner.py", title="Scanner", icon=":material/radar:", url_path="scanner", default=True)
mood = st.Page("portal/mood.py", title="Market mood", icon=":material/insights:", url_path="mood")
backtest = st.Page("portal/backtest.py", title="Backtest", icon=":material/history:", url_path="backtest")
account = st.Page("portal/account.py", title="My account", icon=":material/person:", url_path="account")
pages = {"Trade": [scanner, mood, backtest], "Setup": [connect, account]}
if user.is_admin and not hosted():
    pages["Trade"].append(st.Page("portal/alerts.py", title="Alert bot", icon=":material/notifications_active:", url_path="bot"))
if user.is_admin:
    pending = sum(1 for u in acc.list_users() if u.status == "pending")
    pages["Admin"] = [st.Page("portal/admin.py", title=f"Users ({pending} pending)" if pending else "Users",
                              icon=":material/group:", url_path="admin")]

page = st.navigation(pages)
if (not (up_ok or cs_ok) and page.title == "Scanner" and not st.session_state.get("_sent_to_connect")):
    st.session_state["_sent_to_connect"] = True          # first visit with nothing connected: jump there once
    st.switch_page(connect)

ui.logo()
ui.user_card(user.name, user.email, user.role, up_ok, cs_ok)
if st.sidebar.button("Sign out", key="sign_out", icon=":material/logout:", type="tertiary"):
    acc.log("logout", user.email)
    sign_out()
    st.rerun()
st.sidebar.divider()

try:
    page.run()
finally:
    launcher()                               # Bull & Bear, bottom-right (after the page, so it sees today's mood)
