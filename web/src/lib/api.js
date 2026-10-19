import { API_URL } from './config.js';

const TOKEN_KEY = 's5_token';

// Session token from sign-in, sent as `Authorization: Bearer`. localStorage can be unavailable (private mode,
// blocked storage), so every access is guarded and the app then just behaves as signed-out.
export const tokenStore = {
  get() {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set(token) {
    try { localStorage.setItem(TOKEN_KEY, token); } catch { /* ignore */ }
  },
  clear() {
    try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
  },
};

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// "Waking the server" notice: Render's free plan sleeps, so a request can take 30-60 s. Requests slower than a few
// seconds are announced to whoever listens (the layout shows a banner).
let slow = 0;
const listeners = new Set();
export function onSlowChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
const announce = () => listeners.forEach((fn) => fn(slow > 0));

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

export async function request(path, { method = 'GET', json } = {}) {
  const init = { method, headers: {} };
  const token = tokenStore.get();
  if (token) init.headers.Authorization = `Bearer ${token}`;
  if (json !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(json);
  }
  let flagged = false;
  const timer = setTimeout(() => { flagged = true; slow += 1; announce(); }, 3500);
  let res;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, "Can't reach the Scalp5 server. Check your connection and try again in a moment.");
  } finally {
    clearTimeout(timer);
    if (flagged) { slow -= 1; announce(); }
  }
  let body = null;
  try { body = await res.json(); } catch { /* empty or not JSON */ }
  if (!res.ok) {
    if (res.status === 401 && token && path !== '/api/auth/login') onUnauthorized();
    throw new ApiError(res.status, body?.error || `The server answered ${res.status}.`);
  }
  return body;
}

export const api = {
  get: (path) => request(path),
  post: (path, json) => request(path, { method: 'POST', json: json ?? {} }),
  put: (path, json) => request(path, { method: 'PUT', json }),
  del: (path) => request(path, { method: 'DELETE' }),
};

/** Start a background job (scan, mood, connection test) and poll it until it finishes. */
export async function runJob(start, onProgress, { signal } = {}) {
  let job = await start();
  while (job.status === 'running') {
    onProgress?.(job);
    await new Promise((r) => setTimeout(r, 1000));
    if (signal?.aborted) throw new ApiError(0, 'Cancelled');
    job = await api.get(`/api/jobs/${job.id}`);
  }
  if (job.status === 'error') throw new ApiError(500, job.error || 'The job failed.');
  onProgress?.(job);
  return job.result;
}
