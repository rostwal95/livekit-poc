/** One public immutable native prepare client; shared context facade borrows existing storage. */
import {
  NativeAgentHttpClient,
  type NativeChannelInbox,
} from '@livekit-ecosystem/channel-continuity/native';
import { ChannelError } from '@livekit-ecosystem/channel-continuity/postgres';
import type { DispatchPorts } from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  ChannelRehydrator,
  type CurrentCasePort,
  type RehydrationOptions,
  type RehydrationContext,
} from '@livekit-ecosystem/channel-continuity/rehydration';
import type { FakeSmsIntegration } from '@livekit-ecosystem/channel-continuity/security';
import type { NativeRoomRoute } from './native-room-contract.js';
import {
  parseNativeBridgeConfiguration,
  parseRoomAttach,
  type NativeBridgeConfiguration,
  type RoomAttach,
} from './native-bridge-contract.js';
import { snapshotMethod } from './read-ports.js';
function safeAgentError(error: unknown): ChannelError {
  try {
    if (error instanceof ChannelError) {
      const d = Object.getOwnPropertyDescriptor(error, 'code');
      if (
        d &&
        'value' in d &&
        [
          'AccessDenied',
          'Overloaded',
          'DispatchUnavailable',
          'OperationConflict',
          'InvalidConfiguration',
          'CleanupIncomplete',
        ].includes(d.value)
      )
        return new ChannelError(d.value);
    }
  } catch {
    /* finite */
  }
  return new ChannelError('DispatchUnavailable');
}
type Input = Parameters<DispatchPorts['agent']['prepare']>[0];
export class NativeRoomAgent {
  readonly #client: NativeAgentHttpClient;
  readonly #prepare: DispatchPorts['agent']['prepare'];
  readonly #finish: () => Promise<void>;
  readonly #inspect: NativeAgentHttpClient['metrics'];
  readonly #calls = new Set<Promise<Awaited<ReturnType<DispatchPorts['agent']['prepare']>>>>();
  #closing = false;
  #closed = false;
  #closeTask: Promise<void> | undefined;
  constructor(
    route: NativeRoomRoute,
    configuration: NativeBridgeConfiguration,
    attachment: RoomAttach,
  ) {
    const c = parseNativeBridgeConfiguration(configuration),
      a = parseRoomAttach(attachment);
    this.#client = new NativeAgentHttpClient(c.prepareEndpoint, 'Bearer ' + a.prepareBearer, [
      {
        bindingId: a.bindingId,
        scope: route.scope,
        caseId: route.caseId,
        conversationId: route.conversationId,
      },
    ]);
    this.#prepare = snapshotMethod<DispatchPorts['agent']['prepare']>(this.#client.port, 'prepare');
    this.#finish = snapshotMethod<() => Promise<void>>(this.#client, 'close');
    this.#inspect = snapshotMethod<NativeAgentHttpClient['metrics']>(this.#client, 'metrics');
  }
  stop(): void {
    this.#closing = true;
  }
  metrics(): Readonly<Record<string, number | boolean>> {
    return Object.freeze({
      prepareCalls: this.#calls.size,
      clientActive: this.#inspect().active ?? 0,
      closing: this.#closing,
      closed: this.#closed,
    });
  }
  prepare(
    input: Input,
    signal: AbortSignal,
    current: () => void,
  ): ReturnType<DispatchPorts['agent']['prepare']> {
    if (this.#closing) return Promise.reject(new ChannelError('DispatchUnavailable'));
    if (this.#calls.size >= 1 || (this.#inspect().active ?? 0) >= 1)
      return Promise.reject(new ChannelError('Overloaded'));
    const actual = Promise.resolve()
      .then(() => {
        if (this.#closing) throw new ChannelError('DispatchUnavailable');
        current();
        return this.#prepare(input, signal);
      })
      .then((value) => {
        current();
        return value;
      })
      .catch((error) => {
        throw safeAgentError(error);
      });
    this.#calls.add(actual);
    void actual.then(
      () => this.#calls.delete(actual),
      () => this.#calls.delete(actual),
    );
    return actual;
  }
  close(): Promise<void> {
    this.stop();
    if (this.#closed) return Promise.resolve();
    if (!this.#closeTask) {
      const actual = Promise.resolve()
        .then(async () => {
          await this.#finish();
          await Promise.allSettled([...this.#calls]);
          if (this.#calls.size || this.#inspect().active !== 0)
            throw new ChannelError('CleanupIncomplete');
          this.#closed = true;
        })
        .catch(() => {
          throw new ChannelError('CleanupIncomplete');
        });
      this.#closeTask = actual;
      void actual.then(
        () => {
          this.#closeTask = undefined;
        },
        () => {
          this.#closeTask = undefined;
        },
      );
    }
    return this.#closeTask;
  }
}
export type NativeContextGuard = (
  bearer: string,
  read: () => Promise<RehydrationContext>,
) => Promise<RehydrationContext>;
/** Genuine public facade: check the current room before/after its native read.
 * Public SDK HTTP remains an as-of response; the parent/worker fences late End callbacks.
 * SMS retains the public SDK signed-SMS semantics.
 */
export class CurrentRoomRehydrator extends ChannelRehydrator {
  readonly #guard: NativeContextGuard;
  constructor(
    inbox: NativeChannelInbox,
    cases: CurrentCasePort,
    sms: FakeSmsIntegration,
    options: RehydrationOptions,
    guard: NativeContextGuard,
  ) {
    super(inbox, cases, sms, options);
    this.#guard = guard;
  }
  override native(
    ...args: Parameters<ChannelRehydrator['native']>
  ): ReturnType<ChannelRehydrator['native']> {
    return this.#guard(args[0], () => super.native(...args));
  }
}
