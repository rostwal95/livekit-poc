/** The processor receives actual PCM arrays in this unit harness; actual RTC is a separate gate. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runInNewContext } from 'node:vm';
import { NativePlaybackMeter, PLAYBACK_PROCESSOR } from './p2-playback-meter';
interface Processor {
  port: { onmessage: (event: { data: unknown }) => void };
  process: (input: Float32Array[][]) => boolean;
}
function fixture(sampleRate = 48000) {
  const reports: unknown[] = [];
  let ProcessorClass: (new () => Processor) | undefined;
  class Base {
    port = { onmessage: () => {}, postMessage: (data: unknown) => reports.push(data) };
  }
  runInNewContext(PLAYBACK_PROCESSOR, {
    AudioWorkletProcessor: Base,
    sampleRate,
    registerProcessor: (_name: string, value: new () => Processor) => {
      ProcessorClass = value;
    },
  });
  const processor = new ProcessorClass!();
  return {
    processor,
    reports,
    command: (data: unknown) => processor.port.onmessage({ data }),
    frame: (value: number) => processor.process([[new Float32Array(128).fill(value)]]),
  };
}
it('requires an active response, playing output and non-silent actual PCM', () => {
  const f = fixture();
  for (let i = 0; i < 64; i++) f.frame(0.1);
  expect(f.reports).toEqual([]);
  f.command({ kind: 'response', id: 'original' });
  for (let i = 0; i < 32; i++) f.frame(0.1);
  expect(f.reports).toEqual([]);
  f.command({ kind: 'playing', value: true });
  for (let i = 0; i < 32; i++) f.frame(0);
  expect(f.reports.at(-1)).toEqual({
    responseId: 'original',
    observedAudioMs: 0,
    sampledAudioMs: 85,
  });
  for (let i = 0; i < 32; i++) f.frame(0.1);
  expect(f.reports.at(-1)).toEqual({
    responseId: 'original',
    observedAudioMs: 85,
    sampledAudioMs: 170,
  });
});
it('retains the original response until explicit mapping and resets counters for a new one', () => {
  const f = fixture();
  f.command({ kind: 'response', id: 'a' });
  f.command({ kind: 'playing', value: true });
  for (let i = 0; i < 32; i++) f.frame(0.1);
  f.command({ kind: 'playing', value: false });
  for (let i = 0; i < 32; i++) f.frame(0.1);
  f.command({ kind: 'snapshot' });
  expect(f.reports.at(-1)).toEqual({ responseId: 'a', observedAudioMs: 85, sampledAudioMs: 85 });
  f.command({ kind: 'response', id: 'b' });
  f.command({ kind: 'snapshot' });
  expect(f.reports.at(-1)).toEqual({ responseId: 'b', observedAudioMs: 0, sampledAudioMs: 0 });
});
it('does not count invalid samples or report completion, approval or human hearing', () => {
  const f = fixture();
  f.command({ kind: 'response', id: 'a' });
  f.command({ kind: 'playing', value: true });
  for (let i = 0; i < 32; i++) f.frame(NaN);
  f.command({ kind: 'snapshot' });
  expect(f.reports.at(-1)).toEqual({ responseId: 'a', observedAudioMs: 0, sampledAudioMs: 0 });
});

it('counts only delivered processing windows, with no timer-derived progress', () => {
  const f = fixture();
  f.command({ kind: 'response', id: 'window_a' });
  f.command({ kind: 'playing', value: true });
  f.command({ kind: 'snapshot' });
  f.command({ kind: 'snapshot' });
  expect(f.reports.at(-1)).toEqual({
    responseId: 'window_a',
    observedAudioMs: 0,
    sampledAudioMs: 0,
  });
});
it('measures non-silent quantum windows rather than claiming exact voiced samples or hearing', () => {
  const f = fixture();
  f.command({ kind: 'response', id: 'window_a' });
  f.command({ kind: 'playing', value: true });
  const impulse = new Float32Array(128);
  impulse[0] = 1;
  f.processor.process([[impulse]]);
  f.command({ kind: 'snapshot' });
  expect(f.reports.at(-1)).toEqual({
    responseId: 'window_a',
    observedAudioMs: 2,
    sampledAudioMs: 2,
  });
  expect(Object.keys(f.reports.at(-1) as object).sort()).toEqual([
    'observedAudioMs',
    'responseId',
    'sampledAudioMs',
  ]);
});
it('does not count subthreshold PCM, infinity or a window containing one invalid sample', () => {
  const f = fixture();
  f.command({ kind: 'response', id: 'a' });
  f.command({ kind: 'playing', value: true });
  f.frame(0.0001);
  f.frame(Infinity);
  const mixed = new Float32Array(128).fill(0.1);
  mixed[127] = NaN;
  f.processor.process([[mixed]]);
  f.command({ kind: 'snapshot' });
  expect(f.reports.at(-1)).toEqual({ responseId: 'a', observedAudioMs: 0, sampledAudioMs: 2 });
});
it('bounds the observation window and retains the original samples without implying completion', () => {
  const f = fixture(8);
  f.command({ kind: 'response', id: 'a' });
  f.command({ kind: 'playing', value: true });
  for (let n = 0; n < 40; n++) f.frame(0.1);
  f.command({ kind: 'snapshot' });
  expect(f.reports.at(-1)).toEqual({
    responseId: 'a',
    observedAudioMs: 180000,
    sampledAudioMs: 180000,
  });
  f.frame(0.1);
  f.command({ kind: 'snapshot' });
  expect(f.reports.at(-1)).toEqual({
    responseId: 'a',
    observedAudioMs: 180000,
    sampledAudioMs: 180000,
  });
});

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
const contexts: FakeContext[] = [];
const nodes: FakeNode[] = [];
class FakeSource {
  connect = vi.fn();
  disconnect = vi.fn();
}
class FakeContext {
  state: AudioContextState = 'suspended';
  destination = {};
  source = new FakeSource();
  audioWorklet = { addModule: vi.fn(async () => {}) };
  createMediaStreamSource = vi.fn(() => this.source);
  resume = vi.fn(async () => {
    this.state = 'running';
  });
  close = vi.fn(async () => {
    this.state = 'closed';
  });
  constructor() {
    contexts.push(this);
  }
}
class FakeNode {
  port = {
    onmessage: null as ((event: MessageEvent<unknown>) => void) | null,
    postMessage: vi.fn(),
    close: vi.fn(),
  };
  connect = vi.fn();
  disconnect = vi.fn();
  constructor() {
    nodes.push(this);
  }
}
const track = { kind: 'audio', readyState: 'live', stop: vi.fn() } as unknown as MediaStreamTrack;
async function meter(callback = vi.fn()) {
  const owned = await NativePlaybackMeter.create(track, callback);
  return { owned, callback, context: contexts.at(-1)!, node: nodes.at(-1)! };
}
beforeEach(() => {
  contexts.length = 0;
  nodes.length = 0;
  vi.stubGlobal('AudioContext', FakeContext);
  vi.stubGlobal('AudioWorkletNode', FakeNode);
  vi.stubGlobal(
    'MediaStream',
    class {
      constructor(readonly tracks: MediaStreamTrack[]) {}
    },
  );
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fixture-meter');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('browser meter actual owner lifecycle with mocked native resources', () => {
  it('owns one silent analysis chain without stopping the separately owned remote track', async () => {
    const f = await meter();
    expect(f.context.source.connect).toHaveBeenCalledWith(f.node);
    expect(f.node.connect).toHaveBeenCalledWith(f.context.destination);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:fixture-meter');
    await f.owned.close();
    expect(f.node.port.close).toHaveBeenCalledOnce();
    expect(f.context.source.disconnect).toHaveBeenCalledOnce();
    expect(f.node.disconnect).toHaveBeenCalledOnce();
    expect(f.context.close).toHaveBeenCalledOnce();
    expect(track.stop).not.toHaveBeenCalled();
  });
  it('keeps original response selection on equal replay and rejects late foreign messages', async () => {
    const f = await meter();
    f.owned.response('response_a');
    f.owned.response('response_a');
    expect(f.node.port.postMessage).toHaveBeenCalledTimes(1);
    const notify = f.node.port.onmessage!;
    notify({
      data: { responseId: 'old_response', observedAudioMs: 50, sampledAudioMs: 50 },
    } as MessageEvent);
    for (const data of [
      { responseId: 'response_a', observedAudioMs: NaN, sampledAudioMs: 50 },
      { responseId: 'response_a', observedAudioMs: 60, sampledAudioMs: 50 },
      { responseId: 'response_a', observedAudioMs: 1, sampledAudioMs: 180001 },
      { responseId: 'response_a', observedAudioMs: 1, sampledAudioMs: 1, completed: true },
    ])
      notify({ data } as MessageEvent);
    expect(f.callback).not.toHaveBeenCalled();
    notify({
      data: { responseId: 'response_a', observedAudioMs: 25, sampledAudioMs: 40 },
    } as MessageEvent);
    expect(f.callback).toHaveBeenCalledExactlyOnceWith({
      responseId: 'response_a',
      observedAudioMs: 25,
      sampledAudioMs: 40,
    });
    expect(Object.isFrozen(f.callback.mock.calls[0]?.[0])).toBe(true);
    await f.owned.close();
    notify({
      data: { responseId: 'response_a', observedAudioMs: 30, sampledAudioMs: 50 },
    } as MessageEvent);
    expect(f.callback).toHaveBeenCalledOnce();
  });
  it('retains a shared in-flight close until actual AudioContext closure settles', async () => {
    const f = await meter();
    const gate = deferred();
    f.context.close.mockImplementation(async () => {
      await gate.promise;
      f.context.state = 'closed';
    });
    const first = f.owned.close();
    let settled = false;
    const second = f.owned.close().then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    expect(f.context.close).toHaveBeenCalledOnce();
    gate.resolve();
    await Promise.all([first, second]);
    expect(f.context.state).toBe('closed');
    expect(f.node.port.onmessage).toBeNull();
  });
  it('never makes a rejected context close look successful on a later call', async () => {
    const f = await meter();
    f.context.close.mockRejectedValue(new Error('held_close_failure'));
    await expect(f.owned.close()).rejects.toThrow();
    await expect(f.owned.close()).rejects.toThrow();
    expect(f.context.state).not.toBe('closed');
    f.context.close.mockImplementation(async () => {
      f.context.state = 'closed';
    });
    await f.owned.close();
    expect(f.context.state).toBe('closed');
  });
  it('attempts every independent owner when port and graph disconnects fail', async () => {
    const f = await meter();
    f.node.port.close.mockImplementation(() => {
      throw new Error('port_failed');
    });
    f.context.source.disconnect.mockImplementation(() => {
      throw new Error('source_failed');
    });
    f.node.disconnect.mockImplementation(() => {
      throw new Error('node_failed');
    });
    await expect(f.owned.close()).rejects.toThrow();
    expect(f.node.port.close).toHaveBeenCalledOnce();
    expect(f.context.source.disconnect).toHaveBeenCalledOnce();
    expect(f.node.disconnect).toHaveBeenCalledOnce();
    expect(f.context.close).toHaveBeenCalledOnce();
    f.node.port.close.mockReset();
    f.context.source.disconnect.mockReset();
    f.node.disconnect.mockReset();
    await f.owned.close();
  });
  it('closes the constructed graph when module or graph setup fails', async () => {
    vi.stubGlobal(
      'AudioWorkletNode',
      class extends FakeNode {
        constructor() {
          super();
          this.connect.mockImplementation(() => {
            throw new Error('graph_setup_failed');
          });
        }
      },
    );
    await expect(NativePlaybackMeter.create(track, vi.fn())).rejects.toThrow();
    expect(contexts[0]?.source.disconnect).toHaveBeenCalledOnce();
    expect(nodes[0]?.disconnect).toHaveBeenCalledOnce();
    expect(contexts[0]?.close).toHaveBeenCalledOnce();
  });
  it('exposes failed setup cleanup ownership so End can retain and retry it', async () => {
    vi.stubGlobal(
      'AudioContext',
      class extends FakeContext {
        constructor() {
          super();
          this.audioWorklet.addModule.mockRejectedValue(new Error('module_failed'));
          this.close.mockRejectedValue(new Error('cleanup_failed'));
        }
      },
    );
    const failure: unknown = await NativePlaybackMeter.create(track, vi.fn()).then(
      () => null,
      (error) => error,
    );
    expect(failure).toMatchObject({ owner: expect.any(NativePlaybackMeter) });
    const owned = (failure as { owner: NativePlaybackMeter }).owner;
    expect(contexts[0]?.state).not.toBe('closed');
    contexts[0]!.close.mockImplementation(async () => {
      contexts[0]!.state = 'closed';
    });
    await owned.close();
    expect(contexts[0]?.state).toBe('closed');
  });
});
