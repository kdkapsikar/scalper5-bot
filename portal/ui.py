"""Look and feel: the global stylesheet and a few branded building blocks (sidebar user card, sign-in hero, mood cards).

Colours come from CSS variables set per theme (light / dark follows the viewer's system setting, see
.streamlit/config.toml), so every custom block reads well in both.
"""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parent / "assets"

PALETTE = {
    "light": {"card": "#ffffff", "card2": "#f9fafd", "border": "#e3e7f0", "muted": "#5f6880", "faint": "#8a93a8",
              "brand": "#4f5dff", "brand2": "#3b2fd9", "bull": "#16a34a", "bear": "#e5484d", "warn": "#d97706",
              "bull_bg": "rgba(22,163,74,.10)", "bear_bg": "rgba(229,72,77,.10)", "warn_bg": "rgba(217,119,6,.10)",
              "neutral_bg": "rgba(95,104,128,.10)", "shadow": "0 1px 2px rgba(20,26,43,.04), 0 6px 24px rgba(20,26,43,.06)"},
    "dark": {"card": "#11182c", "card2": "#141c33", "border": "#232c47", "muted": "#9aa3ba", "faint": "#6f7891",
             "brand": "#7c8bff", "brand2": "#5b4dff", "bull": "#22c55e", "bear": "#f05252", "warn": "#f5a524",
             "bull_bg": "rgba(34,197,94,.13)", "bear_bg": "rgba(240,82,82,.13)", "warn_bg": "rgba(245,165,36,.13)",
             "neutral_bg": "rgba(154,163,186,.12)", "shadow": "0 1px 2px rgba(0,0,0,.3), 0 8px 28px rgba(0,0,0,.28)"},
}


def theme_type() -> str:
    try:
        t = st.context.theme.type
    except Exception:
        t = None
    return t if t in PALETTE else "light"


def _vars() -> str:
    p = PALETTE[theme_type()]
    return ";".join(f"--s5-{k.replace('_', '-')}:{v}" for k, v in p.items())


CSS = """
<style>
:root { %(vars)s }

/* ---------- layout ---------- */
[data-testid="stMainBlockContainer"] { padding-top: 2.4rem; padding-bottom: 4rem; max-width: 1240px; }
[data-testid="stHeader"] { background: transparent; }
h1 { letter-spacing: -0.02em; }
h2, h3 { letter-spacing: -0.01em; }
[data-testid="stCaptionContainer"] { color: var(--s5-muted); }
[data-testid="stMainBlockContainer"] > div > div > [data-testid="stElementContainer"]:has(h1) + [data-testid="stElementContainer"] [data-testid="stCaptionContainer"] {
  font-size: 0.95rem; max-width: 64rem; }
hr { margin: 1.2rem 0 !important; }

/* ---------- cards: metrics, forms, bordered containers, expanders ---------- */
[data-testid="stMetric"] {
  background: var(--s5-card); border: 1px solid var(--s5-border); border-radius: 14px;
  padding: 14px 18px 12px; box-shadow: var(--s5-shadow); }
[data-testid="stMetricLabel"] p { font-size: 0.78rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  color: var(--s5-muted); }
[data-testid="stMetricValue"] { font-family: "Space Grotesk", Inter, sans-serif; }
[data-testid="stForm"] { background: var(--s5-card); border: 1px solid var(--s5-border); border-radius: 16px;
  padding: 1.3rem 1.4rem 1.1rem; box-shadow: var(--s5-shadow); }
[data-testid="stExpander"] details { border-radius: 12px; border-color: var(--s5-border); background: var(--s5-card); }
[data-testid="stExpander"] summary p { font-weight: 600; }
[data-testid="stDataFrame"], [data-testid="stTable"] { border-radius: 12px; overflow: hidden; }
[data-testid="stAlert"] { border-radius: 12px; }

/* ---------- buttons ---------- */
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(135deg, var(--s5-brand), var(--s5-brand2)); border: 0; font-weight: 600;
  box-shadow: 0 6px 18px -6px var(--s5-brand); transition: transform .12s ease, box-shadow .12s ease; }
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  transform: translateY(-1px); box-shadow: 0 10px 22px -8px var(--s5-brand); color: #fff; }
button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-secondaryFormSubmit"] { font-weight: 500; }
[data-testid="stLinkButton"] a[kind="primary"], a[data-testid="stBaseLinkButton-primary"] {
  background: linear-gradient(135deg, var(--s5-brand), var(--s5-brand2)); border: 0; font-weight: 600; }

/* ---------- tabs as segmented pills ---------- */
.stTabs [role="tablist"] { gap: 4px; background: var(--s5-card2); border: 1px solid var(--s5-border) !important;
  padding: 4px; border-radius: 12px; width: fit-content; max-width: 100%%; overflow-x: auto; box-shadow: none !important; }
.stTabs [role="tablist"]::before, .stTabs [role="tablist"]::after { display: none !important; }
.stTabs [role="tab"] { height: 34px; padding: 0 14px; border-radius: 9px; font-weight: 500; display: flex; align-items: center; }
.stTabs [role="tab"] p { font-size: .9rem; }
.stTabs [role="tab"][aria-selected="true"] { background: var(--s5-card); box-shadow: 0 1px 3px rgba(20,26,43,.12); }
.stTabs [role="tab"][aria-selected="true"] p { color: var(--s5-brand); font-weight: 600; }
.stTabs .react-aria-SelectionIndicator { display: none; }
.stTabs [role="tabpanel"] { padding-top: .6rem; }

/* ---------- sidebar ---------- */
[data-testid="stSidebarNav"] a { border-radius: 10px; margin: 1px 0; }
[data-testid="stSidebarNav"] a[aria-current="page"] { background: var(--s5-bull-bg);
  background: color-mix(in srgb, var(--s5-brand) 12%%, transparent); }
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: var(--s5-brand); font-weight: 600; }
[data-testid="stSidebarNavSeparator"] { display: none; }
[data-testid="stSidebarHeader"] { padding-bottom: .5rem; }
[data-testid="stLogo"] { height: 2.1rem; max-width: 100%%; }

/* ---------- custom blocks ---------- */
.s5-user { padding: 12px; border-radius: 14px; background: var(--s5-card); border: 1px solid var(--s5-border); }
.s5-user .head { display: flex; align-items: center; gap: 10px; }
.s5-user .who { min-width: 0; flex: 1; }
.s5-user small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.s5-user .role { align-self: flex-start; font-size: .62rem; font-weight: 700; letter-spacing: .08em;
  padding: 2px 7px; border-radius: 6px; color: var(--s5-brand); background: color-mix(in srgb, var(--s5-brand) 14%%, transparent); }
.s5-avatar { width: 36px; height: 36px; border-radius: 50%%; display: grid; place-items: center; flex: none;
  background: linear-gradient(135deg, var(--s5-brand), var(--s5-brand2)); color: #fff; font-weight: 700; font-size: .9rem; }
.s5-user b { display: block; font-size: .92rem; line-height: 1.2; }
.s5-user small { color: var(--s5-muted); font-size: .78rem; }
.s5-conn { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--s5-border); }
.s5-conn .s5-pill { font-size: .7rem; padding: 2px 8px; }
[data-testid='stSidebarUserContent'] button[data-testid='stBaseButton-tertiary'] { color: var(--s5-muted); font-size: .85rem; padding-left: 4px; }
.s5-pill { display: inline-flex; align-items: center; gap: 6px; font-size: .76rem; font-weight: 600; padding: 4px 10px;
  border-radius: 999px; background: var(--s5-neutral-bg); color: var(--s5-muted); white-space: nowrap; }
.s5-pill i { width: 7px; height: 7px; border-radius: 50%%; background: currentColor; display: inline-block; }
.s5-pill.bull { background: var(--s5-bull-bg); color: var(--s5-bull); }
.s5-pill.bear { background: var(--s5-bear-bg); color: var(--s5-bear); }
.s5-pill.warn { background: var(--s5-warn-bg); color: var(--s5-warn); }
.s5-pill.brand { background: color-mix(in srgb, var(--s5-brand) 14%%, transparent); color: var(--s5-brand); }

.s5-eyebrow { font-size: .74rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--s5-brand);
  margin-bottom: -0.6rem; }

.s5-hero { position: relative; overflow: hidden; border-radius: 22px; padding: 34px 34px 30px; color: #eef0ff; min-height: 470px;
  background: radial-gradient(120%% 90%% at 100%% 0%%, rgba(124,139,255,.55) 0%%, rgba(124,139,255,0) 55%%),
              radial-gradient(90%% 70%% at 0%% 100%%, rgba(34,197,94,.28) 0%%, rgba(34,197,94,0) 60%%),
              linear-gradient(160deg, #141a3a 0%%, #0b1020 100%%);
  box-shadow: 0 20px 60px -20px rgba(59,47,217,.45); }
.s5-hero h1 { color: #fff; font-size: 2.3rem; line-height: 1.12; margin: 18px 0 10px; }
.s5-hero p.lead { color: #c4c9e6; font-size: 1.02rem; max-width: 30rem; }
.s5-hero .brand { display: flex; align-items: center; gap: 10px; font-family: "Space Grotesk", Inter, sans-serif;
  font-weight: 700; font-size: 1.25rem; color: #fff; }
.s5-hero .brand img { width: 40px; height: 40px; }
.s5-feat { display: grid; gap: 12px; margin-top: 26px; }
.s5-feat div { display: flex; gap: 12px; align-items: flex-start; background: rgba(255,255,255,.06);
  border: 1px solid rgba(255,255,255,.09); border-radius: 14px; padding: 12px 14px; }
.s5-feat span.ic { font-size: 1.25rem; line-height: 1.4; }
.s5-feat b { color: #fff; font-size: .95rem; }
.s5-feat small { display: block; color: #aab1d6; font-size: .84rem; margin-top: 2px; }
.s5-ticker { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 22px; }
.s5-ticker span { font-family: "JetBrains Mono", monospace; font-size: .76rem; padding: 4px 9px; border-radius: 8px;
  background: rgba(255,255,255,.07); color: #d7dbf5; }
.s5-cover { margin-top: 24px; font-size: .7rem; letter-spacing: .14em; text-transform: uppercase; color: #8f97c4; }
.s5-cover + .s5-ticker { margin-top: 8px; }
.s5-fine { color: var(--s5-faint); font-size: .8rem; margin-top: .6rem; }

.s5-mood { border-radius: 18px; padding: 20px 22px 6px; border: 1px solid var(--s5-border); background: var(--s5-card);
  box-shadow: var(--s5-shadow); position: relative; overflow: hidden; }
.s5-mood::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 4px; background: var(--tone); }
.s5-mood .top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.s5-mood .mkt { font-size: .78rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--s5-muted); }
.s5-mood .label { font-family: "Space Grotesk", Inter, sans-serif; font-size: 1.9rem; font-weight: 700; color: var(--tone);
  line-height: 1.15; margin-top: 4px; }
.s5-mood .animal { font-size: 3rem; line-height: 1; filter: drop-shadow(0 6px 14px rgba(0,0,0,.18)); }
.s5-mood .score { font-family: "Space Grotesk", Inter, sans-serif; font-size: .95rem; color: var(--s5-muted); margin-top: 2px; }
.s5-mood .score b { color: var(--tone); font-size: 1.05rem; }
.s5-bar { position: relative; height: 10px; border-radius: 999px; margin: 18px 0 6px;
  background: linear-gradient(90deg, var(--s5-bear) 0%%, color-mix(in srgb, var(--s5-bear) 35%%, transparent) 30%%,
              var(--s5-neutral-bg) 50%%, color-mix(in srgb, var(--s5-bull) 35%%, transparent) 70%%, var(--s5-bull) 100%%); }
.s5-bar i { position: absolute; top: 50%%; width: 18px; height: 18px; border-radius: 50%%; transform: translate(-50%%, -50%%);
  background: var(--s5-card); border: 4px solid var(--tone); box-shadow: 0 2px 8px rgba(0,0,0,.25); }
.s5-scale { display: flex; justify-content: space-between; font-size: .72rem; color: var(--s5-faint); margin-bottom: 14px; }
.s5-facts { list-style: none; padding: 0; margin: 0 0 12px; }
.s5-facts li { display: flex; gap: 10px; padding: 8px 0; border-top: 1px dashed var(--s5-border); font-size: .92rem; margin: 0; }
.s5-facts li:first-child { border-top: 0; }
.s5-facts li span { color: var(--s5-faint); flex: none; width: 1.1rem; text-align: center; }
.s5-meta { display: flex; gap: 8px; flex-wrap: wrap; margin: 2px 0 14px; }

.s5-empty { text-align: center; padding: 38px 20px; border: 1px dashed var(--s5-border); border-radius: 16px; color: var(--s5-muted);
  background: var(--s5-card2); }
.s5-empty .ic { font-size: 2rem; } .s5-empty b { display: block; color: inherit; font-size: 1rem; margin: 6px 0 2px; }
.s5-signal-up { color: var(--s5-bull); font-weight: 700; } .s5-signal-dn { color: var(--s5-bear); font-weight: 700; }

.s5-kv { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; margin: 6px 0 10px; }
.s5-kv div { background: var(--s5-card); border: 1px solid var(--s5-border); border-radius: 12px; padding: 10px 14px; }
.s5-kv span { display: block; font-size: .72rem; font-weight: 600; letter-spacing: .05em; text-transform: uppercase;
  color: var(--s5-muted); margin-bottom: 3px; }
.s5-kv b { font-weight: 600; font-size: .92rem; }

@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] { padding-top: 4.2rem; padding-left: 1rem; padding-right: 1rem; }
  .s5-hero { min-height: 0; padding: 22px 20px; } .s5-hero h1 { font-size: 1.5rem; margin-top: 12px; }
  .s5-hero .s5-feat, .s5-hero .s5-cover, .s5-hero .s5-ticker { display: none; }
  [data-testid="stHorizontalBlock"]:has(.s5-hero) { flex-direction: column-reverse; }
  .tablet-hide { display: none; }
}
</style>
"""


def apply_theme() -> None:
    """Global stylesheet and the sidebar logo. Call once per run, before the page renders."""
    st.markdown(CSS % {"vars": _vars()}, unsafe_allow_html=True)


def logo() -> None:
    st.logo(str(ASSETS / "logo.svg"), size="large", icon_image=str(ASSETS / "mark.svg"))


def esc(x) -> str:
    return html.escape(str(x))


def pill(text: str, tone: str = "") -> str:
    return f'<span class="s5-pill {tone}"><i></i>{esc(text)}</span>'


def eyebrow(text: str) -> None:
    st.markdown(f'<div class="s5-eyebrow">{esc(text)}</div>', unsafe_allow_html=True)


def empty_state(icon: str, title: str, text: str = "") -> None:
    st.markdown(f'<div class="s5-empty"><div class="ic">{icon}</div><b>{esc(title)}</b>{esc(text)}</div>',
                unsafe_allow_html=True)


def user_card(name: str, email: str, role: str, up_ok: bool, cs_ok: bool) -> None:
    initials = "".join(w[0] for w in (name or email).replace("@", " ").split()[:2]).upper() or "?"
    st.sidebar.markdown(
        f'<div class="s5-user"><div class="head"><div class="s5-avatar">{esc(initials)}</div>'
        f'<div class="who"><b>{esc(name or email.split("@")[0])}</b><small>{esc(email)}</small></div>'
        f'{"<span class=role>ADMIN</span>" if role == "admin" else ""}</div>'
        f'<div class="s5-conn">{pill("Upstox", "bull" if up_ok else "bear")}'
        f'{pill("CoinSwitch", "bull" if cs_ok else "bear")}</div></div>',
        unsafe_allow_html=True)


def _svg_data_uri(path: Path) -> str:
    import base64
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()


def sign_in_hero() -> None:
    st.markdown(f"""
<div class="s5-hero">
  <div class="brand"><img src="{_svg_data_uri(ASSETS / 'mark.svg')}" alt=""/>Scalp5</div>
  <h1>Read the tape.<br/>Bull or bear,<br/>every 5 minutes.</h1>
  <p class="lead">Confluence signals and a live market mood for Indian index &amp; F&amp;O futures and crypto,
  computed from your own broker feeds.</p>
  <div class="s5-feat">
    <div><span class="ic">📈</span><span><b>Scanner</b><small>SMA 22/33 and 200 DEMA triggers, filtered by Supertrend, RSI and pivot room.</small></span></div>
    <div><span class="ic">🐂</span><span><b>Market mood</b><small>A Bull / Bear score for NSE futures and crypto, with the reasons behind it.</small></span></div>
    <div><span class="ic">🔐</span><span><b>Your accounts, your keys</b><small>Connect your own Upstox and CoinSwitch; keys are encrypted.</small></span></div>
  </div>
  <div class="s5-cover">Covers</div>
  <div class="s5-ticker"><span>NIFTY</span><span>BANKNIFTY</span><span>FINNIFTY</span><span>200+ F&amp;O stocks</span>
  <span>BTCUSDT</span><span>ETHUSDT</span><span>PAXGUSDT</span><span>XAUUSDT</span></div>
</div>""", unsafe_allow_html=True)


def key_values(d: dict) -> None:
    cells = "".join(f'<div><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in d.items())
    st.markdown(f'<div class="s5-kv">{cells}</div>', unsafe_allow_html=True)


TONE = {"bull": "var(--s5-bull)", "bear": "var(--s5-bear)", "neutral": "var(--s5-muted)", "none": "var(--s5-faint)"}


def mood_card(market: str, m) -> None:
    """Headline card for one market's mood (m is scalpbot.mood.Mood)."""
    tone = TONE[m.side]
    animal = {"bull": "🐂", "bear": "🐻", "neutral": "⚖️"}.get(m.side, "❔")
    if m.score is None:
        body = f'<ul class="s5-facts"><li><span>•</span>{esc(" ".join(m.facts))}</li></ul>'
        score = '<div class="score">No reading yet</div>'
        bar = ""
    else:
        pos = (m.score + 100) / 2
        score = f'<div class="score">Score <b>{m.score:+.0f}</b> / 100</div>'
        bar = (f'<div class="s5-bar"><i style="left:{pos:.1f}%"></i></div>'
               '<div class="s5-scale"><span>Strong bear</span><span>Neutral</span><span>Strong bull</span></div>')
        body = '<ul class="s5-facts">' + "".join(f"<li><span>›</span>{esc(f)}</li>" for f in m.facts) + "</ul>"
    meta = pill(f"{m.n} measured", "")
    if m.stale:
        meta += pill(f"{m.stale} closed", "warn")
    if m.errors:
        meta += pill(f"{m.errors} failed", "bear")
    st.markdown(f"""
<div class="s5-mood" style="--tone:{tone}">
  <div class="top"><div><div class="mkt">{esc(market)}</div><div class="label">{esc(m.label)}</div>{score}</div>
  <div class="animal">{animal}</div></div>
  {bar}<div class="s5-meta">{meta}</div>{body}
</div>""", unsafe_allow_html=True)
