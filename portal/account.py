"""My account: profile and password."""
from __future__ import annotations

import streamlit as st

from scalpbot.accounts import MIN_PASSWORD, AccountError

from portal import ui
from portal.auth import accounts, current_user

acc = accounts()
user = current_user()

ui.eyebrow("Setup")
st.title("My account")
c = st.columns(3)
c[0].metric("Email", user.email)
c[1].metric("Role", user.role.title())
c[2].metric("Member since", f"{user.created_at:%d %b %Y}")

st.subheader("Change password")
with st.form("pw"):
    old = st.text_input("Current password", type="password", key="pw_old")
    new = st.text_input(f"New password (at least {MIN_PASSWORD} characters)", type="password", key="pw_new")
    new2 = st.text_input("Repeat new password", type="password", key="pw_new2")
    if st.form_submit_button("Change password"):
        if new != new2:
            st.error("The two new passwords don't match.")
        else:
            try:
                acc.change_password(user.id, old, new)
                st.success("Password changed.")
            except AccountError as e:
                st.error(str(e))
