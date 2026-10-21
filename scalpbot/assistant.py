"""Bull & Bear: the portal's chat assistant. Pure logic (no Streamlit), so it can be tested on its own.

The Bull is upbeat, the Bear is cautious. Whichever matches the market leads the reply; the other adds a caveat.
They only describe what the rules and indicators show, from the person's own broker data. No advice, no orders.

    intent(text, names)      -> (intent, argument)   what the person asked for
    match_ticker(text, names)-> best instrument name or None
    reply_*(...)             -> list[Msg]            the duo's answer
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Optional

from .scan import stale_text
from .strategy import fmt

BULL, BEAR = "bull", "bear"


@dataclass
class Msg:
    who: str            # "bull" | "bear" | "user"
    text: str           # markdown


MENU = [
    ("mood", "🐂🐻 Market mood"),
    ("signals", "⚡ Live signals"),
    ("ticker", "🔎 Check a ticker"),
    ("explain", "📚 Explain"),
    ("connections", "🔌 My connections"),
]

GLOSSARY = {
    "sma": ("SMA 22 / 33",
            "Simple moving averages of the last 22 and 33 closes. **22 crossing above 33** is the main LONG trigger, "
            "**below** is the SHORT trigger."),
    "dema": ("200 DEMA",
             "A double exponential moving average over 200 candles: the big-picture trend. Longs need price **above** "
             "it, shorts **below**. The 22/33 lines crossing it is the second trigger."),
    "supertrend": ("Supertrend (10, 3)",
                   "A trailing line built from ATR. When it flips up the trend filter allows longs, when it flips down "
                   "it allows shorts. The backtest also uses it as a trailing exit."),
    "rsi": ("RSI (14)",
            "Momentum from 0 to 100. Longs want RSI **35-62 and rising** (room to run, not overbought); shorts want "
            "**30-60 and falling**."),
    "pivot": ("Daily pivots",
              "P, R1-R3 and S1-S3 from the previous day's high, low and close. The next level in the trade's direction "
              "is the target, and it has to be at least 0.5 ATR away."),
    "atr": ("ATR (14)",
            "Average true range: how much a candle typically moves. The stop is **1.5 x ATR** from entry."),
    "mood": ("Market mood score",
             "From -100 to +100: 200 DEMA breadth 30%, Supertrend breadth 20%, SMA 22/33 breadth 15%, the leader "
             "(NIFTY FUT / BTCUSDT) 20%, median RSI 10%, fresh signals 5%. 15+ is Bull, -15 or lower is Bear."),
    "fees": ("Fees and slippage",
             "Charged per side in basis points (1 bps = 0.01%). A round trip costs 2 x (fee + slippage), e.g. "
             "2 x (5 + 2) = 0.14%, taken off every backtest trade."),
    "blocked": ("Blocked setups",
                "A trigger fired but one of the filters (Supertrend, 200 DEMA side, RSI, pivot room) said no. The "
                "Scanner's near-misses table names the filter."),
}
_GLOSS_WORDS = {
    "sma": ["sma", "moving average", "22", "33", "crossover"], "dema": ["dema", "200"],
    "supertrend": ["supertrend", "super trend"], "rsi": ["rsi", "momentum", "overbought", "oversold"],
    "pivot": ["pivot", "target", "r1", "s1"], "atr": ["atr", "stop", "stoploss", "stop loss"],
    "mood": ["mood", "score", "bull", "bear"], "fees": ["fee", "fees", "slippage", "bps", "cost"],
    "blocked": ["blocked", "near miss", "near-miss", "filter"],
}

_INTENTS = [
    ("connections", ["connect", "connection", "token", "login", "log in", "upstox", "coinswitch", "keys", "api key"]),
    ("explain", ["what is", "what's", "whats", "explain", "meaning", "how does", "how do", "define", "why"]),
    ("signals", ["signal", "signals", "setup", "setups", "trade now", "opportunit", "scan"]),
    ("mood", ["mood", "market", "bull", "bear", "trend", "sentiment", "tape", "how is", "how's"]),
    ("help", ["help", "menu", "hi", "hello", "namaste", "hey", "start"]),
]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9& ]+", " ", (s or "").lower()).strip()


def match_ticker(text: str, names: list[str]) -> Optional[str]:
    """Best instrument for free text such as 'nifty', 'reliance fut', 'btc', 'gold'."""
    q = _norm(text)
    if not q:
        return None
    aliases = {"oanda": "XAUUSD (OANDA)", "xauusd": "XAUUSD (OANDA)", "spot gold": "XAUUSD (OANDA)",   # first: "oanda gold"
               "mcx gold": "GOLD FUT", "gold mini": "GOLDM FUT", "mcx silver": "SILVER FUT", "silver mini": "SILVERM FUT",
               "silver": "SILVER FUT", "crude oil": "CRUDEOIL FUT", "crude mini": "CRUDEOILM FUT", "crude": "CRUDEOIL FUT",
               "natural gas": "NATURALGAS FUT", "natgas": "NATURALGAS FUT", "aluminum": "ALUMINIUM FUT",
               "btc": "BTCUSDT", "bitcoin": "BTCUSDT", "eth": "ETHUSDT", "ethereum": "ETHUSDT",
               "paxg": "PAXGUSDT", "gold": "XAUUSDT", "xau": "XAUUSDT", "xauusdt": "XAUUSDT", "nifty 50": "NIFTY FUT",
               "bank nifty": "BANKNIFTY FUT"}
    by_key = {_norm(n): n for n in names}
    for k, v in aliases.items():
        if re.search(rf"\b{re.escape(k)}\b", q) and v in names:
            return v
    words = [w for w in q.split() if w not in {"fut", "futures", "check", "show", "the", "for", "of", "is", "how",
                                               "about", "what", "status", "ticker", "price", "me", "on", "a"}]
    for w in words:                                  # exact underlying, e.g. "reliance" -> "RELIANCE FUT"
        for k, n in by_key.items():
            if k == w or k == f"{w} fut" or k.replace(" fut", "") == w:
                return n
    cand = difflib.get_close_matches(" ".join(words), list(by_key), n=1, cutoff=0.75)
    if cand:
        return by_key[cand[0]]
    for w in words:
        cand = difflib.get_close_matches(w, [k.replace(" fut", "") for k in by_key], n=1, cutoff=0.85)
        if cand:
            for k, n in by_key.items():
                if k.replace(" fut", "") == cand[0]:
                    return n
    return None


def glossary_topic(text: str) -> Optional[str]:
    q = f" {_norm(text)} "
    best, hits = None, 0
    for topic, words in _GLOSS_WORDS.items():
        n = sum(1 for w in words if f" {w} " in q or (len(w) > 3 and w in q))
        if n > hits:
            best, hits = topic, n
    return best


def intent(text: str, names: list[str]) -> tuple[str, Optional[str]]:
    q = f" {_norm(text)} "
    for name, words in _INTENTS:
        if name == "explain" and any(f" {w} " in q for w in words):
            return "explain", glossary_topic(text)
        if name == "connections" and any(f" {w} " in q for w in words):
            return "connections", None
    t = match_ticker(text, names)
    if t:
        return "ticker", t
    for name, words in _INTENTS:
        if any(f" {w} " in q or (len(w) > 4 and w in q) for w in words):
            return name, glossary_topic(text) if name == "explain" else None
    topic = glossary_topic(text)
    if topic:
        return "explain", topic
    return "unknown", None


# --------------------------------------------------------------------------- replies
def reply_help(first_name: str = "") -> list[Msg]:
    hi = f"Namaste{', ' + first_name if first_name else ''}! 🐂"
    return [Msg(BULL, f"{hi} I'm **Bull** and this is my cautious friend **Bear**. Ask us how the market looks, "
                      "for live setups, about any ticker (try *nifty*, *reliance*, *btc*), or what an indicator means."),
            Msg(BEAR, "We read **your own** broker data and describe what the rules see. We never place orders and "
                      "this isn't advice. 🐻")]


def reply_unknown() -> list[Msg]:
    return [Msg(BEAR, "Hmm, I didn't catch that. 🐻 Try *market mood*, *signals*, a ticker such as *banknifty* or "
                      "*eth*, or *what is supertrend*.")]


def reply_explain(topic: Optional[str]) -> list[Msg]:
    if topic is None:
        topics = ", ".join(f"*{v[0]}*" for v in GLOSSARY.values())
        return [Msg(BULL, f"Happy to explain! Ask about: {topics}.")]
    title, body = GLOSSARY[topic]
    who = BEAR if topic in ("atr", "fees", "blocked") else BULL
    return [Msg(who, f"**{title}**: {body}")]


def reply_mood(moods: dict) -> list[Msg]:
    """moods: {"India": Mood, "Crypto": Mood} from scalpbot.mood."""
    measured = [m for m in moods.values() if m.score is not None]
    if not measured:
        return [Msg(BEAR, "I can't read the market yet: nothing came back from your brokers. Check **My connections** "
                          "(the Upstox token expires every day). 🐻")]
    lines = []
    for market, m in moods.items():
        if m.score is None:
            lines.append(f"- **{market}**: no data")
            continue
        lines.append(f"- **{market}**: {m.icon} **{m.label}** ({m.score:+.0f}/100)")
    avg = sum(m.score for m in measured) / len(measured)
    lead = BULL if avg >= 0 else BEAR
    head = ("The herd is charging! 🐂" if avg >= 40 else "Leaning bullish. 🐂" if avg >= 15 else
            "Mostly sideways, nobody's winning. ⚖️" if avg > -15 else "Leaning bearish. 🐻" if avg > -40 else
            "Deep in hibernation territory. 🐻")
    out = [Msg(lead, head + "\n\n" + "\n".join(lines))]
    strongest = max(measured, key=lambda m: abs(m.score))
    if strongest.facts:
        out.append(Msg(lead, f"Why ({strongest.market}): " + " ".join(strongest.facts[:3])))
    other = BEAR if lead == BULL else BULL
    caveat = ("Moods turn fast on 5-minute charts. Wait for a closed-candle signal and respect the stop. 🐻"
              if other == BEAR else "Bears get caught when breadth flips: watch the leader for a turn. 🐂")
    if any(m.stale for m in measured if m.market == "Crypto"):
        caveat = "Some crypto candles are arriving late from the broker, so that part may lag a little. " + caveat
    if any(m.stale for m in measured if m.market != "Crypto"):
        caveat = "Indian futures look closed, so that part is the last session. " + caveat
    out.append(Msg(other, caveat))
    return out


def reply_signals(results: list, lookback: int, scope: str) -> list[Msg]:
    hits = [r for r in results if r.status in ("LONG", "SHORT")]
    errors = sum(1 for r in results if r.status == "ERROR")
    if not results or errors == len(results):
        return [Msg(BEAR, "Every instrument failed to load, which usually means a login is missing or expired. "
                          "Check **My connections**. 🐻")]
    if not hits:
        blocked = [r for r in results if r.status == "BLOCKED"]
        txt = f"No full setups in the last {lookback} closed candles across {len(results)} {scope}. 🐻 Patience pays."
        if blocked:
            txt += "\n\nNear misses: " + ", ".join(f"**{r.name}** {r.side.lower()} (blocked by {', '.join(r.blocked_by)})"
                                                   for r in blocked[:5])
        return [Msg(BEAR, txt)]
    longs = [r for r in hits if r.status == "LONG"]
    shorts = [r for r in hits if r.status == "SHORT"]
    out = []

    def line(r) -> str:
        bits = [f"**{r.name}** at {fmt(r.signal_price)}", r.trigger, f"{r.age} candle{'s' if r.age != 1 else ''} ago"]
        if r.stop is not None:
            bits.append(f"stop {fmt(r.stop)}")
        if r.target is not None:
            bits.append(f"target {fmt(r.target)}")
        return "- " + " · ".join(bits)

    if longs:
        out.append(Msg(BULL, f"🟢 {len(longs)} LONG setup{'s' if len(longs) != 1 else ''}:\n" + "\n".join(map(line, longs[:8]))))
    if shorts:
        out.append(Msg(BEAR, f"🔴 {len(shorts)} SHORT setup{'s' if len(shorts) != 1 else ''}:\n" + "\n".join(map(line, shorts[:8]))))
    out.append(Msg(BEAR if longs else BULL, "These are what the rules flagged, not recommendations. Size small and "
                                             "check the chart on the Scanner page first."))
    return out


def reply_ticker(res, lookback: int) -> list[Msg]:
    """res: scalpbot.scan.Result for one instrument."""
    if res.status == "ERROR":
        return [Msg(BEAR, f"I couldn't load **{res.name}**: {res.error} 🐻")]
    trend_up = sum(bool(x) for x in (res.above_dema, res.st_up, res.sma_up))
    who = BULL if trend_up >= 2 else BEAR
    facts = [f"price **{fmt(res.price)}**",
             f"{'above' if res.above_dema else 'below'} the 200 DEMA",
             f"Supertrend **{'up' if res.st_up else 'down'}**",
             f"SMA 22 {'above' if res.sma_up else 'below'} 33"]
    if res.rsi is not None:
        facts.append(f"RSI {res.rsi:.0f}")
    lean = {3: "Fully bullish structure. 🐂", 2: "Leaning bullish. 🐂", 1: "Leaning bearish. 🐻", 0: "Fully bearish structure. 🐻"}[trend_up]
    out = [Msg(who, f"**{res.name}**: " + ", ".join(facts) + f". {lean}")]
    if res.stale:
        out.append(Msg(BEAR, stale_text(res) + " So this may not be current."))
    if res.status in ("LONG", "SHORT"):
        side_who = BULL if res.status == "LONG" else BEAR
        t = f"{'🟢' if res.status == 'LONG' else '🔴'} **{res.status}** signal ({res.trigger}), {res.age} candle(s) ago at {fmt(res.signal_price)}"
        if res.stop is not None:
            t += f" · stop {fmt(res.stop)}"
        if res.target is not None:
            t += f" · target {fmt(res.target)}"
        out.append(Msg(side_who, t + "."))
    elif res.status == "BLOCKED":
        out.append(Msg(BEAR, f"A {res.side} trigger fired ({res.trigger}) but it's blocked by: {', '.join(res.blocked_by)}."))
    else:
        out.append(Msg(BEAR if who == BULL else BULL, f"No signal in the last {lookback} closed candles."))
    return out


def reply_connections(up_token: bool, up_age_h: Optional[float], cs_ok: bool, oanda_ok: Optional[bool] = None) -> list[Msg]:
    lines = []
    if not up_token:
        lines.append("- **Upstox**: not logged in. Do today's login on the **Connect** page.")
    elif up_age_h is not None and up_age_h > 20:
        lines.append(f"- **Upstox**: token is {up_age_h:.0f} h old and has probably expired. Log in again on **Connect**.")
    else:
        lines.append(f"- **Upstox**: connected" + (f" (token {up_age_h:.1f} h old)" if up_age_h is not None else "") + ".")
    lines.append("- **CoinSwitch**: " + ("keys saved." if cs_ok else "no keys yet. Add them on **Connect**."))
    if oanda_ok is not None:
        lines.append("- **OANDA**: " + ("token saved." if oanda_ok else
                                        "not connected (optional, for XAUUSD (OANDA)). Add a token on **Connect**."))
    ok = up_token and (up_age_h is None or up_age_h <= 20) and cs_ok
    return [Msg(BULL if ok else BEAR, ("All set, both feeds are ready! 🐂\n\n" if ok else "Some setup left: 🐻\n\n")
                + "\n".join(lines))]
