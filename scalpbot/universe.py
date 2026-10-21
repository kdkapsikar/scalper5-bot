"""Trading universe: nearest-expiry NSE index + F&O stock futures (Upstox) and crypto futures (CoinSwitch).

The Upstox instrument file is downloaded once a day and cached in .state/universe.json, so futures roll to the
next expiry automatically. Configure it in the `universe:` section of watchlist.yaml.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
from pathlib import Path

import pandas as pd

from .brokers import IST, _load_instruments, _to_ms, clear_instrument_cache
from .watchlist import Instrument, load_universe_config, load_watchlist

log = logging.getLogger("scalpbot.universe")

GROUP_INDEX, GROUP_STOCK, GROUP_MCX = "Index futures", "Stock futures", "MCX futures"
GROUP_CRYPTO, GROUP_FX, GROUP_CUSTOM = "Crypto", "Forex & metals", "Custom"
GROUPS = [GROUP_INDEX, GROUP_STOCK, GROUP_MCX, GROUP_CRYPTO, GROUP_FX, GROUP_CUSTOM]
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
_CACHE_KEYS = ("index_futures", "stock_futures", "mcx", "roll_days", "only", "exclude")


def _expiry_date(row: dict) -> dt.date:
    return pd.Timestamp(_to_ms(row["expiry"]), unit="ms", tz="UTC").tz_convert(IST).date()


SPOT_GOLD = "XAUUSD (spot)"


def pick_futures(rows: list, today: dt.date, roll_days: int = 0) -> dict:
    """Nearest unexpired future per underlying. With roll_days, move to the next month when expiry is that close."""
    by: dict[str, list] = {}
    for r in rows:
        if r.get("instrument_type") != "FUT":
            continue
        u = str(r.get("underlying_symbol", "")).strip().upper()
        if not u or not r.get("expiry"):
            continue
        d = _expiry_date(r)
        if d >= today:
            by.setdefault(u, []).append((d, r))
    out = {}
    for u, lst in by.items():
        lst.sort(key=lambda x: x[0])
        pick = lst[0]
        if roll_days > 0 and (pick[0] - today).days <= roll_days and len(lst) > 1:
            pick = lst[1]
        out[u] = pick[1]
    return out


def _fut(u: str, row: dict, group: str) -> Instrument:
    return Instrument(name=f"{u} FUT", source="upstox", instrument_key=row["instrument_key"],
                      symbol=str(row.get("trading_symbol", "")), group=group)


def upstox_instruments(conf: dict, today: dt.date, nse_rows: list, mcx_rows: list) -> tuple[list, list]:
    out: list[Instrument] = []
    warnings: list[str] = []
    only, excl = {s.upper() for s in conf["only"]}, {s.upper() for s in conf["exclude"]}
    if conf["index_futures"] or conf["stock_futures"]:
        picked = pick_futures([r for r in nse_rows if r.get("segment") == "NSE_FO"], today, conf["roll_days"])
        for u in sorted(picked):
            row = picked[u]
            is_index = str(row.get("underlying_type", "")).upper() == "INDEX" or u in INDEX_UNDERLYINGS
            if u in excl or (is_index and not conf["index_futures"]) or (not is_index and not conf["stock_futures"]):
                continue
            if not is_index and only and u not in only:
                continue
            out.append(_fut(u, row, GROUP_INDEX if is_index else GROUP_STOCK))
        if only:
            missing = sorted(only - set(picked))
            if missing:
                warnings.append(f"No NSE future found for: {', '.join(missing)}")
    if conf["mcx"]:
        picked = pick_futures([r for r in mcx_rows if r.get("segment") == "MCX_FO"], today, conf["roll_days"])
        missing = []
        for u in conf["mcx"]:
            row = picked.get(u.upper())
            if row is None:
                missing.append(u)
            elif u.upper() not in excl:
                out.append(_fut(u.upper(), row, GROUP_MCX))
        if missing:
            warnings.append(f"No MCX future found for: {', '.join(missing)}")
    return out, warnings


def build_universe(path: str = "watchlist.yaml", today: dt.date | None = None,
                   state_dir: str | None = None) -> tuple[list[Instrument], list[str]]:
    """Every instrument to watch (futures + crypto + custom entries) and any warnings to show the user."""
    state = Path(state_dir or os.getenv("SCALP_STATE_DIR", ".state"))
    today = today or dt.datetime.now(IST).date()
    conf = load_universe_config(path)
    out: list[Instrument] = []
    warnings: list[str] = []
    if conf is not None:
        key = json.dumps({k: conf[k] for k in _CACHE_KEYS}, sort_keys=True)
        cache_file = state / "universe.json"
        items = None
        try:
            c = json.loads(cache_file.read_text())
            if c.get("date") == today.isoformat() and c.get("conf") == key:
                items = [Instrument(**x) for x in c["items"]]
                warnings += c.get("warnings", [])
        except Exception:
            pass
        if items is None:
            try:
                nse = _load_instruments("NSE") if (conf["index_futures"] or conf["stock_futures"]) else []
                mcx = _load_instruments("MCX") if conf["mcx"] else []
                items, up_warn = upstox_instruments(conf, today, nse, mcx)
                warnings += up_warn
                if items:
                    state.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps({
                        "date": today.isoformat(), "conf": key, "warnings": up_warn,
                        "items": [dataclasses.asdict(i) for i in items]}))
                elif conf["index_futures"] or conf["stock_futures"] or conf["mcx"]:
                    warnings.append("The Upstox instrument file contained no matching futures "
                                    "(field names may have changed): Indian futures are unavailable.")
            except Exception as e:
                items = []
                warnings.append(f"Could not load the Upstox instrument list ({str(e)[:140]}). "
                                "Indian futures are unavailable until it loads; crypto still works.")
            finally:
                clear_instrument_cache()
        out += items
        out += [Instrument(name=s.upper(), source="coinswitch", symbol=s.upper(), group=GROUP_CRYPTO)
                for s in conf["crypto"]]
        if conf["spot_gold"]:
            out.append(Instrument(name=SPOT_GOLD, source="spotindex", symbol="XAUUSDT", group=GROUP_FX))
    out += load_watchlist(path)
    seen, unique = set(), []
    for i in out:
        if i.name in seen:
            warnings.append(f"Duplicate instrument name '{i.name}' ignored")
            continue
        seen.add(i.name)
        unique.append(i)
    return unique, warnings
