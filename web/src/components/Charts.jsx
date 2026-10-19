import { useEffect, useRef } from 'react';
import { createChart, LineStyle } from 'lightweight-charts';

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const ist = (t) => new Date(t * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
// Axis labels: the date where a new day/month/year starts, otherwise the time (tickMarkType 0-2 = year/month/day).
const istTick = (t, type) => new Date(t * 1000).toLocaleString('en-IN', type < 3
  ? { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short' }
  : { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });

function useChart(build, deps, height) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const chart = createChart(el, {
      height, autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: css('--muted'), fontFamily: 'Inter, system-ui, sans-serif' },
      grid: { vertLines: { color: 'rgba(128,140,170,.12)' }, horzLines: { color: 'rgba(128,140,170,.12)' } },
      rightPriceScale: { borderColor: 'rgba(128,140,170,.25)' },
      timeScale: { borderColor: 'rgba(128,140,170,.25)', timeVisible: true, tickMarkFormatter: istTick },
      localization: { timeFormatter: ist },
      crosshair: { mode: 0 },
    });
    build(chart);
    chart.timeScale().fitContent();
    return () => chart.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}

/** Candles + SMA 22/33, 200 DEMA, Supertrend, pivots and signal markers (data from /api/ticker). */
export function CandleChart({ chart, height = 460 }) {
  const ref = useChart((c) => {
    const bull = css('--bull'); const bear = css('--bear');
    const candles = c.addCandlestickSeries({ upColor: bull, downColor: bear, borderUpColor: bull, borderDownColor: bear, wickUpColor: bull, wickDownColor: bear });
    candles.setData(chart.candles);
    const line = (data, color, width, style = LineStyle.Solid) => {
      const s = c.addLineSeries({ color, lineWidth: width, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData(data);
    };
    line(chart.sma_fast, '#f59e0b', 1.5);
    line(chart.sma_slow, '#0ea5e9', 1.5);
    line(chart.dema, '#7c5cff', 2.5);
    // Supertrend: green while up, red while down; the segment that jumps between bands at a flip is transparent.
    const st = (chart.supertrend || []).map((p, i, a) => ({
      time: p.time, value: p.value,
      color: i < a.length - 1 && a[i + 1].dir !== p.dir ? 'rgba(0,0,0,0)' : (p.dir === 1 ? bull : bear),  // a point colours the segment after it
    }));
    const sts = c.addLineSeries({ color: bull, lineWidth: 2, lineStyle: LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    sts.setData(st);
    for (const [k, v] of Object.entries(chart.pivots || {})) {
      if (['R2', 'R1', 'P', 'S1', 'S2'].includes(k)) {
        candles.createPriceLine({ price: v, color: 'rgba(128,140,170,.55)', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: k });
      }
    }
    candles.setMarkers(chart.signals.map((s) => ({
      time: s.time, position: s.side === 'LONG' ? 'belowBar' : 'aboveBar', shape: s.side === 'LONG' ? 'arrowUp' : 'arrowDown',
      color: s.side === 'LONG' ? bull : bear, text: s.side,
    })));
  }, [chart], height);
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs muted">
        <Legend color="#f59e0b">SMA 22</Legend><Legend color="#0ea5e9">SMA 33</Legend><Legend color="#7c5cff">200 DEMA</Legend>
        <Legend color="var(--bull)" dotted>Supertrend up</Legend><Legend color="var(--bear)" dotted>Supertrend down</Legend>
        <span>Dashed: daily pivots · times in IST</span>
      </div>
      <div ref={ref} style={{ height }} />
    </div>
  );
}

function Legend({ color, dotted, children }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <i style={{ width: 16, borderTop: `2px ${dotted ? 'dotted' : 'solid'} ${color}`, display: 'inline-block' }} />{children}
    </span>
  );
}

/** Cumulative return of a backtest's trades. */
export function EquityChart({ trades, height = 260 }) {
  const ref = useChart((c) => {
    let eq = 1;
    const seen = new Set();
    const data = [];
    for (const t of trades) {
      eq *= 1 + t.ret_pct / 100;
      let time = Math.floor(new Date(t.exit_time).getTime() / 1000);
      while (seen.has(time)) time += 1;           // lightweight-charts needs strictly increasing times
      seen.add(time);
      data.push({ time, value: +(100 * (eq - 1)).toFixed(3) });
    }
    const up = (data.at(-1)?.value ?? 0) >= 0;
    const color = up ? css('--bull') : css('--bear');
    const s = c.addAreaSeries({ lineColor: color, topColor: up ? 'rgba(22,163,74,.25)' : 'rgba(229,72,77,.25)', bottomColor: 'rgba(0,0,0,0)', lineWidth: 2, lineType: 1,
      priceFormat: { type: 'custom', formatter: (v) => `${v.toFixed(2)}%` } });
    s.setData(data);
    s.createPriceLine({ price: 0, color: 'rgba(128,140,170,.6)', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false });
  }, [trades], height);
  return <div ref={ref} style={{ height }} />;
}
