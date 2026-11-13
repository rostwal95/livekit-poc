/** Explicit synthetic spoken input. Native microphone APIs are never replaced or invoked. */
export interface ScriptedInputSource { readonly track: MediaStreamTrack; replay(): void; close(): Promise<void> }
export interface ScriptedInputOptions { readonly signal?: AbortSignal }
export type ScriptedInputErrorCode = 'unsupported' | 'aborted' | 'invalid' | 'timed_out' | 'unavailable';
export class ScriptedInputError extends Error {
  constructor(readonly code: ScriptedInputErrorCode) { super('The local scripted input could not be prepared or fully closed.'); this.name = 'ScriptedInputError'; }
}
const URL = '/fixtures/input-investigate.wav', SAMPLE_RATE = 16_000, MAX_BYTES = 512 * 1024, MAX_SECONDS = 12;
const CREATE_MILLISECONDS = 5_000, CLOSE_MILLISECONDS = 1_000;

function wavFrames(bytes: Uint8Array): number {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const text = (offset: number): string => String.fromCharCode(...bytes.subarray(offset, offset + 4));
  if (bytes.length < 44 || bytes.length > MAX_BYTES || text(0) !== 'RIFF' || text(8) !== 'WAVE' || view.getUint32(4, true) + 8 !== bytes.length) throw new ScriptedInputError('invalid');
  let offset = 12, chunks = 0, format = false, frames = 0;
  while (offset + 8 <= bytes.length) {
    if (++chunks > 16) throw new ScriptedInputError('invalid');
    const tag = text(offset), size = view.getUint32(offset + 4, true), start = offset + 8;
    if (start + size > bytes.length) throw new ScriptedInputError('invalid');
    if (tag === 'fmt ') {
      if (format || size !== 16 || view.getUint16(start, true) !== 1 || view.getUint16(start + 2, true) !== 1 || view.getUint32(start + 4, true) !== SAMPLE_RATE || view.getUint32(start + 8, true) !== SAMPLE_RATE * 2 || view.getUint16(start + 12, true) !== 2 || view.getUint16(start + 14, true) !== 16) throw new ScriptedInputError('invalid');
      format = true;
    } else if (tag === 'data') {
      if (frames !== 0 || size === 0 || size % 2 || size > SAMPLE_RATE * MAX_SECONDS * 2) throw new ScriptedInputError('invalid');
      frames = size / 2;
    }
    offset = start + size + size % 2;
  }
  if (!format || !frames || offset !== bytes.length) throw new ScriptedInputError('invalid');
  return frames;
}

/** Invoke directly inside the explicit source-selection click, before awaiting anything else. */
export async function createScriptedInput(options: ScriptedInputOptions = {}): Promise<ScriptedInputSource> {
  if (options.signal?.aborted) throw new ScriptedInputError('aborted');
  if (typeof AudioContext === 'undefined') throw new ScriptedInputError('unsupported');
  const transport = new AbortController();
  let context: AudioContext | null = null, source: AudioBufferSourceNode | null = null, destination: MediaStreamAudioDestinationNode | null = null;
  let closing: Promise<void> | null = null, stopped = false, failure: ScriptedInputError | null = null;
  let rejectDeadline!: (error: ScriptedInputError) => void;
  const deadline = new Promise<never>((_resolve, reject) => { rejectDeadline = reject; });
  void deadline.catch(() => undefined);
  const requireActive = (): void => { if (failure) throw failure; if (stopped) throw new ScriptedInputError('aborted'); };
  const wait = async <T>(operation: Promise<T>): Promise<T> => { const value = await Promise.race([operation, deadline]); requireActive(); return value; };
  const cancel = (code: 'aborted' | 'timed_out'): void => {
    if (failure || stopped) return;
    failure = new ScriptedInputError(code); rejectDeadline(failure); transport.abort();
    void close().catch(() => undefined);
  };
  const onAbort = (): void => cancel('aborted');
  const timer = setTimeout(() => cancel('timed_out'), CREATE_MILLISECONDS);
  options.signal?.addEventListener('abort', onAbort, { once: true });

  function close(): Promise<void> {
    if (closing) return closing;
    stopped = true; clearTimeout(timer); options.signal?.removeEventListener('abort', onAbort); transport.abort();
    try { source?.stop(); } catch { /* A source may not have started before cancellation. */ }
    try { source?.disconnect(); } catch { /* Track stop and context closure remain independently owned. */ }
    destination?.stream.getTracks().forEach((track) => track.stop());
    try { destination?.disconnect(); } catch { /* Context closure owns the remaining graph. */ }
    const owned = context;
    closing = (async () => {
      if (!owned || owned.state === 'closed') return;
      let closeTimer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([owned.close(), new Promise<never>((_resolve, reject) => { closeTimer = setTimeout(() => reject(new ScriptedInputError('timed_out')), CLOSE_MILLISECONDS); })]);
      } catch (error) { throw error instanceof ScriptedInputError ? error : new ScriptedInputError('unavailable'); }
      finally { if (closeTimer !== undefined) clearTimeout(closeTimer); }
    })();
    return closing;
  }

  try {
    // Both calls occur synchronously in the user activation before the first await.
    context = new AudioContext({ sampleRate: SAMPLE_RATE });
    const resumed = context.resume();
    void resumed.catch(() => undefined);
    const response = await wait(fetch(URL, { credentials: 'omit', cache: 'no-store', redirect: 'error', signal: transport.signal }));
    if (!response.ok || !response.body) throw new ScriptedInputError('unavailable');
    const declared = response.headers.get('Content-Length');
    if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > MAX_BYTES)) throw new ScriptedInputError('invalid');
    const reader = response.body.getReader(), parts: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const next = await wait(reader.read());
        if (next.done) break;
        size += next.value.byteLength;
        if (size > MAX_BYTES) throw new ScriptedInputError('invalid');
        parts.push(next.value);
      }
    } finally {
      // Cancel promptly on an abandoned read; release only after cancellation settles.
      const release = (): void => { try { reader.releaseLock(); } catch { /* Pending native reads can settle later. */ } };
      void reader.cancel().then(release, release);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
    const frames = wavFrames(bytes);
    await wait(resumed);
    if (context.state !== 'running' || context.sampleRate !== SAMPLE_RATE) throw new ScriptedInputError('unavailable');
    const audio = await wait(context.decodeAudioData(bytes.buffer));
    if (audio.numberOfChannels !== 1 || audio.sampleRate !== SAMPLE_RATE || audio.length !== frames || !Number.isFinite(audio.duration) || audio.duration <= 0 || audio.duration > MAX_SECONDS) throw new ScriptedInputError('invalid');
    requireActive();
    destination = context.createMediaStreamDestination();
    const tracks = destination.stream.getAudioTracks();
    if (tracks.length !== 1 || tracks[0]?.kind !== 'audio' || tracks[0].readyState !== 'live') throw new ScriptedInputError('invalid');
    const replay = (): void => {
      requireActive();
      if (context?.state !== 'running' || tracks[0]?.readyState !== 'live') throw new ScriptedInputError('unavailable');
      try {
        // A prepared/published track is silent until a verified manual turn begins.
        // Replace the previous bounded source and replay the same clip from sample zero.
        source?.stop(); source?.disconnect();
        source = context.createBufferSource(); source.buffer = audio; source.loop = false;
        source.connect(destination!); source.start(0, 0);
      } catch {
        void close().catch(() => undefined);
        throw new ScriptedInputError('unavailable');
      }
    };
    clearTimeout(timer);
    return Object.freeze({ track: tracks[0], replay, close });
  } catch (error) {
    const safe = failure ?? (error instanceof ScriptedInputError ? error : new ScriptedInputError('unavailable'));
    try { await close(); } catch { /* Preserve the creation failure; every owned resource was stopped first. */ }
    throw safe;
  }
}
