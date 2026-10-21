import { useState } from 'react';
import { api, runJob } from '../lib/api.js';
import { useAuth } from '../context/Auth.jsx';
import { Banner, Button, ErrorText, Field, Metric, Metrics, PageHeader, Progress, Segmented } from '../components/ui.jsx';

function KeyForm({ fields, onSaved, submit = 'Save' }) {
  const [values, setValues] = useState(() => Object.fromEntries(fields.map((f) => [f.name, f.initial ?? ''])));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  async function save(e) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const r = await api.put('/api/keys', { values });
      setMsg({ ok: true, text: r.saved.length ? `Saved: ${r.saved.join(', ')}` : 'Nothing to save.' });
      setValues((v) => Object.fromEntries(Object.entries(v).map(([k, x]) => [k, fields.find((f) => f.name === k)?.secret ? '' : x])));
      onSaved?.();
    } catch (err) { setMsg({ ok: false, text: err.message }); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={save} className="card grid gap-4 p-5">
      {fields.map((f) => (
        <Field key={f.name} label={f.label} hint={f.hint}>
          {f.options ? (
            <select className="input" value={values[f.name]} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
              {f.options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          ) : (
            <input className="input" type={f.secret ? 'password' : 'text'} autoComplete="off" value={values[f.name]}
              placeholder={f.saved ? 'saved (leave empty to keep)' : f.placeholder || ''}
              onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
          )}
        </Field>
      ))}
      <div><button type="submit" className="btn primary" disabled={busy}>{busy && <span className="spinner" />}{submit}</button></div>
      {msg && <Banner kind={msg.ok ? 'ok' : 'bad'}>{msg.text}</Banner>}
    </form>
  );
}

function UpstoxTab({ me, refresh }) {
  const c = me.connections;
  const saved = (k) => k in c.saved;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [code, setCode] = useState('');
  const [msg, setMsg] = useState(null);

  async function login() {
    setBusy(true); setError(null);
    try { window.location.assign((await api.post('/api/upstox/login-url')).url); } catch (e) { setError(e); setBusy(false); }
  }
  async function finish(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { setMsg((await api.post('/api/upstox/code', { code, state: '' })).message); setCode(''); refresh(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div className="grid gap-6">
      <section>
        <h2 className="mb-1 text-lg font-bold">Step 1: your Upstox app (one time)</h2>
        <p className="mb-3 text-sm muted">Create an app on the Upstox developer site under your own Upstox account and register this exact
          redirect URI there: <code className="rounded px-1.5 py-0.5" style={{ background: 'var(--card2)' }}>{me.upstox_redirect_default}</code></p>
        <KeyForm onSaved={refresh} submit="Save Upstox app details" fields={[
          { name: 'UPSTOX_API_KEY', label: 'API key', secret: true, saved: saved('UPSTOX_API_KEY') },
          { name: 'UPSTOX_API_SECRET', label: 'API secret', secret: true, saved: saved('UPSTOX_API_SECRET') },
          { name: 'UPSTOX_REDIRECT_URI', label: 'Redirect URI', initial: c.upstox.redirect_uri || me.upstox_redirect_default },
        ]} />
      </section>
      <section>
        <h2 className="mb-1 text-lg font-bold">Step 2: today's login (every trading morning)</h2>
        <p className="mb-3 text-sm muted">Upstox tokens expire every day. Log in on Upstox; it sends you back here and the token is saved to your account.</p>
        <Button className="primary" busy={busy} disabled={!c.upstox.app_saved} onClick={login}>Log in to Upstox →</Button>
        {!c.upstox.app_saved && <span className="ml-3 text-sm faint">Save your API key and secret first.</span>}
        <ErrorText error={error} />
        {msg && <Banner kind="ok">{msg}</Banner>}
        <details className="fold mt-4"><summary>Landed somewhere else? Paste the code or the whole address</summary>
          <form onSubmit={finish} className="flex flex-wrap gap-2">
            <input className="input flex-1" value={code} onChange={(e) => setCode(e.target.value)} placeholder="https://…/upstox/callback?code=…" />
            <button type="submit" className="btn" disabled={busy || !code.trim()}>Finish login</button>
          </form>
        </details>
        <details className="fold mt-3"><summary>Advanced: paste an access token you already have</summary>
          <KeyForm onSaved={refresh} submit="Save token" fields={[{ name: 'UPSTOX_ACCESS_TOKEN', label: 'Access token', secret: true }]} />
        </details>
      </section>
    </div>
  );
}

function TestTab({ me }) {
  const [scope, setScope] = useState('sample');
  const [prog, setProg] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  async function run() {
    setError(null); setProg({ done: 0, total: 0 });
    try { setData(await runJob(() => api.post(`/api/connections/test?scope=${scope}`), setProg)); } catch (e) { setError(e); } finally { setProg(null); }
  }
  const ok = data?.rows.filter((r) => r.Status.startsWith('OK')).length;
  return (
    <div>
      <p className="mb-3 text-sm muted">Fetches real candles and shows what came back. Check that PAXGUSDT and XAUUSDT are OK. NSE futures show
        "market closed" outside 9:15-15:30 IST.</p>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Segmented options={[['sample', 'Sample (3 per group)'], ['all', 'Everything']]} value={scope} onChange={setScope} />
        <Button className="primary" busy={!!prog} onClick={run}>Run connection test</Button>
      </div>
      {prog && <Progress done={prog.done} total={prog.total} label="Testing…" />}
      <ErrorText error={error} />
      {data && (
        <>
          {data.warnings.map((w) => <Banner key={w} kind="warn">{w}</Banner>)}
          <p className="mb-2 font-semibold">{ok} of {data.rows.length} OK</p>
          <div className="table-wrap"><table className="data">
            <thead><tr><th>Ticker</th><th>Group</th><th className="num">Candles</th><th>Last closed candle (IST)</th><th>Status</th></tr></thead>
            <tbody>{data.rows.map((r) => (
              <tr key={r.Ticker}><td className="font-semibold">{r.Ticker}</td><td>{r.Group}</td><td className="num">{r.Candles}</td>
                <td>{r['Last closed candle (IST)']}</td><td className={r.Status.startsWith('OK') ? 'up' : 'dn'} style={{ whiteSpace: 'normal' }}>{r.Status}</td></tr>))}</tbody>
          </table></div>
          {data.rows.some((r) => r.Status.startsWith('LOGIN')) && <Banner kind="warn">Some instruments need a login: finish the Upstox steps or add the CoinSwitch keys.</Banner>}
        </>
      )}
      <RemoveKeys me={me} />
    </div>
  );
}

function RemoveKeys({ me }) {
  const { refresh } = useAuth();
  const names = Object.keys(me.connections.saved);
  const [pick, setPick] = useState([]);
  const [busy, setBusy] = useState(false);
  if (!names.length) return null;
  return (
    <details className="fold mt-6"><summary>Remove saved keys</summary>
      <div className="flex flex-wrap gap-1.5">{names.map((n) => (
        <button key={n} type="button" className="chip" aria-pressed={pick.includes(n)} onClick={() => setPick(pick.includes(n) ? pick.filter((x) => x !== n) : [...pick, n])}>{n}</button>))}</div>
      <Button className="danger mt-3" busy={busy} disabled={!pick.length} onClick={async () => {
        setBusy(true); try { await api.del(`/api/keys?names=${pick.join(',')}`); setPick([]); await refresh(); } finally { setBusy(false); }
      }}>Remove selected</Button>
    </details>
  );
}

export default function Connect() {
  const { me, refresh } = useAuth();
  const [tab, setTab] = useState('upstox');
  if (!me) return null;
  const c = me.connections;
  const age = c.upstox.token_age_h;
  return (
    <>
      <PageHeader eyebrow="Setup · your broker accounts" title="Connect">
        Connect <b>your own</b> Upstox and CoinSwitch accounts (and OANDA, optionally). Keys are encrypted before they are stored and only used for your own pages;
        they are never shown again. The portal operator holds the encryption key, so use keys that can't withdraw funds.
      </PageHeader>
      <Metrics>
        <Metric label="Upstox token" value={c.upstox.token ? 'Saved' : 'Missing'} tone={c.upstox.token ? 'bull' : 'bear'} />
        <Metric label="Token age" value={age === null ? '-' : `${age} h`} tone={age !== null && age > 20 ? 'warn' : undefined} />
        <Metric label="CoinSwitch keys" value={c.coinswitch ? 'Saved' : 'Missing'} tone={c.coinswitch ? 'bull' : 'bear'} />
        <Metric label="OANDA token" value={c.oanda?.token ? `Saved (${c.oanda.env})` : 'Not set'} tone={c.oanda?.token ? 'bull' : undefined} />
      </Metrics>
      {age !== null && age > 20 && <Banner kind="warn">Your Upstox token is more than 20 hours old and has probably expired. Log in again below.</Banner>}
      <div className="mb-5"><Segmented options={[['upstox', '1 · Upstox (India)'], ['coinswitch', '2 · CoinSwitch (crypto)'], ['oanda', '3 · OANDA (forex & metals)'], ['test', '4 · Test connections']]} value={tab} onChange={setTab} /></div>
      {tab === 'upstox' && <UpstoxTab me={me} refresh={refresh} />}
      {tab === 'coinswitch' && (
        <div className="max-w-2xl">
          <p className="mb-3 text-sm muted">Create the key on CoinSwitch PRO with no withdrawal rights. The portal's server address changes, so an
            IP-restricted key will be rejected. Crypto candles are read only; nothing here places orders.</p>
          <KeyForm onSaved={refresh} submit="Save CoinSwitch keys" fields={[
            { name: 'COINSWITCH_API_KEY', label: 'API key', secret: true, saved: 'COINSWITCH_API_KEY' in c.saved },
            { name: 'COINSWITCH_SECRET_KEY', label: 'Secret key (hex)', secret: true, saved: 'COINSWITCH_SECRET_KEY' in c.saved },
          ]} />
        </div>
      )}
      {tab === 'oanda' && (
        <div className="max-w-2xl">
          <p className="mb-3 text-sm muted">Optional. Everyone already gets <b>XAUUSD (spot)</b>, real-time spot gold from a public index that
            tracks OANDA:XAUUSD within about $1-2. An OANDA token adds <b>XAUUSD (OANDA)</b>, OANDA's own prices.
            Any OANDA account works, including a free practice (demo) account. In OANDA's hub open <i>Manage API Access</i>,
            generate a personal access token, and pick the matching account type below. Prices are read only.</p>
          <KeyForm onSaved={refresh} submit="Save OANDA token" fields={[
            { name: 'OANDA_API_TOKEN', label: 'Personal access token', secret: true, saved: 'OANDA_API_TOKEN' in c.saved },
            { name: 'OANDA_ENV', label: 'Account type', initial: c.oanda?.env || 'practice',
              options: [['practice', 'Practice (demo) account'], ['live', 'Live account']] },
          ]} />
        </div>
      )}
      {tab === 'test' && <TestTab me={me} />}
    </>
  );
}
