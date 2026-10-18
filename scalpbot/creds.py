"""Whose broker keys the current code path uses.

The command-line tools (check, scan, bot) read keys from the environment / `.env`, as before. The multi-user
portal instead activates the signed-in user's keys for the duration of a page run, so one person's requests never
fall back to anyone else's keys. Worker threads must be started with `contextvars.copy_context().run` (see `submit`).
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, fields

FIELDS = ["UPSTOX_API_KEY", "UPSTOX_API_SECRET", "UPSTOX_REDIRECT_URI", "UPSTOX_ACCESS_TOKEN",
          "COINSWITCH_API_KEY", "COINSWITCH_SECRET_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]


@dataclass(frozen=True)
class Creds:
    UPSTOX_API_KEY: str = ""
    UPSTOX_API_SECRET: str = ""
    UPSTOX_REDIRECT_URI: str = ""
    UPSTOX_ACCESS_TOKEN: str = ""
    COINSWITCH_API_KEY: str = ""
    COINSWITCH_SECRET_KEY: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Creds":
        names = {f.name for f in fields(cls)}
        return cls(**{k: str(v or "").strip() for k, v in d.items() if k in names})


_CURRENT: contextvars.ContextVar[Creds | None] = contextvars.ContextVar("scalp_creds", default=None)
_STRICT = [False]


def strict() -> None:
    """Multi-user mode (the portal): code paths that have no active user get no keys at all, never the server's
    environment. Called once by the portal at start-up."""
    _STRICT[0] = True


def activate(c: Creds | None) -> None:
    """Use these keys for the rest of this run (None = fall back to the environment, CLI behaviour)."""
    _CURRENT.set(c)


def current() -> Creds | None:
    c = _CURRENT.get()
    return Creds() if c is None and _STRICT[0] else c


def submit(executor, fn, *args, **kwargs):
    """executor.submit that carries the active user's keys into the worker thread."""
    return executor.submit(contextvars.copy_context().run, fn, *args, **kwargs)
