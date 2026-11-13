/** Counts actual rendered PCM windows; it never establishes hearing or completion. */
export interface PlaybackSample {
  readonly responseId: string;
  readonly observedAudioMs: number;
  readonly sampledAudioMs: number;
}
export const PLAYBACK_PROCESSOR = `
class P2PlaybackMeter extends AudioWorkletProcessor {
  constructor() {
    super(); this.response = null; this.playing = false;
    this.frames = 0; this.sampled = 0; this.since = 0;
    this.port.onmessage = ({data}) => {
      if (data?.kind === 'response' && typeof data.id === 'string') {
        this.response = data.id; this.frames = 0; this.sampled = 0; this.since = 0;
      } else if (data?.kind === 'playing') this.playing = data.value === true;
      else if (data?.kind === 'snapshot') this.report();
    };
  }
  report() {
    if (this.response) this.port.postMessage({responseId:this.response,
      observedAudioMs:Math.min(180000,Math.floor(this.frames*1000/sampleRate)),
      sampledAudioMs:Math.min(180000,Math.floor(this.sampled*1000/sampleRate))});
    this.since = 0;
  }
  process(inputs) {
    const pcm = inputs[0]?.[0];
    if (this.response && this.playing && pcm?.length && this.sampled < sampleRate*180) {
      let square = 0;
      for (const value of pcm) { if (!Number.isFinite(value)) return true; square += value*value; }
      this.sampled += pcm.length;
      if (square / pcm.length >= 0.00000025) this.frames += pcm.length;
      this.since += pcm.length;
      if (this.since >= 4096) this.report();
    }
    return true;
  }
}
registerProcessor('p2-playback-meter', P2PlaybackMeter);
`;
export class PlaybackMeterError extends Error {
  constructor(readonly owner: NativePlaybackMeter | null = null) {
    super('Playback observation cleanup is incomplete.');
  }
}
export class NativePlaybackMeter {
  #closed = false;
  #stopping = false;
  #closing: Promise<void> | null = null;
  #portClosed = false;
  #sourceDisconnected = false;
  #nodeDisconnected = false;
  #responseId: string | null = null;
  #source: MediaStreamAudioSourceNode | null = null;
  #node: AudioWorkletNode | null = null;
  private constructor(
    readonly context: AudioContext,
    readonly callback: (sample: PlaybackSample) => void,
  ) {}
  static async create(
    track: MediaStreamTrack,
    callback: (sample: PlaybackSample) => void,
  ): Promise<NativePlaybackMeter> {
    const context = new AudioContext(),
      owned = new NativePlaybackMeter(context, callback);
    let url: string | null = null;
    try {
      url = URL.createObjectURL(new Blob([PLAYBACK_PROCESSOR], { type: 'text/javascript' }));
      await context.audioWorklet.addModule(url);
      const source = context.createMediaStreamSource(new MediaStream([track]));
      owned.#source = source;
      const node = new AudioWorkletNode(context, 'p2-playback-meter', {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });
      owned.#node = node;
      node.port.onmessage = ({ data }: MessageEvent<unknown>) => {
        if (owned.#stopping || !data || typeof data !== 'object') return;
        const row = data as Record<string, unknown>;
        if (
          Object.keys(row).sort().join() !== 'observedAudioMs,responseId,sampledAudioMs' ||
          row.responseId !== owned.#responseId ||
          !Number.isInteger(row.observedAudioMs) ||
          !Number.isInteger(row.sampledAudioMs) ||
          (row.observedAudioMs as number) < 0 ||
          (row.sampledAudioMs as number) > 180000 ||
          (row.observedAudioMs as number) > (row.sampledAudioMs as number)
        )
          return;
        callback(
          Object.freeze({
            responseId: row.responseId as string,
            observedAudioMs: row.observedAudioMs as number,
            sampledAudioMs: row.sampledAudioMs as number,
          }),
        );
      };
      // The processor writes silence. The original media element owns audible output.
      source.connect(node);
      node.connect(context.destination);
      return owned;
    } catch {
      try {
        await owned.close();
      } catch {
        throw new PlaybackMeterError(owned);
      }
      throw new PlaybackMeterError();
    } finally {
      if (url !== null) URL.revokeObjectURL(url);
    }
  }
  response(id: string): void {
    if (this.#stopping || id === this.#responseId) return;
    this.#responseId = id;
    this.#node?.port.postMessage({ kind: 'response', id });
  }
  playing(value: boolean): void {
    if (!this.#stopping) this.#node?.port.postMessage({ kind: 'playing', value });
  }
  async resume(): Promise<void> {
    if (!this.#stopping) await this.context.resume();
  }
  close(): Promise<void> {
    if (this.#closed) return Promise.resolve();
    if (this.#closing) return this.#closing;
    this.#stopping = true;
    this.#closing = (async () => {
      let failed = false;
      if (!this.#portClosed)
        try {
          if (this.#node) {
            this.#node.port.onmessage = null;
            this.#node.port.close();
          }
          this.#portClosed = true;
        } catch {
          failed = true;
        }
      if (!this.#sourceDisconnected)
        try {
          this.#source?.disconnect();
          this.#sourceDisconnected = true;
        } catch {
          failed = true;
        }
      if (!this.#nodeDisconnected)
        try {
          this.#node?.disconnect();
          this.#nodeDisconnected = true;
        } catch {
          failed = true;
        }
      try {
        if (this.context.state !== 'closed') await this.context.close();
      } catch {
        failed = true;
      }
      this.#closed =
        this.#portClosed &&
        this.#sourceDisconnected &&
        this.#nodeDisconnected &&
        this.context.state === 'closed';
      if (failed || !this.#closed) throw new PlaybackMeterError(this);
    })().finally(() => {
      this.#closing = null;
    });
    return this.#closing;
  }
}
