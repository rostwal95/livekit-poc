/** Synthetic DOM and HTTP drive the real panel and controller; no browser or backend claim. */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mountBusinessPanel } from './business-panel';
import type { BusinessPanelHandle, BusinessPanelOptions } from './business-panel';

const fixture = readFileSync(
  new URL('../../../contracts/business/case-projection.json', import.meta.url),
  'utf-8',
);
const TASK = '11111111-1111-4111-8111-111111111111';
const TOKEN = 'private-ui-test-operator-token';
const TYPED = 'partially-typed-replacement-token';
class Node extends EventTarget {
  textContent = '';
  value = '';
  hidden = false;
  disabled = false;
  checked = false;
  className = '';
  dateTime = '';
  readonly dataset: Record<string, string> = {};
  readonly classList = { add: (): void => undefined };
  setAttribute(): void {}
  focus(): void {}
  append(): void {}
  replaceChildren(): void {}
  querySelectorAll(): Node[] {
    return [];
  }
}
class Host extends Node {
  innerHTML = '';
  readonly nodes = new Map<string, Node>();
  querySelector(selector: string): Node {
    let node = this.nodes.get(selector);
    if (!node) this.nodes.set(selector, (node = new Node()));
    return node;
  }
}
const tick = async () => {
  for (let i = 0; i < 60; i++) await Promise.resolve();
};
const observed = () => Response.json(JSON.parse(fixture) as unknown);
const status = (code: number) => new Response('', { status: code });
function setup(replies: Response[], tokens: Partial<BusinessPanelOptions> = {}) {
  const host = new Host();
  const fetcher = vi.fn<typeof fetch>(async () => replies.shift() ?? status(503));
  vi.stubGlobal('fetch', fetcher);
  const forgetToken = vi.fn(() => handle.forget());
  const handle: BusinessPanelHandle = mountBusinessPanel(host as unknown as HTMLElement, {
    takeToken: () => TOKEN,
    heldToken: () => TOKEN,
    forgetToken,
    ...tokens,
  });
  const node = (selector: string) => host.querySelector(selector);
  const dispatch = (selector: string, kind: string) =>
    node(selector).dispatchEvent(new Event(kind, { cancelable: true }));
  const resume = async () => {
    node('#business-resume-id').value = TASK;
    dispatch('#business-resume-form', 'submit');
    await tick();
  };
  return { fetcher, forgetToken, handle, node, dispatch, resume };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('document', { hidden: false, createElement: () => new Node() });
  vi.stubGlobal('window', {
    setTimeout: (handler: () => void, milliseconds: number) => setTimeout(handler, milliseconds),
    clearTimeout: (timer: ReturnType<typeof setTimeout>) => clearTimeout(timer),
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('operator-access denial of a P1 command', () => {
  it('keeps a 401-rejected command definitive so a later 409 replay clears it', async () => {
    const s = setup([observed(), status(401), observed(), status(409)]);
    await s.resume();
    s.dispatch('#business-request-quote', 'click');
    await tick();
    expect(s.forgetToken).toHaveBeenCalledOnce();
    expect(s.node('#business-pending').hidden).toBe(false);
    s.dispatch('#business-refresh', 'click');
    await tick();
    expect(s.node('#business-reconcile').disabled).toBe(false);
    s.dispatch('#business-reconcile', 'click');
    await tick();
    const [original, replay] = s.fetcher.mock.calls
      .filter(([path]) => String(path).endsWith('/quote'))
      .map(([, init]) => init?.body);
    expect(replay).toBe(original);
    expect(s.node('#business-pending').hidden).toBe(true);
  });
  it('keeps a 401-rejected submission correctable after a later 422', async () => {
    const s = setup([status(401), status(422)]);
    s.node('#business-booking').value = 'DEMO-BK-001';
    s.node('#business-check-in').value = '2030-12-10';
    s.node('#business-investigation').checked = true;
    s.dispatch('#business-form', 'submit');
    await tick();
    expect(s.forgetToken).toHaveBeenCalledOnce();
    expect(s.node('#business-request-key').hidden).toBe(false);
    s.dispatch('#business-form', 'submit');
    await tick();
    const [original, replay] = s.fetcher.mock.calls.map(([, init]) => init?.body);
    expect(replay).toBe(original);
    expect(s.node('#business-request-key').hidden).toBe(true);
    expect(s.node('#business-booking').disabled).toBe(false);
  });
});

describe('background business reads', () => {
  it('polls and follows agent task hints with the held token, leaving the access field alone', async () => {
    const access = { field: TOKEN, held: '' };
    const s = setup([observed(), observed(), observed()], {
      takeToken: () => {
        const value = access.field.trim() || access.held;
        if (value.length < 16) throw new Error('missing');
        access.held = value;
        access.field = '';
        return value;
      },
      heldToken: () => {
        if (!access.held) throw new Error('missing');
        return access.held;
      },
    });
    await s.resume();
    expect(access.field).toBe('');
    access.field = TYPED;
    await vi.advanceTimersByTimeAsync(1500);
    await tick();
    await s.handle.observeTask(TASK);
    const sent = s.fetcher.mock.calls.map(
      ([, init]) => (init?.headers as Record<string, string>).Authorization,
    );
    expect(sent).toEqual([`Bearer ${TOKEN}`, `Bearer ${TOKEN}`, `Bearer ${TOKEN}`]);
    expect(access.field).toBe(TYPED);
    expect(access.held).toBe(TOKEN);
  });
});
