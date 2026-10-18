"""Backtest page: replay the rules on an instrument's recent history using your live broker feed."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from scalpbot.backtest import backtest, summarize
from scalpbot.watchlist import fetch_candles, make_config

from portal import ui
from portal.common import get_universe, strategy_rules


def equity_chart(trades: pd.DataFrame):
    import plotly.graph_objects as go
    eq = ((1 + trades["ret"]).cumprod() - 1) * 100
    x = pd.to_datetime(trades["exit_time"]).dt.tz_convert("Asia/Kolkata")
    up = float(eq.iloc[-1]) >= 0
    color = "#16a34a" if up else "#e5484d"
    fig = go.Figure(go.Scatter(x=x, y=eq, mode="lines+markers", line=dict(color=color, width=2.4, shape="hv"),
                               marker=dict(size=5), fill="tozeroy",
                               fillcolor="rgba(22,163,74,.12)" if up else "rgba(229,72,77,.12)",
                               hovertemplate="%{x|%d %b %H:%M}<br>%{y:+.2f}%<extra></extra>"))
    fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="rgba(128,140,170,.6)")
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=36, b=10), yaxis_ticksuffix="%",
                      title=dict(text="Equity curve (cumulative return)", font=dict(size=14)), showlegend=False)
    return fig


def trade_table(trades: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    for c in ("entry_time", "exit_time"):
        t[c] = pd.to_datetime(t[c]).dt.tz_convert("Asia/Kolkata").dt.strftime("%d %b %H:%M")
    t["ret"] = t["ret"] * 100
    return t.rename(columns={"entry_time": "Entry (IST)", "exit_time": "Exit (IST)", "side": "Side", "entry": "Entry",
                             "exit": "Exit", "ret": "Return %", "reason": "Exit reason", "bars": "Candles",
                             "trigger": "Trigger"})

ui.eyebrow("Trade · research")
st.title("Backtest")
st.caption("Replays the exact rules on the history your broker feed provides (about 20 days for Upstox, depending on what "
           "CoinSwitch returns). Entry is at the next candle's open, with fees and slippage deducted. Past results do not "
           "predict future results: treat fewer than 100 trades as inconclusive.")

universe, _ = get_universe()
by_name = {i.name: i for i in universe}
if not by_name:
    st.info("No instruments available.")
    st.stop()

c1, c2, c3 = st.columns([2, 1, 1])
pick = c1.selectbox("Ticker (type to search)", list(by_name), key="bt_ticker")
fee = c2.number_input("Fee per side (bps)", 0.0, 100.0, 5.0, key="bt_fee")
slip = c3.number_input("Slippage per side (bps)", 0.0, 100.0, 2.0, key="bt_slip")
with st.expander("Strategy rules"):
    flags, _ = strategy_rules(st, prefix="bt_")
compare = st.checkbox("Compare all three 200 DEMA trigger modes (off / fast / both)", True, key="bt_compare")

if st.button("Run backtest", type="primary", key="bt_run"):
    inst = by_name[pick]
    with st.spinner(f"Fetching history for {pick}..."):
        try:
            df = fetch_candles(inst, 5000)
        except Exception as e:
            st.error(f"Could not fetch candles: {e}")
            st.stop()
    if len(df) < 400:
        st.error(f"Only {len(df)} candles came back; need about 400 or more.")
        st.stop()
    modes = ["off", "fast", "both"] if compare else [flags["dema_cross_mode"]]
    results = {}
    for m in modes:
        cfg = make_config(inst, {**flags, "dema_cross_mode": m})
        trades = backtest(df, cfg, fee, slip)
        results[m] = (trades, summarize(trades))
    st.session_state["bt"] = {"name": pick, "df_range": (df.index[0], df.index[-1], len(df)), "results": results}

bt = st.session_state.get("bt")
if bt:
    a, b, n = bt["df_range"]
    st.write(f"**{bt['name']}**: {n} candles, {a:%d %b %Y %H:%M} to {b:%d %b %Y %H:%M} UTC")
    table = []
    for m, (trades, s) in bt["results"].items():
        table.append({"DEMA trigger": m, "Trades": s.get("trades", 0), "Win %": s.get("win_rate_%"), "Avg win %": s.get("avg_win_%"),
                      "Avg loss %": s.get("avg_loss_%"), "Profit factor": s.get("profit_factor"),
                      "Total return %": s.get("total_return_%"), "Max drawdown %": s.get("max_drawdown_%")})
    st.dataframe(pd.DataFrame(table), hide_index=True)
    if any(r["Trades"] < 100 for r in table):
        st.warning("Fewer than 100 trades in at least one row: that is too few to say anything reliable.")
    mode = st.selectbox("Show trades for", list(bt["results"]), index=len(bt["results"]) - 1, key="bt_mode")
    trades, s = bt["results"][mode]
    if trades.empty:
        st.info("No trades with this setting.")
    else:
        eq = (1 + trades["ret"]).cumprod()
        st.plotly_chart(equity_chart(trades), config={"displayModeBar": False})
        if s.get("by_trigger"):
            st.write("By trigger:")
            bt_tr = pd.DataFrame(s["by_trigger"]).T.rename_axis("Trigger").reset_index()
            st.dataframe(bt_tr.rename(columns={"trades": "Trades", "win_%": "Win %", "avg_%": "Avg return %"}), hide_index=True)
        st.dataframe(trade_table(trades), hide_index=True, column_config={
            "Return %": st.column_config.NumberColumn(format="%+.2f%%"),
            "Entry": st.column_config.NumberColumn(format="%.4g"), "Exit": st.column_config.NumberColumn(format="%.4g")})
        st.download_button("Download trades as CSV", trades.to_csv(index=False), f"{bt['name']}_trades.csv", "text/csv")
