"""Helpers behind the API: the Upstox login round trip, connection checks, and the local alert bot process."""
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

from scalpbot import portal_tools as pt

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
