import { afterEach, describe, expect, it, vi } from 'vitest';
import { BACKGROUND_LIMITS, BackgroundController, BackgroundError } from './p3-background-policy';
import type { BackgroundCallbacks } from './p3-background-policy';
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (value: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const tick = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve();
};
function setup(changed: () => void = vi.fn()) {
  let callbacks!: BackgroundCallbacks;
  const port = {
    join: vi.fn<() => Promise<void>>(async () => undefined),
    sendText: vi.fn<() => Promise<void>>(async () => undefined),
    read: vi.fn(async () => ({ value: 'known' })),
    clearCredential: vi.fn(),
    close: vi.fn<() => Promise<void>>(async () => undefined),
  };
  const factory = vi.fn((_token: string, cb: BackgroundCallbacks) => {
    callbacks = cb;
    return port;
  });
  const controller = new BackgroundController(factory, changed, (value) =>
    value.value === 'unknown' ? 'unavailable' : null,
  );
  return { controller, port, factory, callbacks: () => callbacks };
}
async function joined() {
  const s = setup();
  await s.controller.connect('credential');
  s.callbacks().ready(true);
  return s;
}
afterEach(() => vi.useRealTimers());
describe('P3 native conversation ownership', () => {
  it('clears safe session identity on Forget and fences its late callback', async () => {
    const s = await joined();
    const identity = {
      sessionId: '33333333-3333-4333-8333-333333333333',
      caseId: 'case_demo',
      delegationId: 'delegation_demo',
      requestRevision: 1,
      inputFingerprint: '1'.repeat(64),
    };
    s.callbacks().session?.(identity);
    expect(s.controller.snapshot().identity).toEqual(identity);
    await s.controller.forget();
    s.callbacks().session?.(identity);
    expect(s.controller.snapshot().identity).toBeNull();
  });

  it('requires actual join and matching readiness before text, while reads remain independent', async () => {
    const s = setup(),
      joining = deferred<void>();
    s.port.join.mockReturnValueOnce(joining.promise);
    const pending = s.controller.connect('credential');
    await expect(s.controller.send('hello')).rejects.toMatchObject({ code: 'closed' });
    joining.resolve();
    await pending;
    await expect(s.controller.send('hello')).rejects.toMatchObject({ code: 'closed' });
    await s.controller.refresh();
    expect(s.controller.snapshot().observation).toEqual({ value: 'known' });
    s.callbacks().ready(true);
    await s.controller.send('hello');
    expect(s.port.sendText).toHaveBeenCalledExactlyOnceWith('hello');
    await s.controller.end();
  });
  it('never stores a credential in public state or diagnostics', async () => {
    const s = await joined();
    expect(JSON.stringify(s.controller.snapshot())).not.toContain('credential');
    await s.controller.forget();
    expect(s.port.clearCredential).toHaveBeenCalledOnce();
  });
  it('retains an ignored read after the caller deadline and rejects another admission', async () => {
    vi.useFakeTimers();
    const s = await joined(),
      held = deferred<{ value: string }>();
    s.port.read.mockReturnValueOnce(held.promise);
    const read = s.controller.refresh(),
      observed = expect(read).rejects.toMatchObject({ code: 'unavailable' });
    await vi.advanceTimersByTimeAsync(BACKGROUND_LIMITS.readMs);
    await observed;
    expect(s.controller.snapshot()).toMatchObject({ actualRequests: 1, reading: false });
    await expect(s.controller.refresh()).rejects.toMatchObject({ code: 'overloaded' });
    expect(s.port.read).toHaveBeenCalledOnce();
    held.resolve({ value: 'late' });
    await tick();
    expect(s.controller.snapshot()).toMatchObject({ actualRequests: 0, observation: null });
    await s.controller.refresh();
    expect(s.controller.snapshot().observation).toEqual({ value: 'known' });
    await s.controller.end();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('labels retained facts historical after error, then replaces them only on a successful read', async () => {
    const s = await joined();
    await s.controller.refresh();
    s.port.read.mockRejectedValueOnce(new Error('PRIVATE_SENTINEL'));
    await expect(s.controller.refresh()).rejects.toMatchObject({ code: 'unavailable' });
    expect(s.controller.snapshot()).toMatchObject({
      historical: true,
      observation: { value: 'known' },
    });
    s.port.read.mockResolvedValueOnce({ value: 'fresh' });
    await s.controller.refresh();
    expect(s.controller.snapshot()).toMatchObject({
      historical: false,
      observation: { value: 'fresh' },
    });
    await s.controller.end();
  });
  it('retains known facts when a successful HTTP read reports fresh application uncertainty', async () => {
    const s = await joined();
    await s.controller.refresh();
    s.port.read.mockResolvedValueOnce({ value: 'unknown' });
    await s.controller.refresh();
    expect(s.controller.snapshot()).toMatchObject({
      code: 'unavailable',
      historical: true,
      observation: { value: 'known' },
    });
    await s.controller.end();
  });
  it('blocks reads after access denial until Forget and explicit new connection', async () => {
    const s = await joined();
    await s.controller.refresh();
    s.port.read.mockRejectedValueOnce(new BackgroundError('access_denied'));
    await expect(s.controller.refresh()).rejects.toMatchObject({ code: 'access_denied' });
    await expect(s.controller.refresh()).rejects.toMatchObject({ code: 'closed' });
    await expect(s.controller.send('blocked')).rejects.toMatchObject({ code: 'closed' });
    expect(s.port.sendText).not.toHaveBeenCalled();
    await s.controller.forget();
    expect(s.controller.snapshot().observation).toBeNull();
    await s.controller.connect('new-credential');
    await s.controller.end();
  });
  it('clears private display immediately on Forget but retains ignored actual work and one close observer', async () => {
    vi.useFakeTimers();
    const s = await joined();
    await s.controller.refresh();
    const held = deferred<{ value: string }>();
    s.port.read.mockReturnValueOnce(held.promise);
    const read = s.controller.refresh();
    void read.catch(() => undefined);
    const first = s.controller.forget(),
      second = s.controller.forget();
    expect(second).toBe(first);
    expect(s.controller.snapshot()).toMatchObject({
      observation: null,
      messages: [],
      ownedClient: 1,
      cleanupComplete: false,
    });
    const failed = expect(first).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    await vi.advanceTimersByTimeAsync(BACKGROUND_LIMITS.closeMs);
    await failed;
    await expect(s.controller.connect('new-credential')).rejects.toMatchObject({
      code: 'overloaded',
    });
    expect(s.factory).toHaveBeenCalledOnce();
    s.callbacks().text('late private text');
    held.resolve({ value: 'late' });
    await tick();
    expect(s.controller.snapshot()).toMatchObject({
      ownedClient: 0,
      observation: null,
      messages: [],
      cleanupComplete: true,
    });
    await s.controller.connect('new-credential');
    await s.controller.end();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('retries actual failed close without reopening or losing the retained client', async () => {
    const s = await joined();
    s.port.close.mockRejectedValueOnce(new Error('PRIVATE_SENTINEL'));
    await expect(s.controller.end()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    expect(s.controller.snapshot().ownedClient).toBe(1);
    await s.controller.end();
    expect(s.port.close).toHaveBeenCalledTimes(2);
    expect(s.controller.snapshot().cleanupComplete).toBe(true);
  });
  it('retains an ignored join and cleans its late completion without admitting a second owner', async () => {
    vi.useFakeTimers();
    const s = setup(),
      held = deferred<void>();
    s.port.join.mockReturnValueOnce(held.promise);
    const joining = s.controller.connect('credential');
    void joining.catch(() => undefined);
    const ending = s.controller.end();
    const failed = expect(ending).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    await vi.advanceTimersByTimeAsync(BACKGROUND_LIMITS.closeMs);
    await failed;
    await expect(s.controller.connect('other')).rejects.toMatchObject({ code: 'overloaded' });
    held.resolve();
    await joining;
    await tick();
    expect(s.controller.snapshot()).toMatchObject({ ownedClient: 0, ready: false });
    expect(vi.getTimerCount()).toBe(0);
  });
  it('contains presentation exceptions without freeing owned I/O', async () => {
    const s = setup(() => {
      throw new Error('observer');
    });
    await s.controller.connect('credential');
    s.callbacks().ready(true);
    await s.controller.send('hello');
    expect(s.controller.snapshot().ownedClient).toBe(1);
    await s.controller.end();
  });
  it('handles reentrant End during inert port construction without joining or leaking the new port', async () => {
    let controller!: BackgroundController<null>;
    let ending!: Promise<void>;
    const close = vi.fn<() => Promise<void>>(async () => undefined),
      join = vi.fn<() => Promise<void>>(async () => undefined);
    controller = new BackgroundController(
      (_token, callbacks) => {
        callbacks.ready(true);
        return {
          join,
          sendText: async () => undefined,
          read: async () => null,
          clearCredential: vi.fn(),
          close,
        };
      },
      (state) => {
        if (state.ready) ending = controller.end();
      },
    );
    await expect(controller.connect('credential')).rejects.toMatchObject({ code: 'closed' });
    await ending;
    expect(join).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
    expect(controller.snapshot().ownedClient).toBe(0);
  });
  it('marks an abandoned send unknown, never automatically resends, and retains its actual reservation', async () => {
    vi.useFakeTimers();
    const s = await joined(),
      held = deferred<void>();
    s.port.sendText.mockReturnValueOnce(held.promise);
    const sending = s.controller.send('check policy'),
      failed = expect(sending).rejects.toMatchObject({ code: 'unknown' });
    await vi.advanceTimersByTimeAsync(BACKGROUND_LIMITS.sendMs);
    await failed;
    expect(s.controller.snapshot()).toMatchObject({
      actualSends: 1,
      messages: [{ delivery: 'unknown' }],
    });
    await expect(s.controller.send('again')).rejects.toMatchObject({ code: 'overloaded' });
    expect(s.port.sendText).toHaveBeenCalledOnce();
    held.resolve();
    await tick();
    expect(s.controller.snapshot()).toMatchObject({
      actualSends: 0,
      messages: [{ delivery: 'sent' }],
    });
    await s.controller.end();
  });
  it('enforces UTF-8 bounds and a finite transcript without changing work authority', async () => {
    const s = await joined();
    await expect(s.controller.send('é'.repeat(2049))).rejects.toMatchObject({ code: 'invalid' });
    expect(s.port.sendText).not.toHaveBeenCalled();
    for (let n = 0; n < 40; n++) s.callbacks().text(`answer ${n}`);
    expect(s.controller.snapshot().messages).toHaveLength(32);
    expect(s.controller.snapshot().messages[0]?.text).toBe('answer 8');
    await s.controller.end();
  });
});

describe('synchronous presentation reentrancy boundaries', () => {
  it.each(['reservation', 'message'] as const)(
    'does not send after Forget from the %s presentation callback',
    async (cut) => {
      let ending: Promise<void> | undefined;
      let injected = false;
      let s: ReturnType<typeof setup>;
      s = setup(() => {
        const state = s.controller.snapshot();
        if (
          !injected &&
          (cut === 'reservation'
            ? state.actualSends === 1
            : state.messages.some((m) => m.delivery === 'sending'))
        ) {
          injected = true;
          ending = s.controller.forget();
          void ending.catch(() => undefined);
        }
      });
      await s.controller.connect('credential');
      s.callbacks().ready(true);
      await expect(s.controller.send('private draft')).rejects.toMatchObject({ code: 'closed' });
      await ending;
      expect(s.port.sendText).not.toHaveBeenCalled();
      expect(s.controller.snapshot()).toMatchObject({ messages: [], ownedClient: 0 });
    },
  );
  it('does not begin a read after Forget from the read-reservation callback', async () => {
    let ending: Promise<void> | undefined;
    let injected = false;
    let s: ReturnType<typeof setup>;
    s = setup(() => {
      if (!injected && s.controller.snapshot().actualRequests === 1) {
        injected = true;
        ending = s.controller.forget();
        void ending.catch(() => undefined);
      }
    });
    await s.controller.connect('credential');
    await expect(s.controller.refresh()).rejects.toMatchObject({ code: 'closed' });
    await ending;
    expect(s.port.read).not.toHaveBeenCalled();
    expect(s.controller.snapshot().observation).toBeNull();
  });
  it('fences callbacks before publishing the cleared Forget view', async () => {
    let injecting = false;
    let injected = false;
    let s: ReturnType<typeof setup>;
    s = setup(() => {
      const state = s.controller.snapshot();
      if (injecting && !injected && state.messages.length === 0) {
        injected = true;
        s.callbacks().ready(true);
        s.callbacks().text('late private answer');
      }
    });
    await s.controller.connect('credential');
    s.callbacks().ready(true);
    s.callbacks().text('prior answer');
    injecting = true;
    await s.controller.forget();
    expect(s.controller.snapshot()).toMatchObject({ messages: [], ready: false, ownedClient: 0 });
  });
});
