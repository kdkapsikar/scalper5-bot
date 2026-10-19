import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, setUnauthorizedHandler, tokenStore } from '../lib/api.js';

const AuthContext = createContext(null);

/** Who is signed in, their broker connections, and the market mood the mascots greet with. */
export function AuthProvider({ children }) {
  const [state, setState] = useState({ loading: !!tokenStore.get(), me: null });
  // Average mood score, set by the Mood page / Bull & Bear; remembered for 10 minutes so a reload keeps the greeting.
  const [mood, setMoodState] = useState(() => {
    try {
      const m = JSON.parse(sessionStorage.getItem('s5_mood') || 'null');
      return m && Date.now() - m.at < 600000 ? m.score : null;
    } catch { return null; }
  });
  const setMood = useCallback((score) => {
    setMoodState(score);
    try { sessionStorage.setItem('s5_mood', JSON.stringify({ score, at: Date.now() })); } catch { /* ignore */ }
  }, []);

  const refresh = useCallback(async () => {
    if (!tokenStore.get()) { setState({ loading: false, me: null }); return null; }
    try {
      const me = await api.get('/api/me');
      setState({ loading: false, me });
      return me;
    } catch {
      setState({ loading: false, me: null });
      return null;
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => { tokenStore.clear(); setState({ loading: false, me: null }); });
    refresh();
  }, [refresh]);

  const signIn = useCallback(async (token) => {
    tokenStore.set(token);
    return refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    try { await api.post('/api/auth/logout'); } catch { /* signed out locally either way */ }
    tokenStore.clear();
    setState({ loading: false, me: null });
  }, []);

  const value = useMemo(() => ({
    loading: state.loading, me: state.me, user: state.me?.user ?? null, connections: state.me?.connections ?? null,
    refresh, signIn, signOut, mood, setMood,
  }), [state, refresh, signIn, signOut, mood, setMood]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
