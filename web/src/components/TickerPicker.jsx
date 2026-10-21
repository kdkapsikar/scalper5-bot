import { useEffect, useMemo, useRef, useState } from 'react';

const GROUP_ORDER = ['Index futures', 'Stock futures', 'MCX futures', 'Crypto', 'Forex & metals', 'Custom'];

/**
 * Searchable ticker picker. Opening it shows every instrument, grouped by market; typing filters by name or group.
 * Keyboard: ↑ ↓ to move, Enter to pick, Esc to close. What you type never replaces the chosen ticker until you pick.
 */
export default function TickerPicker({ instruments, value, onChange, label = 'Ticker' }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [hi, setHi] = useState(0);
  const box = useRef(null);
  const list = useRef(null);

  // Market by market (in the app's usual order), then alphabetically, so each group appears once.
  const sorted = useMemo(() => {
    const rank = (g) => { const k = GROUP_ORDER.indexOf(g); return k < 0 ? GROUP_ORDER.length : k; };
    return [...instruments].sort((a, b) => rank(a.group) - rank(b.group) || a.name.localeCompare(b.name));
  }, [instruments]);

  const matches = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return sorted.filter((i) => words.every((w) => `${i.name} ${i.group}`.toLowerCase().includes(w)));
  }, [sorted, query]);

  const groups = useMemo(() => {
    const out = [];
    for (const i of matches) {
      const last = out.at(-1);
      if (last && last.group === i.group) last.items.push(i);
      else out.push({ group: i.group, items: [i] });
    }
    return out;
  }, [matches]);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  useEffect(() => { setHi(0); }, [query]);
  useEffect(() => {
    list.current?.querySelector(`[data-i="${hi}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [hi, open]);

  function show() {
    setQuery('');
    setOpen(true);
    const at = sorted.findIndex((i) => i.name === value);
    setHi(at < 0 ? 0 : at);
  }

  function pick(i) {
    onChange(i.name);
    setOpen(false);
    setQuery('');
  }

  function onKey(e) {
    if (!open && (e.key === 'ArrowDown' || e.key === 'Enter')) { e.preventDefault(); show(); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => Math.min(h + 1, matches.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); if (matches[hi]) pick(matches[hi]); }
    else if (e.key === 'Escape') { setOpen(false); setQuery(''); }
  }

  let n = -1;
  return (
    <div className="field relative" ref={box}>
      <span>{label}</span>
      <div className="relative">
        <input className="input pr-9" role="combobox" aria-expanded={open} aria-controls="ticker-list" autoComplete="off"
          value={open ? query : value} placeholder={open ? `Search ${instruments.length} instruments… (e.g. gold, reliance, btc)` : 'Pick a ticker'}
          onFocus={show} onClick={() => !open && show()} onChange={(e) => { setQuery(e.target.value); setOpen(true); }} onKeyDown={onKey} />
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs faint">▾</span>
      </div>
      {open && (
        <div id="ticker-list" ref={list} role="listbox"
          className="card absolute left-0 right-0 top-full z-30 mt-1 max-h-80 overflow-y-auto p-1" style={{ boxShadow: 'var(--shadow)' }}>
          {groups.length === 0 && <div className="p-3 text-sm muted">No instrument matches “{query}”.</div>}
          {groups.map((g) => (
            <div key={g.group}>
              <div className="sticky top-0 px-2.5 py-1.5 text-[.7rem] font-bold uppercase tracking-wider faint" style={{ background: 'var(--card)' }}>
                {g.group} <span className="font-normal">· {g.items.length}</span>
              </div>
              {g.items.map((i) => {
                n += 1;
                const idx = n;
                return (
                  <div key={i.name} data-i={idx} role="option" aria-selected={i.name === value}
                    className="flex cursor-pointer items-center justify-between rounded-lg px-2.5 py-1.5 text-sm"
                    style={{ background: idx === hi ? 'color-mix(in srgb, var(--brand) 12%, transparent)' : undefined,
                      color: i.name === value ? 'var(--brand)' : undefined, fontWeight: i.name === value ? 600 : 400 }}
                    onMouseEnter={() => setHi(idx)} onMouseDown={(e) => { e.preventDefault(); pick(i); }}>
                    <span>{i.name}</span>{i.name === value && <span>✓</span>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
