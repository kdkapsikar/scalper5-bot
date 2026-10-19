import { useState } from 'react';
import { api, tokenStore } from '../lib/api.js';
import { localDateTime } from '../lib/format.js';
import { useAuth } from '../context/Auth.jsx';
import { Banner, Field, Metric, Metrics, PageHeader } from '../components/ui.jsx';

export default function Account() {
  const { user } = useAuth();
  const [f, setF] = useState({ old: '', new: '', again: '' });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  async function change(e) {
    e.preventDefault();
    if (f.new !== f.again) { setMsg({ ok: false, text: "The two new passwords don't match." }); return; }
    setBusy(true); setMsg(null);
    try {
      const r = await api.post('/api/me/password', { old: f.old, new: f.new });
      tokenStore.set(r.token);
      setF({ old: '', new: '', again: '' });
      setMsg({ ok: true, text: "Password changed. You've been signed out on your other devices." });
    } catch (err) { setMsg({ ok: false, text: err.message }); } finally { setBusy(false); }
  }
  if (!user) return null;
  return (
    <>
      <PageHeader eyebrow="Setup" title="My account" />
      <Metrics>
        <Metric label="Email" value={user.email} /><Metric label="Role" value={user.role === 'admin' ? 'Admin' : 'User'} />
        <Metric label="Member since" value={new Date(user.created_at).toLocaleDateString('en-IN', { dateStyle: 'medium' })} />
      </Metrics>
      <p className="mb-6 text-sm muted">Last sign-in: {localDateTime(user.last_login_at)}</p>
      <h2 className="mb-3 text-lg font-bold">Change password</h2>
      <form onSubmit={change} className="card grid max-w-lg gap-4 p-5">
        <Field label="Current password"><input className="input" type="password" autoComplete="current-password" value={f.old} onChange={(e) => setF({ ...f, old: e.target.value })} /></Field>
        <Field label="New password" hint="At least 10 characters, mixing letters with numbers or symbols."><input className="input" type="password" autoComplete="new-password" value={f.new} onChange={(e) => setF({ ...f, new: e.target.value })} /></Field>
        <Field label="Repeat new password"><input className="input" type="password" autoComplete="new-password" value={f.again} onChange={(e) => setF({ ...f, again: e.target.value })} /></Field>
        <div><button type="submit" className="btn primary" disabled={busy || !f.old || !f.new}>{busy && <span className="spinner" />}Change password</button></div>
        {msg && <Banner kind={msg.ok ? 'ok' : 'bad'}>{msg.text}</Banner>}
      </form>
    </>
  );
}
