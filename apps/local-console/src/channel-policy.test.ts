/** Synthetic trusted transports exercise the real coordinator; no backend/media claim. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { JoinedApplication } from './channel-policy';
import { JoinedPanel, policyReadCaption } from './channel-policy-panel';
import type { PanelFacts } from './channel-policy-panel';
import type { View } from './channel-policy-policy';
import type { JoinedRoom } from './channel-policy-room';
import type { FrozenNativeInput } from './p2-native-policy';
const O = '11111111-1111-4111-8111-111111111111',
  B = '33333333-3333-4333-8333-333333333333',
  T = '2026-11-13T12:00:00.000Z',
  KEY = 'A'.repeat(43);
function held<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
const tick = async () => {
  for (let i = 0; i < 60; i++) await Promise.resolve();
};
class ElementStub extends EventTarget {
  textContent = '';
  readonly dataset: Record<string, string> = {};
  querySelectorAll(): HTMLElement[] {
    return [];
  }
  value = '';
  hidden = false;
  disabled = false;
  open = false;
  focus = vi.fn();
  attributes = new Map<string, string>();
  setAttribute(key: string, value: string) {
    this.attributes.set(key, value);
  }
}
class Panel extends JoinedPanel {
  readonly items = new Map<string, ElementStub>();
  view: View | null = null;
  facts: PanelFacts | null = null;
  override element<T extends HTMLElement>(name: string): T {
    let item = this.items.get(name);
    if (!item) {
      item = new ElementStub();
      this.items.set(name, item);
    }
    return item as unknown as T;
  }
  override render(view: View, facts: PanelFacts): void {
    this.view = view;
    this.facts = facts;
  }
}
const status = (generation = '0', command: string | null = null, stage = 'idle') => ({
  schemaVersion: 1,
  ownerEpoch: O,
  generation,
  originalStartCommandId: command,
  stage,
  asOf: T,
  nodeCursor: {
    nodeEpoch: B,
    generation: '7',
    recoveryRequired: false,
    endpoint: { host: '127.0.0.1', port: 11029 },
  },
  sdkReady: false,
  workerRunning: !['idle', 'closed'].includes(stage),
  expiresAt: null,
});
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
    },
  });
function setup(
  overrides: Partial<Record<string, (body: Record<string, unknown>) => Promise<Response>>> = {},
) {
  let command: string | null = null;
  const fetcher = vi.fn<typeof fetch>(async (path, options) => {
    const purpose = String(path).split('/').at(-1)!,
      body = JSON.parse(options!.body as string) as Record<string, unknown>;
    if (overrides[purpose]) return overrides[purpose]!(body);
    if (purpose === 'status')
      return response(status(command ? '1' : '0', command, command ? 'waiting_browser' : 'idle'));
    if (purpose === 'case')
      return response({
        schemaVersion: 1,
        case: { revision: '1', observedAt: T },
      });
    if (purpose === 'progress')
      return response({
        schemaVersion: 1,
        asOf: T,
        counts: {
          native: 0,
          sms: 0,
          pending: 0,
          running: 0,
          dispatched: 0,
          blocked: 0,
          exhausted: 0,
          uncertain: 0,
          workKnown: 0,
        },
      });
    if (purpose === 'start') {
      command = body.commandId as string;
      return response({
        schemaVersion: 1,
        ownerEpoch: O,
        generation: '1',
        originalStartCommandId: command,
        mode: 'scripted',
        stage: 'waiting_browser',
        rtc: {
          url: 'ws://127.0.0.1:7880',
          token: 'abc.def.ghi',
          roomId: 'room-a',
          participantId: 'browser-a',
          agentId: 'agent-a',
          bindingId: B,
          expiresAt: '2026-11-13T12:03:00.000Z',
        },
      });
    }
    if (purpose === 'end')
      return response(status('1', body.originalStartCommandId as string, 'closed'));
    return response({ schemaVersion: 1, status: 'unavailable', code: 'unavailable' }, 503);
  });
  const media = held<void>(),
    connect = held<void>();
  const port = {
    connect: vi.fn(() => connect.promise),
    close: vi.fn(() => media.promise),
    whenClosed: vi.fn(() => media.promise),
    sendText: vi.fn<(input: FrozenNativeInput) => Promise<void>>(async () => undefined),
    controlsPending: false,
    voicePrepared: false,
    turnInput: null,
  };
  const factory = vi.fn(() => port as unknown as JoinedRoom),
    panel = new Panel();
  const app = new JoinedApplication(document, fetcher, panel, factory);
  return { app, panel, fetcher, port, factory, media, connect };
}
async function authorize(s: ReturnType<typeof setup>) {
  s.panel.element<HTMLInputElement>('access').value = KEY;
  s.panel.element('access-form').dispatchEvent(new Event('submit', { cancelable: true }));
  await tick();
  expect(s.app.model.snapshot().authorized).toBe(true);
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(T));
  vi.stubGlobal(
    'document',
    Object.assign(new EventTarget(), {
      hidden: true,
      querySelector: () => null,
    }),
  );
  vi.stubGlobal('window', new EventTarget());
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe('joined page coordinator races', () => {
  it('clears the private input before the first HTTP call and keeps it out of rendered state', async () => {
    const s = setup();
    await authorize(s);
    expect(s.panel.element<HTMLInputElement>('access').value).toBe('');
    expect(s.fetcher).toHaveBeenCalled();
    expect(JSON.stringify(s.panel.view)).not.toContain(KEY);
  });
  it('starts actual media close promptly during held connect and blocks B until both owners settle', async () => {
    const s = setup();
    await authorize(s);
    s.app.join();
    await tick();
    expect(s.factory).toHaveBeenCalledTimes(1);
    s.app.end();
    expect(s.port.close).toHaveBeenCalledTimes(1);
    await tick();
    expect(s.app.model.snapshot().roomOwned).toBe(true);
    s.app.join();
    expect(s.factory).toHaveBeenCalledTimes(1);
    s.connect.resolve();
    s.media.resolve();
    await tick();
    expect(s.app.model.snapshot().phase).toBe('dormant');
    expect(s.app.model.snapshot().authorized).toBe(true);
  });
  it('fences a late grant after End and retains the original command rather than making another Room', async () => {
    const late = held<Response>();
    let original: Record<string, unknown> | null = null;
    const s = setup({
      start: async (body) => {
        original = body;
        return late.promise;
      },
    });
    await authorize(s);
    s.app.join();
    await tick();
    s.app.end();
    await tick();
    expect(original).not.toBeNull();
    const end = s.fetcher.mock.calls.find(([path]) => String(path).endsWith('/end'));
    expect(JSON.parse(end![1]!.body as string).originalStartCommandId).toBe(original!.commandId);
    late.resolve(
      response({
        schemaVersion: 1,
        ownerEpoch: O,
        generation: '1',
        originalStartCommandId: original!.commandId,
        mode: 'scripted',
        stage: 'waiting_browser',
        rtc: {
          url: 'ws://127.0.0.1:7880',
          token: 'abc.def.ghi',
          roomId: 'room-a',
          participantId: 'browser-a',
          agentId: 'agent-a',
          bindingId: B,
          expiresAt: '2026-11-13T12:03:00.000Z',
        },
      }),
    );
    await tick();
    expect(s.factory).not.toHaveBeenCalled();
    expect(s.app.model.snapshot().phase).toBe('dormant');
  });
  it('Forget captures End before clearing authorization but hides all old view facts immediately', async () => {
    const s = setup();
    await authorize(s);
    s.app.join();
    await tick();
    s.app.forget();
    expect(s.app.model.snapshot().authorized).toBe(false);
    expect(s.app.model.snapshot().start).toBeNull();
    expect(s.app.model.snapshot().parent).toBeNull();
    expect(s.app.model.snapshot().messages).toEqual([]);
    const end = s.fetcher.mock.calls.find(([path]) => String(path).endsWith('/end'));
    expect((end![1]!.headers as Record<string, string>).Authorization).toBe('Bearer ' + KEY);
    s.connect.resolve();
    s.media.resolve();
    await tick();
    expect(s.app.model.snapshot().roomOwned).toBe(false);
  });
  it('keeps dormant operator auth and freezes SMS occurredAt/body/command through unknown retry', async () => {
    let attempts = 0;
    const payloads: string[] = [];
    const s = setup({
      sms: async (body) => {
        payloads.push(JSON.stringify(body));
        if (++attempts === 1)
          return response(
            {
              schemaVersion: 1,
              status: 'unavailable',
              code: 'outcome_unknown',
            },
            503,
          );
        const id = body.commandId as string,
          event = 'cp_sms_' + id.replaceAll('-', '');
        return response({
          schemaVersion: 1,
          commandId: id,
          replayed: true,
          receipt: {
            receiptId: B,
            eventId: event,
            messageId: event,
            acceptanceSequence: '1',
            acceptedAt: T,
          },
        });
      },
    });
    await authorize(s);
    s.app.join();
    await tick();
    s.app.end();
    s.connect.resolve();
    s.media.resolve();
    await tick();
    s.panel.element<HTMLTextAreaElement>('sms-message').value = 'Investigate';
    s.app.sms();
    await tick();
    expect(s.app.model.snapshot().sms).toBe('unknown');
    JoinedPanel.prototype.render.call(s.panel, s.app.model.snapshot(), s.panel.facts!);
    expect(s.panel.element('sms').textContent).toBe('Retry original SMS');
    expect(s.panel.element<HTMLTextAreaElement>('sms-message').disabled).toBe(true);
    s.panel.element<HTMLTextAreaElement>('sms-message').value = 'Changed';
    vi.setSystemTime(new Date('2026-11-13T12:00:10.000Z'));
    s.app.sms();
    await tick();
    expect(payloads).toHaveLength(2);
    expect(payloads[1]).toBe(payloads[0]);
    expect(s.app.model.snapshot().sms).toBe('accepted');
    expect(s.app.model.snapshot().case?.revision).toBe('1');
  });
});

function originalGrant(body: Record<string, unknown>) {
  const generation = (BigInt(body.expectedGeneration as string) + 1n).toString();
  return {
    schemaVersion: 1,
    ownerEpoch: O,
    generation,
    originalStartCommandId: body.commandId,
    mode: 'scripted',
    stage: 'waiting_browser',
    rtc: {
      url: 'ws://127.0.0.1:17880',
      token: 'abc.def.ghi',
      roomId: 'room_' + generation,
      participantId: 'browser_' + generation,
      agentId: 'agent_' + generation,
      bindingId: generation === '1' ? B : '44444444-4444-4444-8444-444444444444',
      expiresAt: '2026-11-13T12:03:00.000Z',
    },
  };
}
function endCalls(s: ReturnType<typeof setup>) {
  return s.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/end'));
}
function originalEndReply(body: Record<string, unknown>) {
  return response(
    status(body.generation as string, body.originalStartCommandId as string, 'closed'),
  );
}
function readerFault(body: unknown, cancel = Promise.resolve()) {
  const bytes = new TextEncoder().encode(JSON.stringify(body));
  let reads = 0,
    releases = 0;
  const reader = {
    read: async () =>
      ++reads === 1 ? { done: false, value: bytes } : { done: true, value: undefined },
    cancel: vi.fn(() => cancel),
    releaseLock: () => {
      if (++releases === 1) throw new Error('PRIVATE');
    },
  };
  const reply = {
    status: 200,
    redirected: false,
    headers: new Headers({ 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }),
    body: { getReader: () => reader },
  } as unknown as Response;
  return { reply, reader };
}
describe('original-only retirement race families', () => {
  it('sends reserved End while actual Start and status are held, without aborting Start', async () => {
    const start = held<Response>(),
      read = held<Response>(),
      ending = held<Response>();
    let original!: Record<string, unknown>,
      endBody!: Record<string, unknown>,
      statusCalls = 0;
    const s = setup({
      start: async (body) => {
        original = body;
        return start.promise;
      },
      status: async () => (++statusCalls === 1 ? response(status()) : read.promise),
      end: async (body) => {
        endBody = body;
        return ending.promise;
      },
    });
    await authorize(s);
    s.app.join();
    await tick();
    const refresh = s.app.refresh(false);
    await tick();
    expect(s.app.client.pendingCount).toBe(2);
    s.app.end();
    expect(endCalls(s)).toHaveLength(1);
    expect(s.app.client.pendingCount).toBe(3);
    expect(s.app.model.snapshot().requests).toBe(3);
    const startCall = s.fetcher.mock.calls.find(([path]) => String(path).endsWith('/start'))!;
    expect(startCall[1]!.signal!.aborted).toBe(false);
    s.app.end();
    s.app.join();
    expect(endCalls(s)).toHaveLength(1);
    expect(s.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/start'))).toHaveLength(
      1,
    );
    ending.resolve(originalEndReply(endBody));
    await tick();
    expect(s.app.model.snapshot().phase).not.toBe('dormant');
    start.resolve(response(originalGrant(original)));
    read.resolve(response(status()));
    await refresh;
    await tick();
    expect(s.factory).not.toHaveBeenCalled();
    expect(s.app.client.pendingCount).toBe(0);
    expect(s.app.model.snapshot().phase).toBe('dormant');
  });
  it('replays exact End once after End-first409 and a late original grant, never adopting media', async () => {
    const start = held<Response>();
    let original!: Record<string, unknown>,
      ends = 0;
    const s = setup({
      start: async (body) => {
        original = body;
        return start.promise;
      },
      end: async (body) =>
        ++ends === 1
          ? response({ schemaVersion: 1, status: 'unavailable', code: 'conflict' }, 409)
          : originalEndReply(body),
    });
    await authorize(s);
    s.app.join();
    await tick();
    s.app.end();
    await tick();
    expect(endCalls(s)).toHaveLength(1);
    start.resolve(response(originalGrant(original)));
    await tick();
    expect(endCalls(s)).toHaveLength(2);
    expect(s.factory).not.toHaveBeenCalled();
    expect(endCalls(s)[1]![1]!.body).toBe(endCalls(s)[0]![1]!.body);
    expect((endCalls(s)[1]![1]!.headers as Record<string, string>).Authorization).toBe(
      'Bearer ' + KEY,
    );
    expect(s.app.model.snapshot().phase).toBe('dormant');
    expect(s.app.client.pendingCount).toBe(0);
  });
  it('Forget clears general access immediately and repeated Forget coalesces before late Start', async () => {
    const start = held<Response>();
    let original!: Record<string, unknown>,
      ends = 0;
    const s = setup({
      start: async (body) => {
        original = body;
        return start.promise;
      },
      end: async (body) =>
        ++ends === 1
          ? response({ schemaVersion: 1, status: 'unavailable', code: 'conflict' }, 409)
          : originalEndReply(body),
    });
    await authorize(s);
    const client = s.app.client;
    s.app.join();
    await tick();
    s.app.forget();
    await tick();
    expect(s.app.model.snapshot().authorized).toBe(false);
    expect(s.app.model.snapshot().start).toBeNull();
    expect(JSON.stringify(s.panel.view)).not.toContain(KEY);
    expect(s.panel.element<HTMLButtonElement>('end').disabled).toBe(false);
    s.app.forget();
    s.app.forget();
    await s.app.refresh(false);
    s.app.sms();
    s.app.join();
    await tick();
    expect(endCalls(s)).toHaveLength(1);
    start.resolve(response(originalGrant(original)));
    await tick();
    expect(endCalls(s)).toHaveLength(2);
    expect(s.factory).not.toHaveBeenCalled();
    expect(endCalls(s)[1]![1]!.body).toBe(endCalls(s)[0]![1]!.body);
    expect((endCalls(s)[1]![1]!.headers as Record<string, string>).Authorization).toBe(
      'Bearer ' + KEY,
    );
    expect(s.app.client).toBe(client);
    expect(s.app.model.snapshot().authorized).toBe(false);
    expect(s.app.model.snapshot().phase).toBe('locked');
    s.app.end();
    await tick();
    expect(endCalls(s)).toHaveLength(2);
  });
  it('does not automatically retry a third time, but explicit Retry End makes useful same-scope progress', async () => {
    const start = held<Response>();
    let ends = 0;
    const s = setup({
      start: async () => start.promise,
      end: async (body) =>
        ++ends === 1
          ? response({ schemaVersion: 1, status: 'unavailable', code: 'conflict' }, 409)
          : ends === 2
            ? response({ schemaVersion: 1, status: 'unavailable', code: 'cleanup_incomplete' }, 503)
            : originalEndReply(body),
    });
    await authorize(s);
    s.app.join();
    await tick();
    s.app.end();
    await tick();
    start.resolve(
      response({ schemaVersion: 1, status: 'unavailable', code: 'outcome_unknown' }, 503),
    );
    await tick();
    expect(endCalls(s)).toHaveLength(2);
    expect(s.app.model.snapshot().phase).toBe('cleanup_incomplete');
    expect(s.app.client.pendingCount).toBe(0);
    s.app.join();
    expect(s.factory).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(60000);
    expect(endCalls(s)).toHaveLength(2);
    s.app.end();
    await tick();
    expect(endCalls(s)).toHaveLength(3);
    for (const call of endCalls(s)) expect(call[1]!.body).toBe(endCalls(s)[0]![1]!.body);
    expect(s.app.model.snapshot().phase).toBe('dormant');
    await vi.advanceTimersByTimeAsync(10000);
    expect(endCalls(s)).toHaveLength(3);
  });
  it('keeps exact closed ACK separate from held media and End reader cleanup', async () => {
    const cleanup = held<void>();
    let fault: ReturnType<typeof readerFault> | null = null;
    const s = setup({
      end: async (body) => {
        fault = readerFault(
          status('1', body.originalStartCommandId as string, 'closed'),
          cleanup.promise,
        );
        return fault.reply;
      },
    });
    await authorize(s);
    const client = s.app.client;
    s.app.join();
    await tick();
    s.app.end();
    await tick();
    expect(s.app.client.pendingCount).toBe(1);
    expect(s.app.model.snapshot().roomOwned).toBe(true);
    s.app.end();
    s.app.end();
    await tick();
    expect(endCalls(s)).toHaveLength(1);
    expect(fault!.reader.cancel).toHaveBeenCalledTimes(1);
    s.connect.resolve();
    s.media.resolve();
    await tick();
    expect(s.app.model.snapshot().roomOwned).toBe(false);
    s.app.join();
    expect(s.factory).toHaveBeenCalledTimes(1);
    cleanup.resolve();
    await tick();
    expect(s.app.client.pendingCount).toBe(0);
    expect(s.app.model.snapshot().phase).toBe('dormant');
    expect(s.app.model.snapshot().authorized).toBe(true);
    expect(s.app.client).toBe(client);
  });
  it('explicit Retry End repairs retained original Start and status readers without replacing client or extra End', async () => {
    let original!: Record<string, unknown>,
      statusCalls = 0;
    let startFault: ReturnType<typeof readerFault> | null = null,
      statusFault: ReturnType<typeof readerFault> | null = null;
    const s = setup({
      start: async (body) => {
        original = body;
        startFault = readerFault(originalGrant(body));
        return startFault.reply;
      },
      status: async () => {
        if (++statusCalls === 1) return response(status());
        statusFault = readerFault(status('1', original.commandId as string, 'waiting_browser'));
        return statusFault.reply;
      },
    });
    await authorize(s);
    const client = s.app.client;
    s.app.join();
    await tick();
    const refresh = s.app.refresh(false);
    await tick();
    expect(s.app.client.pendingCount).toBe(2);
    s.app.end();
    await tick();
    s.connect.resolve();
    s.media.resolve();
    await tick();
    expect(endCalls(s)).toHaveLength(1);
    expect(s.app.model.snapshot().phase).not.toBe('dormant');
    expect(s.app.client.pendingCount).toBe(2);
    s.app.end();
    await refresh;
    await tick();
    expect(startFault!.reader.cancel).toHaveBeenCalledTimes(1);
    expect(statusFault!.reader.cancel).toHaveBeenCalledTimes(1);
    expect(endCalls(s)).toHaveLength(1);
    expect(s.app.client.pendingCount).toBe(0);
    expect(s.app.model.snapshot().phase).toBe('dormant');
    expect(s.app.client).toBe(client);
    s.app.join();
    await tick();
    expect(s.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/start'))).toHaveLength(
      2,
    );
  });
  it('rejects foreign closed ACK and keeps the original scope and key after reauthorization', async () => {
    let ends = 0;
    const s = setup({
      end: async (body) =>
        ++ends <= 2
          ? response(status('2', body.originalStartCommandId as string, 'closed'))
          : originalEndReply(body),
    });
    await authorize(s);
    s.app.join();
    await tick();
    s.app.forget();
    await tick();
    s.connect.resolve();
    s.media.resolve();
    await tick();
    expect(endCalls(s)).toHaveLength(2);
    expect(s.app.model.snapshot().phase).toBe('cleanup_incomplete');
    s.app.model.setAuthorization('B'.repeat(43));
    s.app.join();
    expect(s.factory).toHaveBeenCalledTimes(1);
    s.app.end();
    await tick();
    expect(endCalls(s)).toHaveLength(3);
    expect((endCalls(s)[2]![1]!.headers as Record<string, string>).Authorization).toBe(
      'Bearer ' + KEY,
    );
    expect(endCalls(s)[2]![1]!.body).toBe(endCalls(s)[0]![1]!.body);
    expect(s.app.model.snapshot().phase).toBe('dormant');
  });
});

describe('current-result read availability in the actual coordinator', () => {
  const current = (command: Record<string, unknown>, fact: Record<string, unknown>) => ({
    schemaVersion: 1,
    ownerEpoch: command.ownerEpoch,
    generation: command.generation,
    originalStartCommandId: command.originalStartCommandId,
    fact,
  });
  const previous = {
    state: 'not_applicable',
    eligible: null,
    uncertainty: null,
    revision: null,
    asOf: T,
  };
  const fresh = {
    state: 'current',
    eligible: true,
    uncertainty: 'none',
    revision: '1',
    asOf: '2026-11-13T12:00:06.000Z',
  };
  it('automatically progresses from429 to a fresh eligible fact while retaining the prior timestamp', async () => {
    let calls = 0;
    const s = setup({
      current: async (command) => {
        ++calls;
        return calls === 2
          ? response({ schemaVersion: 1, status: 'unavailable', code: 'capacity' }, 429)
          : response(current(command, calls === 1 ? previous : fresh));
      },
    });
    await authorize(s);
    (document as unknown as { hidden: boolean }).hidden = false;
    s.app.join();
    await tick();
    s.connect.resolve();
    await tick();
    expect(calls).toBe(1);
    const retained = s.app.model.snapshot().policy;
    expect(retained?.asOf).toBe(T);
    await vi.advanceTimersByTimeAsync(2000);
    await tick();
    expect(calls).toBe(2);
    expect(s.app.model.snapshot().policy).toBe(retained);
    expect(s.app.model.snapshot().policyRead).toBe('busy');
    expect(policyReadCaption(s.app.model.snapshot())).toBe(
      'Latest read busy; showing the prior observation.',
    );
    expect(s.app.model.snapshot().code).toBeNull();
    await vi.advanceTimersByTimeAsync(2000);
    await tick();
    expect(calls).toBe(3);
    expect(s.app.model.snapshot().policy).toEqual(fresh);
    expect(s.app.model.snapshot().policyRead).toBe('ok');
    expect(policyReadCaption(s.app.model.snapshot())).toBeNull();
    s.app.end();
    s.media.resolve();
    await tick();
  });
  it('keeps a case-lane503 separate from the last successful policy read', async () => {
    let failCase = false,
      calls = 0;
    const s = setup({
      case: async () =>
        failCase
          ? response({ schemaVersion: 1, status: 'unavailable', code: 'unavailable' }, 503)
          : response({ schemaVersion: 1, case: { revision: '1', observedAt: T } }),
      current: async (command) => {
        ++calls;
        return response(current(command, fresh));
      },
    });
    await authorize(s);
    s.app.join();
    await tick();
    s.connect.resolve();
    await tick();
    expect(calls).toBe(1);
    failCase = true;
    await s.app.refresh(false);
    expect(calls).toBe(1);
    expect(s.app.model.snapshot().policy).toEqual(fresh);
    expect(s.app.model.snapshot().policyRead).toBe('ok');
    expect(s.app.model.snapshot().code).toBe('unavailable');
    expect(policyReadCaption(s.app.model.snapshot())).toBeNull();
    s.app.end();
    s.media.resolve();
    await tick();
  });
  it('clears a pending current read immediately on Forget and rejects its late successful fact', async () => {
    const late = held<Response>();
    let command: Record<string, unknown> | null = null;
    const s = setup({
      current: async (value) => {
        command = value;
        return late.promise;
      },
    });
    await authorize(s);
    s.app.join();
    await tick();
    s.connect.resolve();
    await tick();
    const pass = s.app.refresh(false);
    await tick();
    expect(s.app.model.snapshot().policyRead).toBe('pending');
    s.app.forget();
    expect(s.app.model.snapshot().policy).toBeNull();
    expect(s.app.model.snapshot().policyRead).toBe('idle');
    expect(s.app.model.snapshot().authorized).toBe(false);
    late.resolve(response(current(command!, fresh)));
    await pass;
    s.media.resolve();
    await tick();
    expect(s.app.model.snapshot().policy).toBeNull();
    expect(s.app.model.snapshot().policyRead).toBe('idle');
    expect(s.app.model.snapshot().phase).toBe('locked');
  });
});

describe('joined text input identity', () => {
  async function ready() {
    let started: string | null = null;
    const s = setup({
      start: async (body) => {
        started = body.commandId as string;
        return response(originalGrant(body));
      },
      status: async () =>
        response(started ? { ...status('1', started, 'ready'), sdkReady: true } : status()),
    });
    await authorize(s);
    s.app.join();
    await tick();
    s.connect.resolve();
    await tick();
    const room = (
      s.factory.mock.calls[0] as unknown as ConstructorParameters<typeof JoinedRoom>
    )[1];
    room.connection('connected');
    room.native('agent_1', 'agent', {
      'p2.session_ready': 'true',
      'p2.inference_mode': 'scripted',
      'lk.agent.state': 'listening',
    });
    expect(s.app.model.snapshot().ready).toBe(true);
    return { ...s, room };
  }
  const accepted = (inputId: string) =>
    new TextEncoder().encode(
      JSON.stringify({
        schemaVersion: 1,
        bindingId: B,
        inputId,
        channel: 'web_chat',
        status: 'accepted',
        receiptId: '55555555-5555-4555-8555-555555555555',
        operationKey: '66666666-6666-4666-8666-666666666666',
        acceptanceSequence: '1',
        code: null,
      }),
    );
  const users = (s: Awaited<ReturnType<typeof ready>>) =>
    s.app.model.snapshot().messages.filter((row) => row.role === 'user');
  it('reuses one frozen input for a repeated Send until it is accepted, then mints a new one', async () => {
    const s = await ready();
    const field = s.panel.element<HTMLTextAreaElement>('message');
    field.value = 'Is this eligible?';
    s.app.send(false);
    await tick();
    s.app.send(false);
    await tick();
    const [first, second] = s.port.sendText.mock.calls.map(([input]) => input);
    expect(second).toEqual(first);
    expect(s.app.model.snapshot().inputs).toHaveLength(1);
    expect(users(s)).toHaveLength(1);
    s.room.data('p2.acceptance', accepted(first!.inputId));
    expect(field.value).toBe('');
    field.value = 'Does the refund apply?';
    s.app.send(false);
    await tick();
    expect(s.port.sendText.mock.calls[2]![0].inputId).not.toBe(first!.inputId);
    expect(users(s).map((row) => row.text)).toEqual([
      'Is this eligible?',
      'Does the refund apply?',
    ]);
  });
  it('sends on Enter only while Send is enabled and ignores key repeat', async () => {
    const s = await ready();
    const field = s.panel.element<HTMLTextAreaElement>('message'),
      send = s.panel.element<HTMLButtonElement>('send');
    field.value = 'Is this eligible?';
    const enter = (repeat: boolean) => {
      const event = Object.assign(new Event('keydown', { cancelable: true }), {
        key: 'Enter',
        shiftKey: false,
        isComposing: false,
        repeat,
      });
      field.dispatchEvent(event);
      return event.defaultPrevented;
    };
    send.disabled = true;
    expect(enter(false)).toBe(true);
    send.disabled = false;
    expect(enter(true)).toBe(true);
    expect(s.port.sendText).not.toHaveBeenCalled();
    expect(enter(false)).toBe(true);
    expect(s.port.sendText).toHaveBeenCalledOnce();
  });
});
