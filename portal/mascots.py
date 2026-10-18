"""Bull & Bear mascots, drawn as inline SVG and animated with CSS (bob, blink, ear wiggle), so there are no images
to load and motion stops for people who turn on "reduce motion"."""
from __future__ import annotations

import base64

# The Bull: warm brown, cream horns, gold nose ring, green (LONG) scarf.
BULL = """
<svg class="s5-m s5-bull" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-label="Bull">
  <g class="body">
    <path d="M28 98 Q60 120 92 98 L88 112 Q60 124 32 112 Z" fill="#16a34a"/>
    <path d="M52 104 l8 -9 l8 9 Z" fill="#bbf7d0"/>
    <g class="ear l"><ellipse cx="22" cy="52" rx="13" ry="7" fill="#8a4f24" transform="rotate(-20 22 52)"/>
      <ellipse cx="22" cy="52" rx="8" ry="3.6" fill="#e9a77e" transform="rotate(-20 22 52)"/></g>
    <g class="ear r"><ellipse cx="98" cy="52" rx="13" ry="7" fill="#8a4f24" transform="rotate(20 98 52)"/>
      <ellipse cx="98" cy="52" rx="8" ry="3.6" fill="#e9a77e" transform="rotate(20 98 52)"/></g>
    <path d="M34 40 Q14 34 12 12 Q24 26 40 30 Z" fill="#f4e6c8" stroke="#d9c39a" stroke-width="1.5"/>
    <path d="M86 40 Q106 34 108 12 Q96 26 80 30 Z" fill="#f4e6c8" stroke="#d9c39a" stroke-width="1.5"/>
    <path d="M30 46 Q30 24 60 24 Q90 24 90 46 L88 78 Q86 98 60 98 Q34 98 32 78 Z" fill="#9b5a2c"/>
    <path d="M48 26 Q60 34 72 26 Q66 38 60 36 Q54 38 48 26 Z" fill="#6f3d1b"/>
    <g class="eyes">
      <ellipse cx="47" cy="54" rx="6.5" ry="7.5" fill="#fff"/><ellipse cx="73" cy="54" rx="6.5" ry="7.5" fill="#fff"/>
      <circle cx="48" cy="55.5" r="3.6" fill="#1d1d24"/><circle cx="72" cy="55.5" r="3.6" fill="#1d1d24"/>
      <circle cx="49.3" cy="54" r="1.2" fill="#fff"/><circle cx="73.3" cy="54" r="1.2" fill="#fff"/>
    </g>
    <path d="M40 46 q7 -5 14 -1" stroke="#5b3114" stroke-width="2.4" fill="none" stroke-linecap="round"/>
    <path d="M66 45 q7 -4 14 1" stroke="#5b3114" stroke-width="2.4" fill="none" stroke-linecap="round"/>
    <ellipse cx="60" cy="80" rx="22" ry="15" fill="#f0b996"/>
    <ellipse cx="52" cy="79" rx="3.6" ry="4.6" fill="#7a3f22"/><ellipse cx="68" cy="79" rx="3.6" ry="4.6" fill="#7a3f22"/>
    <path d="M52 89 Q60 94 68 89" stroke="#7a3f22" stroke-width="2" fill="none" stroke-linecap="round"/>
    <circle class="ring" cx="60" cy="94" r="6" fill="none" stroke="#f5b83d" stroke-width="2.6"/>
  </g>
</svg>"""

# The Bear: chocolate brown, round ears, tan muzzle, red (SHORT) scarf, sleepy-cautious brows.
BEAR = """
<svg class="s5-m s5-bear" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-label="Bear">
  <g class="body">
    <path d="M28 98 Q60 120 92 98 L88 112 Q60 124 32 112 Z" fill="#e5484d"/>
    <path d="M52 96 l8 9 l8 -9 Z" fill="#fecaca"/>
    <g class="ear l"><circle cx="30" cy="30" r="14" fill="#6b4226"/><circle cx="30" cy="30" r="7.5" fill="#c99a6e"/></g>
    <g class="ear r"><circle cx="90" cy="30" r="14" fill="#6b4226"/><circle cx="90" cy="30" r="7.5" fill="#c99a6e"/></g>
    <circle cx="60" cy="60" r="38" fill="#7b4b2a"/>
    <g class="eyes">
      <circle cx="46" cy="55" r="4.4" fill="#1d1d24"/><circle cx="74" cy="55" r="4.4" fill="#1d1d24"/>
      <circle cx="47.4" cy="53.6" r="1.3" fill="#fff"/><circle cx="75.4" cy="53.6" r="1.3" fill="#fff"/>
    </g>
    <path d="M38 45 q8 3 15 1" stroke="#3f2414" stroke-width="2.6" fill="none" stroke-linecap="round"/>
    <path d="M67 46 q7 2 15 -1" stroke="#3f2414" stroke-width="2.6" fill="none" stroke-linecap="round"/>
    <ellipse cx="60" cy="75" rx="18" ry="14" fill="#d9ab7f"/>
    <path d="M53 69 Q60 64 67 69 Q66 75 60 76 Q54 75 53 69 Z" fill="#2a1a10"/>
    <path d="M60 76 v5 M53 84 Q60 80 67 84" stroke="#2a1a10" stroke-width="2" fill="none" stroke-linecap="round"/>
    <ellipse cx="38" cy="70" rx="5" ry="3" fill="#e5484d" opacity=".25"/>
    <ellipse cx="82" cy="70" rx="5" ry="3" fill="#e5484d" opacity=".25"/>
  </g>
</svg>"""

CSS = """
<style>
.s5-m { display: block; overflow: visible; }
.s5-m .body { transform-origin: 60px 110px; animation: s5-bob 3.2s ease-in-out infinite; }
.s5-bear .body { animation-delay: -1.6s; }
.s5-m .eyes { transform-box: fill-box; transform-origin: center; animation: s5-blink 4.6s infinite; }
.s5-bear .eyes { animation-delay: -2.1s; }
.s5-m .ear { transform-box: fill-box; transform-origin: center bottom; animation: s5-wiggle 5.5s ease-in-out infinite; }
.s5-m .ear.r { animation-delay: -.4s; }
.s5-bull .ring { transform-box: fill-box; transform-origin: center top; animation: s5-swing 2.6s ease-in-out infinite; }
@keyframes s5-bob { 0%,100% { transform: translateY(0) rotate(0) } 50% { transform: translateY(-4px) rotate(-1.5deg) } }
@keyframes s5-blink { 0%,92%,100% { transform: scaleY(1) } 95% { transform: scaleY(.1) } }
@keyframes s5-wiggle { 0%,80%,100% { transform: rotate(0) } 85% { transform: rotate(-9deg) } 90% { transform: rotate(7deg) } }
@keyframes s5-swing { 0%,100% { transform: rotate(-8deg) } 50% { transform: rotate(8deg) } }
@media (prefers-reduced-motion: reduce) { .s5-m * { animation: none !important; } }

/* floating launcher (bottom-right of every signed-in page) */
.st-key-s5bot { position: fixed; right: 22px; bottom: 18px; z-index: 999990; width: 200px !important;
  align-items: flex-end; gap: 6px !important; pointer-events: none; }
.st-key-s5bot > div { pointer-events: auto; }
.s5-duo { display: flex; justify-content: flex-end; align-items: flex-end; margin: 0 6px 2px 0;
  filter: drop-shadow(0 10px 18px rgba(20,26,43,.28)); }
.s5-duo .s5-m { width: 74px; height: 74px; transition: transform .25s ease, opacity .25s ease; }
.s5-duo .lead { width: 92px; height: 92px; z-index: 2; }
.s5-duo .side { opacity: .9; margin-right: -16px; transform: translateY(-4px); }
.s5-bubble { position: relative; background: var(--s5-card); color: inherit; border: 1px solid var(--s5-border);
  border-radius: 14px 14px 4px 14px; padding: 9px 12px; font-size: .82rem; line-height: 1.35; max-width: 200px;
  box-shadow: var(--s5-shadow); margin-bottom: 2px; animation: s5-pop .5s ease-out both .4s; }
.s5-bubble b { color: var(--tone, var(--s5-brand)); }
@keyframes s5-pop { from { opacity: 0; transform: translateY(6px) scale(.96) } to { opacity: 1; transform: none } }
.st-key-s5bot button { border-radius: 999px !important; box-shadow: 0 10px 24px -8px var(--s5-brand); font-weight: 600; }
@media (max-width: 640px) {
  .st-key-s5bot { right: 10px; bottom: 10px; width: 150px !important; }
  .s5-bubble { display: none; }
  .s5-duo .lead { width: 68px; height: 68px; } .s5-duo .side { width: 54px; height: 54px; }
}

/* chat window */
.s5-chat-head { display: flex; align-items: center; gap: 12px; margin: -6px 0 6px; }
.s5-chat-head .s5-m { width: 54px; height: 54px; }
.s5-chat-head .duo { display: flex; } .s5-chat-head .duo .s5-m + .s5-m { margin-left: -14px; }
.s5-chat-head small { display: block; color: var(--s5-muted); font-size: .8rem; }
[data-testid="stChatMessage"] { background: var(--s5-card2); border: 1px solid var(--s5-border); border-radius: 14px;
  padding: .7rem .9rem; }
[data-testid="stChatMessageAvatarCustom"] img, [data-testid="stChatMessage"] img { border-radius: 50%; }
</style>
"""


def _uri(svg: str) -> str:
    """Static (non-animated) data URI for chat avatars."""
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


BULL_AVATAR = _uri(BULL)
BEAR_AVATAR = _uri(BEAR)
