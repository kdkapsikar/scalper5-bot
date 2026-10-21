"""Bull & Bear assistant: understanding questions and the replies (the API serves them, see test_api.py)."""
import pandas as pd
import pytest

from scalpbot import assistant as A
from scalpbot.mood import Mood
from scalpbot.scan import Result

NAMES = ["NIFTY FUT", "BANKNIFTY FUT", "RELIANCE FUT", "HDFCBANK FUT", "SBIN FUT", "M&M FUT", "BTCUSDT", "ETHUSDT",
         "PAXGUSDT", "XAUUSDT", "XAUUSD (spot)", "XAUUSD (OANDA)", "GOLD FUT", "GOLDM FUT", "SILVER FUT", "SILVERM FUT", "CRUDEOIL FUT",
         "CRUDEOILM FUT", "NATURALGAS FUT", "NATGASMINI FUT", "COPPER FUT", "ZINC FUT", "ALUMINIUM FUT", "LEAD FUT"]


@pytest.mark.parametrize("text,expected", [
    ("how is the market", ("mood", None)),
    ("any signals now?", ("signals", None)),
    ("nifty", ("ticker", "NIFTY FUT")),
    ("check reliance", ("ticker", "RELIANCE FUT")),
    ("bank nifty", ("ticker", "BANKNIFTY FUT")),
    ("hdfc bank", ("ticker", "HDFCBANK FUT")),
    ("tell me about eth", ("ticker", "ETHUSDT")),
    ("gold", ("ticker", "XAUUSDT")),
    ("oanda gold", ("ticker", "XAUUSD (OANDA)")),
    ("mcx gold", ("ticker", "GOLD FUT")),
    ("gold mini", ("ticker", "GOLDM FUT")),
    ("how is crude", ("ticker", "CRUDEOIL FUT")),
    ("crude mini", ("ticker", "CRUDEOILM FUT")),
    ("natural gas", ("ticker", "NATURALGAS FUT")),
    ("silver", ("ticker", "SILVER FUT")),
    ("silver mini", ("ticker", "SILVERM FUT")),
    ("zinc", ("ticker", "ZINC FUT")),
    ("check copper", ("ticker", "COPPER FUT")),
    ("how is xauusd", ("ticker", "XAUUSD (spot)")),
    ("spot gold", ("ticker", "XAUUSD (spot)")),
    ("xauusdt", ("ticker", "XAUUSDT")),
    ("m&m", ("ticker", "M&M FUT")),
    ("what is supertrend", ("explain", "supertrend")),
    ("what are fees", ("explain", "fees")),
    ("why blocked", ("explain", "blocked")),
    ("is my upstox connected", ("connections", None)),
    ("namaste", ("help", None)),
    ("qwerty", ("unknown", None)),
])
def test_intent(text, expected):
    assert A.intent(text, NAMES) == expected


def _res(name="NIFTY FUT", status="NONE", up=True, **kw):
    base = dict(name=name, group="Index futures", status=status, price=25000.0, rsi=58.0, above_dema=up, st_up=up,
                sma_up=up)
    base.update(kw)
    return Result(**base)


def test_reply_mood_lead_follows_the_market():
    bull = {"India": Mood("India", 52, "Strong Bull", "🐂", n=10, facts=["80% above DEMA."]),
            "Crypto": Mood("Crypto", 20, "Bull", "🐂", n=4)}
    out = A.reply_mood(bull)
    assert out[0].who == A.BULL and "Strong Bull" in out[0].text and out[-1].who == A.BEAR
    bear = {"India": Mood("India", -50, "Strong Bear", "🐻", n=10, stale=3), "Crypto": Mood("Crypto")}
    out = A.reply_mood(bear)
    assert out[0].who == A.BEAR and "no data" in out[0].text and "closed" in out[-1].text
    assert A.reply_mood({"India": Mood("India"), "Crypto": Mood("Crypto")})[0].who == A.BEAR


def test_reply_signals():
    t = pd.Timestamp("2026-10-16 05:00", tz="UTC")
    hits = [_res(status="LONG", trigger="SMA cross", age=1, signal_price=25010.0, stop=24950.0, target=25100.0,
                 signal_close=t),
            _res("BTCUSDT", status="SHORT", trigger="200 DEMA cross", age=0, signal_price=67000.0, stop=None, target=None,
                 signal_close=t)]
    out = A.reply_signals(hits + [_res("SBIN FUT")], 3, "x")
    assert [m.who for m in out[:2]] == [A.BULL, A.BEAR]
    assert "NIFTY FUT" in out[0].text and "stop 24,950.00" in out[0].text and "BTCUSDT" in out[1].text
    assert "not recommendations" in out[-1].text
    none = A.reply_signals([_res(status="BLOCKED", side="LONG", trigger="SMA cross", blocked_by=["RSI"])], 3, "x")
    assert len(none) == 1 and "Near misses" in none[0].text and "RSI" in none[0].text
    assert "login" in A.reply_signals([_res(status="ERROR", error="x")], 3, "x")[0].text


def test_reply_ticker():
    out = A.reply_ticker(_res(up=False, status="SHORT", trigger="SMA cross", age=2, signal_price=24900.0, stop=25000.0,
                              target=24800.0), 3)
    assert out[0].who == A.BEAR and "Fully bearish" in out[0].text
    assert out[1].who == A.BEAR and "SHORT" in out[1].text and "target 24,800.00" in out[1].text
    out = A.reply_ticker(_res(up=True, stale=True), 3)
    assert out[0].who == A.BULL and any("closed" in m.text for m in out) and "No signal" in out[-1].text
    assert "couldn't load" in A.reply_ticker(_res(status="ERROR", error="boom"), 3)[0].text


def test_reply_connections_and_explain():
    assert A.reply_connections(True, 2.0, True)[0].who == A.BULL
    out = A.reply_connections(True, 30.0, False)[0]
    assert out.who == A.BEAR and "expired" in out.text and "no keys" in out.text
    assert "not logged in" in A.reply_connections(False, None, True)[0].text
    assert "OANDA**: token saved" in A.reply_connections(True, 1.0, True, True)[0].text
    assert "optional" in A.reply_connections(True, 1.0, True, False)[0].text
    assert "Supertrend" in A.reply_explain("supertrend")[0].text
    assert "Ask about" in A.reply_explain(None)[0].text


def test_replies_never_sound_like_advice():
    texts = " ".join(m.text for m in A.reply_help() + A.reply_mood(
        {"India": Mood("India", 60, "Strong Bull", "🐂", n=5)})).lower()
    assert "isn't advice" in texts
    for word in ("buy now", "sell now", "guaranteed", "sure shot"):
        assert word not in texts
