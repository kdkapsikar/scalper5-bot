"""Scalp5 Scanner (Streamlit).  Start it with:   streamlit run app.py

Two ways to use it, chosen in the sidebar:
  * Scan all     - scans the whole universe and lists everything that satisfies the rules right now
  * Single ticker - pick one ticker from the dropdown and see its full status, checklist and chart
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import date, datetime

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from scalpbot import scan as sc
from scalpbot.brokers import upstox_token
from scalpbot.chart import make_chart
from scalpbot.strategy import fmt
from scalpbot.universe import GROUPS, build_universe

st.set_page_config(page_title="Scalp5 Scanner", page_icon="📈", layout="wide")
WATCHLIST = os.getenv("SCALP_WATCHLIST", "watchlist.yaml")


@st.cache_data(ttl=3600, show_spinner="Loading instrument list...")
def load_universe(path: str, day: str):
    return build_universe(path)


@st.cache_data(ttl=900, show_spinner=False)
def load_detail(_inst, name: str, flags_key: str, lookback: int, bucket_id: int, refresh: int):
    """Cached per instrument and per 5-minute bucket, so a new candle always means fresh data."""
    return sc.run_one(_inst, json.loads(flags_key), lookback, ignore_stale=True)


# --------------------------------------------------------------------------- sidebar
try:
    universe, uni_warnings = load_universe(WATCHLIST, date.today().isoformat())
except Exception as e:  # bad watchlist file etc.
    st.error(f"Could not build the instrument list: {e}")
    st.stop()

st.sidebar.header("Scalp5 Scanner")
mode = st.sidebar.radio("Mode", ["Scan all", "Single ticker"], key="mode",
                        help="Scan all lists everything that satisfies the rules. Single ticker shows one instrument in detail.")
available = [g for g in GROUPS if any(i.group == g for i in universe)]
groups = st.sidebar.multiselect("Universe", available, default=available, key="groups")

with st.sidebar.expander("Strategy rules", expanded=False):
    dema_mode = st.selectbox("200 DEMA cross trigger", ["both", "fast", "off"], key="dema_mode",
                             help="both: either 22 or 33 crossing the DEMA counts, once both lines are on the new side. "
                                  "fast: the 22 line crossing is enough. off: SMA 22/33 cross only.")
    req_st = st.checkbox("Supertrend must agree", True, key="req_st")
    req_dema = st.checkbox("Price on the right side of the 200 DEMA", True, key="req_dema")
    req_rsi = st.checkbox("RSI zone and direction", True, key="req_rsi")
    req_room = st.checkbox("Room to the next pivot level", True, key="req_room")
lookback = st.sidebar.slider("Look back (closed candles)", 1, 12, 3, key="lookback",
                             help="Signals fire when a 5-minute candle closes. This also shows signals from the last N "
                                  "candles, so you don't miss one if you open the app a few minutes late.")
ignore_stale = st.sidebar.checkbox("Include closed markets (review last session)", False, key="ignore_stale")

flags = {"dema_cross_mode": dema_mode}
for on, key in ((req_st, "require_supertrend"), (req_dema, "require_dema_bias"),
                (req_rsi, "require_rsi"), (req_room, "require_pivot_room")):
    if not on:
        flags[key] = False
flags_key = json.dumps(flags, sort_keys=True)

st.sidebar.divider()
up_ok = bool(upstox_token())
cs_ok = bool(os.getenv("COINSWITCH_API_KEY") and os.getenv("COINSWITCH_SECRET_KEY"))
st.sidebar.caption("Connections")
st.sidebar.write(("✅" if up_ok else "❌") + " Upstox token" + ("" if up_ok else " missing: run scripts/upstox_token.py"))
st.sidebar.write(("✅" if cs_ok else "❌") + " CoinSwitch keys" + ("" if cs_ok else " missing: see .env.example"))
for w in uni_warnings:
    st.sidebar.warning(w)

chosen = [i for i in universe if i.group in groups]
by_name = {i.name: i for i in chosen}


# --------------------------------------------------------------------------- detail view
def render_detail(inst) -> None:
    with st.spinner(f"Loading {inst.name}..."):
        res, ind, cfg = load_detail(inst, inst.name, flags_key, lookback,
                                    int(time.time() // 300), st.session_state.get("refresh", 0))
    st.subheader(f"{inst.name}  ·  {inst.group}")
    if res.status == "ERROR":
        st.error(res.error)
        return
    if res.stale:
        last = res.last_candle.tz_convert(sc.IST)
        st.warning(f"The market looks closed: the last closed candle is {last:%d %b %H:%M} IST (5-minute candle open). "
                   "Showing the last session.")
    text = sc.headline(res, lookback)
    if res.status in ("LONG", "SHORT"):
        (st.success if res.status == "LONG" else st.error)(text)
        if res.stop is not None:
            st.caption(f"Stop {fmt(res.stop)}" + (f"  ·  Target (next pivot) {fmt(res.target)}" if res.target else ""))
    elif res.status == "BLOCKED":
        st.warning(text)
    else:
        st.info(text)

    m = st.columns(5)
    m[0].metric("Last price", fmt(res.price))
    m[1].metric("RSI (14)", f"{res.rsi:.1f}")
    m[2].metric("Supertrend", "Up" if res.st_up else "Down")
    last = ind.iloc[-1]
    m[3].metric("vs 200 DEMA", f"{(last['close'] / last['dema'] - 1) * 100:+.2f}%")
    m[4].metric("22 vs 33 SMA", "22 above" if last["sma_fast"] > last["sma_slow"] else "22 below")

    c1, c2 = st.columns(2)
    for col, side in ((c1, "LONG"), (c2, "SHORT")):
        col.markdown(f"**{side} checklist** (as of the latest closed candle)")
        col.dataframe(sc.checks_frame(res.checks[side]), hide_index=True)
    st.plotly_chart(make_chart(ind, f"{inst.name} - 5 minute"))
    st.markdown("\n".join(f"- **{k}:** {v}" for k, v in res.snapshot.items()))


# --------------------------------------------------------------------------- the app
st.title("Scalp5 Scanner")
st.caption("5-minute confluence: SMA 22/33 cross or the lines crossing the 200 DEMA, filtered by Supertrend, 200 DEMA side, "
           "RSI and pivot room. For analysis and alerts only; not financial advice.")

if mode == "Scan all":
    c1, c2 = st.columns([1, 4])
    run = c1.button("Run scan", type="primary", key="run_scan", disabled=not chosen)
    c2.caption(f"{len(chosen)} instruments selected. A scan fetches fresh 5-minute candles for each one, "
               "so a full F&O list takes a minute or two.")
    if run:
        bar = st.progress(0.0, text="Scanning...")

        def on_progress(done: int, total: int) -> None:
            bar.progress(done / total, text=f"Scanned {done}/{total}")

        results = sc.scan(chosen, flags, lookback, ignore_stale, workers=4, progress=on_progress)
        bar.empty()
        st.session_state["scan"] = {"results": results, "at": datetime.now(), "lookback": lookback}

    data = st.session_state.get("scan")
    if not data:
        st.info("Press **Run scan** to check every selected instrument against the rules.")
    else:
        results = data["results"]
        cnt = Counter(r.status for r in results)
        cols = st.columns(6)
        for col, label, value in zip(cols, ["Scanned", "Long", "Short", "Blocked", "Market closed", "Errors"],
                                     [len(results), cnt["LONG"], cnt["SHORT"], cnt["BLOCKED"], cnt["STALE"], cnt["ERROR"]]):
            col.metric(label, value)
        st.caption(f"Scan finished {data['at']:%H:%M:%S}, looking back {data['lookback']} closed candle(s). "
                   "Run it again after the next 5-minute close for fresh results.")

        hits = sc.to_frame(results, ("LONG", "SHORT"))
        if hits.empty:
            st.info("No instrument satisfies all the conditions in the look-back window.")
        else:
            st.subheader("Satisfying all conditions")
            st.dataframe(hits, hide_index=True)
            st.download_button("Download as CSV", hits.to_csv(index=False), "scalp5_signals.csv", "text/csv")

        if st.checkbox("Also show near-misses (a trigger fired but a filter blocked it)", key="show_blocked"):
            near = sc.to_frame(results, ("BLOCKED",))
            if near.empty:
                st.caption("No blocked setups in the window.")
            else:
                st.dataframe(near, hide_index=True)

        if cnt["STALE"]:
            with st.expander(f"{cnt['STALE']} instruments skipped because their market looks closed"):
                st.write(", ".join(r.name for r in results if r.status == "STALE"))
        if cnt["ERROR"]:
            with st.expander(f"{cnt['ERROR']} instruments failed"):
                st.dataframe(pd.DataFrame([{"Ticker": r.name, "Error": r.error} for r in results if r.status == "ERROR"]),
                             hide_index=True)

        pick_names = [r.name for r in results if r.status in ("LONG", "SHORT", "BLOCKED")]
        if pick_names:
            st.divider()
            pick = st.selectbox("Open details for", ["-"] + pick_names, key="detail_pick")
            if pick != "-" and pick in by_name:
                render_detail(by_name[pick])
else:
    if not by_name:
        st.info("No instruments in the selected universe.")
        st.stop()
    c1, c2 = st.columns([4, 1])
    choice = c1.selectbox("Ticker (type to search)", list(by_name), key="ticker")
    if c2.button("Refresh", key="refresh_btn"):
        st.session_state["refresh"] = st.session_state.get("refresh", 0) + 1
    render_detail(by_name[choice])
