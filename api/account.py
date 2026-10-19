"""Account endpoints: sign-up / sign-in, my profile and broker keys, the Upstox login round trip, and admin."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from scalpbot import portal_tools as pt
from scalpbot.accounts import AccountError, User
from scalpbot.brokers import clear_candle_caches
from scalpbot.creds import FIELDS

from .core import (accounts, admin_user, current_user, forget_session, forget_user, hosted, keys_changed, use_keys,
                   upstox_redirect_default, user_creds, user_json, _token)

router = APIRouter(prefix="/api")


def _fail(e: AccountError, code: int = 400):
    raise HTTPException(code, str(e))


# --------------------------------------------------------------------------- sign up / in / out
class SignUpIn(BaseModel):
    name: str = Field("", max_length=120)
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class SignInIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


@router.post("/auth/signup")
def signup(body: SignUpIn):
    acc = accounts()
    try:
        user = acc.sign_up(body.email, body.name, body.password)
    except AccountError as e:
        _fail(e)
    if user.status != "active":
        return {"status": "pending", "message": "Account created. An admin will review it; you can sign in once it "
                                                "is approved."}
    acc.log("login", user.email, "", "signed up as admin")
    return {"status": "active", "token": acc.create_session(user.id), "user": user_json(user)}


@router.post("/auth/login")
def login(body: SignInIn):
    acc = accounts()
    try:
        user = acc.authenticate(body.email, body.password)
    except AccountError as e:
        _fail(e, 401)
    return {"token": acc.create_session(user.id), "user": user_json(user)}


@router.post("/auth/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    token = _token(authorization)
    if token:
        accounts().revoke_session(token)
        forget_session(token)
    return {"ok": True}


# --------------------------------------------------------------------------- me
def _connections(user: User) -> dict:
    c = user_creds(user)
    saved = accounts().key_saved_at(user.id)
    t = saved.get("UPSTOX_ACCESS_TOKEN")
    age = (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600 if t and c.UPSTOX_ACCESS_TOKEN else None
    return {
        "upstox": {"token": bool(c.UPSTOX_ACCESS_TOKEN), "token_age_h": None if age is None else round(age, 1),
                   "app_saved": bool(c.UPSTOX_API_KEY and c.UPSTOX_API_SECRET), "redirect_uri": c.UPSTOX_REDIRECT_URI},
        "coinswitch": bool(c.COINSWITCH_API_KEY and c.COINSWITCH_SECRET_KEY),
        "saved": {k: v.isoformat() for k, v in saved.items()},
    }


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"user": user_json(user), "connections": _connections(user), "hosted": hosted(),
            "upstox_redirect_default": upstox_redirect_default()}


class PasswordIn(BaseModel):
    old: str = Field(max_length=200)
    new: str = Field(max_length=200)


@router.post("/me/password")
def change_password(body: PasswordIn, user: User = Depends(current_user)):
    acc = accounts()
    try:
        acc.change_password(user.id, body.old, body.new)        # signs out every device...
    except AccountError as e:
        _fail(e)
    forget_user(user.id)
    return {"token": acc.create_session(user.id)}               # ...and gives this one a fresh session


# --------------------------------------------------------------------------- broker keys
class KeysIn(BaseModel):
    values: dict[str, str]


@router.put("/keys")
def save_keys(body: KeysIn, user: User = Depends(current_user)):
    unknown = set(body.values) - set(FIELDS)
    if unknown:
        raise HTTPException(400, f"Unknown key names: {', '.join(sorted(unknown))}")
    saved = accounts().save_keys(user.id, body.values)
    keys_changed(user.id)
    clear_candle_caches()
    return {"saved": saved, "connections": _connections(user)}


@router.delete("/keys")
def remove_keys(names: str, user: User = Depends(current_user)):
    wanted = [n for n in names.split(",") if n in FIELDS]
    accounts().remove_keys(user.id, wanted)
    keys_changed(user.id)
    return {"removed": wanted, "connections": _connections(user)}


# --------------------------------------------------------------------------- Upstox daily login
@router.post("/upstox/login-url")
def upstox_login_url(user: User = Depends(current_user)):
    c = user_creds(user)
    try:
        url = pt.upstox_login_url(c.UPSTOX_API_KEY, c.UPSTOX_REDIRECT_URI, accounts().new_login_state(user.id))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"url": url}


class CallbackIn(BaseModel):
    code: str = Field(max_length=2000)
    state: str = Field("", max_length=200)


def _save_upstox_token(user: User, code: str) -> dict:
    c = user_creds(user)
    try:
        token = pt.upstox_get_token(code, c.UPSTOX_API_KEY, c.UPSTOX_API_SECRET, c.UPSTOX_REDIRECT_URI)
    except Exception as e:
        raise HTTPException(400, str(e))
    acc = accounts()
    acc.save_keys(user.id, {"UPSTOX_ACCESS_TOKEN": token})
    acc.log("upstox_login", user.email)
    keys_changed(user.id)
    clear_candle_caches()
    return {"message": pt.saved_message()}


@router.post("/upstox/callback")
def upstox_callback(body: CallbackIn):
    """Upstox redirects to the web app with ?code&state; the state names the user who started the login."""
    owner = accounts().consume_login_state(body.state)
    if owner is None:
        raise HTTPException(400, "That Upstox login link has expired or was already used. Start the login again "
                                 "from the Connect page.")
    return _save_upstox_token(owner, body.code)


@router.post("/upstox/code")
def upstox_code(body: CallbackIn, user: User = Depends(current_user)):
    """The pasted code or redirect address, when the redirect did not come back to the app."""
    return _save_upstox_token(user, body.code)


# --------------------------------------------------------------------------- admin
@router.get("/admin/users")
def admin_users(admin: User = Depends(admin_user)):
    return {"users": [user_json(u) for u in accounts().list_users()]}


class ActionIn(BaseModel):
    action: str = Field(pattern="^(approve|disable|enable|make_admin|make_user|delete)$")


@router.post("/admin/users/{user_id}")
def admin_action(user_id: int, body: ActionIn, admin: User = Depends(admin_user)):
    acc = accounts()
    fn = {"approve": acc.approve, "disable": acc.disable, "enable": acc.enable,
          "make_admin": lambda a, uid: acc.set_role(a, uid, "admin"),
          "make_user": lambda a, uid: acc.set_role(a, uid, "user"), "delete": acc.delete_user}[body.action]
    try:
        fn(admin, user_id)
    except AccountError as e:
        _fail(e)
    forget_user(user_id)
    return {"users": [user_json(u) for u in acc.list_users()]}


@router.get("/admin/audit")
def admin_audit(limit: int = 500, admin: User = Depends(admin_user)):
    rows = accounts().audit_log(min(max(limit, 1), 2000))
    for r in rows:
        r["time"] = r["time"].isoformat()
    return {"audit": rows}


# --------------------------------------------------------------------------- Bull & Bear
class AskIn(BaseModel):
    text: str = Field("", max_length=500)
    kind: str = Field("", max_length=20)


@router.post("/assistant")
def assistant(body: AskIn, user: User = Depends(current_user)):
    from scalpbot import assistant as A
    from scalpbot import scan as sc
    from scalpbot.mood import all_moods

    from .core import universe
    from .market import QUICK_GROUPS, measure

    c = use_keys(user)
    names = [i.name for i in universe()[0]]
    kind, arg = (body.kind, None) if body.kind else A.intent(body.text, names)
    mood = None
    if kind == "help":
        msgs = A.reply_help((user.name or "").split(" ")[0])
    elif kind == "mood":
        moods = all_moods(measure(user, QUICK_GROUPS))
        msgs = A.reply_mood(moods)
        scores = [m.score for m in moods.values() if m.score is not None]
        mood = sum(scores) / len(scores) if scores else None
    elif kind == "signals":
        results = measure(user, QUICK_GROUPS)
        live = [r for r in results if not r.stale]
        if results and not live:
            closed = sum(1 for r in results if not sc.always_open(r))
            delayed = len(results) - closed
            why = " and ".join(x for x in ("Indian futures are closed" if closed else "",
                                            "the broker's crypto candles are running late" if delayed else "") if x)
            msgs = [A.Msg(A.BEAR, f"Nothing live to flag: {why}. 🐻")]
        else:
            msgs = A.reply_signals(live, 3, "index futures and crypto") + [
                A.Msg(A.BULL, "For every F&O stock future, run **Scan all** on the Scanner page. 🐂")]
    elif kind == "ticker":
        if arg is None:
            msgs = [A.Msg(A.BULL, "Which one? Type a name like *nifty*, *banknifty*, *reliance*, *btc* or *gold*. 🐂")]
        else:
            inst = next(i for i in universe()[0] if i.name == arg)
            msgs = A.reply_ticker(sc.run_one(inst, {}, 3, ignore_stale=True)[0], 3)
    elif kind == "explain":
        msgs = A.reply_explain(arg)
    elif kind == "connections":
        con = _connections(user)
        msgs = A.reply_connections(con["upstox"]["token"], con["upstox"]["token_age_h"], con["coinswitch"])
    else:
        msgs = A.reply_unknown()
    return {"messages": [{"who": m.who, "text": m.text} for m in msgs], "mood": mood, "kind": kind}
