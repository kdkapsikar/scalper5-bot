"""Accounts store, per-user credentials and the Bull / Bear mood score."""
import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import update

from scalpbot import brokers, creds
from scalpbot.accounts import AccountError, Accounts, generate_master_key, hash_password, login_states, users, \
    verify_password
from scalpbot.mood import label_for, market_mood
from scalpbot.scan import Result


@pytest.fixture
def acc(tmp_path):
    return Accounts(url=f"sqlite:///{tmp_path / 'a.db'}", master_key=generate_master_key(),
                    admin_emails="boss@example.com", state_dir=str(tmp_path))


def test_password_hashing():
    h = hash_password("correct horse 9")
    assert h.startswith("scrypt$") and "correct" not in h
    assert verify_password("correct horse 9", h) and not verify_password("wrong", h)
    assert hash_password("correct horse 9") != h          # salted
    assert not verify_password("x", "garbage")


def test_sign_up_rules(acc):
    with pytest.raises(AccountError, match="valid email"):
        acc.sign_up("nope", "N", "correct horse 9")
    with pytest.raises(AccountError, match="at least"):
        acc.sign_up("a@b.co", "A", "short1")
    with pytest.raises(AccountError, match="Mix"):
        acc.sign_up("a@b.co", "A", "onlyletterslong")
    u = acc.sign_up(" A@B.co ", "A", "correct horse 9")
    assert (u.email, u.role, u.status) == ("a@b.co", "user", "pending")
    with pytest.raises(AccountError, match="already exists"):
        acc.sign_up("a@b.co", "A", "correct horse 9")
    boss = acc.sign_up("boss@example.com", "B", "correct horse 9")
    assert (boss.role, boss.status) == ("admin", "active")


def test_login_lockout_after_five_wrong_passwords(acc):
    boss = acc.sign_up("boss@example.com", "B", "correct horse 9")
    for _ in range(5):
        with pytest.raises(AccountError, match="Wrong email or password"):
            acc.authenticate("boss@example.com", "bad password 1")
    with pytest.raises(AccountError, match="Too many wrong passwords"):
        acc.authenticate("boss@example.com", "correct horse 9")    # even the right one, while locked
    with acc.engine.begin() as c:
        c.execute(update(users).values(locked_until=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)))
    assert acc.authenticate("boss@example.com", "correct horse 9").id == boss.id
    actions = [r["action"] for r in acc.audit_log()]
    assert "login_locked" in actions and actions.count("login_failed") == 4 and actions[0] == "login"
    with pytest.raises(AccountError, match="Wrong email or password"):
        acc.authenticate("nobody@example.com", "x")          # same message: does not reveal which emails exist


def test_admin_actions_and_guards(acc):
    boss = acc.sign_up("boss@example.com", "B", "correct horse 9")
    ann = acc.sign_up("ann@example.com", "A", "correct horse 9")
    with pytest.raises(AccountError, match="waiting"):
        acc.authenticate("ann@example.com", "correct horse 9")
    with pytest.raises(AccountError, match="Only admins"):
        acc.approve(ann, ann.id)
    acc.approve(boss, ann.id)
    assert acc.authenticate("ann@example.com", "correct horse 9").status == "active"
    with pytest.raises(AccountError, match="own account"):
        acc.set_role(boss, boss.id, "user")
    with pytest.raises(AccountError, match="own account"):
        acc.disable(boss, boss.id)
    acc.disable(boss, ann.id)
    with pytest.raises(AccountError, match="disabled"):
        acc.authenticate("ann@example.com", "correct horse 9")
    acc.enable(boss, ann.id)
    acc.set_role(boss, ann.id, "admin")
    assert acc.get(ann.id).is_admin and acc.count_admins() == 2
    acc.save_keys(ann.id, {"COINSWITCH_API_KEY": "X"})
    acc.delete_user(boss, ann.id)
    assert acc.get(ann.id) is None and acc.load_creds(ann.id) == creds.Creds()


def test_keys_are_encrypted_and_need_the_master_key(acc, tmp_path):
    u = acc.sign_up("boss@example.com", "B", "correct horse 9")
    assert acc.save_keys(u.id, {"COINSWITCH_API_KEY": " CK ", "COINSWITCH_SECRET_KEY": "", "NOT_A_KEY": "x"}) == \
        ["COINSWITCH_API_KEY"]
    assert acc.load_creds(u.id).COINSWITCH_API_KEY == "CK"
    acc.save_keys(u.id, {"COINSWITCH_API_KEY": "CK2"})       # overwrite
    assert acc.load_creds(u.id).COINSWITCH_API_KEY == "CK2"
    other = Accounts(url=f"sqlite:///{tmp_path / 'a.db'}", master_key=generate_master_key(), state_dir=str(tmp_path))
    assert other.load_creds(u.id).COINSWITCH_API_KEY == ""   # wrong master key: unreadable, treated as not saved
    assert not any("CK2" in r["detail"] for r in acc.audit_log())


def test_remote_database_requires_a_master_key(monkeypatch, tmp_path):
    monkeypatch.delenv("SCALP_MASTER_KEY", raising=False)
    a = Accounts(url=f"sqlite:///{tmp_path / 'b.db'}", state_dir=str(tmp_path))   # local: key file is created
    assert (tmp_path / "master.key").exists() and a.is_sqlite
    with pytest.raises(RuntimeError, match="SCALP_MASTER_KEY"):
        Accounts._master_key(type("X", (), {"is_sqlite": False})(), None, tmp_path)


def test_login_state_is_single_use_and_expires(acc):
    u = acc.sign_up("boss@example.com", "B", "correct horse 9")
    s = acc.new_login_state(u.id)
    assert acc.consume_login_state(s).id == u.id
    assert acc.consume_login_state(s) is None
    s2 = acc.new_login_state(u.id)
    with acc.engine.begin() as c:
        c.execute(update(login_states).values(created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)))
    assert acc.consume_login_state(s2) is None
    assert acc.consume_login_state("") is None


# --------------------------------------------------------------------------- whose keys the brokers use
def test_active_creds_win_over_env_and_follow_worker_threads(monkeypatch):
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "ENV")
    monkeypatch.setenv("UPSTOX_TOKEN_FILE", "/nonexistent/token")
    assert brokers.upstox_token() == "ENV"                   # CLI: environment

    def in_thread(tok):
        creds.activate(creds.Creds(UPSTOX_ACCESS_TOKEN=tok))
        with ThreadPoolExecutor(4) as ex:
            return [f.result() for f in [creds.submit(ex, brokers.upstox_token) for _ in range(8)]]

    out = {}
    ts = [threading.Thread(target=lambda t=t: out.setdefault(t, in_thread(t))) for t in ("ANN", "BOB")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert out == {"ANN": ["ANN"] * 8, "BOB": ["BOB"] * 8}   # no mixing between users
    creds.activate(creds.Creds())
    try:
        assert brokers.upstox_token() == ""                  # portal user with no token: no env fallback
        with pytest.raises(brokers.AuthExpired):
            brokers._cs_headers("GET", "/x")
    finally:
        creds.activate(None)


def test_strict_mode_never_falls_back_to_server_env(monkeypatch):
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "ENV")
    monkeypatch.setenv("UPSTOX_TOKEN_FILE", "/nonexistent/token")
    monkeypatch.setenv("COINSWITCH_API_KEY", "ENVKEY")
    monkeypatch.setenv("COINSWITCH_SECRET_KEY", "00" * 32)
    creds.activate(None)
    creds.strict()                                           # what the portal does at start-up
    assert brokers.upstox_token() == ""                      # e.g. a dialog rerun that forgot to activate a user
    with pytest.raises(brokers.AuthExpired):
        brokers._cs_headers("GET", "/x")


# --------------------------------------------------------------------------- mood
def _r(name, group, up, rsi=55.0, status="NONE", stale=False):
    return Result(name=name, group=group, status=status, above_dema=up, st_up=up, sma_up=up, rsi=rsi, stale=stale)


def test_mood_bull_bear_neutral():
    bull = [_r("NIFTY FUT", "Index futures", True, 75)] + [_r(f"S{i}", "Stock futures", True, 72) for i in range(12)]
    m = market_mood(bull, "India")
    assert m.label == "Strong Bull" and m.icon == "🐂" and m.score == 100 and m.n == 13
    bear = [_r("BTCUSDT", "Crypto", False, 35), _r("ETHUSDT", "Crypto", False, 38, status="SHORT")]
    m = market_mood(bear, "Crypto")
    assert m.side == "bear" and m.label == "Strong Bear" and m.icon == "🐻"
    mixed = [_r("BTCUSDT", "Crypto", True, 50), _r("ETHUSDT", "Crypto", False, 50)]
    m = market_mood(mixed, "Crypto")
    assert m.side == "neutral" or m.side == "bull"           # leader up, breadth even
    assert any("BTCUSDT" in f for f in m.facts)


def test_mood_ignores_errors_and_other_markets_and_flags_closed():
    rs = [_r("BTCUSDT", "Crypto", True, stale=True), Result(name="ETHUSDT", group="Crypto", status="ERROR", error="x"),
          _r("NIFTY FUT", "Index futures", False)]
    m = market_mood(rs, "Crypto")
    assert m.n == 1 and m.errors == 1 and m.stale == 1 and any("delayed data" in f for f in m.facts)
    india = market_mood([_r("NIFTY FUT", "Index futures", True, stale=True)], "India")
    assert any("look closed" in f for f in india.facts)
    empty = market_mood([Result(name="ETHUSDT", group="Crypto", status="ERROR")], "Crypto")
    assert empty.score is None and empty.label == "No data"


def test_label_thresholds():
    assert [label_for(s)[0] for s in (100, 40, 15, 14.9, 0, -14.9, -15, -40, -100)] == \
        ["Strong Bull", "Strong Bull", "Bull", "Neutral", "Neutral", "Neutral", "Bear", "Strong Bear", "Strong Bear"]


def test_first_local_account_is_admin_only_without_admin_emails(tmp_path):
    a = Accounts(url=f"sqlite:///{tmp_path / 'c.db'}", master_key=generate_master_key(), admin_emails="",
                 state_dir=str(tmp_path))
    first, second = a.sign_up("me@x.io", "Me", "correct horse 9"), a.sign_up("you@x.io", "You", "correct horse 9")
    assert (first.role, first.status) == ("admin", "active") and (second.role, second.status) == ("user", "pending")
