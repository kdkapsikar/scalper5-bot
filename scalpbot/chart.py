"""Plotly chart for one instrument: candles, SMA 22/33, 200 DEMA, Supertrend, pivots and signal markers."""
from __future__ import annotations

import pandas as pd

IST = "Asia/Kolkata"


def make_chart(ind: pd.DataFrame, title: str = "", n: int = 150):
    import plotly.graph_objects as go

    d = ind.iloc[-n:]
    x = d.index.tz_convert(IST).strftime("%d %b %H:%M")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=x, open=d["open"], high=d["high"], low=d["low"], close=d["close"], name="Price"))
    fig.add_trace(go.Scatter(x=x, y=d["sma_fast"], name="SMA 22", line=dict(color="#f59e0b", width=1.6)))
    fig.add_trace(go.Scatter(x=x, y=d["sma_slow"], name="SMA 33", line=dict(color="#3b82f6", width=1.6)))
    fig.add_trace(go.Scatter(x=x, y=d["dema"], name="200 DEMA", line=dict(color="#8b5cf6", width=2.2)))
    fig.add_trace(go.Scatter(x=x, y=d["st"].where(d["st_dir"] == 1), name="Supertrend up",
                             line=dict(color="#16a34a", width=1.2), connectgaps=False))
    fig.add_trace(go.Scatter(x=x, y=d["st"].where(d["st_dir"] == -1), name="Supertrend down",
                             line=dict(color="#dc2626", width=1.2), connectgaps=False))
    for col, name, sym, color, ypos in (("long_sig", "Long signal", "triangle-up", "#16a34a", "low"),
                                        ("short_sig", "Short signal", "triangle-down", "#dc2626", "high")):
        m = d[col].to_numpy(dtype=bool)
        if m.any():
            fig.add_trace(go.Scatter(x=x[m], y=d[ypos].to_numpy()[m], mode="markers", name=name,
                                     marker=dict(symbol=sym, size=13, color=color, line=dict(width=1, color="white"))))
    for k in ("R2", "R1", "P", "S1", "S2"):
        v = d[k].iloc[-1]
        if pd.notna(v):
            fig.add_hline(y=float(v), line_dash="dot", line_width=1, line_color="gray",
                          annotation_text=k, annotation_position="top right")
    lo, hi = float(d["low"].min()), float(d["high"].max())
    pad = (hi - lo) * 0.06 or hi * 0.01
    fig.update_yaxes(range=[lo - pad, hi + pad])
    fig.update_xaxes(type="category", nticks=12)
    fig.update_layout(title=title, xaxis_rangeslider_visible=False, height=560,
                      margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=1.04))
    return fig
