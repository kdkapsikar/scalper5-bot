"""The web portal: Upstox login helpers, background bot control, and the pages (run headless, signed in)."""
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

from scalpbot import portal_tools as pt
from tests.conftest import make_user, sign_in

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    monkeypatch.setattr(pt, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(pt, "TOKEN_FILE", tmp_path / "state" / "upstox_token.txt")
    monkeypatch.setattr(pt, "PID_FILE", tmp_path / "state" / "bot.pid")
    monkeypatch.setattr(pt, "LOG_FILE", tmp_path / "state" / "bot.log")
    return tmp_path


def test_extract_code_accepts_code_or_full_url():
    assert pt.extract_code("abc123") == "abc123"
    assert pt.extract_code("http://localhost:8501/connect?code=XyZ9&state=1") == "XyZ9"
    assert pt.extract_code("  code=QQQ ") == "QQQ"


def test_login_url_needs_key_and_redirect_and_carries_state():
    with pytest.raises(ValueError):
        pt.upstox_login_url("", "")
    url = pt.upstox_login_url("k1", "http://localhost:8501/", "ST4TE")
    assert "client_id=k1" in url and "redirect_uri=http%3A%2F%2Flocalhost%3A8501%2F" in url and "state=ST4TE" in url


class _Ok:
    ok = True
    def json(self): return {"access_token": "TOK123"}


def test_get_token_posts_the_code(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        seen.update(url=url, data=data)
        return _Ok()

    monkeypatch.setattr(pt.requests, "post", fake_post)
    assert pt.upstox_get_token("http://x/?code=CODE9", "k", "s", "http://x/") == "TOK123"
    assert seen["data"]["code"] == "CODE9" and seen["data"]["grant_type"] == "authorization_code"
    assert seen["data"]["client_id"] == "k" and seen["data"]["client_secret"] == "s"


def test_get_token_errors_are_readable(monkeypatch):
    with pytest.raises(ValueError):
        pt.upstox_get_token("", "k", "s", "r")
    with pytest.raises(ValueError):
        pt.upstox_get_token("abc", "", "", "")           # keys missing

    class R:
        ok = False
        status_code = 401
        text = "invalid code"

    monkeypatch.setattr(pt.requests, "post", lambda *a, **k: R())
    with pytest.raises(RuntimeError, match="rejected"):
        pt.upstox_get_token("abc", "k", "s", "r")


def test_bot_env_uses_the_users_keys(sandbox):
    from scalpbot.creds import Creds
    env = pt.bot_env(Creds(UPSTOX_ACCESS_TOKEN="T1", COINSWITCH_API_KEY="CK", COINSWITCH_SECRET_KEY="00"), 7)
    assert env["COINSWITCH_API_KEY"] == "CK" and env["UPSTOX_ACCESS_TOKEN"] == ""
    assert Path(env["UPSTOX_TOKEN_FILE"]).read_text() == "T1" and "/users/7/" in env["UPSTOX_TOKEN_FILE"]


def test_bot_command_and_flags():
    cmd = pt.bot_command(["Index futures", "Crypto"], "fast", 4, True, ["--no-rsi", "--bogus"], ["NIFTY FUT"])
    assert cmd[1:3] == ["-m", "scalpbot.bot"]
    assert cmd[cmd.index("--groups") + 1] == "Index futures,Crypto"
    assert cmd[cmd.index("--only") + 1] == "NIFTY FUT"
    assert cmd[cmd.index("--dema-cross") + 1] == "fast" and cmd[cmd.index("--cooldown") + 1] == "4"
    assert "--dry-run" in cmd and "--no-rsi" in cmd and "--bogus" not in cmd


def test_start_stop_bot_lifecycle(sandbox):
    cmd = [sys.executable, "-c", "import time; print('hello', flush=True); time.sleep(60)"]
    pid = pt.start_bot(cmd)
    try:
        assert pt.bot_pid() == pid
        with pytest.raises(RuntimeError):
            pt.start_bot(cmd)                       # no second copy
        for _ in range(50):
            if "hello" in pt.tail_log():
                break
            time.sleep(0.1)
        assert "hello" in pt.tail_log()
    finally:
        assert pt.stop_bot() is True
    assert pt.bot_pid() is None and not pt.PID_FILE.exists()
    assert pt.stop_bot() is False


def test_dead_bot_is_detected_and_pid_file_cleaned(sandbox):
    pt.start_bot([sys.executable, "-c", "print('bye')"])
    for _ in range(50):
        if pt.bot_pid() is None:
            break
        time.sleep(0.1)
    assert pt.bot_pid() is None and not pt.PID_FILE.exists()


def test_check_instruments_reports_each_outcome(monkeypatch):
    from scalpbot.brokers import AuthExpired
    from scalpbot.watchlist import Instrument
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("5min") - pd.Timedelta(minutes=5), periods=400, freq="5min")
    good = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx)

    def fake(inst, n=1000):
        if inst.name == "A":
            return good
        if inst.name == "B":
            raise AuthExpired("no token")
        raise RuntimeError("symbol not found")

    monkeypatch.setattr(pt, "fetch_candles", fake)
    insts = [Instrument(name=n, source="coinswitch", symbol=n, group="Crypto") for n in "ABC"]
    out = pt.check_instruments(insts).set_index("Ticker")
    assert out.loc["A", "Status"].startswith("OK") and out.loc["A", "Candles"] == 400
    assert out.loc["B", "Status"].startswith("LOGIN NEEDED")
    assert out.loc["C", "Status"].startswith("FAILED") and "symbol not found" in out.loc["C", "Status"]


# --------------------------------------------------------------------------- pages, run headless
@pytest.fixture
def at(monkeypatch, sandbox, portal_db):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from scalpbot import universe
    from tests.test_scanner import MCX_ROWS, NSE_ROWS, _recent_frame

    monkeypatch.setenv("SCALP_WATCHLIST", str(ROOT / "watchlist.yaml"))
    monkeypatch.setenv("SCALP_STATE_DIR", str(sandbox / "state"))
    monkeypatch.setattr(universe, "_load_instruments", lambda ex: NSE_ROWS if ex == "NSE" else MCX_ROWS)
    monkeypatch.setattr(pt, "fetch_candles", lambda inst, n=1000: _recent_frame(inst.name))
    monkeypatch.chdir(ROOT)
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)


def _texts(at):
    return [x.value for x in list(at.markdown) + list(at.caption) + list(at.success) + list(at.error) + list(at.info)]


def test_signed_out_sees_only_the_sign_in_page(at):
    at.run()
    assert not at.exception
    assert [t.value for t in at.title] == ["Welcome to Scalp5"]
    assert not any("Signed in as" in t or "Upstox (log in" in t for t in _texts(at))   # nothing from inside leaks
    assert not at.metric and not at.dataframe


def test_sign_up_is_pending_until_an_admin_approves(at, portal_db):
    at.run()
    at.text_input(key="su_name").set_value("Ann")
    at.text_input(key="su_email").set_value("Ann@Example.com")
    at.text_input(key="su_pw").set_value("correct horse 9")
    at.text_input(key="su_pw2").set_value("correct horse 9")
    at.button[1].click().run()
    assert not at.exception
    assert any("admin will review" in s.value for s in at.success)
    at.text_input(key="si_email").set_value("ann@example.com")
    at.text_input(key="si_pw").set_value("correct horse 9")
    at.button[0].click().run()
    assert any("waiting for an admin" in e.value for e in at.error)
    assert "user_id" not in at.session_state


def test_admin_email_signs_up_straight_in_and_sees_the_admin_page(at, portal_db):
    make_user(portal_db, "ann@example.com")                  # someone waiting
    from sqlalchemy import update
    from scalpbot.accounts import users
    with portal_db.engine.begin() as c:
        c.execute(update(users).values(status="pending"))
    at.run()
    at.text_input(key="su_name").set_value("Boss")
    at.text_input(key="su_email").set_value("boss@example.com")
    at.text_input(key="su_pw").set_value("correct horse 9")
    at.text_input(key="su_pw2").set_value("correct horse 9")
    at.button[1].click().run()
    assert not at.exception
    boss = portal_db.authenticate("boss@example.com", "correct horse 9")
    assert boss.is_admin and at.session_state["user_id"] == boss.id
    at.switch_page("portal/admin.py").run()
    assert not at.exception
    m = {x.label: x.value for x in at.metric}
    assert m["Signed up"] == "2" and m["Pending approval"] == "1"
    approve = [b for b in at.button if b.label == "Approve"][0]
    approve.click().run()
    assert not at.exception
    assert portal_db.authenticate("ann@example.com", "correct horse 9").status == "active"
    log = portal_db.audit_log()
    assert any(r["action"] == "approve" and r["target"] == "ann@example.com" for r in log)


def test_regular_user_cannot_open_the_admin_page(at, portal_db):
    sign_in(at, make_user(portal_db)).run()
    assert not at.exception
    with pytest.raises(ValueError, match="Could not find a navigation page"):
        at.switch_page("portal/admin.py")                   # not even registered for regular users


def test_disabled_user_is_signed_out_on_next_click(at, portal_db):
    boss = make_user(portal_db, "boss@example.com", role="admin")
    ann = make_user(portal_db)
    sign_in(at, ann).run()
    assert at.session_state["user_id"] == ann.id
    portal_db.disable(boss, ann.id)
    at.run()
    assert "user_id" not in at.session_state
    assert any("no longer active" in e.value for e in at.error)


def test_connect_page_opens_first_and_ignores_server_env_keys(at, portal_db):
    sign_in(at, make_user(portal_db)).run()                 # env holds keys (see portal_db); this user has none
    assert not at.exception
    assert any(t.value == "Connect" for t in at.title)
    assert [m.label for m in at.metric][:3] == ["Upstox token", "Token age", "CoinSwitch keys"]
    assert at.metric[0].value == "Missing" and at.metric[2].value == "Missing"


def test_connect_page_saves_keys_per_user_encrypted(at, portal_db):
    ann, bob = make_user(portal_db), make_user(portal_db, "bob@example.com")
    sign_in(at, ann).run()
    at.text_input(key="cs_key").set_value("CSKEY")
    at.text_input(key="cs_secret").set_value("00ff")
    [b for b in at.button if b.label == "Save CoinSwitch keys"][0].click().run()
    assert not at.exception
    assert portal_db.load_creds(ann.id).COINSWITCH_API_KEY == "CSKEY"
    assert portal_db.load_creds(bob.id).COINSWITCH_API_KEY == ""
    from sqlalchemy import select
    from scalpbot.accounts import credentials
    with portal_db.engine.connect() as c:
        stored = [r.value for r in c.execute(select(credentials)).all()]
    assert stored and not any("CSKEY" in v for v in stored)      # encrypted at rest
    at.button(key="run_test").click().run()
    assert not at.exception
    assert any("OK" in m.value for m in at.markdown)


def test_upstox_redirect_saves_token_to_the_user_who_started_the_login(at, portal_db, monkeypatch):
    ann = make_user(portal_db, keys={"UPSTOX_API_KEY": "k", "UPSTOX_API_SECRET": "s", "UPSTOX_REDIRECT_URI": "http://x/"})
    state = portal_db.new_login_state(ann.id)
    monkeypatch.setattr(pt.requests, "post", lambda *a, **k: _Ok())
    at.query_params["code"] = "REDIRECTCODE"
    at.query_params["state"] = state
    at.run()                                                 # a fresh, signed-out tab
    assert not at.exception
    assert portal_db.load_creds(ann.id).UPSTOX_ACCESS_TOKEN == "TOK123"
    assert any("Saved today's Upstox token" in s.value for s in at.success)
    assert portal_db.consume_login_state(state) is None     # single use


def test_upstox_redirect_with_unknown_state_saves_nothing(at, portal_db, monkeypatch):
    ann = make_user(portal_db, keys={"UPSTOX_API_KEY": "k", "UPSTOX_API_SECRET": "s", "UPSTOX_REDIRECT_URI": "http://x/"})
    monkeypatch.setattr(pt.requests, "post", lambda *a, **k: _Ok())
    at.query_params["code"] = "C"
    at.query_params["state"] = "forged"
    at.run()
    assert portal_db.load_creds(ann.id).UPSTOX_ACCESS_TOKEN == ""
    assert any("expired or was already used" in e.value for e in at.error)


def test_alert_bot_page_is_admin_only_and_uses_the_users_keys(at, portal_db, monkeypatch):
    boss = make_user(portal_db, "boss@example.com", role="admin", keys={"UPSTOX_ACCESS_TOKEN": "t"})
    sign_in(at, boss).run()
    at.switch_page("portal/alerts.py").run()
    assert not at.exception
    assert at.metric[0].value == "Stopped"
    started = {}
    monkeypatch.setattr(pt, "start_bot", lambda cmd, env=None: started.update(cmd=cmd, env=env) or 4242)
    at.button(key="bot_start").click().run()
    assert not at.exception
    assert "scalpbot.bot" in started["cmd"] and "--dry-run" in started["cmd"]   # no Telegram set -> practice mode
    assert started["env"]["COINSWITCH_API_KEY"] == ""                            # not the server's env value


def test_alert_bot_page_hidden_when_hosted(at, portal_db, monkeypatch):
    monkeypatch.setenv("SCALP_HOSTED", "1")
    sign_in(at, make_user(portal_db, "boss@example.com", role="admin", keys={"UPSTOX_ACCESS_TOKEN": "t"})).run()
    assert not at.exception
    with pytest.raises(ValueError, match="Could not find a navigation page"):
        at.switch_page("portal/alerts.py")


def test_backtest_page_runs(at, portal_db, monkeypatch):
    from tests.test_scanner import _signal_frame
    import scalpbot.watchlist as wl
    monkeypatch.setattr(wl, "fetch_candles", lambda inst, n=1000: _signal_frame(2999)[["open", "high", "low", "close", "volume"]])
    sign_in(at, make_user(portal_db, keys={"UPSTOX_ACCESS_TOKEN": "t"})).run()
    at.switch_page("portal/backtest.py").run()
    assert not at.exception
    assert at.selectbox(key="bt_ticker").options
    at.button(key="bt_run").click().run()
    assert not at.exception
    frames = [d.value for d in at.dataframe]
    table = [f for f in frames if "DEMA trigger" in f.columns][0]
    assert list(table["DEMA trigger"]) == ["off", "fast", "both"]


def test_market_mood_page(at, portal_db, monkeypatch):
    from scalpbot import scan as sc
    from tests.test_scanner import _recent_frame
    monkeypatch.setattr(sc, "fetch_candles", lambda inst, n=1000: _recent_frame(inst.name))
    sign_in(at, make_user(portal_db, keys={"UPSTOX_ACCESS_TOKEN": "t"})).run()
    at.switch_page("portal/mood.py").run()
    assert not at.exception
    cards = [m.value for m in at.markdown if 'class="s5-mood"' in m.value]
    assert len(cards) == 2 and "India" in cards[0] and "Crypto" in cards[1]
    assert all(any(w in c for w in ("Bull", "Bear", "Neutral")) for c in cards)


def test_change_password(at, portal_db):
    ann = make_user(portal_db)
    sign_in(at, ann).run()
    at.switch_page("portal/account.py").run()
    at.text_input(key="pw_old").set_value("correct horse 9")
    at.text_input(key="pw_new").set_value("new battery 77")
    at.text_input(key="pw_new2").set_value("new battery 77")
    [b for b in at.button if b.label == "Change password"][0].click().run()
    assert not at.exception
    assert any("Password changed" in s.value for s in at.success)
    assert portal_db.authenticate("ann@example.com", "new battery 77").id == ann.id
