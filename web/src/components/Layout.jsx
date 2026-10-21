import { useEffect, useState } from 'react';
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { api, onSlowChange } from '../lib/api.js';
import { useAuth } from '../context/Auth.jsx';
import Assistant from './Assistant.jsx';
import { Pill } from './ui.jsx';

const NAV = [
  ['Trade', [['scanner', '📡', 'Scanner'], ['gold', '🥇', 'TradingView · XAUUSD'], ['mood', '🐂', 'Market mood'], ['backtest', '🧪', 'Backtest']]],
  ['Setup', [['connect', '🔗', 'Connect'], ['account', '👤', 'My account']]],
];

/** Signed-in shell: sidebar navigation, the user card, the waking-server notice and Bull & Bear. */
export default function Layout() {
  const { loading, user, connections, signOut } = useAuth();
  const [menu, setMenu] = useState(false);
  const [waking, setWaking] = useState(false);
  const [pending, setPending] = useState(0);
  const loc = useLocation();
  const nav = useNavigate();

  useEffect(() => onSlowChange(setWaking), []);
  useEffect(() => setMenu(false), [loc.pathname]);
  useEffect(() => {
    if (!user?.is_admin) return;
    api.get('/api/admin/users').then((r) => setPending(r.users.filter((u) => u.status === 'pending').length)).catch(() => {});
  }, [user, loc.pathname]);

  if (loading) return <div className="grid min-h-screen place-items-center muted"><span className="spinner" /></div>;
  if (!user) return <Navigate to="/signin" replace state={{ from: loc.pathname }} />;

  const up = connections?.upstox?.token;
  const cs = connections?.coinswitch;
  const initials = (user.name || user.email).replace('@', ' ').split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  const groups = user.is_admin ? [...NAV, ['Admin', [['admin', '🛡️', pending ? `Users (${pending} pending)` : 'Users']]]] : NAV;

  const sidebar = (
    <div className="flex h-full flex-col gap-1 p-4">
      <Link to="/" className="mb-3 flex items-center gap-2.5 no-underline">
        <img src={`${import.meta.env.BASE_URL}mark.svg`} alt="" width="34" height="34" />
        <span className="display text-lg font-bold">Scalp5</span>
      </Link>
      <nav className="nav">
        {groups.map(([g, items]) => (
          <div key={g}>
            <div className="group">{g}</div>
            {items.map(([to, icon, label]) => (
              <NavLink key={to} to={`/app/${to}`}><span>{icon}</span>{label}</NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="mt-auto pt-4">
        <div className="card p-3" style={{ boxShadow: 'none' }}>
          <div className="flex items-center gap-2.5">
            <div className="avatar">{initials || '?'}</div>
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{user.name || user.email.split('@')[0]}</div>
              <div className="truncate text-xs muted">{user.email}</div>
            </div>
            {user.is_admin && <Pill tone="brand plain">ADMIN</Pill>}
          </div>
          <div className="mt-2.5 flex flex-wrap gap-1.5 border-t pt-2.5" style={{ borderColor: 'var(--border)' }}>
            <Pill tone={up ? 'bull' : 'bear'}>Upstox</Pill><Pill tone={cs ? 'bull' : 'bear'}>CoinSwitch</Pill>
          </div>
        </div>
        <button type="button" className="btn ghost small mt-2" onClick={async () => { await signOut(); nav('/signin'); }}>↩ Sign out</button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[260px_1fr]">
      <aside className="side sticky top-0 hidden h-screen lg:block">{sidebar}</aside>
      <div className="side sticky top-0 z-30 flex items-center justify-between border-b px-4 py-2.5 lg:hidden" style={{ borderColor: 'var(--border)' }}>
        <span className="flex items-center gap-2"><img src={`${import.meta.env.BASE_URL}mark.svg`} alt="" width="28" height="28" /><b className="display">Scalp5</b></span>
        <button type="button" className="btn small" onClick={() => setMenu((x) => !x)} aria-expanded={menu}>☰ Menu</button>
      </div>
      {menu && <div className="side fixed inset-0 top-[53px] z-30 overflow-y-auto lg:hidden">{sidebar}</div>}
      {waking && (
        <div className="waking banner warn flex items-center gap-2 shadow-lg">
          <span className="spinner" /> Waking the server up… (free hosting sleeps when idle; this can take up to a minute)
        </div>
      )}
      <main className="mx-auto w-full max-w-[1240px] px-4 pb-32 pt-8 sm:px-8">
        <Outlet />
      </main>
      <Assistant />
    </div>
  );
}
