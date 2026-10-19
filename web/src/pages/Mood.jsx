import { useCallback, useEffect, useState } from 'react';
import { api, runJob } from '../lib/api.js';
import { useAuth } from '../context/Auth.jsx';
import { Button, ErrorText, PageHeader, Pill, Progress, Segmented, useStored } from '../components/ui.jsx';

const COMPONENTS = {
  dema: '200 DEMA breadth', supertrend: 'Supertrend breadth', sma: 'SMA 22/33 breadth',
  leader: 'Leader (NIFTY FUT / BTCUSDT)', rsi: 'Median RSI', signals: 'Fresh signals',
};
const TONE = { bull: 'var(--bull)', bear: 'var(--bear)', neutral: 'var(--muted)', none: 'var(--faint)' };
const ANIMAL = { bull: '🐂', bear: '🐻', neutral: '⚖️', none: '❔' };

function MoodCard({ market, m }) {
  const total = Object.values(m.weights || {}).reduce((a, b) => a + b, 0) || 1;
  return (
    <div>
      <div className="card mood" style={{ '--tone': TONE[m.side] }}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-bold uppercase tracking-widest muted">{market}</div>
            <div className="label mt-1">{m.label}</div>
            <div className="display muted">{m.score === null ? 'No reading yet' : <>Score <b style={{ color: 'var(--tone)' }}>{m.score > 0 ? '+' : ''}{Math.round(m.score)}</b> / 100</>}</div>
          </div>
          <div className="animal">{ANIMAL[m.side]}</div>
        </div>
        {m.score !== null && (
          <>
            <div className="scorebar"><i style={{ left: `${(m.score + 100) / 2}%` }} /></div>
            <div className="mb-3 flex justify-between text-[.72rem] faint"><span>Strong bear</span><span>Neutral</span><span>Strong bull</span></div>
          </>
        )}
        <div className="mb-3 flex flex-wrap gap-1.5">
          <Pill>{m.n} measured</Pill>
          {m.stale > 0 && <Pill tone="warn">{m.stale} {market === 'Crypto' ? 'delayed' : 'closed'}</Pill>}
          {m.errors > 0 && <Pill tone="bear">{m.errors} failed</Pill>}
        </div>
        <ul className="facts">{m.facts.map((f) => <li key={f}>{f}</li>)}</ul>
      </div>
      {Object.keys(m.components || {}).length > 0 && (
        <details className="fold mt-2"><summary>How the score is built</summary>
          <div className="table-wrap"><table className="data">
            <thead><tr><th>Component</th><th className="num">Reading (-1 to +1)</th><th className="num">Weight</th></tr></thead>
            <tbody>{Object.entries(m.components).map(([k, v]) => (
              <tr key={k}><td>{COMPONENTS[k]}</td><td className="num">{v.toFixed(2)}</td><td className="num">{Math.round((100 * m.weights[k]) / total)}%</td></tr>))}</tbody>
          </table></div>
        </details>
      )}
    </div>
  );
}

const yn = (v) => (v === null || v === undefined ? '-' : v ? '✓' : '✗');

export default function Mood() {
  const { setMood } = useAuth();
  const [scope, setScope] = useStored('mood.scope', 'quick');
  const [data, setData] = useState(null);
  const [prog, setProg] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null); setProg({ done: 0, total: 0 });
    try {
      const r = await runJob(() => api.post(`/api/mood?scope=${scope}`), setProg);
      setData(r);
      const scores = Object.values(r.moods).map((m) => m.score).filter((s) => s !== null);
      if (scores.length) setMood(scores.reduce((a, b) => a + b, 0) / scores.length);
    } catch (e) { setError(e); } finally { setProg(null); }
  }, [scope, setMood]);

  useEffect(() => { load(); }, [load]);

  return (
    <>
      <PageHeader eyebrow="Trade · Bull vs Bear" title="Market mood"
        actions={<div className="flex items-center gap-2">
          <Segmented options={[['quick', 'Quick'], ['full', 'Full breadth']]} value={scope} onChange={setScope} />
          <Button busy={!!prog} onClick={load}>↻ Refresh</Button></div>}>
        Is the tape bullish or bearish right now? A score from -100 (strong bear) to +100 (strong bull), from 200 DEMA, Supertrend
        and SMA 22/33 breadth, the leaders (NIFTY FUT, BTCUSDT), median RSI and fresh signals. Quick reads index futures and
        crypto; Full adds every F&amp;O stock future (a minute or two). It describes the market; it is not a forecast or advice.
      </PageHeader>
      <ErrorText error={error} />
      {prog && <Progress done={prog.done} total={prog.total} label={scope === 'full' ? 'Reading every F&O future and crypto…' : 'Reading index futures and crypto…'} />}
      {data && (
        <div className={prog ? 'opacity-60' : ''}>
          <div className="grid gap-5 lg:grid-cols-2">{Object.entries(data.moods).map(([k, m]) => <MoodCard key={k} market={k} m={m} />)}</div>
          <details className="fold mt-5"><summary>Per-instrument readings</summary>
            <div className="table-wrap"><table className="data">
              <thead><tr><th>Ticker</th><th>Group</th><th>Above 200 DEMA</th><th>Supertrend up</th><th>SMA 22 &gt; 33</th><th className="num">RSI</th><th>Signal</th><th>Note</th></tr></thead>
              <tbody>{data.readings.map((r) => (
                <tr key={r.name}><td className="font-semibold">{r.name}</td><td>{r.group}</td><td>{yn(r.above_dema)}</td><td>{yn(r.st_up)}</td>
                  <td>{yn(r.sma_up)}</td><td className="num">{r.rsi?.toFixed(1) ?? '-'}</td>
                  <td className={r.status === 'LONG' ? 'up' : r.status === 'SHORT' ? 'dn' : ''}>{['LONG', 'SHORT'].includes(r.status) ? r.status : ''}</td>
                  <td className="faint">{r.error || (r.stale ? (r.always_open ? 'data delayed' : 'market closed') : '')}</td></tr>))}</tbody>
            </table></div>
          </details>
        </div>
      )}
    </>
  );
}
