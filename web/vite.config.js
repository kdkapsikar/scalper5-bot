import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Dev: the API runs on :8000 (uvicorn api.main:app --reload); proxying keeps everything same-origin.
const devApi = process.env.API_URL || 'http://localhost:8000';

/**
 * On GitHub Pages the API lives elsewhere and Pages cannot send security headers, so ship a
 * Content-Security-Policy as a <meta> tag at build time (as wardwatch does).
 */
function contentSecurityPolicy(apiUrl) {
  return {
    name: 'scalp5-csp-meta',
    transformIndexHtml() {
      if (!apiUrl) return [];
      const api = new URL(apiUrl).origin;
      const policy = [
        "default-src 'self'",
        "script-src 'self' https://s3.tradingview.com",   // TradingView's embeddable chart (XAUUSD page)
        "frame-src https://www.tradingview-widget.com https://s.tradingview.com https://www.tradingview.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        `connect-src 'self' ${api}`,
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
      ].join('; ');
      return [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: policy }, injectTo: 'head-prepend' }];
    },
  };
}

export default defineConfig(() => ({
  // GitHub Pages project sites live under /<repo>/. The Pages workflow sets VITE_BASE=/scalper5-bot/.
  base: process.env.VITE_BASE || '/',
  plugins: [react(), tailwindcss(), contentSecurityPolicy(process.env.VITE_API_URL)],
  server: { port: 5173, proxy: { '/api': devApi } },
  build: { chunkSizeWarningLimit: 900 },
}));
