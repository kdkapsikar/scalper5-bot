// Where the API lives. Empty = same origin (dev proxy, or the API serving the built app).
// On GitHub Pages the workflow sets VITE_API_URL to the Render address.
export const API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');

/** Router basename: "" normally, "/scalper5-bot" when served from a GitHub Pages project site. */
export const BASENAME = import.meta.env.BASE_URL.replace(/\/+$/, '');

/** Absolute address of a page in this app (e.g. the Upstox redirect URI). */
export function appUrl(path = '') {
  return `${window.location.origin}${BASENAME}${path}`;
}
