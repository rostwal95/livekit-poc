import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createScriptedInput, ScriptedInputError } from './scripted-input';

const fixture = new Uint8Array(await readFile(new URL('../public/fixtures/input-investigate.wav', import.meta.url))), frames = 63865;
function clip(extra: Partial<AudioBuffer> = {}): AudioBuffer { return { length: frames, sampleRate: 16000, numberOfChannels: 1, duration: frames / 16000, ...extra } as AudioBuffer; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { promise, resolve }; }
const contexts: FakeContext[] = [], calls: string[] = [];
function fakeSource() { return { buffer: null as AudioBuffer | null, loop: false, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), disconnect: vi.fn() }; }
class FakeContext {
  state: AudioContextState = 'suspended'; sampleRate = 16000;
  track = { kind: 'audio', readyState: 'live', stop: vi.fn(() => { this.track.readyState = 'ended'; }) };
  source = fakeSource(); sources: ReturnType<typeof fakeSource>[] = [];
  destination = { stream: { getAudioTracks: () => [this.track], getTracks: () => [this.track] }, disconnect: vi.fn() };
  resume = vi.fn(async () => { calls.push('resume'); this.state = 'running'; });
  close = vi.fn(async () => { this.state = 'closed'; });
  decodeAudioData = vi.fn(async (_bytes: ArrayBuffer) => clip());
  createBufferSource = vi.fn(() => { const source = this.sources.length === 0 ? this.source : fakeSource(); this.sources.push(source); return source; });
  createMediaStreamDestination = vi.fn(() => this.destination);
  constructor(options: AudioContextOptions) { expect(options).toEqual({ sampleRate: 16000 }); calls.push('context'); contexts.push(this); }
}
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;
const tick = async (): Promise<void> => { for (let n = 0; n < 20; n += 1) await Promise.resolve(); };
beforeEach(() => {
  contexts.length = 0; calls.length = 0; vi.stubGlobal('AudioContext', FakeContext);
  fetcher = vi.fn<typeof fetch>(async () => { calls.push('fetch'); return new Response(fixture.slice()); }); vi.stubGlobal('fetch', fetcher);
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('explicit spoken WebAudio input ownership', () => {
  it('prepares one silent track in the user activation, replays from zero and closes once', async () => {
    const pending = createScriptedInput(); expect(calls).toEqual(['context', 'resume', 'fetch']);
    const input = await pending, context = contexts[0]!; expect(input.track).toBe(context.track); expect(Object.isFrozen(input)).toBe(true);
    expect(context.createBufferSource).not.toHaveBeenCalled(); expect(context.source.start).not.toHaveBeenCalled();
    input.replay(); expect(context.source.loop).toBe(false); expect(context.source.start).toHaveBeenCalledExactlyOnceWith(0, 0); expect(context.source.connect).toHaveBeenCalledExactlyOnceWith(context.destination);
    expect(fetcher.mock.calls[0]?.[0]).toBe('/fixtures/input-investigate.wav'); expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ credentials: 'omit', cache: 'no-store', redirect: 'error' });
    const closing = input.close(); expect(input.close()).toBe(closing); expect(context.track.stop).toHaveBeenCalledOnce(); expect(context.source.stop).toHaveBeenCalledOnce(); expect(context.source.disconnect).toHaveBeenCalledOnce(); await closing; expect(context.close).toHaveBeenCalledOnce(); expect(context.state).toBe('closed');
  });
  it('replaces each prior source instead of looping or replaying a partially consumed clip', async () => {
    const input = await createScriptedInput(), context = contexts[0]!;
    input.replay(); const first = context.sources[0]!; input.replay(); const second = context.sources[1]!;
    expect(context.sources).toHaveLength(2); expect(first.stop).toHaveBeenCalledOnce(); expect(first.disconnect).toHaveBeenCalledOnce();
    expect(second.buffer).toBe(first.buffer); expect(second.loop).toBe(false); expect(second.start).toHaveBeenCalledExactlyOnceWith(0, 0);
    await input.close(); expect(second.stop).toHaveBeenCalledOnce(); expect(second.disconnect).toHaveBeenCalledOnce();
    expect(() => input.replay()).toThrowError(ScriptedInputError); expect(context.sources).toHaveLength(2);
  });
  it('never starts after mute/abort or with an ended track or suspended context', async () => {
    const controller = new AbortController(), input = await createScriptedInput({ signal: controller.signal }), context = contexts[0]!;
    context.state = 'suspended'; expect(() => input.replay()).toThrowError(ScriptedInputError); expect(context.createBufferSource).not.toHaveBeenCalled();
    context.state = 'running'; context.track.readyState = 'ended'; expect(() => input.replay()).toThrowError(ScriptedInputError); expect(context.createBufferSource).not.toHaveBeenCalled();
    controller.abort(); expect(() => input.replay()).toThrowError(ScriptedInputError); expect(context.createBufferSource).not.toHaveBeenCalled(); await input.close();
  });
  it('stops owned resources and exposes no raw error when replay startup fails', async () => {
    const input = await createScriptedInput(), context = contexts[0]!;
    context.source.start.mockImplementationOnce(() => { throw new Error('SECRET_SENTINEL'); });
    try { input.replay(); throw new Error('expected failure'); } catch (error) { expect(error).toBeInstanceOf(ScriptedInputError); expect(String(error)).not.toContain('SECRET_SENTINEL'); }
    expect(context.track.readyState).toBe('ended'); await input.close(); expect(context.close).toHaveBeenCalledOnce(); expect(context.source.disconnect).toHaveBeenCalledOnce();
  });
  it('verifies copied spoken fixture and provenance against the canonical asset', async () => {
    const original = await readFile(new URL('../../../services/conversation_agent/assets/input-investigate.wav', import.meta.url));
    const manifest = JSON.parse(await readFile(new URL('../public/fixtures/manifest.json', import.meta.url), 'utf8')) as Record<string, unknown>;
    expect(Buffer.from(fixture)).toEqual(original); expect(manifest).toMatchObject({ schema_version: 1, kind: 'synthetic-spoken-input', file: 'input-investigate.wav', bytes: fixture.length, frames, sample_rate_hz: 16000, channels: 1, sample_width_bytes: 2 }); expect(createHash('sha256').update(fixture).digest('hex')).toBe(manifest.sha256);
  });
  it('rejects pre-aborted or unsupported creation before allocation or fetch', async () => {
    const controller = new AbortController(); controller.abort(); await expect(createScriptedInput({ signal: controller.signal })).rejects.toMatchObject({ code: 'aborted' }); vi.stubGlobal('AudioContext', undefined); await expect(createScriptedInput()).rejects.toMatchObject({ code: 'unsupported' }); expect(contexts).toHaveLength(0); expect(fetcher).not.toHaveBeenCalled();
  });
  it.each(['header', 'rate', 'channels', 'bits', 'truncated'])('rejects invalid %s before decode or startup', async (kind) => {
    let bytes = fixture.slice(); const view = new DataView(bytes.buffer);
    if (kind === 'header') bytes[0] = 0; if (kind === 'rate') view.setUint32(24, 22050, true); if (kind === 'channels') view.setUint16(22, 2, true); if (kind === 'bits') view.setUint16(34, 8, true); if (kind === 'truncated') bytes = bytes.slice(0, -1);
    fetcher.mockResolvedValueOnce(new Response(bytes)); await expect(createScriptedInput()).rejects.toMatchObject({ code: 'invalid' }); const context = contexts[0]!; expect(context.decodeAudioData).not.toHaveBeenCalled(); expect(context.source.start).not.toHaveBeenCalled(); expect(context.state).toBe('closed');
  });
  it('bounds declared and streamed bytes without trusting content length', async () => {
    fetcher.mockResolvedValueOnce(new Response('small', { headers: { 'Content-Length': '524289' } })); await expect(createScriptedInput()).rejects.toMatchObject({ code: 'invalid' });
    const cancelled = vi.fn(), body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array(262144)); controller.enqueue(new Uint8Array(262144)); controller.enqueue(new Uint8Array(1)); }, cancel: cancelled });
    fetcher.mockResolvedValueOnce(new Response(body)); await expect(createScriptedInput()).rejects.toMatchObject({ code: 'invalid' }); await tick(); expect(cancelled).toHaveBeenCalledOnce(); expect(contexts.every((context) => context.state === 'closed')).toBe(true);
  });
  it('times out a stalled stream and cancels its native reader', async () => {
    vi.useFakeTimers(); const cancelled = vi.fn(); fetcher.mockResolvedValueOnce(new Response(new ReadableStream({ cancel: cancelled })));
    const result = expect(createScriptedInput()).rejects.toMatchObject({ code: 'timed_out' }); await vi.advanceTimersByTimeAsync(5000); await result; expect(contexts[0]?.state).toBe('closed'); expect(cancelled).toHaveBeenCalledOnce();
  });
  it('aborts during noncancelable decode and never starts a late source', async () => {
    const decoded = deferred<AudioBuffer>(), controller = new AbortController(), pending = createScriptedInput({ signal: controller.signal }); contexts[0]!.decodeAudioData.mockReturnValueOnce(decoded.promise);
    await vi.waitFor(() => expect(contexts[0]!.decodeAudioData).toHaveBeenCalledOnce()); controller.abort(); await expect(pending).rejects.toMatchObject({ code: 'aborted' }); decoded.resolve(clip()); await tick(); expect(contexts[0]!.createBufferSource).not.toHaveBeenCalled(); expect(contexts[0]!.state).toBe('closed');
  });
  it('times out pending resume and handles late resolution without allocation', async () => {
    vi.useFakeTimers(); const resumed = deferred<void>(); vi.stubGlobal('AudioContext', class extends FakeContext { override resume = vi.fn(() => resumed.promise); });
    const result = expect(createScriptedInput()).rejects.toMatchObject({ code: 'timed_out' }); await vi.advanceTimersByTimeAsync(5000); await result; resumed.resolve(); await tick(); expect(contexts[0]!.state).toBe('closed'); expect(contexts[0]!.createBufferSource).not.toHaveBeenCalled();
  });
  it.each([{ numberOfChannels: 2 }, { sampleRate: 48000 }, { length: frames + 1 }, { duration: 13 }, { duration: Number.NaN }])('rejects inconsistent decode %o', async (extra) => {
    const pending = createScriptedInput(); contexts[0]!.decodeAudioData.mockResolvedValueOnce(clip(extra)); await expect(pending).rejects.toMatchObject({ code: 'invalid' }); expect(contexts[0]!.createBufferSource).not.toHaveBeenCalled(); expect(contexts[0]!.state).toBe('closed');
  });
  it('stops the created source on later abort and keeps close idempotent', async () => {
    const controller = new AbortController(), input = await createScriptedInput({ signal: controller.signal }); input.replay(); controller.abort(); expect(input.track.readyState).toBe('ended'); await input.close(); expect(contexts[0]!.close).toHaveBeenCalledOnce(); expect(contexts[0]!.source.stop).toHaveBeenCalledOnce();
  });
  it('bounds a hanging native close and keeps the stopped resources owned through late completion', async () => {
    vi.useFakeTimers(); const input = await createScriptedInput(), context = contexts[0]!, nativeClose = deferred<void>();
    context.close.mockImplementationOnce(async () => { await nativeClose.promise; context.state = 'closed'; });
    input.replay(); const closing = input.close(), result = expect(closing).rejects.toMatchObject({ code: 'timed_out' });
    expect(context.track.readyState).toBe('ended'); expect(context.source.stop).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1000); await result; expect(input.close()).toBe(closing);
    nativeClose.resolve(); await tick(); expect(context.state).toBe('closed'); expect(context.close).toHaveBeenCalledOnce();
  });
  it('returns fixed errors for private fetch and close failures after stopping tracks', async () => {
    fetcher.mockRejectedValueOnce(new Error('SECRET_SENTINEL')); await expect(createScriptedInput()).rejects.toMatchObject({ code: 'unavailable' }); const input = await createScriptedInput(), context = contexts.at(-1)!; context.close.mockRejectedValueOnce(new Error('SECRET_SENTINEL')); input.replay();
    try { await input.close(); throw new Error('expected failure'); } catch (error) { expect(error).toBeInstanceOf(ScriptedInputError); expect(String(error)).not.toContain('SECRET_SENTINEL'); } expect(context.track.readyState).toBe('ended'); expect(context.source.stop).toHaveBeenCalledOnce();
  });
});
