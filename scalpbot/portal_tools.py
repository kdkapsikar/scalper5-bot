"""Helpers behind the web portal: saving keys, the Upstox login, connection checks, and the background bot.

Nothing here prints or logs secrets. In the portal each user's keys live encrypted in the accounts database
(scalpbot/accounts.py); the helpers below take keys as arguments rather than reading the environment.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pandas as pd
import requests

from .bot import CANDLE_MIN, DISPLAY_TZ
from .brokers import AuthExpired
from .watchlist import Instrument, fetch_candles

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.getenv("SCALP_STATE_DIR", ROOT / ".state"))
TOKEN_FILE = Path(os.getenv("UPSTOX_TOKEN_FILE", STATE_DIR / "upstox_token.txt"))
PID_FILE = STATE_DIR / "bot.pid"
LOG_FILE = STATE_DIR / "bot.log"

UPSTOX_AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


# --------------------------------------------------------------------------- Upstox login
def upstox_login_url(api_key: str, redirect_uri: str, state: str = "") -> str:
    if not (api_key and redirect_uri):
        raise ValueError("Save your Upstox API key and redirect URI first.")
    q = {"client_id": api_key, "redirect_uri": redirect_uri, "response_type": "code"}
    if state:
        q["state"] = state
    return f"{UPSTOX_AUTH_URL}?{urlencode(q)}"


def extract_code(text: str) -> str:
    """Accept the bare code or the whole redirect URL and return the code."""
    text = (text or "").strip()
    if "code=" in text:
        q = parse_qs(urlparse(text).query)
        if q.get("code"):
            return q["code"][0]
        m = re.search(r"code=([^&\s]+)", text)
        if m:
            return m.group(1)
    return text


def upstox_get_token(code_or_url: str, api_key: str, api_secret: str, redirect_uri: str) -> str:
    """Trade the one-time login code for today's access token and return it (the caller stores it)."""
    code = extract_code(code_or_url)
    if not code:
        raise ValueError("Paste the code (or the whole redirect URL) first.")
    if not (api_key and api_secret and redirect_uri):
        raise ValueError("Upstox API key, secret and redirect URI must all be saved first.")
    r = requests.post(
        UPSTOX_TOKEN_URL,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={"code": code, "client_id": api_key, "client_secret": api_secret, "redirect_uri": redirect_uri,
              "grant_type": "authorization_code"},
        timeout=20,
    )
    if not r.ok:
        raise RuntimeError(f"Upstox rejected the code (HTTP {r.status_code}): {r.text[:200]}. "
                           "Codes are single-use and expire in minutes; start the login again.")
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Upstox did not return an access token.")
    return token


def saved_message() -> str:
    return f"Saved today's Upstox token at {pd.Timestamp.now(tz=DISPLAY_TZ):%H:%M} IST."


def write_token_file(token: str, path: Path | None = None) -> None:
    """For the local command-line bot, which reads the token from a file."""
    path = path or TOKEN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    try:
        path.chmod(0o600)
    except OSError:
        pass


# --------------------------------------------------------------------------- connection check
def check_instruments(insts: list[Instrument], candles: int = 1000) -> pd.DataFrame:
    """Fetch candles for each instrument and report what came back (same logic as `python -m scalpbot.check`)."""
    rows = []
    for inst in insts:
        row = {"Ticker": inst.name, "Group": inst.group, "Candles": 0, "Last closed candle (IST)": "-", "Status": ""}
        try:
            df = fetch_candles(inst, candles)
            if df.empty:
                raise RuntimeError("no closed candles returned")
            last = df.index[-1]
            age = (pd.Timestamp.now(tz="UTC") - (last + pd.Timedelta(minutes=CANDLE_MIN))).total_seconds() / 60
            row["Candles"] = len(df)
            row["Last closed candle (IST)"] = f"{last.tz_convert(DISPLAY_TZ):%d %b %H:%M}"
            note = "OK" if len(df) >= 300 else f"OK, but only {len(df)} candles (indicators need ~300)"
            if age > 120:
                note += f" (market closed? {age / 60:.1f}h old)"
            elif age > 12:
                note += f" ({age:.0f} min old)"
            row["Status"] = note
        except AuthExpired as e:
            row["Status"] = f"LOGIN NEEDED: {e}"
        except Exception as e:
            row["Status"] = f"FAILED: {str(e)[:160]}"
        rows.append(row)
    return pd.DataFrame(rows)


def sample_per_group(insts: list[Instrument], n: int = 3) -> list[Instrument]:
    seen: dict[str, int] = {}
    out = []
    for i in insts:
        seen[i.group] = seen.get(i.group, 0) + 1
        if seen[i.group] <= n:
            out.append(i)
    return out


def telegram_test(token: str, chat: str) -> str:
    if not (token and chat):
        raise ValueError("Save the Telegram bot token and chat id first.")
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": "✅ scalp5-bot test message: Telegram alerts are working."}, timeout=10)
    if not r.ok:
        raise RuntimeError(f"Telegram said HTTP {r.status_code}: {r.text[:150]}")
    return "Test message sent. Check Telegram."


# --------------------------------------------------------------------------- background bot
_PROCS: dict[int, subprocess.Popen] = {}   # children started by this process, so exited ones get reaped


def _pid_alive(pid: int) -> bool:
    proc = _PROCS.get(pid)
    if proc is not None:
        if proc.poll() is not None:        # exited (reaps the zombie)
            _PROCS.pop(pid, None)
            return False
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def bot_pid() -> int | None:
    """PID of the running bot started from the portal, or None (stale files are cleaned up)."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        PID_FILE.unlink(missing_ok=True)
        return None
    if _pid_alive(pid):
        return pid
    PID_FILE.unlink(missing_ok=True)
    return None


def bot_command(groups: list[str], dema_mode: str, cooldown: int, dry_run: bool, flags_off: list[str],
                only: list[str] | None = None) -> list[str]:
    cmd = [sys.executable, "-m", "scalpbot.bot", "--dema-cross", dema_mode, "--cooldown", str(int(cooldown))]
    if groups:
        cmd += ["--groups", ",".join(groups)]
    if only:
        cmd += ["--only", ",".join(only)]
    if dry_run:
        cmd.append("--dry-run")
    cmd += [f for f in flags_off if f in ("--no-dema", "--no-supertrend", "--no-rsi", "--no-room")]
    return cmd


def bot_token_file(user_id: int) -> Path:
    return STATE_DIR / "users" / str(user_id) / "upstox_token.txt"


def bot_env(c, user_id: int) -> dict[str, str]:
    """Environment for the local alert bot: the signed-in user's keys. The Upstox token goes through a per-user file,
    which the portal rewrites after each daily login, so the running bot picks it up without a restart."""
    if c.UPSTOX_ACCESS_TOKEN:
        write_token_file(c.UPSTOX_ACCESS_TOKEN, bot_token_file(user_id))
    env = {k: getattr(c, k) for k in ("COINSWITCH_API_KEY", "COINSWITCH_SECRET_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
    env["UPSTOX_ACCESS_TOKEN"] = ""
    env["UPSTOX_TOKEN_FILE"] = str(bot_token_file(user_id))
    return env


def start_bot(cmd: list[str], env_overrides: dict[str, str] | None = None) -> int:
    if bot_pid():
        raise RuntimeError("The bot is already running.")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "ab")
    log.write(f"\n--- started {pd.Timestamp.now(tz=DISPLAY_TZ):%Y-%m-%d %H:%M:%S} IST: {' '.join(cmd[2:])}\n".encode())
    log.flush()
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            start_new_session=True, env={**os.environ, **(env_overrides or {})})
    _PROCS[proc.pid] = proc
    PID_FILE.write_text(str(proc.pid))
    return proc.pid


def stop_bot(timeout: float = 8.0) -> bool:
    pid = bot_pid()
    if not pid:
        return False
    os.kill(pid, signal.SIGTERM)
    end = time.time() + timeout
    while time.time() < end and _pid_alive(pid):
        time.sleep(0.2)
    if _pid_alive(pid):
        os.kill(pid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)
    return True


def tail_log(n: int = 60) -> str:
    if not LOG_FILE.exists():
        return ""
    data = LOG_FILE.read_bytes()[-60_000:].decode("utf-8", "replace")
    return "\n".join(data.splitlines()[-n:])
