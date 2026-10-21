import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, runJob } from '../lib/api.js';
import { downloadCsv, fmt, istTime, pct } from '../lib/format.js';
import { CandleChart } from '../components/Charts.jsx';
import Rules, { DEFAULT_RULES } from '../components/Rules.jsx';
import TickerPicker from '../components/TickerPicker.jsx';
import { Banner, Button, Empty, ErrorText, Metric, Metrics, PageHeader, Progress, Segmented, useStored } from '../components/ui.jsx';

export function useUniverse() {
  const [u, setU] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api.get('/api/universe').then(setU).catch(setError); }, []);
  return { universe: u, error };
}

const SIDE = { LONG: ['up', '🟢 LONG'], SHORT: ['dn', '🔴 SHORT'], BLOCKED: ['amber', '🟡 blocked'] };

function ResultTable({ rows, onPick, blocked }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr>
          <th>Ticker</th><th>Signal</th><th>Trigger</th><th className="num">Candles ago</th><th>Close (IST)</th>
          <th className="num">Price</th><th className="num">Stop</th><th className="num">Target</th><th className="num">RSI</th>
          {blocked && <th>Blocked by</th>}
        </tr></thead>
        <tbody>
          {rows.map((r) => {
            const [cls, label] = SIDE[r.status === 'BLOCKED' ? 'BLOCKED' : r.status];
            return (
              <tr key={r.name} className="click" onClick={() => onPick(r.name)} title="Open details">
                <td className="font-semibold">{r.name}</td>
                <td className={cls}>{r.status === 'BLOCKED' ? `🟡 ${r.side}` : label}</td>
                <td>{r.trigger}</td><td className="num">{r.age}</td><td>{istTime(r.signal_close)}</td>
                <td className="num">{fmt(r.signal_price)}</td><td className="num">{fmt(r.stop)}</td><td className="num">{fmt(r.target)}</td>
                <td className="num">{r.rsi?.toFixed(1) ?? '-'}</td>
                {blocked && <td>{r.blocked_by.join(', ')}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const csvRows = (rows) => rows.map((r) => ({
  ticker: r.name, group: r.group, signal: r.status === 'BLOCKED' ? `${r.side} (blocked)` : r.status, trigger: r.trigger,
  candles_ago: r.age, candle_close_ist: istTime(r.signal_close), price: r.signal_price, stop: r.stop, target: r.target,
  rsi: r.rsi?.toFixed(1), blocked_by: r.blocked_by.join('; '),
}));

function ScanAll({ universe, rules, lookback, includeClosed, groups, onPick }) {
  const [busy, setBusy] = useState(false);
  const [prog, setProg] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [showBlocked, setShowBlocked] = useState(false);
  const chosen = universe.instruments.filter((i) => groups.includes(i.group)).length;

  async function run() {
    setBusy(true); setError(null); setProg({ done: 0, total: chosen });
    try {
      const result = await runJob(() => api.post('/api/scan', { groups, rules, lookback, include_closed: includeClosed }), (j) => setProg(j));
      setData({ ...result, at: new Date(), lookback });
    } catch (e) { setError(e); } finally { setBusy(false); setProg(null); }
  }

  const c = data?.counts;
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button className="primary" busy={busy} disabled={!chosen} onClick={run}>📡 Run scan</Button>
        <span className="text-sm muted">{chosen} instruments selected. A full F&amp;O scan takes a minute or two (Upstox's rate limits); the page stays usable meanwhile.</span>
      </div>
      {prog && <Progress done={prog.done} total={prog.total} label="Scanning…" />}
      <ErrorText error={error} />
      {!data && !busy && <Empty icon="📡" title="Ready when you are">Press Run scan to check every selected instrument against the rules.</Empty>}
      {data && (
        <>
          <Metrics>
            <Metric label="Scanned" value={c.scanned} /><Metric label="Long" value={c.long} tone="bull" />
            <Metric label="Short" value={c.short} tone="bear" /><Metric label="Blocked" value={c.blocked} tone="warn" />
            <Metric label="Closed / delayed" value={c.stale} /><Metric label="Errors" value={c.errors} />
          </Metrics>
          {c.scanned > 0 && c.errors === c.scanned && (
            <Banner kind="bad">Every instrument failed, which usually means a broker login is missing or expired. <Link to="/app/connect">Open Connect</Link>.</Banner>
          )}
          <p className="mb-3 text-sm faint">Scan finished {data.at.toLocaleTimeString('en-IN', { hour12: false })}, looking back {data.lookback} closed candle(s). Run it again after the next 5-minute close.</p>
          {data.hits.length ? (
            <>
              <div className="mb-2 flex items-center justify-between"><h2 className="text-lg font-bold">Satisfying all conditions</h2>
                <Button className="small" onClick={() => downloadCsv(csvRows(data.hits), 'scalp5_signals.csv')}>⬇ CSV</Button></div>
              <ResultTable rows={data.hits} onPick={onPick} />
            </>
          ) : <Empty icon="🧘" title="No setups right now">Nothing satisfies all the conditions in the look-back window. Try again after the next 5-minute close.</Empty>}
          <label className="my-4 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={showBlocked} onChange={(e) => setShowBlocked(e.target.checked)} className="h-4 w-4 accent-[var(--brand)]" />
            Also show near-misses (a trigger fired but a filter blocked it)
          </label>
          {showBlocked && (data.blocked.length ? <ResultTable rows={data.blocked} onPick={onPick} blocked /> : <p className="text-sm muted">No blocked setups in the window.</p>)}
          {data.stale.length > 0 && (
            <details className="fold mt-4"><summary>{data.stale.length} instruments skipped: market closed or data delayed</summary>
              <div className="table-wrap"><table className="data"><tbody>{data.stale.map((r) => (
                <tr key={r.name}><td className="font-semibold">{r.name}</td><td style={{ whiteSpace: 'normal' }}>{r.stale_text}</td></tr>))}</tbody></table></div>
            </details>
          )}
          {data.errors.length > 0 && (
            <details className="fold mt-3"><summary>{data.errors.length} instruments failed</summary>
              <div className="table-wrap"><table className="data"><tbody>{data.errors.map((r) => (
                <tr key={r.name}><td className="font-semibold">{r.name}</td><td style={{ whiteSpace: 'normal' }}>{r.error}</td></tr>))}</tbody></table></div>
            </details>
          )}
        </>
      )}
    </div>
  );
}

const VIEW_TONE = { bull: 'var(--bull)', bear: 'var(--bear)', neutral: 'var(--muted)', none: 'var(--faint)' };
const VIEW_ANIMAL = { bull: '🐂', bear: '🐻', neutral: '⚖️', none: '❔' };

/** Bull / Bear verdict for one ticker, and what stands between it and a signal. */
function ViewCard({ view }) {
  if (!view || view.score === null) return null;
  return (
    <div className="card mood mb-5" style={{ '--tone': VIEW_TONE[view.side] }}>
      <div className="grid gap-5 md:grid-cols-[1fr_1.2fr]">
        <div>
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-bold uppercase tracking-widest muted">Bull / Bear view</div>
              <div className="label mt-1">{view.label}</div>
              <div className="display muted">Score <b style={{ color: 'var(--tone)' }}>{view.score > 0 ? '+' : ''}{Math.round(view.score)}</b> / 100</div>
            </div>
            <div className="animal">{VIEW_ANIMAL[view.side]}</div>
          </div>
          <div className="scorebar"><i style={{ left: `${(view.score + 100) / 2}%` }} /></div>
          <div className="mb-3 flex justify-between text-[.72rem] faint"><span>Strong bear</span><span>Neutral</span><span>Strong bull</span></div>
          <ul className="facts">{view.facts.map((f) => <li key={f}>{f}</li>)}</ul>
        </div>
        <div className="md:border-l md:pl-5" style={{ borderColor: 'var(--border)' }}>
          <div className="mb-2 text-xs font-bold uppercase tracking-widest muted">Signal status</div>
          <ul className="facts">{view.why.map((w, i) => <li key={w} style={i === 0 ? { fontWeight: 600 } : undefined}>{w}</li>)}</ul>
          <p className="mt-2 text-xs faint">Reads the current 5-minute structure; it is not a forecast or advice.</p>
        </div>
      </div>
    </div>
  );
}

function Checklist({ title, checks }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr><th colSpan={3}>{title} checklist <span className="faint">(latest closed candle)</span></th></tr></thead>
        <tbody>{checks.map((c) => (
          <tr key={c.name}>
            <td>{c.name}</td>
            <td>{c.ok ? '✅' : c.required ? '❌' : <span className="faint">➖ off</span>}</td>
            <td className="muted" style={{ whiteSpace: 'normal' }}>{c.detail}</td>
          </tr>))}
        </tbody>
      </table>
    </div>
  );
}

export function TickerDetail({ name, rules, lookback, autoRefresh = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [n, setN] = useState(0);
  const key = JSON.stringify(rules);

  useEffect(() => {                                    // optional: re-fetch every `autoRefresh` seconds
    if (!autoRefresh) return undefined;
    const t = setInterval(() => { if (document.visibilityState === 'visible') setN((x) => x + 1); }, autoRefresh * 1000);
    return () => clearInterval(t);
  }, [autoRefresh]);

  useEffect(() => {
    if (!name) return;
    let live = true;
    setBusy(true); setError(null);
    api.post('/api/ticker', { name, rules, lookback })
      .then((d) => live && setData(d)).catch((e) => live && setError(e)).finally(() => live && setBusy(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, key, lookback, n]);

  if (!data && busy) return <div className="flex items-center gap-2 py-10 muted"><span className="spinner" /> Loading {name}…</div>;
  if (error) return <ErrorText error={error} />;
  if (!data) return null;
  if (data.status === 'ERROR') return <Banner kind="bad">{data.error}</Banner>;
  const tone = { LONG: 'ok', SHORT: 'bad', BLOCKED: 'warn' }[data.status] || 'info';
  const lastDema = data.chart?.dema?.at(-1)?.value;
  const vsDema = lastDema ? (100 * (data.price / lastDema - 1)) : null;
  return (
    <div className={busy ? 'opacity-60 transition-opacity' : ''}>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold">{data.name} <span className="faint font-normal">· {data.group}</span></h2>
        <Button className="small" busy={busy} onClick={() => setN((x) => x + 1)}>↻ Refresh</Button>
      </div>
      {data.stale && <Banner kind="warn">{data.stale_text} Showing the latest data available.</Banner>}
      {data.filled && <p className="text-sm faint">⏱️ CoinSwitch's candle history was behind, so the latest {data.filled.candles} closed candle(s) came from {data.filled.provider[0].toUpperCase() + data.filled.provider.slice(1)}'s real-time feed (the same market).</p>}
      <Banner kind={tone}>{data.headline}{data.stop !== null && ['LONG', 'SHORT'].includes(data.status) && <> · Stop {fmt(data.stop)}{data.target !== null && <> · Target {fmt(data.target)}</>}</>}</Banner>
      <ViewCard view={data.view} />
      <Metrics>
        <Metric label="Last price" value={fmt(data.price)} /><Metric label="RSI (14)" value={data.rsi?.toFixed(1) ?? '-'} />
        <Metric label="Supertrend" value={data.st_up ? 'Up' : 'Down'} tone={data.st_up ? 'bull' : 'bear'} />
        <Metric label="vs 200 DEMA" value={pct(vsDema)} tone={vsDema >= 0 ? 'bull' : 'bear'} />
        <Metric label="22 vs 33 SMA" value={data.sma_up ? '22 above' : '22 below'} tone={data.sma_up ? 'bull' : 'bear'} />
      </Metrics>
      <div className="mb-5 grid gap-4 lg:grid-cols-2">
        <Checklist title="LONG" checks={data.checks.LONG} /><Checklist title="SHORT" checks={data.checks.SHORT} />
      </div>
      {data.chart && <div className="card mb-5 p-4"><CandleChart chart={data.chart} /></div>}
      <div className="kv">{Object.entries(data.snapshot || {}).map(([k, v]) => <div key={k}><span>{k}</span><b>{v}</b></div>)}</div>
    </div>
  );
}

export default function Scanner() {
  const { universe, error } = useUniverse();
  const [mode, setMode] = useStored('scan.mode', 'all');
  // Remember the groups you switched OFF, so groups added later (e.g. Forex & metals) show up by themselves.
  const [hidden, setHidden] = useStored('scan.hiddenGroups', []);
  const [rules, setRules] = useStored('scan.rules', DEFAULT_RULES);
  const [lookback, setLookback] = useStored('scan.lookback', 3);
  const [includeClosed, setIncludeClosed] = useStored('scan.closed', false);
  const [ticker, setTicker] = useStored('scan.ticker', '');
  const allGroups = universe?.groups ?? [];
  const active = allGroups.filter((g) => !hidden.includes(g));
  // Single ticker lists every instrument; the Universe chips choose what "Scan all" scans.
  const names = useMemo(() => (universe?.instruments ?? []).map((i) => i.name), [universe]);

  useEffect(() => { if (universe && (!ticker || !names.includes(ticker)) && names.length) setTicker(names[0]); }, [universe, names, ticker, setTicker]);

  const pick = (name) => { setTicker(name); setMode('one'); window.scrollTo({ top: 0, behavior: 'smooth' }); };
  const toggle = (g) => setHidden(hidden.includes(g) ? hidden.filter((x) => x !== g) : [...hidden, g]);

  return (
    <>
      <PageHeader eyebrow="Trade · 5-minute confluence" title="Scanner"
        actions={<Segmented options={[['all', 'Scan all'], ['one', 'Single ticker']]} value={mode} onChange={setMode} />}>
        SMA 22/33 cross or the lines crossing the 200 DEMA, filtered by Supertrend, 200 DEMA side, RSI and pivot room. Analysis only; not financial advice.
      </PageHeader>
      <ErrorText error={error} />
      {universe?.warnings?.map((w) => <Banner key={w} kind="warn">{w}</Banner>)}
      {universe && (
        <>
          <div className="card mb-5 grid gap-4 p-4 md:grid-cols-[1fr_1fr]">
            <div className="grid content-start gap-2">
              <span className="text-sm font-medium">Universe <span className="font-normal faint">(what Scan all scans)</span></span>
              <div className="flex flex-wrap gap-1.5">{allGroups.map((g) => <button key={g} type="button" className="chip" aria-pressed={active.includes(g)} onClick={() => toggle(g)}>{g}</button>)}</div>
              <label className="mt-2 grid gap-1 text-sm font-medium">
                <span>Look back: {lookback} closed candle{lookback > 1 ? 's' : ''}</span>
                <input type="range" min={1} max={12} value={lookback} onChange={(e) => setLookback(+e.target.value)} className="accent-[var(--brand)]" />
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={includeClosed} onChange={(e) => setIncludeClosed(e.target.checked)} className="h-4 w-4 accent-[var(--brand)]" />
                Include closed markets (review the last session)
              </label>
            </div>
            <Rules value={rules} onChange={setRules} />
          </div>
          {mode === 'all' ? (
            <ScanAll universe={universe} rules={rules} lookback={lookback} includeClosed={includeClosed} groups={active} onPick={pick} />
          ) : (
            <>
              <div className="mb-5 max-w-md">
                <TickerPicker instruments={universe?.instruments ?? []} value={ticker} onChange={setTicker} />
              </div>
              {names.includes(ticker) ? <TickerDetail name={ticker} rules={rules} lookback={lookback} />
                : <Empty icon="🔎" title="Pick a ticker">Type a name from the list, e.g. NIFTY FUT, RELIANCE FUT or BTCUSDT.</Empty>}
            </>
          )}
        </>
      )}
      {!universe && !error && <div className="flex items-center gap-2 muted"><span className="spinner" /> Loading the instrument list…</div>}
    </>
  );
}
