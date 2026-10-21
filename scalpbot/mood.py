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
    "MCX": {"groups": ("MCX futures",), "leader": "GOLD FUT"},
    "Crypto": {"groups": ("Crypto",), "leader": "BTCUSDT"},
    "Forex & metals": {"groups": ("Forex & metals",), "leader": "XAUUSD (spot)"},
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
        m.facts.append(f"{_pct(up, n)} of {n} instruments close above their 200 DEMA." if n != 1 else
                       f"It closes {'above' if up else 'below'} its 200 DEMA.")
    b, up, n = _breadth([r.st_up for r in ok])
    if b is not None:
        comp["supertrend"] = b
        m.facts.append(f"Supertrend points up on {_pct(up, n)} of them." if n != 1 else
                       f"Supertrend points {'up' if up else 'down'}.")
    b, up, n = _breadth([r.sma_up for r in ok])
    if b is not None:
        comp["sma"] = b
        m.facts.append(f"SMA 22 is above SMA 33 on {_pct(up, n)}." if n != 1 else
                       f"SMA 22 is {'above' if up else 'below'} SMA 33.")

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
    """One Mood per market that has instruments in the results (markets you don't watch are left out)."""
    return {k: market_mood(results, k) for k, spec in MARKETS.items()
            if any(r.group in spec["groups"] for r in results)}


# --------------------------------------------------------------------------- one instrument's Bull / Bear view
VIEW_WEIGHTS = {"dema": 0.35, "supertrend": 0.25, "sma": 0.20, "rsi": 0.10, "signal": 0.10}


def ticker_view(res, cfg) -> dict:
    """Bull / Bear verdict for one instrument (scalpbot.scan.Result), and what stands between it and a signal.

    Score -100..+100 from: 200 DEMA side 35%, Supertrend 25%, SMA 22 vs 33 20%, RSI 10%, a signal in the look-back 10%.
    It reads the current structure; it is not a forecast.
    """
    comp = {}
    if res.above_dema is not None:
        comp["dema"] = 1.0 if res.above_dema else -1.0
    if res.st_up is not None:
        comp["supertrend"] = 1.0 if res.st_up else -1.0
    if res.sma_up is not None:
        comp["sma"] = 1.0 if res.sma_up else -1.0
    if res.rsi is not None:
        comp["rsi"] = max(-1.0, min(1.0, (res.rsi - 50) / 20))
    if res.status in ("LONG", "SHORT"):
        comp["signal"] = 1.0 if res.status == "LONG" else -1.0
    if not comp:
        return {"score": None, "label": "No data", "side": "none", "facts": [], "why": []}
    score = round(100 * sum(VIEW_WEIGHTS[k] * v for k, v in comp.items()) / sum(VIEW_WEIGHTS[k] for k in comp), 1)
    label, icon = label_for(score)
    side = "bull" if score >= 15 else "bear" if score <= -15 else "neutral"

    facts = [f"{'Above' if res.above_dema else 'Below'} the 200 DEMA (the big-picture trend is {'up' if res.above_dema else 'down'}).",
             f"Supertrend {'up' if res.st_up else 'down'}, SMA 22 {'above' if res.sma_up else 'below'} SMA 33."]
    if res.rsi is not None:
        tone = ("overbought" if res.rsi >= 70 else "strong" if res.rsi >= 55 else "oversold" if res.rsi <= 30
                else "weak" if res.rsi <= 45 else "neutral")
        facts.append(f"RSI {res.rsi:.1f} ({tone}).")

    why = []
    if res.status in ("LONG", "SHORT"):
        why.append(f"A {res.status} signal is live ({res.trigger}, {res.age} candle(s) ago).")
    else:
        want = "LONG" if score >= 0 else "SHORT"           # the side the structure leans to
        lo, hi = cfg.rsi_long if want == "LONG" else cfg.rsi_short
        for c in res.checks.get(want, []):
            if c.passed:
                continue
            if c.name.startswith("Trigger"):
                why.append(f"No fresh trigger: a {want} needs SMA 22 to cross {'above' if want == 'LONG' else 'below'} "
                           f"SMA 33, or the lines to cross {'up through' if want == 'LONG' else 'down through'} the 200 DEMA.")
            elif c.name.startswith("RSI") and res.rsi is not None:
                if res.rsi > hi:
                    why.append(f"RSI {res.rsi:.1f} is above {hi:.0f}: {'overbought, so longs wait for a pullback' if want == 'LONG' else 'too strong for a short'} "
                               f"into {lo:.0f}-{hi:.0f}.")
                elif res.rsi < lo:
                    why.append(f"RSI {res.rsi:.1f} is below {lo:.0f}: {'too weak for a long' if want == 'LONG' else 'oversold, so shorts wait for a bounce'} "
                               f"into {lo:.0f}-{hi:.0f}.")
                else:
                    why.append(f"RSI {res.rsi:.1f} is in the {lo:.0f}-{hi:.0f} zone but must be {'rising' if want == 'LONG' else 'falling'}.")
            else:
                why.append(f"{c.name}: not yet ({c.detail}).")
        if not why:
            why.append(f"All {want} filters pass; it needs the trigger on a closed candle.")
        why.insert(0, f"Leaning {want.lower()}, but no {want} signal yet because:")
    return {"score": score, "label": label, "icon": icon, "side": side, "facts": facts, "why": why}
