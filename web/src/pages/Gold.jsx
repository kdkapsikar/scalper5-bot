import { useEffect, useRef } from 'react';
import Rules, { DEFAULT_RULES } from '../components/Rules.jsx';
import { PageHeader, Segmented, useStored } from '../components/ui.jsx';
import { TickerDetail } from './Scanner.jsx';

const SPOT = 'XAUUSD (spot)';
const TV_SYMBOL = 'OANDA:XAUUSD';

/** TradingView's own live chart (their free embeddable widget). */
function TradingViewChart({ height = 520 }) {
  const box = useRef(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    el.innerHTML = '<div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div>';
    const s = document.createElement('script');
    s.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    s.async = true;
    s.textContent = JSON.stringify({
      symbol: TV_SYMBOL, interval: '5', timezone: 'Asia/Kolkata', theme: dark ? 'dark' : 'light', style: '1',
      locale: 'en', autosize: true, allow_symbol_change: false, hide_side_toolbar: true, calendar: false,
      support_host: 'https://www.tradingview.com',
    });
    el.appendChild(s);
    return () => { el.innerHTML = ''; };
  }, []);
  return <div ref={box} className="tradingview-widget-container overflow-hidden rounded-xl" style={{ height }} />;
}

/** One page for spot gold: Scalp5's signal and checklists for XAUUSD (spot), next to TradingView's OANDA:XAUUSD. */
export default function Gold() {
  const [rules, setRules] = useStored('gold.rules', DEFAULT_RULES);
  const [lookback, setLookback] = useStored('gold.lookback', 3);
  return (
    <>
      <PageHeader eyebrow="Trade · spot gold" title="TradingView · XAUUSD"
        actions={<a className="btn" href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(TV_SYMBOL)}`} target="_blank" rel="noreferrer">Open on TradingView ↗</a>}>
        Spot gold only. Scalp5's signal, checklists and indicators below use real-time spot gold from a public index that tracks
        TradingView's <b>OANDA:XAUUSD</b> within about $1-2 (not the CoinSwitch XAUUSDT perpetual, which trades a few dollars above spot).
        TradingView's own chart is underneath for comparison. Refreshes every minute; analysis only, not advice.
      </PageHeader>
      <div className="card mb-5 grid gap-4 p-4 md:grid-cols-[1fr_1fr]">
        <div className="grid content-start gap-2">
          <span className="text-sm font-medium">Look back</span>
          <Segmented options={[[1, '1 candle'], [3, '3 candles'], [6, '6 candles'], [12, '12 candles']]} value={lookback} onChange={setLookback} />
          <span className="text-xs faint">Signals from the last N closed 5-minute candles count as current.</span>
        </div>
        <Rules value={rules} onChange={setRules} />
      </div>
      <TickerDetail name={SPOT} rules={rules} lookback={lookback} autoRefresh={60} />
      <section className="mt-8">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-bold">TradingView: {TV_SYMBOL} (5 minute)</h2>
          <span className="text-xs faint">Live chart from TradingView; prices may differ from the index above by a dollar or two.</span>
        </div>
        <div className="card p-2"><TradingViewChart /></div>
      </section>
    </>
  );
}
