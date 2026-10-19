const IST = 'Asia/Kolkata';

/** Prices like the Python side's fmt(): 2 decimals, more for small numbers, Indian digit grouping. */
export function fmt(x) {
  if (x === null || x === undefined || Number.isNaN(x)) return '-';
  const a = Math.abs(x);
  const digits = a >= 1000 ? 2 : a >= 1 ? 2 : a >= 0.01 ? 4 : 6;
  return x.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(x, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return '-';
  return `${x > 0 ? '+' : ''}${x.toFixed(digits)}%`;
}

export function istTime(iso, withDate = true) {
  if (!iso) return '-';
  const d = new Date(iso);
  return d.toLocaleString('en-IN', {
    timeZone: IST, hour: '2-digit', minute: '2-digit', hour12: false,
    ...(withDate ? { day: '2-digit', month: 'short' } : {}),
  });
}

export function localDateTime(iso) {
  if (!iso) return 'never';
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

/** Download rows (array of flat objects) as a CSV file. */
export function downloadCsv(rows, filename) {
  if (!rows?.length) return;
  const cols = Object.keys(rows[0]);
  const esc = (v) => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = [cols.join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** Tiny, safe markdown for the assistant: **bold**, *italic*, "- " lists and line breaks. */
export function miniMarkdown(text) {
  const escape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const inline = (s) => escape(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\*(.+?)\*/g, '<i>$1</i>');
  const out = [];
  let list = [];
  const flush = () => { if (list.length) { out.push(`<ul>${list.join('')}</ul>`); list = []; } };
  for (const line of text.split('\n')) {
    if (/^\s*- /.test(line)) list.push(`<li>${inline(line.replace(/^\s*- /, ''))}</li>`);
    else { flush(); if (line.trim()) out.push(`<p>${inline(line)}</p>`); }
  }
  flush();
  return out.join('');
}
