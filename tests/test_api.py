"""The FastAPI service the web app talks to: auth, keys, Upstox login, market endpoints, jobs, admin, Bull & Bear."""
from pathlib import Path

import pandas as pd
import pytest

from scalpbot import creds

ROOT = Path(__file__).resolve().parent.parent
PW = "correct horse 9"


@pytest.fixture
def client(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from scalpbot import portal_tools as pt
    from scalpbot import scan as sc
    from scalpbot import universe, watchlist
    from scalpbot.accounts import generate_master_key
    from tests.test_scanner import MCX_ROWS, NSE_ROWS, _recent_frame, _signal_frame

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("SCALP_MASTER_KEY", generate_master_key())
    monkeypatch.setenv("SCALP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("SCALP_WATCHLIST", str(ROOT / "watchlist.yaml"))
    monkeypatch.setenv("CORS_ORIGINS", "https://kdkapsikar.github.io")
    for k in creds.FIELDS:
        monkeypatch.setenv(k, "SERVER-ENV-VALUE-MUST-NOT-BE-USED")
    monkeypatch.setattr(universe, "_load_instruments", lambda ex: NSE_ROWS if ex == "NSE" else MCX_ROWS)

    def fake(inst, n=1000):
        c = creds.current()
        if inst.source == "coinswitch" and not (c and c.COINSWITCH_API_KEY):
            from scalpbot.brokers import AuthExpired
            raise AuthExpired("COINSWITCH keys not set")
        return _recent_frame(inst.name)

    monkeypatch.setattr(sc, "fetch_candles", fake)
    monkeypatch.setattr(pt, "fetch_candles", fake)
    import api.market as m
    monkeypatch.setattr(m, "fetch_candles", lambda inst, n=1000: _signal_frame(2999)[["open", "high", "low", "close", "volume"]])
    from api import core
    from api.main import app
    core.reset()
    yield TestClient(app)
    core.reset()


def signup(c, email, name="X"):
    return c.post("/api/auth/signup", json={"email": email, "name": name, "password": PW})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def boss(client):
    r = signup(client, "boss@example.com", "Boss")
    assert r.status_code == 200 and r.json()["status"] == "active"
    return auth(r.json()["token"])


def approved(client, boss, email="ann@example.com"):
    assert signup(client, email, "Ann").json()["status"] == "pending"
    uid = next(u["id"] for u in client.get("/api/admin/users", headers=boss).json()["users"] if u["email"] == email)
    client.post(f"/api/admin/users/{uid}", json={"action": "approve"}, headers=boss)
    r = client.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200
    return auth(r.json()["token"]), uid


# --------------------------------------------------------------------------- auth
def test_health_cors_and_anonymous(client):
    r = client.get("/api/health", headers={"Origin": "https://kdkapsikar.github.io"})
    assert r.json() == {"ok": True}
    assert r.headers["access-control-allow-origin"] == "https://kdkapsikar.github.io"
    assert client.get("/api/health", headers={"Origin": "https://evil.example"}).headers.get(
        "access-control-allow-origin") is None
    for path in ("/api/me", "/api/universe", "/api/admin/users"):
        r = client.get(path)
        assert r.status_code == 401 and r.json()["error"] == "Please sign in again."


def test_signup_pending_login_logout(client, boss):
    r = signup(client, "ann@example.com")
    assert r.json()["status"] == "pending" and "token" not in r.json()
    r = client.post("/api/auth/login", json={"email": "ann@example.com", "password": PW})
    assert r.status_code == 401 and "waiting for an admin" in r.json()["error"]
    r = client.post("/api/auth/login", json={"email": "boss@example.com", "password": "wrong password 1"})
    assert r.status_code == 401 and r.json()["error"] == "Wrong email or password."
    assert signup(client, "bad", "x").status_code == 400
    me = client.get("/api/me", headers=boss).json()
    assert me["user"]["is_admin"] and me["connections"]["coinswitch"] is False
    client.post("/api/auth/logout", headers=boss)
    assert client.get("/api/me", headers=boss).status_code == 401


def test_admin_actions_and_regular_users_are_kept_out(client, boss):
    ann, uid = approved(client, boss)
    assert client.get("/api/admin/users", headers=ann).status_code == 403
    r = client.post(f"/api/admin/users/{uid}", json={"action": "disable"}, headers=boss)
    assert [u["status"] for u in r.json()["users"] if u["id"] == uid] == ["disabled"]
    assert client.get("/api/me", headers=ann).status_code == 401           # sessions revoked
    me_id = client.get("/api/me", headers=boss).json()["user"]["id"]
    r = client.post(f"/api/admin/users/{me_id}", json={"action": "make_user"}, headers=boss)
    assert r.status_code == 400 and "your own account" in r.json()["error"]
    audit = client.get("/api/admin/audit", headers=boss).json()["audit"]
    assert any(a["action"] == "disable" for a in audit)


def test_password_change_signs_out_other_devices(client, boss):
    other = auth(client.post("/api/auth/login", json={"email": "boss@example.com", "password": PW}).json()["token"])
    r = client.post("/api/me/password", json={"old": PW, "new": "new battery 77"}, headers=boss)
    fresh = auth(r.json()["token"])
    assert client.get("/api/me", headers=other).status_code == 401
    assert client.get("/api/me", headers=fresh).status_code == 200


# --------------------------------------------------------------------------- keys and Upstox
def test_keys_are_per_user_and_never_the_servers(client, boss):
    ann, _ = approved(client, boss)
    r = client.put("/api/keys", json={"values": {"COINSWITCH_API_KEY": "CK", "COINSWITCH_SECRET_KEY": "00"}}, headers=ann)
    assert r.json()["saved"] == ["COINSWITCH_API_KEY", "COINSWITCH_SECRET_KEY"] and r.json()["connections"]["coinswitch"]
    assert client.get("/api/me", headers=boss).json()["connections"]["coinswitch"] is False
    assert client.put("/api/keys", json={"values": {"EVIL": "x"}}, headers=ann).status_code == 400
    # the boss has no keys: crypto must fail for them rather than use the server's environment keys
    t = client.post("/api/ticker", json={"name": "BTCUSDT"}, headers=boss).json()
    assert t["status"] == "ERROR" and "COINSWITCH" in t["error"]
    t = client.post("/api/ticker", json={"name": "BTCUSDT"}, headers=ann).json()
    assert t["status"] != "ERROR"
    r = client.delete("/api/keys?names=COINSWITCH_API_KEY", headers=ann)
    assert r.json()["connections"]["coinswitch"] is False


def test_upstox_login_round_trip(client, boss, monkeypatch):
    from scalpbot import portal_tools as pt
    client.put("/api/keys", json={"values": {"UPSTOX_API_KEY": "k", "UPSTOX_API_SECRET": "s",
                                             "UPSTOX_REDIRECT_URI": "https://x/upstox/callback"}}, headers=boss)
    url = client.post("/api/upstox/login-url", headers=boss).json()["url"]
    state = url.split("state=")[1]

    class R:
        ok = True
        def json(self): return {"access_token": "TOK"}

    monkeypatch.setattr(pt.requests, "post", lambda *a, **k: R())
    r = client.post("/api/upstox/callback", json={"code": "C", "state": state})       # no Authorization needed
    assert r.status_code == 200 and "Saved today's Upstox token" in r.json()["message"]
    assert client.get("/api/me", headers=boss).json()["connections"]["upstox"]["token"] is True
    assert client.post("/api/upstox/callback", json={"code": "C", "state": state}).status_code == 400   # single use
    assert client.post("/api/upstox/callback", json={"code": "C", "state": "forged"}).status_code == 400


# --------------------------------------------------------------------------- market
@pytest.fixture
def ready(client, boss):
    client.put("/api/keys", json={"values": {"UPSTOX_ACCESS_TOKEN": "t", "COINSWITCH_API_KEY": "k",
                                             "COINSWITCH_SECRET_KEY": "00", "OANDA_API_TOKEN": "o"}}, headers=boss)
    return boss


def _wait(client, headers, job):
    from api import jobs
    jobs.wait(job["id"])
    return client.get(f"/api/jobs/{job['id']}", headers=headers).json()


def test_universe_scan_and_ticker(client, ready):
    u = client.get("/api/universe", headers=ready).json()
    assert {"Index futures", "Stock futures", "MCX futures", "Crypto", "Forex & metals"} <= set(u["groups"])
    assert len(u["instruments"]) == 11                      # the test data's MCX file only has GOLDM
    assert "XAUUSD (spot)" in [i["name"] for i in u["instruments"]]
    assert "No MCX future found for: GOLD, SILVER" in " ".join(u["warnings"])
    job = client.post("/api/scan", json={"groups": ["Index futures", "Crypto"], "include_closed": True},
                      headers=ready).json()
    assert job["status"] in ("running", "done")
    done = _wait(client, ready, job)
    assert done["status"] == "done" and done["total"] == 6
    c = done["result"]["counts"]
    assert c["scanned"] == 6 and c["errors"] == 0
    t = client.post("/api/ticker", json={"name": "NIFTY FUT", "rules": {"require_rsi": False}}, headers=ready).json()
    assert t["status"] in ("LONG", "SHORT", "BLOCKED", "NONE") and t["headline"]
    assert set(t["checks"]) == {"LONG", "SHORT"} and len(t["checks"]["LONG"]) == 5
    assert len(t["chart"]["candles"]) == 150 and t["chart"]["dema"] and t["chart"]["pivots"]
    assert all(None not in (c["open"], c["high"], c["low"], c["close"]) for c in t["chart"]["candles"])
    times = [c["time"] for c in t["chart"]["candles"]]
    assert times == sorted(set(times)) and all(b - a == 300 for a, b in zip(times, times[1:]))   # 5-minute steps
    assert abs(times[-1] - pd.Timestamp(t["last_candle"]).timestamp()) < 1
    assert client.post("/api/ticker", json={"name": "NOPE"}, headers=ready).status_code == 404
    assert client.get(f"/api/jobs/{job['id']}", headers=ready).status_code == 200


def test_mood_backtest_connections_and_assistant(client, ready):
    m = _wait(client, ready, client.post("/api/mood?scope=quick", headers=ready).json())
    assert set(m["result"]["moods"]) == {"India", "MCX", "Crypto", "Forex & metals"} and m["result"]["readings"]
    assert all(v["label"] for v in m["result"]["moods"].values())
    b = client.post("/api/backtest", json={"name": "NIFTY FUT"}, headers=ready).json()
    assert [r["mode"] for r in b["results"]] == ["off", "fast", "both"] and b["candles"] > 400
    t = _wait(client, ready, client.post("/api/connections/test", headers=ready).json())
    assert t["result"]["rows"] and all(r["Status"].startswith("OK") for r in t["result"]["rows"])
    for text, kind in (("how is the market", "mood"), ("signals", "signals"), ("nifty", "ticker"),
                       ("what is rsi", "explain"), ("is my upstox connected", "connections"), ("qwerty", "unknown")):
        r = client.post("/api/assistant", json={"text": text}, headers=ready).json()
        assert r["kind"] == kind and r["messages"], text
    r = client.post("/api/assistant", json={"kind": "mood"}, headers=ready).json()
    assert r["mood"] is not None and r["messages"][0]["who"] in ("bull", "bear")


def test_api_home_forwards_to_the_web_app(client, monkeypatch):
    monkeypatch.setenv("APP_URL", "https://kdkapsikar.github.io/scalper5-bot")
    r = client.get("/", follow_redirects=False)
    if r.status_code == 200:
        pytest.skip("web/dist is built here, so the API serves the app itself")
    assert r.status_code == 302 and r.headers["location"] == "https://kdkapsikar.github.io/scalper5-bot"
    r = client.get("/?code=AB&state=XY&evil=1", follow_redirects=False)
    assert r.headers["location"] == "https://kdkapsikar.github.io/scalper5-bot/upstox/callback?code=AB&state=XY"


def test_oanda_instruments_only_for_people_who_connected_oanda(client, boss):
    names = lambda: [i["name"] for i in client.get("/api/universe", headers=boss).json()["instruments"]]
    assert "XAUUSD (OANDA)" not in names() and "XAUUSDT" in names()
    r = client.put("/api/keys", json={"values": {"OANDA_API_TOKEN": "tok", "OANDA_ENV": "live"}}, headers=boss)
    assert r.json()["connections"]["oanda"] == {"token": True, "env": "live"}
    assert "XAUUSD (OANDA)" in names()
    a = client.post("/api/assistant", json={"text": "oanda gold"}, headers=boss).json()
    assert a["kind"] == "ticker" and "XAUUSD (OANDA)" in a["messages"][0]["text"]
