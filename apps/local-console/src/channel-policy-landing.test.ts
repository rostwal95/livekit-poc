import { describe, expect, it } from 'vitest';
import { consoleUrl, DEFAULT_CONSOLE_URL } from './channel-policy-landing';

describe('landing console link', () => {
  it('keeps a configured loopback console origin', () => {
    expect(consoleUrl('http://127.0.0.1:23000/')).toBe('http://127.0.0.1:23000/');
  });
  it('falls back to the default port for anything else', () => {
    for (const value of [
      undefined,
      '',
      'http://example.com:23000/',
      'https://127.0.0.1:23000/',
      'http://127.0.0.1:99999/',
      'http://127.0.0.1:23000/console',
      'javascript:alert(1)',
    ])
      expect(consoleUrl(value)).toBe(DEFAULT_CONSOLE_URL);
  });
});
