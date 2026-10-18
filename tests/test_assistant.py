"""Bull & Bear assistant: understanding questions, the replies, and the floating launcher + chat in the portal."""
from pathlib import Path

import pandas as pd
import pytest

from scalpbot import assistant as A
from scalpbot.mood import Mood
from scalpbot.scan import Result
from tests.conftest import make_user, sign_in

ROOT = Path(__file__).resolve().parent.parent
NAMES = ["NIFTY FUT", "BANKNIFTY FUT", "RELIANCE FUT", "HDFCBANK FUT", "SBIN FUT", "M&M FUT", "BTCUSDT", "ETHUSDT",
         "PAXGUSDT", "XAUUSDT"]


@pytest.mark.parametrize("text,expected", [
    ("how is the market", ("mood", None)),
    ("any signals now?", ("signals", None)),
    ("nifty", ("ticker", "NIFTY FUT")),
    ("check reliance", ("ticker", "RELIANCE FUT")),
    ("bank nifty", ("ticker", "BANKNIFTY FUT")),
    ("hdfc bank", ("ticker", "HDFCBANK FUT")),
    ("tell me about eth", ("ticker", "ETHUSDT")),
    ("gold", ("ticker", "XAUUSDT")),
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
    assert "Supertrend" in A.reply_explain("supertrend")[0].text
    assert "Ask about" in A.reply_explain(None)[0].text


def test_replies_never_sound_like_advice():
    texts = " ".join(m.text for m in A.reply_help() + A.reply_mood(
        {"India": Mood("India", 60, "Strong Bull", "🐂", n=5)})).lower()
    assert "isn't advice" in texts
    for word in ("buy now", "sell now", "guaranteed", "sure shot"):
        assert word not in texts


# --------------------------------------------------------------------------- in the portal
@pytest.fixture
def at(monkeypatch, tmp_path, portal_db):
    from streamlit.testing.v1 import AppTest
    from scalpbot import scan as sc
    from scalpbot import universe
    from tests.test_scanner import MCX_ROWS, NSE_ROWS, _recent_frame

    monkeypatch.setenv("SCALP_WATCHLIST", str(ROOT / "watchlist.yaml"))
    monkeypatch.setenv("SCALP_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(universe, "_load_instruments", lambda ex: NSE_ROWS if ex == "NSE" else MCX_ROWS)
    monkeypatch.setattr(sc, "fetch_candles", lambda inst, n=1000: _recent_frame(inst.name))
    monkeypatch.chdir(ROOT)
    user = make_user(portal_db, keys={"UPSTOX_ACCESS_TOKEN": "t", "COINSWITCH_API_KEY": "k", "COINSWITCH_SECRET_KEY": "00"})
    return sign_in(AppTest.from_file(str(ROOT / "app.py"), default_timeout=120), user)


def test_launcher_on_every_signed_in_page(at):
    at.run()
    assert not at.exception
    assert any('class="s5-duo"' in m.value for m in at.markdown)
    assert at.button(key="s5bot_open").label == "Ask Bull & Bear"
    at.switch_page("portal/mood.py").run()
    assert not at.exception
    bubble = [m.value for m in at.markdown if 'class="s5-bubble"' in m.value][0]
    assert "Market mood:" in bubble                          # greets with the mood the page just measured


def test_launcher_hidden_when_signed_out(monkeypatch, tmp_path, portal_db):
    from streamlit.testing.v1 import AppTest
    monkeypatch.chdir(ROOT)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert not any('s5-duo' in m.value for m in at.markdown)


def test_chat_opens_and_answers(at):
    at.run()
    at.button(key="s5bot_open").click().run()
    assert not at.exception
    assert any("Your market desk" in m.value for m in at.markdown)
    assert any("Namaste" in m.value for m in at.markdown)
    # In the browser the dialog reruns on its own; AppTest reruns the whole script, so open it and ask in one run.
    at.button(key="s5bot_open").click()
    at.chat_input(key="s5bot_input").set_value("is my upstox connected").run()
    assert not at.exception
    texts = " ".join(m.value for m in at.markdown)
    assert "All set" in texts                                 # answered with this user's saved keys


def test_chat_menu_chip_reads_the_market(at):
    at.run()
    at.button(key="s5bot_open").click().run()
    chips = [w for w in at.button_group if w.key and w.key.startswith("s5bot_pill")] if hasattr(at, "button_group") else []
    if not chips:
        pytest.skip("this Streamlit version's AppTest does not expose st.pills")
    at.button(key="s5bot_open").click()
    chips[0].set_value("🐂🐻 Market mood").run()
    assert not at.exception
    assert any("India" in m.value and "/100" in m.value for m in at.markdown)
