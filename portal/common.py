"""Shared bits for the portal pages."""
from __future__ import annotations

import os
import time
from datetime import date

import streamlit as st

from scalpbot import scan as sc
from scalpbot.universe import GROUP_CRYPTO, GROUP_INDEX, GROUP_STOCK, build_universe

WATCHLIST = os.getenv("SCALP_WATCHLIST", "watchlist.yaml")


@st.cache_data(ttl=3600, show_spinner="Loading instrument list...")
def load_universe(path: str, day: str):
    return build_universe(path)


def get_universe():
    """(instruments, warnings), or stops the page with a readable error."""
    try:
        return load_universe(WATCHLIST, date.today().isoformat())
    except Exception as e:  # bad watchlist file, no network for the instrument list, etc.
        st.error(f"Could not build the instrument list: {e}")
        st.stop()


def strategy_rules(container, prefix: str = ""):
    """The strategy switches. Returns (flags dict for the strategy, list of --no-* CLI flags for the bot)."""
    dema_mode = container.selectbox(
        "200 DEMA cross trigger", ["both", "fast", "off"], key=f"{prefix}dema_mode",
        help="both: either the 22 or the 33 line crossing the DEMA counts, once both lines are on the new side. "
             "fast: the 22 line crossing is enough. off: SMA 22/33 cross only.")
    req_st = container.checkbox("Supertrend must agree", True, key=f"{prefix}req_st")
    req_dema = container.checkbox("Price on the right side of the 200 DEMA", True, key=f"{prefix}req_dema")
    req_rsi = container.checkbox("RSI zone and direction", True, key=f"{prefix}req_rsi")
    req_room = container.checkbox("Room to the next pivot level", True, key=f"{prefix}req_room")
    flags = {"dema_cross_mode": dema_mode}
    cli_off = []
    for on, key, cli in ((req_st, "require_supertrend", "--no-supertrend"), (req_dema, "require_dema_bias", "--no-dema"),
                         (req_rsi, "require_rsi", "--no-rsi"), (req_room, "require_pivot_room", "--no-room")):
        if not on:
            flags[key] = False
            cli_off.append(cli)
    return flags, cli_off


QUICK_GROUPS = (GROUP_INDEX, GROUP_CRYPTO)
FULL_GROUPS = (GROUP_INDEX, GROUP_STOCK, GROUP_CRYPTO)


@st.cache_data(ttl=600, show_spinner=False)
def _measure(_insts, user_id: int, names: tuple, bucket_id: int, refresh: int):
    return sc.scan(list(_insts), {}, lookback=3, ignore_stale=True, workers=4)


def measure(groups=QUICK_GROUPS, refresh: int = 0):
    """Default-rules scan of the chosen groups, cached per user (their own keys) and per 5-minute candle.
    Shared by the Market mood page and the Bull & Bear assistant. Returns (results, instruments)."""
    universe, _ = get_universe()
    insts = [i for i in universe if i.group in groups]
    res = _measure(tuple(insts), st.session_state["user_id"], tuple(i.name for i in insts),
                   int(time.time() // 300), refresh)
    return res, insts


@st.cache_data(ttl=600, show_spinner=False)
def _one(_inst, user_id: int, name: str, bucket_id: int):
    return sc.run_one(_inst, {}, 3, ignore_stale=True)[0]


def check_one(inst):
    """One instrument's status with the default rules, cached per user and per 5-minute candle."""
    return _one(inst, st.session_state["user_id"], inst.name, int(time.time() // 300))
