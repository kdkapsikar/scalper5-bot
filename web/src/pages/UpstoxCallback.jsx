import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../lib/api.js';
import { useAuth } from '../context/Auth.jsx';
import Mascot from '../components/Mascot.jsx';
import { Banner } from '../components/ui.jsx';

/** Upstox sends people back here with ?code&state after the daily login; the state says whose token it is. */
export default function UpstoxCallback() {
  const [params] = useSearchParams();
  const { user, refresh } = useAuth();
  const [result, setResult] = useState(null);
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    const code = params.get('code');
    const state = params.get('state') || '';
    if (!code) { setResult({ ok: false, text: 'Upstox did not send a login code. Start the login again from the Connect page.' }); return; }
    api.post('/api/upstox/callback', { code, state })
      .then((r) => { setResult({ ok: true, text: r.message }); refresh(); })
      .catch((e) => setResult({ ok: false, text: e.message }));
  }, [params, refresh]);

  return (
    <div className="mx-auto grid min-h-screen max-w-md place-items-center px-4">
      <div className="card w-full p-6 text-center">
        <div className="flex justify-center"><Mascot who={result && !result.ok ? 'bear' : 'bull'} size={110} /></div>
        <h1 className="page-title text-2xl">Upstox login</h1>
        {!result && <p className="muted"><span className="spinner" /> Saving today's token…</p>}
        {result && <Banner kind={result.ok ? 'ok' : 'bad'}>{result.text}</Banner>}
        {result && <Link className="btn primary mt-2" to={user ? '/app/connect' : '/signin'}>{user ? 'Back to Connect' : 'Sign in'}</Link>}
      </div>
    </div>
  );
}
