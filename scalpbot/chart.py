"""Plotly chart for one instrument: candles, SMA 22/33, 200 DEMA, Supertrend, pivots and signal markers."""
from __future__ import annotations

import pandas as pd

IST = "Asia/Kolkata"
BULL, BEAR = "#16a34a", "#e5484d"


def make_chart(ind: pd.DataFrame, title: str = "", n: int = 150):
    import plotly.graph_objects as go

    d = ind.iloc[-n:]
    x = d.index.tz_convert(IST).strftime("%d %b %H:%M")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=x, open=d["open"], high=d["high"], low=d["low"], close=d["close"], name="Price",
                             increasing=dict(line=dict(color=BULL, width=1), fillcolor=BULL),
                             decreasing=dict(line=dict(color=BEAR, width=1), fillcolor=BEAR)))
    fig.add_trace(go.Scatter(x=x, y=d["sma_fast"], name="SMA 22", line=dict(color="#f59e0b", width=1.5)))
    fig.add_trace(go.Scatter(x=x, y=d["sma_slow"], name="SMA 33", line=dict(color="#0ea5e9", width=1.5)))
    fig.add_trace(go.Scatter(x=x, y=d["dema"], name="200 DEMA", line=dict(color="#7c5cff", width=2.4)))
    fig.add_trace(go.Scatter(x=x, y=d["st"].where(d["st_dir"] == 1), name="Supertrend up",
                             line=dict(color=BULL, width=1.4, dash="dot"), connectgaps=False))
    fig.add_trace(go.Scatter(x=x, y=d["st"].where(d["st_dir"] == -1), name="Supertrend down",
                             line=dict(color=BEAR, width=1.4, dash="dot"), connectgaps=False))
    for col, name, sym, color, ypos in (("long_sig", "Long signal", "triangle-up", BULL, "low"),
                                        ("short_sig", "Short signal", "triangle-down", BEAR, "high")):
        m = d[col].to_numpy(dtype=bool)
        if m.any():
            fig.add_trace(go.Scatter(x=x[m], y=d[ypos].to_numpy()[m], mode="markers", name=name,
                                     marker=dict(symbol=sym, size=13, color=color, line=dict(width=1, color="white"))))
    for k in ("R2", "R1", "P", "S1", "S2"):
        v = d[k].iloc[-1]
        if pd.notna(v):
            fig.add_hline(y=float(v), line_dash="dot", line_width=1, line_color="rgba(128,140,170,.55)",
                          annotation_text=k, annotation_position="top right", annotation_font=dict(size=10, color="#8a93a8"))
    lo, hi = float(d["low"].min()), float(d["high"].max())
    pad = (hi - lo) * 0.06 or hi * 0.01
    fig.update_yaxes(range=[lo - pad, hi + pad])
    fig.update_xaxes(type="category", nticks=12)
    fig.update_layout(title=dict(text=title, font=dict(size=15)) if title else None, xaxis_rangeslider_visible=False,
                      height=560, margin=dict(l=10, r=10, t=72 if title else 36, b=10), hovermode="x unified",
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, font=dict(size=11)))
    return fig
