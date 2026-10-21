import { useEffect, useState } from 'react';
import { api } from '../lib/api.js';
import { downloadCsv, fmt, istTime } from '../lib/format.js';
import { EquityChart } from '../components/Charts.jsx';
import Rules, { DEFAULT_RULES } from '../components/Rules.jsx';
import TickerPicker from '../components/TickerPicker.jsx';
import { Banner, Button, ErrorText, Field, PageHeader, Segmented, useStored } from '../components/ui.jsx';
import { useUniverse } from './Scanner.jsx';

const n = (v, d = 2) => (v === null || v === undefined ? '-' : Number(v).toFixed(d));

export default function Backtest() {
  const { universe, error: uErr } = useUniverse();
  const [name, setName] = useStored('bt.name', 'NIFTY FUT');
  const [fee, setFee] = useStored('bt.fee', 5);
  const [slip, setSlip] = useStored('bt.slip', 2);
  const [rules, setRules] = useStored('bt.rules', DEFAULT_RULES);
  const [compare, setCompare] = useStored('bt.compare', true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const [mode, setMode] = useState('both');
  const names = universe?.instruments.map((i) => i.name) ?? [];

  useEffect(() => { if (names.length && !names.includes(name)) setName(names[0]); }, [names, name, setName]);

  async function run() {
    setBusy(true); setError(null);
    try {
      const r = await api.post('/api/backtest', { name, fee_bps: +fee, slippage_bps: +slip, rules, compare });
      setData(r);
      setMode(r.results.at(-1).mode);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  const shown = data?.results.find((r) => r.mode === mode) ?? data?.results.at(-1);
  const byTrigger = shown?.summary.by_trigger ?? {};
  return (
    <>
      <PageHeader eyebrow="Trade · research" title="Backtest">
        Replays the exact rules on the history your broker feed provides (about 20 days for Upstox). Entry is at the next candle's
        open; fees and slippage are charged per side, so a round trip costs 2 × (fee + slippage). Treat fewer than 100 trades as inconclusive.
      </PageHeader>
      <ErrorText error={uErr} />
      <div className="card mb-5 grid gap-4 p-4">
        <div className="grid gap-4 md:grid-cols-[2fr_1fr_1fr]">
          <TickerPicker instruments={universe?.instruments ?? []} value={name} onChange={setName} />
          <Field label="Fee per side (bps)" hint="1 bps = 0.01%"><input className="input" type="number" min={0} max={100} step={0.5} value={fee} onChange={(e) => setFee(e.target.value)} /></Field>
          <Field label="Slippage per side (bps)"><input className="input" type="number" min={0} max={100} step={0.5} value={slip} onChange={(e) => setSlip(e.target.value)} /></Field>
        </div>
        <Rules value={rules} onChange={setRules} />
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} className="h-4 w-4 accent-[var(--brand)]" />
            Compare all three 200 DEMA trigger modes (off / fast / both)
          </label>
          <Button className="primary" busy={busy} disabled={!names.includes(name)} onClick={run}>🧪 Run backtest</Button>
        </div>
      </div>
      <ErrorText error={error} />
      {data && (
        <>
          <p className="mb-3 text-sm muted"><b>{data.name}</b>: {data.candles} candles, {istTime(data.from)} to {istTime(data.to)} IST · round trip {(2 * (data.fee_bps + data.slippage_bps) / 100).toFixed(2)}%</p>
          <div className="table-wrap mb-3"><table className="data">
            <thead><tr><th>DEMA trigger</th><th className="num">Trades</th><th className="num">Win %</th><th className="num">Avg win %</th><th className="num">Avg loss %</th>
              <th className="num">Profit factor</th><th className="num">Total return %</th><th className="num">Max drawdown %</th></tr></thead>
            <tbody>{data.results.map(({ mode: m, summary: s }) => (
              <tr key={m} className="click" onClick={() => setMode(m)} style={m === shown.mode ? { fontWeight: 600 } : undefined}>
                <td>{m}</td><td className="num">{s.trades}</td><td className="num">{n(s['win_rate_%'], 1)}</td><td className="num">{n(s['avg_win_%'], 3)}</td>
                <td className="num">{n(s['avg_loss_%'], 3)}</td><td className="num">{s.profit_factor === null ? '∞' : n(s.profit_factor)}</td>
                <td className={`num ${s['total_return_%'] >= 0 ? 'up' : 'dn'}`}>{n(s['total_return_%'])}</td><td className="num">{n(s['max_drawdown_%'])}</td></tr>))}</tbody>
          </table></div>
          {data.results.some((r) => r.summary.trades < 100) && <Banner kind="warn">Fewer than 100 trades in at least one row: too few to say anything reliable.</Banner>}
          {data.results.length > 1 && <div className="my-4"><Segmented options={data.results.map((r) => [r.mode, `Show "${r.mode}"`])} value={shown.mode} onChange={setMode} /></div>}
          {shown.trades.length === 0 ? <p className="muted">No trades with this setting.</p> : (
            <>
              <div className="card mb-5 p-4"><div className="mb-2 font-semibold">Equity curve (cumulative return)</div><EquityChart trades={shown.trades} /></div>
              {Object.keys(byTrigger).length > 0 && (
                <div className="table-wrap mb-5"><table className="data">
                  <thead><tr><th>Trigger</th><th className="num">Trades</th><th className="num">Win %</th><th className="num">Avg return %</th></tr></thead>
                  <tbody>{Object.entries(byTrigger).map(([t, v]) => <tr key={t}><td>{t}</td><td className="num">{v.trades}</td><td className="num">{n(v['win_%'], 1)}</td><td className="num">{n(v['avg_%'], 3)}</td></tr>)}</tbody>
                </table></div>
              )}
              <div className="mb-2 flex items-center justify-between"><h2 className="text-lg font-bold">Trades</h2>
                <Button className="small" onClick={() => downloadCsv(shown.trades, `${data.name}_trades.csv`)}>⬇ CSV</Button></div>
              <div className="table-wrap"><table className="data">
                <thead><tr><th>Entry (IST)</th><th>Exit (IST)</th><th>Side</th><th className="num">Entry</th><th className="num">Exit</th><th className="num">Return %</th><th>Exit reason</th><th className="num">Candles</th><th>Trigger</th></tr></thead>
                <tbody>{shown.trades.map((t, i) => (
                  <tr key={i}><td>{istTime(t.entry_time)}</td><td>{istTime(t.exit_time)}</td><td className={t.side === 'LONG' ? 'up' : 'dn'}>{t.side}</td>
                    <td className="num">{fmt(t.entry)}</td><td className="num">{fmt(t.exit)}</td><td className={`num ${t.ret_pct >= 0 ? 'up' : 'dn'}`}>{t.ret_pct > 0 ? '+' : ''}{t.ret_pct.toFixed(2)}%</td>
                    <td>{t.reason}</td><td className="num">{t.candles}</td><td>{t.trigger}</td></tr>))}</tbody>
              </table></div>
            </>
          )}
        </>
      )}
    </>
  );
}
