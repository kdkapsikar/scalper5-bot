"""Portal accounts: users and roles, each user's encrypted broker keys, and an audit log.

Storage is any SQLAlchemy URL in DATABASE_URL. Locally it defaults to SQLite in .state/portal.db; on Streamlit
Community Cloud (no lasting disk) point it at a hosted Postgres such as Neon or Supabase.

Security model
  - Passwords: scrypt with a per-user random salt; never stored or logged in clear.
  - Broker keys: Fernet-encrypted with SCALP_MASTER_KEY (kept in the host's secrets, never in the database or git).
    Whoever holds both the database and the master key (the portal operator) can decrypt them; users are told so.
  - Sign-ups start as "pending" until an admin approves them. Emails listed in ADMIN_EMAILS become admins on sign-up
    (on a local SQLite install without ADMIN_EMAILS, the first account becomes the admin).
  - Five wrong passwords lock the account for 15 minutes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import (Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text, create_engine,
                        delete, func, insert, select, update)
from sqlalchemy.engine import Engine

from .creds import FIELDS, Creds

ROLES = ("user", "admin")
STATUSES = ("pending", "active", "disabled")
MIN_PASSWORD = 10
MAX_FAILED = 5
LOCK_MINUTES = 15
STATE_TTL_MIN = 15          # Upstox login "state" values expire after this long
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

meta = MetaData()
users = Table(
    "users", meta,
    Column("id", Integer, primary_key=True),
    Column("email", String(254), unique=True, nullable=False),
    Column("name", String(120), nullable=False, default=""),
    Column("password_hash", String(400), nullable=False),
    Column("role", String(10), nullable=False, default="user"),
    Column("status", String(10), nullable=False, default="pending"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_login_at", DateTime(timezone=True)),
    Column("failed_logins", Integer, nullable=False, default=0),
    Column("locked_until", DateTime(timezone=True)),
)
credentials = Table(
    "credentials", meta,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("name", String(40), primary_key=True),
    Column("value", Text, nullable=False),            # Fernet token
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
login_states = Table(
    "login_states", meta,
    Column("state", String(64), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
audit = Table(
    "audit", meta,
    Column("id", Integer, primary_key=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("actor", String(254), nullable=False, default=""),
    Column("action", String(40), nullable=False),
    Column("target", String(254), nullable=False, default=""),
    Column("detail", String(400), nullable=False, default=""),
)


class AccountError(ValueError):
    """A readable problem to show the person (wrong password, pending account, ...)."""


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    role: str
    status: str
    created_at: dt.datetime
    last_login_at: dt.datetime | None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(t: dt.datetime | None) -> dt.datetime | None:
    """SQLite hands back naive datetimes; everything here is stored in UTC."""
    if t is None:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _user(row) -> User:
    return User(id=row.id, email=row.email, name=row.name, role=row.role, status=row.status,
                created_at=_aware(row.created_at), last_login_at=_aware(row.last_login_at))


# --------------------------------------------------------------------------- passwords + encryption
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(h) // 2)
        return hmac.compare_digest(got.hex(), h)
    except (ValueError, TypeError):
        return False


def check_password_rules(pw: str) -> None:
    if len(pw) < MIN_PASSWORD:
        raise AccountError(f"Use at least {MIN_PASSWORD} characters for the password.")
    if pw.isdigit() or pw.isalpha():
        raise AccountError("Mix letters with numbers or symbols in the password.")


def generate_master_key() -> str:
    return Fernet.generate_key().decode()


# --------------------------------------------------------------------------- store
class Accounts:
    def __init__(self, url: str | None = None, master_key: str | None = None, admin_emails: str | None = None,
                 state_dir: str | None = None):
        state = Path(state_dir or os.getenv("SCALP_STATE_DIR", ".state"))
        url = url or os.getenv("DATABASE_URL", "").strip()
        if not url:
            state.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{state / 'portal.db'}"
        if url.startswith("postgres://"):           # Heroku/Neon style URLs; SQLAlchemy wants the driver named
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        self.is_sqlite = url.startswith("sqlite")
        self.engine: Engine = create_engine(url, pool_pre_ping=True, future=True)
        meta.create_all(self.engine)
        self._fernet = Fernet(self._master_key(master_key, state).encode())
        raw = admin_emails if admin_emails is not None else os.getenv("ADMIN_EMAILS", "")
        self.admin_emails = {e.strip().lower() for e in raw.split(",") if e.strip()}

    def _master_key(self, given: str | None, state: Path) -> str:
        key = (given or os.getenv("SCALP_MASTER_KEY", "")).strip()
        if key:
            return key
        if not self.is_sqlite:
            raise RuntimeError("SCALP_MASTER_KEY is not set. Add it to the app's secrets "
                               "(generate one with: python -m scalpbot.accounts --new-master-key).")
        f = state / "master.key"                    # local single-machine use: create one next to the database
        if not f.exists():
            f.write_text(generate_master_key())
            f.chmod(0o600)
        return f.read_text().strip()

    # ----------------------------------------------------------------------- audit
    def log(self, action: str, actor: str = "", target: str = "", detail: str = "") -> None:
        with self.engine.begin() as c:
            c.execute(insert(audit).values(ts=_now(), actor=actor or "", action=action, target=target or "",
                                           detail=(detail or "")[:400]))

    def audit_log(self, limit: int = 500) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(audit).order_by(audit.c.id.desc()).limit(limit)).all()
        return [{"time": _aware(r.ts), "who": r.actor, "action": r.action, "target": r.target, "detail": r.detail}
                for r in rows]

    # ----------------------------------------------------------------------- users
    def _row(self, c, *, email: str | None = None, user_id: int | None = None):
        q = select(users).where(users.c.email == email.strip().lower()) if email is not None \
            else select(users).where(users.c.id == user_id)
        return c.execute(q).first()

    def get(self, user_id: int) -> User | None:
        with self.engine.connect() as c:
            row = self._row(c, user_id=user_id)
        return _user(row) if row else None

    def list_users(self) -> list[User]:
        with self.engine.connect() as c:
            return [_user(r) for r in c.execute(select(users).order_by(users.c.created_at)).all()]

    def count_admins(self) -> int:
        with self.engine.connect() as c:
            return c.execute(select(func.count()).select_from(users)
                             .where(users.c.role == "admin", users.c.status == "active")).scalar_one()

    def sign_up(self, email: str, name: str, password: str) -> User:
        email = (email or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise AccountError("Enter a valid email address.")
        check_password_rules(password)
        # Local single-machine install without ADMIN_EMAILS: the first account becomes the admin. On a shared server
        # ADMIN_EMAILS is required, so nobody can claim admin by signing up first.
        is_admin = email in self.admin_emails or (not self.admin_emails and self.is_sqlite and self.count_admins() == 0)
        with self.engine.begin() as c:
            if self._row(c, email=email):
                raise AccountError("An account with this email already exists. Sign in instead.")
            uid = c.execute(insert(users).values(
                email=email, name=(name or "").strip()[:120], password_hash=hash_password(password),
                role="admin" if is_admin else "user", status="active" if is_admin else "pending",
                created_at=_now(), failed_logins=0)).inserted_primary_key[0]
        self.log("sign_up", email, email, "admin from ADMIN_EMAILS" if is_admin else "awaiting approval")
        return self.get(uid)

    def authenticate(self, email: str, password: str) -> User:
        email = (email or "").strip().lower()
        wrong = "Wrong email or password."
        outcome, detail = "ok", ""
        with self.engine.begin() as c:          # decide and record inside one transaction; log + raise after commit
            row = self._row(c, email=email)
            locked = _aware(row.locked_until) if row else None
            if not row:
                hash_password(password)         # same work as a real check, so timing does not reveal emails
                outcome, detail = "login_failed", "unknown email"
            elif locked and locked > _now():
                mins = int((locked - _now()).total_seconds() // 60) + 1
                outcome, detail = "locked", f"Too many wrong passwords. Try again in {mins} minute{'s' if mins != 1 else ''}."
            elif not verify_password(password, row.password_hash):
                n = row.failed_logins + 1
                vals = {"failed_logins": n}
                if n >= MAX_FAILED:
                    vals = {"failed_logins": 0, "locked_until": _now() + dt.timedelta(minutes=LOCK_MINUTES)}
                c.execute(update(users).where(users.c.id == row.id).values(**vals))
                outcome, detail = ("login_locked" if n >= MAX_FAILED else "login_failed"), f"attempt {n}"
            elif row.status == "pending":
                outcome = "pending"
            elif row.status == "disabled":
                outcome = "disabled"
            else:
                c.execute(update(users).where(users.c.id == row.id)
                          .values(failed_logins=0, locked_until=None, last_login_at=_now()))
        if outcome in ("login_failed", "login_locked"):
            self.log(outcome, email, email, detail)
            raise AccountError(wrong)
        if outcome == "locked":
            raise AccountError(detail)
        if outcome == "pending":
            raise AccountError("Your account is waiting for an admin to approve it.")
        if outcome == "disabled":
            raise AccountError("This account has been disabled. Contact the portal admin.")
        self.log("login", email)
        return self.get(row.id)

    def change_password(self, user_id: int, old: str, new: str) -> None:
        with self.engine.begin() as c:
            row = self._row(c, user_id=user_id)
            if not row or not verify_password(old, row.password_hash):
                raise AccountError("Your current password is not correct.")
            check_password_rules(new)
            c.execute(update(users).where(users.c.id == user_id).values(password_hash=hash_password(new)))
        self.log("password_changed", row.email, row.email)

    # ----------------------------------------------------------------------- admin actions
    def _admin_change(self, admin: User, user_id: int, action: str, **vals) -> User:
        if not admin.is_admin:
            raise AccountError("Only admins can do that.")
        target = self.get(user_id)
        if not target:
            raise AccountError("No such user.")
        if target.id == admin.id and (vals.get("status", "active") != "active" or vals.get("role", "admin") != "admin"):
            raise AccountError("You can't disable or demote your own account.")
        with self.engine.begin() as c:
            c.execute(update(users).where(users.c.id == user_id).values(**vals))
        self.log(action, admin.email, target.email, ", ".join(f"{k}={v}" for k, v in vals.items()))
        return self.get(user_id)

    def approve(self, admin: User, user_id: int) -> User:
        return self._admin_change(admin, user_id, "approve", status="active")

    def disable(self, admin: User, user_id: int) -> User:
        return self._admin_change(admin, user_id, "disable", status="disabled")

    def enable(self, admin: User, user_id: int) -> User:
        return self._admin_change(admin, user_id, "enable", status="active", failed_logins=0, locked_until=None)

    def set_role(self, admin: User, user_id: int, role: str) -> User:
        if role not in ROLES:
            raise AccountError(f"Role must be one of {ROLES}.")
        return self._admin_change(admin, user_id, "role_change", role=role)

    def delete_user(self, admin: User, user_id: int) -> None:
        if not admin.is_admin:
            raise AccountError("Only admins can do that.")
        target = self.get(user_id)
        if not target:
            raise AccountError("No such user.")
        if target.id == admin.id:
            raise AccountError("You can't delete your own account.")
        with self.engine.begin() as c:
            c.execute(delete(credentials).where(credentials.c.user_id == user_id))
            c.execute(delete(login_states).where(login_states.c.user_id == user_id))
            c.execute(delete(users).where(users.c.id == user_id))
        self.log("delete_user", admin.email, target.email, "account and saved keys deleted")

    # ----------------------------------------------------------------------- broker keys
    def save_keys(self, user_id: int, values: dict[str, str]) -> list[str]:
        """Encrypt and store non-empty values. Returns the names saved (never the values)."""
        values = {k: v.strip() for k, v in values.items() if k in FIELDS and v is not None and v.strip()}
        if not values:
            return []
        now = _now()
        with self.engine.begin() as c:
            for k, v in values.items():
                c.execute(delete(credentials).where(credentials.c.user_id == user_id, credentials.c.name == k))
                c.execute(insert(credentials).values(user_id=user_id, name=k, updated_at=now,
                                                     value=self._fernet.encrypt(v.encode()).decode()))
        u = self.get(user_id)
        self.log("keys_saved", u.email if u else str(user_id), "", ", ".join(sorted(values)))
        return sorted(values)

    def remove_keys(self, user_id: int, names: list[str]) -> None:
        with self.engine.begin() as c:
            c.execute(delete(credentials).where(credentials.c.user_id == user_id, credentials.c.name.in_(names)))
        u = self.get(user_id)
        self.log("keys_removed", u.email if u else str(user_id), "", ", ".join(sorted(names)))

    def load_creds(self, user_id: int) -> Creds:
        out = {}
        with self.engine.connect() as c:
            for r in c.execute(select(credentials).where(credentials.c.user_id == user_id)).all():
                try:
                    out[r.name] = self._fernet.decrypt(r.value.encode()).decode()
                except InvalidToken:                # master key changed: treat as not saved
                    continue
        return Creds.from_dict(out)

    def key_saved_at(self, user_id: int) -> dict[str, dt.datetime]:
        with self.engine.connect() as c:
            rows = c.execute(select(credentials.c.name, credentials.c.updated_at)
                             .where(credentials.c.user_id == user_id)).all()
        return {r.name: _aware(r.updated_at) for r in rows}

    # ----------------------------------------------------------------------- Upstox login round trip
    def new_login_state(self, user_id: int) -> str:
        """A one-time value sent through the Upstox login, so the redirect knows whose token it is."""
        s = secrets.token_urlsafe(32)
        with self.engine.begin() as c:
            c.execute(delete(login_states).where(login_states.c.created_at < _now() - dt.timedelta(minutes=STATE_TTL_MIN)))
            c.execute(insert(login_states).values(state=s, user_id=user_id, created_at=_now()))
        return s

    def consume_login_state(self, state: str) -> User | None:
        if not state:
            return None
        with self.engine.begin() as c:
            row = c.execute(select(login_states).where(login_states.c.state == state)).first()
            if not row:
                return None
            c.execute(delete(login_states).where(login_states.c.state == state))
        if _aware(row.created_at) < _now() - dt.timedelta(minutes=STATE_TTL_MIN):
            return None
        u = self.get(row.user_id)
        return u if u and u.status == "active" else None


if __name__ == "__main__":
    import sys
    if "--new-master-key" in sys.argv:
        print(generate_master_key())
    else:
        print("usage: python -m scalpbot.accounts --new-master-key")
