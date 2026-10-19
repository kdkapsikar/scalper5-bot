import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api.js';
import { miniMarkdown } from '../lib/format.js';
import { useAuth } from '../context/Auth.jsx';
import Mascot from './Mascot.jsx';

const MENU = [
  ['mood', '🐂🐻 Market mood'], ['signals', '⚡ Live signals'], ['ticker', '🔎 Check a ticker'],
  ['explain', '📚 Explain'], ['connections', '🔌 My connections'],
];

function moodLabel(avg) {
  if (avg === null || avg === undefined) return null;
  const label = avg >= 40 ? 'Strong Bull' : avg >= 15 ? 'Bull' : avg > -15 ? 'Neutral' : avg > -40 ? 'Bear' : 'Strong Bear';
  const tone = avg >= 15 ? 'var(--bull)' : avg <= -15 ? 'var(--bear)' : 'var(--muted)';
  return { label, tone };
}

/** Bull & Bear: the floating launcher on every signed-in page, and the chat panel it opens. */
export default function Assistant() {
  const { user, mood, setMood } = useAuth();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const end = useRef(null);
  const bullLeads = mood === null || mood >= 0;
  const m = moodLabel(mood);

  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [msgs, busy]);
  useEffect(() => {
    if (open && msgs.length === 0) ask({ kind: 'help' }, null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function ask(body, shown) {
    if (shown) setMsgs((x) => [...x, { who: 'user', text: shown }]);
    setBusy(true);
    try {
      const r = await api.post('/api/assistant', body);
      if (r.mood !== null && r.mood !== undefined) setMood(r.mood);
      setMsgs((x) => [...x, ...r.messages]);
    } catch (e) {
      setMsgs((x) => [...x, { who: 'bear', text: `Hmm, that didn't work: ${e.message} 🐻` }]);
    } finally {
      setBusy(false);
    }
  }

  function submit(e) {
    e.preventDefault();
    const t = text.trim();
    if (!t || busy) return;
    setText('');
    ask({ text: t }, t);
  }

  return (
    <>
      {!open && (
        <div className="fixed bottom-4 right-4 z-40 flex flex-col items-end gap-1.5">
          <div className="bubble hidden sm:block">
            {m ? <>Market mood: <b style={{ color: m.tone }}>{m.label}</b> ({mood > 0 ? '+' : ''}{Math.round(mood)}). Want the details?</>
               : <>Namaste{user?.name ? `, ${user.name.split(' ')[0]}` : ''}! 🐂🐻 Ask us how the market looks.</>}
          </div>
          <div className="flex items-end" style={{ filter: 'drop-shadow(0 10px 18px rgba(20,26,43,.28))' }}>
            <Mascot who={bullLeads ? 'bear' : 'bull'} size={62} style={{ marginRight: -14, opacity: 0.92 }} />
            <Mascot who={bullLeads ? 'bull' : 'bear'} size={80} />
          </div>
          <button type="button" className="btn primary" style={{ borderRadius: 999 }} onClick={() => setOpen(true)}>💬 Ask Bull &amp; Bear</button>
        </div>
      )}
      {open && (
        <div className="card fixed inset-x-2 bottom-2 top-16 z-50 flex flex-col sm:inset-auto sm:bottom-4 sm:right-4 sm:h-[620px] sm:max-h-[calc(100vh-2rem)] sm:w-[440px]"
          role="dialog" aria-label="Bull and Bear assistant">
          <div className="flex items-center gap-3 border-b px-4 py-3" style={{ borderColor: 'var(--border)' }}>
            <div className="flex"><Mascot who="bull" size={42} /><Mascot who="bear" size={42} style={{ marginLeft: -12 }} /></div>
            <div className="min-w-0 flex-1">
              <div className="display font-bold">Bull &amp; Bear</div>
              <div className="text-xs faint">Your market desk · reads your own broker data · not advice</div>
            </div>
            <button type="button" className="btn ghost small" onClick={() => setOpen(false)} aria-label="Close">✕</button>
          </div>
          <div className="flex flex-wrap gap-1.5 px-4 pt-3">
            {MENU.map(([k, label]) => (
              <button key={k} type="button" className="chip" disabled={busy} onClick={() => ask({ kind: k }, label)}>{label}</button>
            ))}
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {msgs.map((x, i) => (
              <div key={i} className={`chatmsg ${x.who === 'user' ? 'me' : ''}`}>
                {x.who !== 'user' && <span className="av"><Mascot who={x.who} size={34} /></span>}
                <div className="txt" dangerouslySetInnerHTML={{ __html: miniMarkdown(x.text) }} />
              </div>
            ))}
            {busy && <div className="flex items-center gap-2 text-sm muted"><span className="spinner" /> Bull and Bear are reading the tape…</div>}
            <div ref={end} />
          </div>
          <form onSubmit={submit} className="flex gap-2 border-t p-3" style={{ borderColor: 'var(--border)' }}>
            <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Try: nifty, any signals?, what is rsi" maxLength={500} />
            <button type="submit" className="btn primary" disabled={busy || !text.trim()}>Ask</button>
          </form>
        </div>
      )}
    </>
  );
}
