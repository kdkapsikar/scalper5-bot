"""Sign-in state for the portal pages.

Streamlit keeps session state in server memory per browser tab, so on its own a refresh, a dropped connection or the
host restarting (Render's free plan sleeps after ~15 idle minutes) signs people out. To "stay signed in", a sign-in
also creates a server-side session (scalpbot.accounts) whose random token is kept in a browser cookie; a new tab or
reconnect restores the user from it. The signed-in user and their keys are cached in the session and re-checked
against the database once a minute, instead of on every click.
"""
from __future__ import annotations

import json
import os
import time

import streamlit as st

from scalpbot.accounts import SESSION_DAYS, Accounts, User
from scalpbot.creds import Creds

COOKIE = "s5_session"
RECHECK_SECONDS = 60          # how stale the cached user / keys may get (a disable takes effect within this)


@st.cache_resource(show_spinner=False)
def accounts() -> Accounts:
    return Accounts()


def hosted() -> bool:
    """True on a shared server (Render, Streamlit Community Cloud...), where the background alert bot can't run."""
    flag = os.getenv("SCALP_HOSTED", "").strip().lower()
    if flag:
        return flag in ("1", "true", "yes")
    return not accounts().is_sqlite


def portal_url() -> str:
    """Public address of the portal, used as the Upstox redirect URI."""
    return os.getenv("PORTAL_URL", "http://localhost:8501/").strip()


# --------------------------------------------------------------------------- the cookie
def _cookie_token() -> str:
    try:
        v = st.context.cookies.get(COOKIE, "")
    except Exception:
        return ""
    return v if isinstance(v, str) else ""


def write_cookie() -> None:
    """Set or clear the cookie in the browser when sign-in / sign-out asked for it. Call once per run."""
    token = st.session_state.pop("_cookie_set", None)
    clear = st.session_state.pop("_cookie_clear", False)
    if token is None and not clear:
        return
    value = json.dumps(token or "")
    age = SESSION_DAYS * 86400 if token else 0
    st.html(f"""<script>
      (function () {{
        var secure = window.location.protocol === "https:" ? "; Secure" : "";
        document.cookie = "{COOKIE}=" + {value} + "; Max-Age={age}; Path=/; SameSite=Lax" + secure;
      }})();
    </script>""", unsafe_allow_javascript=True)


# --------------------------------------------------------------------------- signing in and out
def _remember(user: User, token: str) -> None:
    st.session_state["user_id"] = user.id
    st.session_state["_user"] = user
    st.session_state["_user_at"] = time.time()
    st.session_state["_session_token"] = token


def sign_in(user: User) -> None:
    token = accounts().create_session(user.id)
    _remember(user, token)
    st.session_state["_cookie_set"] = token


def sign_out() -> None:
    accounts().revoke_session(st.session_state.get("_session_token") or _cookie_token())
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state["_cookie_clear"] = True


def _drop(msg: tuple[str, str]) -> None:
    sign_out()
    st.session_state["auth_msg"] = msg


def current_user() -> User | None:
    """The signed-in user: cached in the session, re-checked once a minute; restored from the cookie after a refresh."""
    if st.session_state.get("user_id") is None:
        token = _cookie_token()
        if not token or st.session_state.get("_cookie_clear"):
            return None
        user = accounts().user_for_session(token)
        if user is None:                       # expired or revoked: forget the cookie
            st.session_state["_cookie_clear"] = True
            return None
        _remember(user, token)
        return user
    if time.time() - st.session_state.get("_user_at", 0) < RECHECK_SECONDS and st.session_state.get("_user"):
        return st.session_state["_user"]
    user = accounts().get(st.session_state["user_id"])
    if user is None or user.status != "active":
        _drop(("error", "Your account is no longer active."))
        return None
    st.session_state["_user"] = user
    st.session_state["_user_at"] = time.time()
    st.session_state.pop("_creds_at", None)    # re-read keys too
    return user


def my_creds(user: User) -> Creds:
    """This user's decrypted broker keys, cached in the session like the user."""
    if st.session_state.get("_creds_uid") == user.id and \
            time.time() - st.session_state.get("_creds_at", 0) < RECHECK_SECONDS:
        return st.session_state["_creds"]
    c = accounts().load_creds(user.id)
    st.session_state.update(_creds=c, _creds_uid=user.id, _creds_at=time.time())
    return c


def refresh() -> None:
    """Re-read the user and their keys on the next run (after saving keys, a role change...)."""
    st.session_state.pop("_user_at", None)
    st.session_state.pop("_creds_at", None)


def require_admin() -> User:
    user = current_user()
    if user is None or not user.is_admin:
        st.error("This page is for admins only.")
        st.stop()
    return user
