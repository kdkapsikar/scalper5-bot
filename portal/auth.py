"""Sign-in state for the portal pages."""
from __future__ import annotations

import os
import time

import streamlit as st

from scalpbot.accounts import Accounts, User

IDLE_HOURS = 12


@st.cache_resource(show_spinner=False)
def accounts() -> Accounts:
    return Accounts()


def hosted() -> bool:
    """True on a shared server (Streamlit Community Cloud etc.), where the background alert bot can't run."""
    flag = os.getenv("SCALP_HOSTED", "").strip().lower()
    if flag:
        return flag in ("1", "true", "yes")
    return not accounts().is_sqlite


def portal_url() -> str:
    """Public address of the portal, used as the Upstox redirect URI."""
    return os.getenv("PORTAL_URL", "http://localhost:8501/").strip()


def sign_in(user: User) -> None:
    st.session_state["user_id"] = user.id
    st.session_state["last_seen"] = time.time()


def sign_out() -> None:
    for k in list(st.session_state.keys()):
        del st.session_state[k]


def current_user() -> User | None:
    """The signed-in user, re-read on every run so a disable or role change takes effect at once."""
    uid = st.session_state.get("user_id")
    if uid is None:
        return None
    if time.time() - st.session_state.get("last_seen", 0) > IDLE_HOURS * 3600:
        sign_out()
        st.session_state["auth_msg"] = ("info", "You were signed out after a long idle period. Sign in again.")
        return None
    user = accounts().get(uid)
    if user is None or user.status != "active":
        sign_out()
        st.session_state["auth_msg"] = ("error", "Your account is no longer active.")
        return None
    st.session_state["last_seen"] = time.time()
    return user


def require_admin() -> User:
    user = current_user()
    if user is None or not user.is_admin:
        st.error("This page is for admins only.")
        st.stop()
    return user
