import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { api } from '../lib/api.js';
import { useAuth } from '../context/Auth.jsx';
import Mascot from '../components/Mascot.jsx';
import { Banner, Field, Segmented } from '../components/ui.jsx';

export default function SignIn() {
  const { user, signIn } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [tab, setTab] = useState('in');
  const [f, setF] = useState({ name: '', email: '', password: '', again: '' });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  if (user) return <Navigate to={loc.state?.from || '/app'} replace />;

  async function submit(e) {
    e.preventDefault();
    setMsg(null);
    if (tab === 'up' && f.password !== f.again) { setMsg({ ok: false, text: "The two passwords don't match." }); return; }
    setBusy(true);
    try {
      if (tab === 'in') {
        const r = await api.post('/api/auth/login', { email: f.email, password: f.password });
        await signIn(r.token);
        nav(loc.state?.from || '/app', { replace: true });
      } else {
        const r = await api.post('/api/auth/signup', { name: f.name, email: f.email, password: f.password });
        if (r.token) { await signIn(r.token); nav('/app', { replace: true }); }
        else { setMsg({ ok: true, text: r.message }); setTab('in'); }
      }
    } catch (err) { setMsg({ ok: false, text: err.message }); } finally { setBusy(false); }
  }

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="mx-auto grid min-h-screen max-w-[1120px] items-center gap-10 px-4 py-10 lg:grid-cols-[1.1fr_1fr]">
      <div className="hero order-2 hidden rounded-[22px] p-9 shadow-2xl lg:order-1 lg:block">
        <Link to="/" className="flex items-center gap-2.5 text-white no-underline"><img src={`${import.meta.env.BASE_URL}mark.svg`} alt="" width="40" height="40" /><b className="display text-xl">Scalp5</b></Link>
        <h1 className="display mt-6 text-[2.3rem] font-bold leading-tight">Read the tape.<br /><span className="grad">Bull or bear,</span><br />every 5 minutes.</h1>
        <p className="mt-3 text-[#c4c9e6]">Confluence signals and a live market mood for Indian index &amp; F&amp;O futures and crypto, from your own broker accounts.</p>
        <div className="mt-8 flex items-end"><Mascot who="bull" size={150} /><Mascot who="bear" size={150} style={{ marginLeft: -28 }} /></div>
      </div>
      <div className="order-1 lg:order-2">
        <Link to="/" className="mb-6 flex items-center gap-2 no-underline lg:hidden"><img src={`${import.meta.env.BASE_URL}mark.svg`} alt="" width="34" height="34" /><b className="display text-lg">Scalp5</b></Link>
        <h1 className="page-title">Welcome to Scalp5</h1>
        <p className="mb-5 muted">Sign in, or create an account. New accounts are approved by the portal admin.</p>
        <div className="mb-4"><Segmented options={[['in', 'Sign in'], ['up', 'Create account']]} value={tab} onChange={(v) => { setTab(v); setMsg(null); }} /></div>
        <form onSubmit={submit} className="card grid gap-4 p-5">
          {tab === 'up' && <Field label="Your name"><input className="input" value={f.name} onChange={set('name')} autoComplete="name" /></Field>}
          <Field label="Email"><input className="input" type="email" value={f.email} onChange={set('email')} autoComplete="email" placeholder="you@example.com" required /></Field>
          <Field label="Password" hint={tab === 'up' ? 'At least 10 characters, mixing letters with numbers or symbols.' : undefined}>
            <input className="input" type="password" value={f.password} onChange={set('password')} autoComplete={tab === 'in' ? 'current-password' : 'new-password'} required />
          </Field>
          {tab === 'up' && <Field label="Repeat password"><input className="input" type="password" value={f.again} onChange={set('again')} autoComplete="new-password" required /></Field>}
          <button type="submit" className="btn primary w-full" disabled={busy}>{busy && <span className="spinner" />}{tab === 'in' ? 'Sign in' : 'Create account'}</button>
          {msg && <Banner kind={msg.ok ? 'ok' : 'bad'}>{msg.text}</Banner>}
        </form>
        <p className="mt-4 text-xs faint">You stay signed in on this browser until you sign out. Analysis only: nothing here places orders or gives financial advice.</p>
      </div>
    </div>
  );
}
