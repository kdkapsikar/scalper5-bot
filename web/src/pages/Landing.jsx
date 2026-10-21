import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { API_URL } from '../lib/config.js';
import { useAuth } from '../context/Auth.jsx';
import Mascot from '../components/Mascot.jsx';

const FEATURES = [
  ['📡', 'Scanner', 'Scan every index and F&O stock future plus crypto, or open one ticker with its checklist and chart.'],
  ['🐂', 'Market mood', 'A score from -100 to +100 for India and crypto, built from 200 DEMA, Supertrend and SMA breadth, the leaders and RSI.', 'bull'],
  ['🐻', 'Bull & Bear assistant', 'Two mascots on every page. Ask about the mood, live setups, any ticker or any indicator.', 'bear'],
  ['🧪', 'Backtest', 'Replay the rules on recent history with fees and slippage, and compare the trigger modes.'],
  ['🔐', 'Your accounts, your keys', 'Everyone connects their own brokers. Keys are encrypted and only used for their own pages.'],
  ['🛡️', 'Invite-only access', "New sign-ups wait for the admin's approval, and every sign-in and admin action is logged."],
];

/** Public home page. It also starts waking the API (Render's free plan sleeps) so the app is ready on click. */
export default function Landing() {
  const { user } = useAuth();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let stop = false;
    const ping = (n) => fetch(`${API_URL}/api/health`, { cache: 'no-store' })
      .then((r) => { if (!stop && r.ok) setReady(true); })
      .catch(() => { if (!stop && n < 8) setTimeout(() => ping(n + 1), 5000); });
    ping(0);
    return () => { stop = true; };
  }, []);
  const cta = user ? '/app' : '/signin';

  return (
    <div>
      <nav className="side sticky top-0 z-20 border-b backdrop-blur" style={{ borderColor: 'var(--border)' }}>
        <div className="mx-auto flex h-16 max-w-[1120px] items-center justify-between px-6">
          <Link to="/" className="flex items-center gap-2.5 no-underline"><img src={`${import.meta.env.BASE_URL}mark.svg`} alt="" width="34" height="34" /><b className="display text-lg">Scalp5</b></Link>
          <div className="flex items-center gap-5 text-sm muted">
            <a href="#features" className="hidden no-underline sm:inline">Features</a>
            <a href="#start" className="hidden no-underline sm:inline">Get started</a>
            <Link to={cta} className="btn primary small">{user ? 'Open the app' : 'Sign in'}</Link>
          </div>
        </div>
      </nav>

      <header className="hero">
        <div className="mx-auto grid max-w-[1120px] items-center gap-10 px-6 py-16 md:grid-cols-[1.25fr_1fr] md:py-20">
          <div>
            <span className="glass inline-flex px-3 py-1.5 text-xs font-bold uppercase tracking-[.12em] text-[#aeb6ff]">🐂 🐻 5-minute market desk</span>
            <h1 className="display my-5 text-[clamp(2.3rem,5vw,3.6rem)] font-bold leading-[1.1]">Read the tape.<br /><span className="grad">Bull or bear,</span> every 5 minutes.</h1>
            <p className="mb-7 max-w-xl text-lg text-[#c4c9e6]">Confluence signals and a live Bull / Bear market mood for Indian index &amp; F&amp;O futures and crypto,
              computed from <b className="text-white">your own</b> Upstox and CoinSwitch accounts.</p>
            <div className="flex flex-wrap gap-3">
              <Link to={cta} className="btn primary" style={{ height: 46, padding: '0 22px' }}>{user ? 'Open the app →' : 'Sign in →'}</Link>
              <a href="#start" className="btn" style={{ height: 46, padding: '0 22px' }}>How to join</a>
            </div>
            <div className="mt-5 flex items-center gap-2 text-sm text-[#aab1d6]">
              <span className={`status-dot ${ready ? 'ok' : ''}`} />{ready ? 'Server is awake and ready' : 'Waking the server up (free hosting sleeps when idle)…'}
            </div>
          </div>
          <div className="flex flex-col items-center">
            <div className="mb-3 max-w-[300px] self-start rounded-[18px_18px_18px_6px] bg-white px-4 py-3 text-[.95rem] text-[#141a2b] shadow-2xl md:ml-[12%]">
              Namaste! I'm <b className="text-[#16a34a]">Bull</b>, and that's my cautious friend <b className="text-[#e5484d]">Bear</b>. Ask us how the market looks.
            </div>
            <div className="flex items-end" style={{ filter: 'drop-shadow(0 24px 30px rgba(0,0,0,.45))' }}>
              <Mascot who="bull" size={180} /><Mascot who="bear" size={180} style={{ marginLeft: -32 }} />
            </div>
          </div>
        </div>
      </header>

      <section id="features" className="mx-auto max-w-[1120px] px-6 py-20">
        <div className="eyebrow">What's inside</div>
        <h2 className="mb-2 mt-2 text-[clamp(1.8rem,3.4vw,2.4rem)] font-bold">Everything a 5-minute scalper checks, in one place</h2>
        <p className="mb-9 max-w-2xl muted">One set of rules drives the scanner, the market mood, the assistant and the backtest, so they always agree.</p>
        <div className="grid gap-4 md:grid-cols-3">
          {FEATURES.map(([ic, title, text, tone]) => (
            <div key={title} className="card p-6" style={tone ? { borderTop: `4px solid var(--${tone})` } : undefined}>
              <div className="mb-3 grid h-11 w-11 place-items-center rounded-xl text-xl" style={{ background: 'color-mix(in srgb, var(--brand) 12%, transparent)' }}>{ic}</div>
              <h3 className="mb-1 text-lg font-bold">{title}</h3><p className="text-[.95rem] muted">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="start" style={{ background: 'var(--card2)' }}>
        <div className="mx-auto max-w-[1120px] px-6 py-20">
          <div className="eyebrow">Get started</div>
          <h2 className="mb-8 mt-2 text-[clamp(1.8rem,3.4vw,2.4rem)] font-bold">Three steps to your desk</h2>
          <div className="grid gap-4 md:grid-cols-3">
            {[['Create an account', 'Sign up with your email and a password.'], ['Wait for approval', 'The admin reviews new accounts; you can sign in once approved.'],
              ['Connect your brokers', 'Add your Upstox app and CoinSwitch keys on the Connect page, then ask Bull & Bear.']].map(([t, d], i) => (
              <div key={t} className="card relative p-6 pl-[74px]">
                <span className="display absolute left-[22px] top-[22px] grid h-9 w-9 place-items-center rounded-[10px] font-bold text-white" style={{ background: 'linear-gradient(135deg,var(--brand),var(--brand2))' }}>{i + 1}</span>
                <h3 className="mb-1 font-bold">{t}</h3><p className="text-[.94rem] muted">{d}</p>
              </div>
            ))}
          </div>
          <div className="eyebrow mb-3 mt-12">Covers</div>
          <div className="flex flex-wrap gap-2">{['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', '200+ F&O stock futures', 'MCX: gold, silver, crude, gas, base metals', 'BTCUSDT', 'ETHUSDT', 'PAXGUSDT', 'XAUUSDT', 'XAUUSD (OANDA)'].map((x) => (
            <span key={x} className="card px-3 py-1.5 font-mono text-[.84rem]" style={{ boxShadow: 'none' }}>{x}</span>))}</div>
          <div className="card mt-14 p-10 text-center">
            <h2 className="mb-2 text-[clamp(1.6rem,3vw,2.1rem)] font-bold">Ready to read the tape?</h2>
            <p className="mb-6 muted">The pages open instantly; the first data request after a quiet spell can take up to a minute while the server wakes up.</p>
            <Link to={cta} className="btn primary" style={{ height: 46, padding: '0 22px' }}>{user ? 'Open the app →' : 'Sign in →'}</Link>
          </div>
        </div>
      </section>

      <footer className="border-t py-9 text-sm faint" style={{ borderColor: 'var(--border)' }}>
        <div className="mx-auto flex max-w-[1120px] flex-wrap justify-between gap-6 px-6">
          <span className="flex items-center gap-2"><img src={`${import.meta.env.BASE_URL}mark.svg`} alt="" width="26" height="26" /><b className="display">Scalp5</b></span>
          <p className="max-w-xl">Analysis only. Scalp5 never places orders, and nothing here is financial advice. Trading futures and crypto carries substantial risk;
            backtest and paper-trade before risking money.</p>
        </div>
      </footer>
    </div>
  );
}
