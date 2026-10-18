"""Bull / Bear market mood, from the same indicators the scanner computes.

For each market (Indian futures, crypto) the score runs from -100 (strong bear) to +100 (strong bull) and blends:

    weight  component                 +1 when ...                                   -1 when ...
    30 %    200 DEMA breadth          every instrument closes above its 200 DEMA    every one is below
    20 %    Supertrend breadth        every Supertrend points up                    every one points down
    15 %    SMA 22/33 breadth         every SMA 22 is above its SMA 33              every one is below
    20 %    leader                    NIFTY FUT / BTCUSDT above DEMA, ST up, 22>33  all three bearish
    10 %    median RSI                median RSI >= 70                              median RSI <= 30
     5 %    fresh signals             only LONG signals in the look-back            only SHORT signals

Breadth is (bullish - bearish) / instruments. Missing components (e.g. no leader in the selection) are dropped and
the remaining weights rescaled. Labels: >= 40 Strong Bull, >= 15 Bull, <= -40 Strong Bear, <= -15 Bear, else Neutral.
This describes the tape; it is not a forecast or advice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Optional

MARKETS = {
    "India": {"groups": ("Index futures", "Stock futures"), "leader": "NIFTY FUT"},
    "Crypto": {"groups": ("Crypto",), "leader": "BTCUSDT"},
}
WEIGHTS = {"dema": 0.30, "supertrend": 0.20, "sma": 0.15, "leader": 0.20, "rsi": 0.10, "signals": 0.05}


@dataclass
class Mood:
    market: str
    score: Optional[float] = None          # -100 .. +100, None when nothing could be measured
    label: str = "No data"
    icon: str = "❔"
    n: int = 0                             # instruments measured
    errors: int = 0
    stale: int = 0                         # measured instruments without fresh candles (closed, or crypto feed delayed)
    components: dict = field(default_factory=dict)   # name -> value in -1..+1
    facts: list = field(default_factory=list)        # plain-language reasons

    @property
    def side(self) -> str:
        if self.score is None:
            return "none"
        return "bull" if self.score >= 15 else "bear" if self.score <= -15 else "neutral"


def label_for(score: float) -> tuple[str, str]:
    if score >= 40:
        return "Strong Bull", "🐂"
    if score >= 15:
        return "Bull", "🐂"
    if score <= -40:
        return "Strong Bear", "🐻"
    if score <= -15:
        return "Bear", "🐻"
    return "Neutral", "⚖️"


def _breadth(values: list[Optional[bool]]) -> tuple[Optional[float], int, int]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None, 0, 0
    up = sum(1 for v in vals if v)
    return (2 * up - len(vals)) / len(vals), up, len(vals)


def _pct(up: int, n: int) -> str:
    return f"{100 * up / n:.0f}%" if n else "-"


def market_mood(results: list, market: str) -> Mood:
    """Mood for one market from scan Results (scalpbot.scan.Result)."""
    spec = MARKETS[market]
    mine = [r for r in results if r.group in spec["groups"]]
    m = Mood(market=market, errors=sum(1 for r in mine if r.status == "ERROR"))
    ok = [r for r in mine if r.status != "ERROR" and r.above_dema is not None]
    m.n, m.stale = len(ok), sum(1 for r in ok if r.stale)
    if not ok:
        m.facts.append("Nothing could be measured: check the connections on the Connect page.")
        return m

    comp: dict[str, float] = {}
    b, up, n = _breadth([r.above_dema for r in ok])
    if b is not None:
        comp["dema"] = b
        m.facts.append(f"{_pct(up, n)} of {n} instruments close above their 200 DEMA.")
    b, up, n = _breadth([r.st_up for r in ok])
    if b is not None:
        comp["supertrend"] = b
        m.facts.append(f"Supertrend points up on {_pct(up, n)} of them.")
    b, up, n = _breadth([r.sma_up for r in ok])
    if b is not None:
        comp["sma"] = b
        m.facts.append(f"SMA 22 is above SMA 33 on {_pct(up, n)}.")

    lead = next((r for r in ok if r.name == spec["leader"]), None)
    if lead is not None:
        parts = [lead.above_dema, lead.st_up, lead.sma_up]
        b, up, n = _breadth(parts)
        if b is not None:
            comp["leader"] = b
            m.facts.append(f"{lead.name}: {'above' if lead.above_dema else 'below'} the 200 DEMA, Supertrend "
                           f"{'up' if lead.st_up else 'down'}, SMA 22 {'above' if lead.sma_up else 'below'} 33.")

    rsis = [r.rsi for r in ok if r.rsi is not None]
    if rsis:
        med = median(rsis)
        comp["rsi"] = max(-1.0, min(1.0, (med - 50) / 20))
        m.facts.append(f"Median RSI is {med:.0f}.")

    longs = sum(1 for r in ok if r.status == "LONG")
    shorts = sum(1 for r in ok if r.status == "SHORT")
    if longs + shorts:
        comp["signals"] = (longs - shorts) / (longs + shorts)
        m.facts.append(f"Fresh signals: {longs} LONG, {shorts} SHORT.")

    total_w = sum(WEIGHTS[k] for k in comp)
    m.components = comp
    m.score = round(100 * sum(WEIGHTS[k] * v for k, v in comp.items()) / total_w, 1)
    m.label, m.icon = label_for(m.score)
    if m.n < 10 and market == "India":
        m.facts.append(f"Based on only {m.n} instruments: add stock futures for a broader read.")
    if m.stale and market == "Crypto":
        m.facts.append(f"{m.stale} of {m.n} have delayed data from the broker (newest candle over 12 minutes old), "
                       "so their part of the score is not fully current.")
    elif m.stale:
        m.facts.append(f"{m.stale} of {m.n} markets look closed, so part of this reflects the last session.")
    return m


def all_moods(results: list) -> dict[str, Mood]:
    return {k: market_mood(results, k) for k in MARKETS}
