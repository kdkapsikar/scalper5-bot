"""Bull & Bear, the floating chat assistant on every signed-in page (the Scalp5 cousin of eNagarparishad's मदतनीस).

The launcher sits at the bottom-right: the mascot matching today's mood stands in front and greets you. Tapping
"Ask Bull & Bear" opens the chat in a dialog. Menu chips or free text ("nifty", "signals", "what is rsi") are
answered from the person's own broker data via scalpbot.assistant. Analysis only: no orders, no advice.
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from scalpbot import assistant as A
from scalpbot import creds
from scalpbot.mood import all_moods

from portal import mascots, ui
from portal.auth import accounts, current_user
from portal.common import QUICK_GROUPS, check_one, get_universe, measure

HISTORY = "s5_chat"
AVATAR = {A.BULL: mascots.BULL_AVATAR, A.BEAR: mascots.BEAR_AVATAR, "user": ":material/person:"}


def _mood_avg() -> float | None:
    moods = st.session_state.get("s5_moods")
    scores = [m.score for m in (moods or {}).values() if m.score is not None]
    return sum(scores) / len(scores) if scores else None


def launcher() -> None:
    """Floating mascots + greeting + the button that opens the chat."""
    st.markdown(mascots.CSS, unsafe_allow_html=True)
    avg = _mood_avg()
    bull_leads = avg is None or avg >= 0
    lead, side = (mascots.BULL, mascots.BEAR) if bull_leads else (mascots.BEAR, mascots.BULL)
    if avg is None:
        bubble = "Namaste! 🐂🐻 Ask us how the market looks."
        tone = "var(--s5-brand)"
    else:
        label = ("Strong Bull" if avg >= 40 else "Bull" if avg >= 15 else "Neutral" if avg > -15 else
                 "Bear" if avg > -40 else "Strong Bear")
        tone = "var(--s5-bull)" if avg >= 15 else "var(--s5-bear)" if avg <= -15 else "var(--s5-muted)"
        bubble = f"Market mood: <b>{label}</b> ({avg:+.0f}). Want the details?"
    with st.container(key="s5bot"):
        st.markdown(f'<div class="s5-bubble" style="--tone:{tone}">{bubble}</div>'
                    f'<div class="s5-duo">{side.replace("s5-m ", "s5-m side ", 1)}'
                    f'{lead.replace("s5-m ", "s5-m lead ", 1)}</div>', unsafe_allow_html=True)
        if st.button("Ask Bull & Bear", key="s5bot_open", type="primary", icon=":material/forum:"):
            chat()


def _say(msgs: list[A.Msg]) -> None:
    st.session_state[HISTORY] += [{"who": m.who, "text": m.text} for m in msgs]


def _answer(kind: str, arg) -> None:
    user = current_user()
    universe, _ = get_universe()
    by_name = {i.name: i for i in universe}
    if kind == "help":
        _say(A.reply_help((user.name or "").split(" ")[0]))
    elif kind == "mood":
        with st.spinner("Bull and Bear are reading the tape..."):
            results, _ = measure(QUICK_GROUPS)
        moods = all_moods(results)
        st.session_state["s5_moods"] = moods
        _say(A.reply_mood(moods))
    elif kind == "signals":
        with st.spinner("Scanning index futures and crypto..."):
            results, _ = measure(QUICK_GROUPS)
        live = [r for r in results if not r.stale]
        if results and not live:
            _say([A.Msg(A.BEAR, "All these markets look closed right now, so there's nothing live to flag. 🐻 "
                                "The Scanner page can review the last session (*Include closed markets*).")])
        else:
            _say(A.reply_signals(live, 3, "index futures and crypto"))
            _say([A.Msg(A.BULL, "For every F&O stock future, run **Scan all** on the Scanner page. 🐂")])
    elif kind == "ticker":
        if arg is None:
            _say([A.Msg(A.BULL, "Which one? Type a name like *nifty*, *banknifty*, *reliance*, *btc* or *gold*. 🐂")])
        else:
            with st.spinner(f"Checking {arg}..."):
                _say(A.reply_ticker(check_one(by_name[arg]), 3))
    elif kind == "explain":
        _say(A.reply_explain(arg))
    elif kind == "connections":
        c = creds.current() or creds.Creds()
        saved = accounts().key_saved_at(user.id)
        t = saved.get("UPSTOX_ACCESS_TOKEN")
        age = (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600 if t and c.UPSTOX_ACCESS_TOKEN else None
        _say(A.reply_connections(bool(c.UPSTOX_ACCESS_TOKEN), age, bool(c.COINSWITCH_API_KEY and c.COINSWITCH_SECRET_KEY)))
    else:
        _say(A.reply_unknown())


@st.dialog("Bull & Bear", width="large")
def chat() -> None:
    user = current_user()
    if user is None:
        st.stop()
    creds.activate(accounts().load_creds(user.id))   # dialog reruns skip app.py, so re-activate this user's keys
    if HISTORY not in st.session_state:
        st.session_state[HISTORY] = []
        _say(A.reply_help((user.name or "").split(" ")[0]))
    st.markdown(f'<div class="s5-chat-head"><div class="duo">{mascots.BULL}{mascots.BEAR}</div>'
                '<div><b>Your market desk</b><small>Reads your own broker data · analysis only, not advice</small></div></div>',
                unsafe_allow_html=True)

    names = [i.name for i in get_universe()[0]]
    n = st.session_state.get("s5bot_n", 0)          # a fresh chips widget after every answer clears the selection
    picked = st.pills("Ask", [label for _, label in A.MENU], key=f"s5bot_pill_{n}", label_visibility="collapsed")
    box = st.container(height=420, border=False)    # filled below, after this run's question is answered
    typed = st.chat_input("Ask about the market, a ticker, or an indicator...", key="s5bot_input")
    if picked:
        kind = next(k for k, label in A.MENU if label == picked)
        st.session_state[HISTORY].append({"who": "user", "text": picked})
        with box:
            _answer(kind, None)
        st.session_state["s5bot_n"] = n + 1
    elif typed:
        st.session_state[HISTORY].append({"who": "user", "text": typed})
        kind, arg = A.intent(typed, names)
        with box:
            _answer(kind, arg)

    with box:
        for m in st.session_state[HISTORY][-30:]:
            with st.chat_message("user" if m["who"] == "user" else "assistant", avatar=AVATAR[m["who"]]):
                st.markdown(m["text"])
    c1, c2 = st.columns([1, 1])
    if c1.button("Clear chat", key="s5bot_clear", type="tertiary", icon=":material/delete_sweep:"):
        st.session_state.pop(HISTORY, None)
        st.rerun(scope="fragment")
    c2.markdown('<div class="s5-fine" style="text-align:right">Data is cached per 5-minute candle.</div>',
                unsafe_allow_html=True)
