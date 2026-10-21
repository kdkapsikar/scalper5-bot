"""Market endpoints: instrument list, scan, one ticker (with chart data), market mood, backtest, connection test."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from scalpbot import portal_tools as pt
from scalpbot import scan as sc
from scalpbot.accounts import User
from scalpbot.backtest import backtest, summarize
from scalpbot.brokers import FILL_INFO, clear_instrument_cache
from scalpbot.mood import WEIGHTS, all_moods, ticker_view
from scalpbot.strategy import PIVOT_COLS
from scalpbot.universe import GROUP_CRYPTO, GROUP_FX, GROUP_INDEX, GROUP_MCX, GROUP_STOCK, GROUPS
from scalpbot.watchlist import fetch_candles, make_config

from . import jobs
from .core import bucket, current_user, memo, universe, use_keys

router = APIRouter(prefix="/api")
QUICK_GROUPS = (GROUP_INDEX, GROUP_MCX, GROUP_CRYPTO, GROUP_FX)
FULL_GROUPS = (GROUP_INDEX, GROUP_STOCK, GROUP_MCX, GROUP_CRYPTO, GROUP_FX)
IST = "Asia/Kolkata"


class Rules(BaseModel):
    """The strategy switches from the Scanner / Backtest pages."""
    dema_cross_mode: str = Field("both", pattern="^(both|fast|off)$")
    require_supertrend: bool = True
    require_dema_bias: bool = True
    require_rsi: bool = True
    require_pivot_room: bool = True

    def flags(self) -> dict:
        f = {"dema_cross_mode": self.dema_cross_mode}
        for k in ("require_supertrend", "require_dema_bias", "require_rsi", "require_pivot_room"):
            if not getattr(self, k):
                f[k] = False
        return f


# --------------------------------------------------------------------------- serialisation
def _num(x) -> Optional[float]:
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def _ts(t) -> Optional[str]:
    return None if t is None or pd.isna(t) else pd.Timestamp(t).isoformat()


def result_json(r: sc.Result, with_checks: bool = False) -> dict:
    d = {
        "name": r.name, "group": r.group, "source": r.source, "status": r.status, "side": r.side, "stale": r.stale,
        "error": r.error, "trigger": r.trigger, "age": r.age, "last_candle": _ts(r.last_candle),
        "signal_close": _ts(r.signal_close), "price": _num(r.price), "signal_price": _num(r.signal_price),
        "stop": _num(r.stop), "target": _num(r.target), "rsi": _num(r.rsi), "st_up": r.st_up,
        "above_dema": r.above_dema, "sma_up": r.sma_up, "blocked_by": list(r.blocked_by),
        "stale_text": sc.stale_text(r) if r.stale else "",
        "always_open": sc.always_open(r),
    }
    fill = FILL_INFO.get(r.name) if r.source == "coinswitch" else None
    d["filled"] = {"candles": fill["candles"], "provider": fill["provider"]} if fill and fill["candles"] else None
    if with_checks:
        d["checks"] = {side: [{"name": c.name, "ok": c.ok, "required": c.required, "detail": c.detail}
                              for c in cs] for side, cs in r.checks.items()}
        d["snapshot"] = r.snapshot
    return d


def chart_json(ind: pd.DataFrame, n: int = 150) -> dict:
    d = ind.iloc[-n:]
    t = [int(ts.timestamp()) for ts in d.index]       # unix seconds, whatever unit pandas stores the index in

    def series(col, where=None):
        if where is None:
            return [{"time": ti, "value": _num(v)} for ti, v in zip(t, d[col]) if _num(v) is not None]
        # Supertrend up/down: a point without a value is a gap, so the line breaks where the trend flipped
        return [{"time": ti, "value": _num(v)} if _num(v) is not None else {"time": ti}
                for ti, v in zip(t, d[col].where(where))]

    last = d.iloc[-1]
    return {
        "candles": [{"time": ti, "open": o, "high": h, "low": lo, "close": c}
                    for ti, o, h, lo, c in zip(t, *(map(_num, d[k]) for k in ("open", "high", "low", "close")))
                    if None not in (o, h, lo, c)],         # the chart rejects incomplete candles
        "sma_fast": series("sma_fast"), "sma_slow": series("sma_slow"), "dema": series("dema"),
        "st_up": series("st", d["st_dir"] == 1), "st_down": series("st", d["st_dir"] == -1),
        # one Supertrend line with its direction per point; the web app colours it and hides the jump at each flip
        "supertrend": [{"time": ti, "value": _num(v), "dir": int(sd)} for ti, v, sd in zip(t, d["st"], d["st_dir"])
                       if _num(v) is not None],
        "signals": [{"time": ti, "side": "LONG" if bool(lg) else "SHORT"}
                    for ti, lg, sh in zip(t, d["long_sig"], d["short_sig"]) if bool(lg) or bool(sh)],
        "pivots": {k: _num(last[k]) for k in PIVOT_COLS if k in d.columns and _num(last[k]) is not None},
    }


def mood_json(m) -> dict:
    d = asdict(m)
    d["side"] = m.side
    d["weights"] = {k: WEIGHTS[k] for k in m.components}
    return d


def _pick(names: list[str] | None, groups: list[str] | None):
    insts, warnings = universe()
    if groups:
        insts = [i for i in insts if i.group in groups]
    if names:
        wanted = set(names)
        insts = [i for i in insts if i.name in wanted]
    return insts, warnings


def _by_name(name: str):
    for i in universe()[0]:
        if i.name == name:
            return i
    raise HTTPException(404, f"No instrument called {name}.")


# --------------------------------------------------------------------------- endpoints
@router.get("/universe")
def get_universe(user: User = Depends(current_user)):
    insts, warnings = universe()
    return {"groups": [g for g in GROUPS if any(i.group == g for i in insts)],
            "instruments": [{"name": i.name, "group": i.group, "source": i.source} for i in insts],
            "warnings": warnings}


class ScanIn(BaseModel):
    groups: list[str] = Field(default_factory=lambda: list(FULL_GROUPS))
    rules: Rules = Field(default_factory=Rules)
    lookback: int = Field(3, ge=1, le=12)
    include_closed: bool = False


def scan_summary(results: list[sc.Result]) -> dict:
    cnt = Counter(r.status for r in results)
    order = lambda r: (r.age if r.age is not None else 99, r.name)
    return {
        "counts": {"scanned": len(results), "long": cnt["LONG"], "short": cnt["SHORT"], "blocked": cnt["BLOCKED"],
                   "stale": cnt["STALE"], "errors": cnt["ERROR"]},
        "hits": [result_json(r) for r in sorted([r for r in results if r.status in ("LONG", "SHORT")], key=order)],
        "blocked": [result_json(r) for r in sorted([r for r in results if r.status == "BLOCKED"], key=order)],
        "stale": [result_json(r) for r in results if r.status == "STALE"],
        "errors": [{"name": r.name, "error": r.error} for r in results if r.status == "ERROR"],
    }


@router.post("/scan")
def start_scan(body: ScanIn, user: User = Depends(current_user)):
    use_keys(user)
    insts, _ = _pick(None, body.groups)
    if not insts:
        raise HTTPException(400, "Pick at least one group to scan.")
    flags = body.rules.flags()

    def run(progress):
        return scan_summary(sc.scan(insts, flags, body.lookback, body.include_closed, workers=4, progress=progress))

    return jobs.start(user.id, "scan", run).json()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(current_user)):
    j = jobs.get(job_id, user.id)
    if j is None:
        raise HTTPException(404, "That job has finished long ago or never existed. Start it again.")
    return j.json()


class TickerIn(BaseModel):
    name: str
    rules: Rules = Field(default_factory=Rules)
    lookback: int = Field(3, ge=1, le=12)


@router.post("/ticker")
def ticker(body: TickerIn, user: User = Depends(current_user)):
    use_keys(user)
    inst = _by_name(body.name)
    res, ind, cfg = sc.run_one(inst, body.rules.flags(), body.lookback, ignore_stale=True)
    out = result_json(res, with_checks=res.status != "ERROR")
    out["headline"] = sc.headline(res, body.lookback)
    out["view"] = ticker_view(res, cfg) if cfg is not None else None
    out["chart"] = chart_json(ind) if ind is not None else None
    return out


def measure(user: User, groups: tuple) -> list[sc.Result]:
    """Default-rules scan of the groups, shared by Market mood and Bull & Bear, cached per user per candle."""
    insts, _ = _pick(None, list(groups))
    return memo((user.id, "measure", groups, bucket()),
                lambda: sc.scan(insts, {}, lookback=3, ignore_stale=True, workers=4))


def mood_payload(results: list[sc.Result]) -> dict:
    moods = all_moods(results)
    return {"moods": {k: mood_json(m) for k, m in moods.items()},
            "readings": [result_json(r) for r in results]}


@router.post("/mood")
def start_mood(scope: str = "quick", user: User = Depends(current_user)):
    use_keys(user)
    groups = FULL_GROUPS if scope == "full" else QUICK_GROUPS
    return jobs.start(user.id, f"mood-{scope}", lambda progress: mood_payload(measure(user, groups))).json()


class BacktestIn(BaseModel):
    name: str
    fee_bps: float = Field(5.0, ge=0, le=100)
    slippage_bps: float = Field(2.0, ge=0, le=100)
    rules: Rules = Field(default_factory=Rules)
    compare: bool = True


@router.post("/backtest")
def run_backtest(body: BacktestIn, user: User = Depends(current_user)):
    use_keys(user)
    inst = _by_name(body.name)
    try:
        df = fetch_candles(inst, 5000)
    except Exception as e:
        raise HTTPException(502, f"Could not fetch candles: {e}")
    if len(df) < 400:
        raise HTTPException(422, f"Only {len(df)} candles came back; the backtest needs about 400 or more.")
    flags = body.rules.flags()
    modes = ["off", "fast", "both"] if body.compare else [flags["dema_cross_mode"]]
    out = []
    for m in modes:
        trades = backtest(df, make_config(inst, {**flags, "dema_cross_mode": m}), body.fee_bps, body.slippage_bps)
        s = summarize(trades)
        if s.get("profit_factor") == float("inf"):
            s["profit_factor"] = None
        rows = [] if trades.empty else [{
            "entry_time": _ts(t.entry_time), "exit_time": _ts(t.exit_time), "side": t.side, "entry": _num(t.entry),
            "exit": _num(t.exit), "ret_pct": round(100 * float(t.ret), 3), "reason": t.reason, "candles": int(t.bars),
            "trigger": str(t.trigger)} for t in trades.itertuples()]
        out.append({"mode": m, "summary": s, "trades": rows})
    return {"name": inst.name, "candles": len(df), "from": _ts(df.index[0]), "to": _ts(df.index[-1]),
            "fee_bps": body.fee_bps, "slippage_bps": body.slippage_bps, "results": out}


@router.post("/connections/test")
def test_connections(scope: str = "sample", user: User = Depends(current_user)):
    use_keys(user)
    insts, warnings = universe()
    chosen = insts if scope == "all" else pt.sample_per_group(insts)

    def run(progress):
        clear_instrument_cache()
        rows = []
        for k, inst in enumerate(chosen, 1):
            rows += pt.check_instruments([inst]).to_dict("records")
            progress(k, len(chosen))
        return {"rows": rows, "warnings": warnings}

    return jobs.start(user.id, "test", run).json()
