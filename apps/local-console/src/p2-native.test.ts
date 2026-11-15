/** Synthetic SDK, DOM and HTTP drive the real page script; no backend or media claim. */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const sdk = vi.hoisted(() => {
  const agent = {
    identity: 'agent-a',
    kind: 'agent',
    attributes: {} as Record<string, string>,
    audioTrackPublications: new Map<string, never>(),
  };
  const rooms: FakeRoom[] = [];
  class FakeRoom {
    readonly handlers = new Map<string, (...args: unknown[]) => void>();
    readonly remoteParticipants = new Map([[agent.identity, agent]]);
    readonly localParticipant = { sendText: vi.fn(async () => undefined) };
    readonly connect = vi.fn(async () => undefined);
    readonly disconnect = vi.fn(async () => undefined);
    readonly registerTextStreamHandler = vi.fn();
    readonly unregisterTextStreamHandler = vi.fn();
    readonly removeAllListeners = vi.fn();
    constructor() {
      rooms.push(this);
    }
    on(event: string, handler: (...args: unknown[]) => void): this {
      this.handlers.set(event, handler);
      return this;
    }
    emit(event: string, ...args: unknown[]): void {
      this.handlers.get(event)?.(...args);
    }
  }
  return { agent, rooms, FakeRoom };
});
vi.mock('livekit-client', () => ({
  Room: sdk.FakeRoom,
  ParticipantKind: { AGENT: 'agent' },
  DataPacket_Kind: { RELIABLE: 0, LOSSY: 1 },
  Track: { Kind: { Audio: 'audio' }, Source: { Microphone: 'microphone' } },
  RoomEvent: Object.fromEntries(
    [
      'ParticipantConnected',
      'ParticipantDisconnected',
      'ParticipantAttributesChanged',
      'Reconnecting',
      'Reconnected',
      'Disconnected',
      'TrackSubscribed',
      'TrackUnsubscribed',
      'DataReceived',
    ].map((name) => [name, name]),
  ),
}));

const BINDING = '44444444-4444-4444-8444-444444444444',
  OPERATION = '66666666-6666-4666-8666-666666666666';
class Node extends EventTarget {
  readonly children: Node[] = [];
  readonly dataset: Record<string, string> = {};
  textContent = '';
  value = '';
  hidden = false;
  disabled = false;
  checked = true;
  className = '';
  constructor(readonly tagName = 'DIV') {
    super();
  }
  append(...nodes: Node[]): void {
    this.children.push(...nodes);
  }
  replaceChildren(...nodes: Node[]): void {
    this.children.splice(0, this.children.length, ...nodes);
  }
  setAttribute(): void {}
  remove(): void {}
  focus(): void {}
  querySelector(selector: string): Node | null {
    return this.#all().find((node) => `[data-lane="${node.dataset.lane}"]` === selector) ?? null;
  }
  querySelectorAll(selector: string): Node[] {
    return this.#all().filter((node) => node.tagName === selector.toUpperCase());
  }
  #all(): Node[] {
    return this.children.flatMap((node) => [node, ...node.#all()]);
  }
}
const nodes = new Map<string, Node>();
function node(id: string): Node {
  let item = nodes.get(id);
  if (!item) nodes.set(id, (item = new Node()));
  return item;
}
const click = (id: string) => node(id).dispatchEvent(new Event('click'));
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value));
const tick = async () => {
  for (let i = 0; i < 100; i++) await Promise.resolve();
};
function held<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  vi.resetModules();
  nodes.clear();
  sdk.rooms.length = 0;
  sdk.agent.attributes = {
    'p2.session_ready': 'true',
    'p2.inference_mode': 'scripted',
    'lk.agent.state': 'listening',
  };
  vi.stubGlobal('document', {
    getElementById: node,
    createElement: (tag: string) => new Node(tag.toUpperCase()),
  });
  vi.stubGlobal('window', new EventTarget());
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('keeps a response evidence read out of the concurrent context-read guard', async () => {
  const context = held<Response>();
  const fetcher = vi.fn<typeof fetch>(async (path) => {
    if (String(path) === '/p2/session')
      return Response.json({
        schemaVersion: 1,
        url: 'ws://127.0.0.1:7880',
        token: 'abc.def.ghi',
        roomId: 'room-a',
        participantId: 'browser-a',
        agentId: sdk.agent.identity,
        bindingId: BINDING,
      });
    if (String(path) === '/p2/context') return context.promise;
    return new Response('', { status: 503 });
  });
  const calls = (path: string) =>
    fetcher.mock.calls.filter(([target]) => String(target) === path).length;
  const actualReads = () =>
    (JSON.parse(node('native-evidence').textContent) as { rehydration: { actualReads: number } })
      .rehydration.actualReads;
  vi.stubGlobal('fetch', fetcher);
  await import('./p2-native');
  node('native-access').value = 'A'.repeat(43);
  click('native-join');
  await tick();
  expect(node('native-readiness').textContent).toBe('Native agent ready');
  const room = sdk.rooms[0]!,
    inputId = node('native-text-id').value;
  node('native-message').value = 'Is this eligible?';
  click('native-send');
  await tick();
  const receive = (topic: string, value: unknown) =>
    room.emit('DataReceived', bytes(value), sdk.agent, 0, topic);
  receive('p2.acceptance', {
    schemaVersion: 1,
    bindingId: BINDING,
    inputId,
    channel: 'web_chat',
    status: 'accepted',
    receiptId: '55555555-5555-4555-8555-555555555555',
    operationKey: OPERATION,
    acceptanceSequence: '1',
    code: null,
  });
  receive('p2.response', {
    schemaVersion: 1,
    bindingId: BINDING,
    generationId: '77777777-7777-4777-8777-777777777777',
    inputId,
    operationKey: OPERATION,
    responseId: '88888888-8888-4888-8888-888888888888',
    sdkSpeechId: 'speech_1',
    observationCount: 1,
  });
  await tick();
  expect(calls('/p2/response')).toBe(1);
  Object.assign(sdk.agent.attributes, {
    'p2.rehydration_profile': 'current_case_v1',
    'p2.context_ready': 'true',
  });
  room.emit('ParticipantAttributesChanged');
  await tick();
  click('native-context-refresh');
  await tick();
  expect(calls('/p2/context')).toBe(1);
  expect(node('native-context-refresh').disabled).toBe(true);
  expect(actualReads()).toBe(1);
  context.resolve(new Response('', { status: 503 }));
  await tick();
  expect(actualReads()).toBe(0);
  click('native-end');
  await tick();
  expect(room.disconnect).toHaveBeenCalledOnce();
});
