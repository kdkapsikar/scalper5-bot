"""Shared fixtures: a throwaway accounts database and a way to open the portal as a signed-in user."""
import time

import pytest

from scalpbot import creds
from scalpbot.creds import FIELDS


@pytest.fixture(autouse=True)
def _reset_creds_mode(monkeypatch):
    """The portal switches the process to strict multi-user mode; keep that from leaking into CLI tests.
    Also: no real network calls to Bybit/Binance from the crypto gap fill unless a test turns it on."""
    monkeypatch.setenv("SCALP_CRYPTO_FILL", "off")
    yield
    creds._STRICT[0] = False
    creds.activate(None)


@pytest.fixture
def portal_db(monkeypatch, tmp_path):
    """Point the portal at a fresh SQLite database with its own master key; returns the Accounts store."""
    st = pytest.importorskip("streamlit")
    from scalpbot.accounts import Accounts, generate_master_key

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'portal.db'}")
    monkeypatch.setenv("SCALP_MASTER_KEY", generate_master_key())
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.delenv("SCALP_HOSTED", raising=False)
    for k in FIELDS:                       # the portal must never fall back to keys in the server's environment
        monkeypatch.setenv(k, "SERVER-ENV-VALUE-MUST-NOT-BE-USED")
    st.cache_data.clear()
    st.cache_resource.clear()
    yield Accounts()
    st.cache_resource.clear()


def make_user(acc, email="ann@example.com", role="user", keys=None):
    """An approved user (admins come from ADMIN_EMAILS) with optional saved broker keys."""
    u = acc.sign_up(email, email.split("@")[0].title(), "correct horse 9")
    if u.status != "active" or u.role != role:
        from sqlalchemy import update
        from scalpbot.accounts import users
        with acc.engine.begin() as c:
            c.execute(update(users).where(users.c.id == u.id).values(status="active", role=role))
        u = acc.get(u.id)
    if keys:
        acc.save_keys(u.id, keys)
    return u


def sign_in(at, user):
    at.session_state["user_id"] = user.id
    at.session_state["last_seen"] = time.time()
    return at
