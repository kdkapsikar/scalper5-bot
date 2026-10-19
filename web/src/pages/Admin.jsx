import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api.js';
import { downloadCsv, localDateTime } from '../lib/format.js';
import { useAuth } from '../context/Auth.jsx';
import { Banner, Button, ErrorText, Metric, Metrics, PageHeader, Pill } from '../components/ui.jsx';

export default function Admin() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState(null);
  const [audit, setAudit] = useState([]);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState('');
  const [filter, setFilter] = useState('');

  const load = useCallback(async () => {
    try {
      const [u, a] = await Promise.all([api.get('/api/admin/users'), api.get('/api/admin/audit?limit=1000')]);
      setUsers(u.users); setAudit(a.audit);
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function act(u, action, done) {
    if (action === 'delete' && !window.confirm(`Delete ${u.email} and their saved keys? This can't be undone.`)) return;
    setBusy(`${u.id}:${action}`); setMsg(null);
    try {
      const r = await api.post(`/api/admin/users/${u.id}`, { action });
      setUsers(r.users); setMsg({ ok: true, text: done });
      api.get('/api/admin/audit?limit=1000').then((a) => setAudit(a.audit)).catch(() => {});
    } catch (e) { setMsg({ ok: false, text: e.message }); } finally { setBusy(''); }
  }

  const shownAudit = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? audit.filter((a) => [a.who, a.target, a.action].some((x) => x.toLowerCase().includes(q))) : audit;
  }, [audit, filter]);

  if (error) return <ErrorText error={error} />;
  if (!users) return <div className="flex items-center gap-2 muted"><span className="spinner" /> Loading…</div>;
  const pending = users.filter((u) => u.status === 'pending');
  const tone = { active: 'bull', pending: 'warn', disabled: 'bear' };

  return (
    <>
      <PageHeader eyebrow="Admin" title="Users">Who has signed up, approvals and roles. Broker keys are never shown here.</PageHeader>
      <Metrics>
        <Metric label="Signed up" value={users.length} /><Metric label="Pending approval" value={pending.length} tone={pending.length ? 'warn' : undefined} />
        <Metric label="Active" value={users.filter((u) => u.status === 'active').length} />
        <Metric label="Admins" value={users.filter((u) => u.role === 'admin' && u.status === 'active').length} />
      </Metrics>
      {msg && <Banner kind={msg.ok ? 'ok' : 'bad'}>{msg.text}</Banner>}
      {pending.length > 0 && (
        <section className="mb-6">
          <h2 className="mb-3 text-lg font-bold">Waiting for approval</h2>
          <div className="grid gap-2">{pending.map((u) => (
            <div key={u.id} className="card flex flex-wrap items-center gap-3 p-3">
              <div className="min-w-0 flex-1"><b>{u.name || '(no name)'}</b><div className="truncate text-sm muted">{u.email}</div></div>
              <span className="text-sm faint">since {localDateTime(u.created_at)}</span>
              <Button className="primary small" busy={busy === `${u.id}:approve`} onClick={() => act(u, 'approve', `Approved ${u.email}.`)}>Approve</Button>
              <Button className="danger small" busy={busy === `${u.id}:delete`} onClick={() => act(u, 'delete', `Rejected and removed ${u.email}.`)}>Reject</Button>
            </div>))}</div>
        </section>
      )}
      <h2 className="mb-3 text-lg font-bold">Everyone</h2>
      <div className="table-wrap mb-8"><table className="data">
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Signed up</th><th>Last sign-in</th><th /></tr></thead>
        <tbody>{users.map((u) => {
          const self = u.id === me.id;
          return (
            <tr key={u.id}>
              <td className="font-semibold">{u.name || '-'}</td><td>{u.email}</td>
              <td>{u.role === 'admin' ? <Pill tone="brand">admin</Pill> : 'user'}</td><td><Pill tone={tone[u.status]}>{u.status}</Pill></td>
              <td>{localDateTime(u.created_at)}</td><td>{localDateTime(u.last_login_at)}</td>
              <td className="text-right">{self ? <span className="text-sm faint">you</span> : (
                <span className="inline-flex gap-1.5">
                  {u.status === 'active'
                    ? <Button className="small" busy={busy === `${u.id}:disable`} onClick={() => act(u, 'disable', `Disabled ${u.email}; they are signed out within a minute.`)}>Disable</Button>
                    : <Button className="small" busy={busy === `${u.id}:enable`} onClick={() => act(u, 'enable', `${u.email} can sign in now.`)}>{u.status === 'pending' ? 'Approve' : 'Enable'}</Button>}
                  {u.role === 'user'
                    ? <Button className="small" busy={busy === `${u.id}:make_admin`} onClick={() => act(u, 'make_admin', `${u.email} is now an admin.`)}>Make admin</Button>
                    : <Button className="small" busy={busy === `${u.id}:make_user`} onClick={() => act(u, 'make_user', `${u.email} is now a regular user.`)}>Make user</Button>}
                  <Button className="danger small" busy={busy === `${u.id}:delete`} onClick={() => act(u, 'delete', `Deleted ${u.email}.`)}>Delete</Button>
                </span>)}</td>
            </tr>);
        })}</tbody>
      </table></div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-bold">Activity log</h2>
        <div className="flex gap-2">
          <input className="input w-64" placeholder="Filter by email or action" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <Button onClick={() => downloadCsv(shownAudit, 'scalp5_activity.csv')}>⬇ CSV</Button>
        </div>
      </div>
      <div className="table-wrap"><table className="data">
        <thead><tr><th>Time</th><th>By</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
        <tbody>{shownAudit.slice(0, 300).map((a, i) => (
          <tr key={i}><td>{localDateTime(a.time)}</td><td>{a.who}</td><td>{a.action}</td><td>{a.target}</td><td className="muted" style={{ whiteSpace: 'normal' }}>{a.detail}</td></tr>))}</tbody>
      </table></div>
    </>
  );
}
