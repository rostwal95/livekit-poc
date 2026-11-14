import './channel-policy-landing.css';

export const DEFAULT_CONSOLE_URL = 'http://127.0.0.1:13000/';

/** Accept only a loopback console origin; anything else keeps the default port. */
export function consoleUrl(configured: unknown): string {
  if (typeof configured !== 'string') return DEFAULT_CONSOLE_URL;
  const match = /^http:\/\/127\.0\.0\.1:([0-9]{2,5})\/$/.exec(configured);
  const port = match ? Number(match[1]) : 0;
  return port >= 1 && port <= 65535 ? configured : DEFAULT_CONSOLE_URL;
}

if (typeof document !== 'undefined') {
  const link = document.querySelector<HTMLAnchorElement>('[data-p1-console]');
  if (link) link.href = consoleUrl(import.meta.env.VITE_P1_CONSOLE_URL);
}
