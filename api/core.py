"""Shared plumbing for the API: the accounts store, who is calling, their broker keys, and small TTL caches.

Sign-in works like wardwatch: the web app keeps an opaque session token (scalpbot.accounts sessions; only its sha256
is stored) and sends it as `Authorization: Bearer <token>`. Every endpoint that touches broker data activates the
caller's own keys first (scalpbot.creds), and the API runs in strict mode, so the server's environment keys are
never used for anyone.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict
from datetime import date
from functools import lru_cache

from fastapi import Header, HTTPException

from scalpbot import creds
from scalpbot.accounts import Accounts, User
from scalpbot.universe import build_universe

RECHECK_SECONDS = 60
CANDLE_SECONDS = 300


@lru_cache(maxsize=1)
def accounts() -> Accounts:
    return Accounts()


def reset() -> None:
    """Forget the accounts store and caches (tests point DATABASE_URL somewhere new)."""
    accounts.cache_clear()
    _SESSIONS.clear()
    _CREDS.clear()
    _MEMO.clear()
    _universe.cache_clear()


def app_url() -> str:
    """Public address of the web app (GitHub Pages), used to suggest the Upstox redirect URI."""
    return os.getenv("APP_URL", os.getenv("PORTAL_URL", "http://localhost:5173/")).strip().rstrip("/")


def upstox_redirect_default() -> str:
    return app_url() + "/upstox/callback"


def hosted() -> bool:
    flag = os.getenv("SCALP_HOSTED", "").strip().lower()
    return flag in ("1", "true", "yes") if flag else not accounts().is_sqlite


# --------------------------------------------------------------------------- tiny TTL caches
class TTLCache:
    def __init__(self, seconds: float):
        self.seconds, self._d, self._lock = seconds, {}, threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._d.get(key)
            if hit and time.time() - hit[0] < self.seconds:
                return hit[1]
            self._d.pop(key, None)
            return None

    def put(self, key, value) -> None:
        with self._lock:
            self._d[key] = (time.time(), value)

    def pop(self, key) -> None:
        with self._lock:
            self._d.pop(key, None)

    def pop_where(self, pred) -> None:
        with self._lock:
            for k in [k for k in self._d if pred(k)]:
                self._d.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


_SESSIONS = TTLCache(RECHECK_SECONDS)        # token -> User   (a disable / sign-out takes effect within a minute)
_CREDS = TTLCache(RECHECK_SECONDS)           # user id -> Creds
_MEMO = TTLCache(CANDLE_SECONDS * 2)          # (user id, what, ...) -> computed market data


def memo(key, fn):
    """Per-user market results, reused within one 5-minute candle (the key includes the candle bucket)."""
    hit = _MEMO.get(key)
    if hit is None:
        hit = fn()
        _MEMO.put(key, hit)
    return hit


def bucket() -> int:
    return int(time.time() // CANDLE_SECONDS)


# --------------------------------------------------------------------------- who is calling
def _token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def optional_user(authorization: str | None = Header(default=None)) -> User | None:
    token = _token(authorization)
    if not token:
        return None
    user = _SESSIONS.get(token)
    if user is None:
        user = accounts().user_for_session(token)
        if user is not None:
            _SESSIONS.put(token, user)
    return user


def current_user(authorization: str | None = Header(default=None)) -> User:
    user = optional_user(authorization)
    if user is None:
        raise HTTPException(401, "Please sign in again.")
    return user


def admin_user(authorization: str | None = Header(default=None)) -> User:
    user = current_user(authorization)
    if not user.is_admin:
        raise HTTPException(403, "Only admins can do that.")
    return user


def forget_session(token: str) -> None:
    _SESSIONS.pop(token)


def forget_user(user_id: int) -> None:
    """After a disable / role change / delete: drop cached sessions and keys for this user."""
    _SESSIONS.pop_where(lambda _: True)       # tokens are not indexed by user; clearing all is cheap
    _CREDS.pop(user_id)


# --------------------------------------------------------------------------- their broker keys
def user_creds(user: User) -> creds.Creds:
    c = _CREDS.get(user.id)
    if c is None:
        c = accounts().load_creds(user.id)
        _CREDS.put(user.id, c)
    return c


def use_keys(user: User) -> creds.Creds:
    """Activate this user's keys for the rest of this request (call inside the endpoint, not a dependency)."""
    c = user_creds(user)
    creds.activate(c)
    return c


def keys_changed(user_id: int) -> None:
    _CREDS.pop(user_id)
    _MEMO.pop_where(lambda k: isinstance(k, tuple) and k and k[0] == user_id)


# --------------------------------------------------------------------------- the instrument list
@lru_cache(maxsize=2)
def _universe(day: str):
    return build_universe(os.getenv("SCALP_WATCHLIST", "watchlist.yaml"))


def universe():
    """(instruments, warnings), rebuilt once a day so futures roll to the next expiry."""
    return _universe(date.today().isoformat())


def user_json(u: User) -> dict:
    d = asdict(u)
    for k in ("created_at", "last_login_at"):
        d[k] = d[k].isoformat() if d[k] else None
    d["is_admin"] = u.is_admin
    return d
