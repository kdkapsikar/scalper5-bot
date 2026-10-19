import { useEffect, useState } from 'react';

export function PageHeader({ eyebrow, title, children, actions }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1 className="page-title">{title}</h1>
        {children && <p className="lead text-[.95rem]">{children}</p>}
      </div>
      {actions}
    </header>
  );
}

export function Metric({ label, value, tone }) {
  const color = { bull: 'var(--bull)', bear: 'var(--bear)', warn: 'var(--warn)' }[tone];
  return (
    <div className="metric">
      <div className="label" style={color ? { color } : undefined}>{label}</div>
      <div className="value" title={String(value)}>{value}</div>
    </div>
  );
}

export function Metrics({ children }) {
  return <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(140px,1fr))] mb-5">{children}</div>;
}

export function Banner({ kind = 'info', children }) {
  return <div className={`banner ${kind} my-3`}>{children}</div>;
}

export function Empty({ icon, title, children }) {
  return <div className="empty"><div className="ic">{icon}</div><b>{title}</b>{children}</div>;
}

export function Segmented({ options, value, onChange }) {
  return (
    <div className="seg" role="group">
      {options.map((o) => {
        const [v, label] = Array.isArray(o) ? o : [o, o];
        return <button key={v} type="button" aria-pressed={v === value} onClick={() => onChange(v)}>{label}</button>;
      })}
    </div>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}

export function Button({ busy, children, className = '', ...props }) {
  return (
    <button type="button" className={`btn ${className}`} disabled={busy || props.disabled} {...props}>
      {busy && <span className="spinner" />}{children}
    </button>
  );
}

export function Progress({ done, total, label }) {
  const p = total ? Math.round((100 * done) / total) : 0;
  return (
    <div className="my-4">
      <div className="mb-1.5 flex justify-between text-sm muted"><span>{label}</span><span>{total ? `${done}/${total}` : ''}</span></div>
      <div className="progress"><i style={{ width: `${total ? p : 8}%` }} /></div>
    </div>
  );
}

export function ErrorText({ error }) {
  if (!error) return null;
  return <Banner kind="bad">{String(error.message || error)}</Banner>;
}

/** A value kept in localStorage (per browser), for remembered choices like the scanner's groups. */
export function useStored(key, initial) {
  const [v, setV] = useState(() => {
    try { const s = localStorage.getItem(`s5:${key}`); return s === null ? initial : JSON.parse(s); } catch { return initial; }
  });
  useEffect(() => { try { localStorage.setItem(`s5:${key}`, JSON.stringify(v)); } catch { /* ignore */ } }, [key, v]);
  return [v, setV];
}

export function Pill({ tone = '', children }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}
