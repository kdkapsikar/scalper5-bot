"""Sign in / create an account. The only page visible before signing in."""
from __future__ import annotations

import streamlit as st

from scalpbot.accounts import MIN_PASSWORD, AccountError

from portal import ui
from portal.auth import accounts, sign_in

st.markdown("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl']{display:none}"
            "[data-testid='stMainBlockContainer']{max-width:1120px;padding-top:3.2rem}</style>", unsafe_allow_html=True)

acc = accounts()
hero, gap, panel = st.columns([1.15, 0.08, 1], vertical_alignment="center")
with hero:
    ui.sign_in_hero()

with panel:
    st.title("Welcome to Scalp5")
    st.caption("Sign in to your account, or create one. New accounts are approved by the portal admin.")

    msg = st.session_state.pop("auth_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])

    tab_in, tab_up = st.tabs(["Sign in", "Create account"])
    with tab_in:
        with st.form("signin", border=True):
            email = st.text_input("Email", key="si_email", placeholder="you@example.com")
            pw = st.text_input("Password", type="password", key="si_pw")
            if st.form_submit_button("Sign in", type="primary", use_container_width=True):
                try:
                    sign_in(acc.authenticate(email, pw))
                    st.rerun()
                except AccountError as e:
                    st.error(str(e))

    with tab_up:
        with st.form("signup", border=True):
            name = st.text_input("Your name", key="su_name")
            email = st.text_input("Email", key="su_email", placeholder="you@example.com")
            c1, c2 = st.columns(2)
            pw = c1.text_input("Password", type="password", key="su_pw", help=f"At least {MIN_PASSWORD} characters, "
                               "mixing letters with numbers or symbols.")
            pw2 = c2.text_input("Repeat password", type="password", key="su_pw2")
            if st.form_submit_button("Create account", type="primary", use_container_width=True):
                if pw != pw2:
                    st.error("The two passwords don't match.")
                else:
                    try:
                        user = acc.sign_up(email, name, pw)
                        if user.status == "active":
                            sign_in(user)
                            st.rerun()
                        st.success("Account created. An admin will review it; you can sign in once it is approved.")
                    except AccountError as e:
                        st.error(str(e))
        st.markdown('<div class="s5-fine">After approval you connect your own Upstox and CoinSwitch accounts. '
                    'Keys are encrypted and only used for your own pages.</div>', unsafe_allow_html=True)

    st.markdown('<div class="s5-fine">Analysis only. Nothing here places orders or gives financial advice.</div>',
                unsafe_allow_html=True)
