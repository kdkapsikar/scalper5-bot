"""Market mood: a Bull / Bear read of Indian futures and crypto, built from the scanner's indicators."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from scalpbot.mood import WEIGHTS, all_moods

from portal import ui
from portal.common import FULL_GROUPS, QUICK_GROUPS, get_universe, measure

COMPONENT_NAMES = {"dema": "200 DEMA breadth", "supertrend": "Supertrend breadth", "sma": "SMA 22/33 breadth",
                   "leader": "Leader (NIFTY FUT / BTCUSDT)", "rsi": "Median RSI", "signals": "Fresh signals"}


ui.eyebrow("Trade · Bull vs Bear")
st.title("Market mood")
st.caption("Is the tape bullish or bearish right now? A score from -100 (strong bear) to +100 (strong bull), built from 200 DEMA, "
           "Supertrend and SMA 22/33 breadth, the leader (NIFTY FUT, BTCUSDT), median RSI and fresh signals. "
           "It describes the market; it is not a forecast or advice.")

c1, c2, c3 = st.columns([3, 2, 1], vertical_alignment="bottom")
scope = c1.segmented_control("Breadth", ["Quick", "Full"], default="Quick", key="mood_scope",
                             help="Quick: index futures + crypto. Full: also every F&O stock future, a better read of "
                                  "Indian breadth that takes a minute or two on Upstox.") or "Quick"
groups = FULL_GROUPS if scope == "Full" else QUICK_GROUPS
if c3.button("Refresh", key="mood_refresh", icon=":material/refresh:", use_container_width=True):
    st.session_state["mood_refresh_n"] = st.session_state.get("mood_refresh_n", 0) + 1
n = sum(1 for i in get_universe()[0] if i.group in groups)
c2.caption(f"{n} instruments · updates every 5-min candle")

with st.spinner(f"Reading {n} instruments..."):
    results, insts = measure(groups, st.session_state.get("mood_refresh_n", 0))
moods = all_moods(results)
st.session_state["s5_moods"] = moods          # the Bull & Bear launcher greets with this

cols = st.columns(len(moods), gap="medium")
for col, (market, m) in zip(cols, moods.items()):
    with col:
        ui.mood_card(market, m)
        if m.components:
            with st.expander("How the score is built"):
                rows = [{"Component": COMPONENT_NAMES[k], "Reading (-1 to +1)": round(v, 2),
                         "Weight": f"{100 * WEIGHTS[k] / sum(WEIGHTS[x] for x in m.components):.0f}%"}
                        for k, v in m.components.items()]
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

st.write("")
with st.expander("Per-instrument readings"):
    rows = [{"Ticker": r.name, "Group": r.group, "Above 200 DEMA": r.above_dema, "Supertrend up": r.st_up,
             "SMA 22 > 33": r.sma_up, "RSI": None if r.rsi is None else round(r.rsi, 1),
             "Signal": r.status if r.status in ("LONG", "SHORT") else "", "Market closed": r.stale,
             "Error": r.error} for r in results]
    st.dataframe(pd.DataFrame(rows), hide_index=True)
