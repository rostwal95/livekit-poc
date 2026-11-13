import {
  RehydrationError,
  type RehydrationContext,
} from '@livekit-ecosystem/channel-continuity/rehydration';
import type { DispatchPorts } from '@livekit-ecosystem/channel-continuity/dispatch';
import type { ProviderScope } from '@livekit-ecosystem/channel-continuity';
import { NativeRoomAgent } from './native-room-agent.js';
import {
  parseNativeBridgeConfiguration,
  parseRoomAttach,
  nativeBridgeInput,
  type NativeBridgeConfiguration,
  type RoomAttach,
  type RoomAttachment,
} from './native-bridge-contract.js';
/** One current protocol/grant owner; deeper global P2 result I/O remains application-owned. */
import { createHash, randomUUID, timingSafeEqual } from 'node:crypto';
import { ChannelError } from '@livekit-ecosystem/channel-continuity/postgres';
import {
  ResultReceiverError,
  type ResultNativeView,
} from '@livekit-ecosystem/channel-continuity/result-receiver';
import type {
  NativeBindingReceipt,
  NativePublication,
} from '@livekit-ecosystem/channel-continuity/native';
import { snapshotMethod } from './read-ports.js';
import { NativeRoomHttp } from './native-room-http.js';
import {
  NativeRoomError,
  roomFailure,
  roomText,
  ROOM_TOKEN,
  parseNativeRoomOptions,
  parseNativeRoomRoute,
  parseRoomOpen,
  parseRoomCommand,
  parseRoomRead,
  parseRoomRecover,
  publicationReceipt,
  revocationReceipt,
  snapshotNativeResult,
  type NativeRoomOptions,
  type NativeRoomRoute,
  type RoomControlConfiguration,
  type RoomOpen,
  type RoomCommand,
  type RoomRead,
  type RoomRecover,
  type RoomObservation,
  type RoomRecoveryObservation,
  type RoomControlReady,
  type RoomEndpoint,
  type RoomRevocation,
} from './native-room-contract.js';
export type NativeRoomPorts = Readonly<{
  publish: (value: NativePublication) => Promise<NativeBindingReceipt>;
  revoke: (bindingId: string) => Promise<Readonly<{ bindingId: string; revokedAt: string }>>;
  native: (bearer: string, deliveryId: string) => Promise<ResultNativeView | null>;
  ready: () => boolean;
}>;
type Room = {
  request: RoomOpen;
  generation: string;
  fingerprint: string;
  phase: RoomObservation['state'];
  expires: number;
  publication: NativeBindingReceipt | null;
  revocation: RoomRevocation | null;
  publishTask: Promise<NativeBindingReceipt> | undefined;
  publishStarted: boolean;
  closeTask: Promise<void> | undefined;
  reads: Set<Promise<ResultNativeView | null>>;
  timer: ReturnType<typeof setTimeout> | undefined;
  attachment: RoomAttach | undefined;
  attachmentFingerprint: string | undefined;
  agent: NativeRoomAgent | undefined;
  contexts: Set<Promise<RehydrationContext>>;
};
type Recovery = {
  request: RoomRecover;
  task: Promise<RoomRevocation> | undefined;
  observation: RoomRecoveryObservation | undefined;
};
const hash = (text: string) => createHash('sha256').update(text, 'utf8').digest('hex');
function sameBearer(value: string, expected: string): boolean {
  return (
    value.length === 43 &&
    timingSafeEqual(Buffer.from(hash(value), 'hex'), Buffer.from(expected, 'hex'))
  );
}
function contextFailure(error: unknown): RehydrationError {
  try {
    if (error instanceof RehydrationError) {
      const d = Object.getOwnPropertyDescriptor(error, 'code');
      if (
        d &&
        'value' in d &&
        ['access_denied', 'invalid_query', 'context_unavailable', 'overloaded', 'closed'].includes(
          d.value,
        )
      )
        return new RehydrationError(d.value);
    }
  } catch {
    /* finite */
  }
  return new RehydrationError('context_unavailable');
}
function dependencyCode(error: unknown): string | undefined {
  try {
    if (error instanceof ChannelError || error instanceof ResultReceiverError) {
      const d = Object.getOwnPropertyDescriptor(error, 'code');
      if (d && 'value' in d && typeof d.value === 'string') return d.value;
    }
  } catch {
    /* no dependency getters */
  }
  return undefined;
}
export class NativeRoomManager {
  readonly #route: NativeRoomRoute;
  readonly #configuration: RoomControlConfiguration;
  readonly #ports: NativeRoomPorts;
  readonly #publisherToken: string;
  readonly #forbidden: Set<string>;
  readonly #http: NativeRoomHttp;
  readonly #bridge: NativeBridgeConfiguration | undefined;
  readonly #epoch = randomUUID();
  readonly #grants = new Set<Promise<unknown>>();
  #generation = 0;
  #room: Room | undefined;
  #lastClosed:
    | Readonly<{
        observation: RoomObservation;
        fingerprint: string;
        nativeHash: string;
        viewHash: string;
        prepareHash: string | undefined;
      }>
    | undefined;
  #recovery: Recovery | undefined;
  #recoverId: string | null;
  #endpoint: RoomEndpoint | undefined;
  #starting: Promise<RoomControlReady> | undefined;
  #startupDeadline = 0;
  #closeTask: Promise<void> | undefined;
  #closing = false;
  #closed = false;
  #publications = 0;
  #revocations = 0;
  constructor(
    route: NativeRoomRoute,
    options: NativeRoomOptions,
    ports: NativeRoomPorts,
    bridge?: NativeBridgeConfiguration,
  ) {
    try {
      this.#route = parseNativeRoomRoute(route);
      const opts = parseNativeRoomOptions(options);
      this.#configuration = opts.configuration;
      this.#publisherToken = opts.publisherToken;
      this.#forbidden = new Set([hash(this.#publisherToken), ...opts.forbiddenBearers.map(hash)]);
      this.#ports = Object.freeze({
        publish: snapshotMethod<NativeRoomPorts['publish']>(ports, 'publish'),
        revoke: snapshotMethod<NativeRoomPorts['revoke']>(ports, 'revoke'),
        native: snapshotMethod<NativeRoomPorts['native']>(ports, 'native'),
        ready: snapshotMethod<NativeRoomPorts['ready']>(ports, 'ready'),
      });
      this.#recoverId = this.#configuration.recoverBindingId;
      this.#bridge = bridge === undefined ? undefined : parseNativeBridgeConfiguration(bridge);
      if (
        this.#bridge &&
        (this.#bridge.prepareEndpoint.port === this.#configuration.port ||
          this.#bridge.rehydrationPort === this.#configuration.port)
      )
        throw new NativeRoomError('invalid_input');
      this.#http = new NativeRoomHttp(
        this,
        this.#publisherToken,
        this.#bridge ? this.attachAgent.bind(this) : undefined,
      );
    } catch {
      throw new NativeRoomError('invalid_input');
    }
  }
  metrics(): Readonly<Record<string, number | boolean>> {
    return Object.freeze({
      roomOwners: this.#room ? 1 : 0,
      recoveryOwners: this.#recoverId ? 1 : 0,
      grantCalls: this.#grants.size,
      publicReadCalls: this.#room?.reads.size ?? 0,
      opening: this.#room?.phase === 'opening' ? 1 : 0,
      closingRoom: this.#room?.phase === 'closing' ? 1 : 0,
      closing: this.#closing,
      closed: this.#closed,
      globalReaderDrainGuaranteed: false,
      publications: this.#publications,
      nativeAgentOwners: this.#room?.agent ? 1 : 0,
      nativeAgentCalls: this.#room?.agent?.metrics().prepareCalls ?? 0,
      nativeAgentClientActive: this.#room?.agent?.metrics().clientActive ?? 0,
      contextCalls: this.#room?.contexts.size ?? 0,
      revocations: this.#revocations,
      ...this.#http.metrics(),
    });
  }
  ready(): RoomControlReady | null {
    if (!this.#endpoint || this.#closing) return null;
    return Object.freeze({
      nodeEpoch: this.#epoch,
      endpoint: this.#endpoint,
      generation: String(this.#generation),
      recoveryRequired: this.#recoverId !== null,
    });
  }
  start(): Promise<RoomControlReady> {
    if (this.#closing) return Promise.reject(new NativeRoomError('closed'));
    if (!this.#starting) {
      this.#startupDeadline = performance.now() + 2000;
      const actual = this.#http.start(this.#configuration.port).then((endpoint) => {
        this.#endpoint = endpoint;
        if (this.#closing) throw new NativeRoomError('closed');
        return this.ready()!;
      });
      this.#starting = actual;
      void actual.catch(() => {
        this.#closing = true;
        void this.close().catch(() => {});
      });
    }
    return this.#wait(
      this.#starting,
      this.#endpoint ? 2000 : Math.max(0, this.#startupDeadline - performance.now()),
      'unavailable',
    ).catch((error) => {
      this.#closing = true;
      void this.close().catch(() => {});
      throw roomFailure(error);
    });
  }
  #admit(): void {
    if (this.#closing) throw new NativeRoomError('closed');
    if (!this.#endpoint) throw new NativeRoomError('unavailable');
    let ready = false;
    try {
      ready = this.#ports.ready() === true;
    } catch {
      /* finite below */
    }
    if (!ready) throw new NativeRoomError('unavailable');
  }
  #epochCheck(epoch: string): void {
    if (epoch !== this.#epoch) throw new NativeRoomError('conflict');
  }
  async #wait<T>(
    actual: Promise<T>,
    milliseconds: number,
    code: 'unavailable' | 'outcome_unknown' | 'cleanup_incomplete',
  ): Promise<T> {
    const deadline = performance.now() + milliseconds;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const value = await Promise.race([
        actual,
        new Promise<never>((_r, reject) => {
          timer = setTimeout(() => reject(new NativeRoomError(code)), milliseconds);
        }),
      ]);
      if (performance.now() >= deadline) throw new NativeRoomError(code);
      return value;
    } catch (error) {
      throw roomFailure(error, code);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  #grant<T>(action: () => Promise<T>): Promise<T> {
    if (this.#grants.size >= 1) throw new NativeRoomError('capacity');
    const actual = Promise.resolve().then(action);
    this.#grants.add(actual);
    void actual.then(
      () => this.#grants.delete(actual),
      () => this.#grants.delete(actual),
    );
    return actual;
  }
  #view(room: Room): RoomObservation {
    return Object.freeze({
      schemaVersion: 1,
      nodeEpoch: this.#epoch,
      generation: room.generation,
      openId: room.request.openId,
      state: room.phase,
      publication: room.publication,
      revocation: room.revocation,
      globalReaderDrained: false,
    });
  }
  #closingRoom(room: Room): void {
    if (room.phase === 'closed') return;
    room.phase = 'closing';
    room.agent?.stop();
    if (room.timer) {
      clearTimeout(room.timer);
      room.timer = undefined;
    }
  }
  #publish(room: Room): Promise<NativeBindingReceipt> {
    const publication: NativePublication = Object.freeze({
      bindingId: room.request.binding.bindingId,
      bearer: room.request.binding.nativeBearer,
      roomId: room.request.binding.roomId,
      participantId: room.request.binding.participantId,
      expiresAt: room.request.binding.expiresAt,
    });
    const actual = this.#grant(async () => {
      this.#admit();
      if (this.#room !== room || room.phase === 'closing' || performance.now() >= room.expires)
        throw new NativeRoomError('closed');
      room.publishStarted = true;
      this.#publications = Math.min(Number.MAX_SAFE_INTEGER, this.#publications + 1);
      const receipt = publicationReceipt(await this.#ports.publish(publication), publication);
      room.publication = receipt;
      if (
        this.#view(room).state !== 'closing' &&
        this.#room === room &&
        !this.#closing &&
        performance.now() < room.expires
      )
        room.phase = 'ready';
      else {
        this.#closingRoom(room);
        void this.#finishRoom(room).catch(() => {});
      }
      return receipt;
    });
    room.publishTask = actual;
    room.phase = 'opening';
    void actual.catch(() => {
      if (this.#room === room && room.phase !== 'closing' && room.phase !== 'closed')
        room.phase = 'publication_unknown';
    });
    return actual;
  }
  async open(value: RoomOpen): Promise<RoomObservation> {
    try {
      const request = parseRoomOpen(value);
      this.#admit();
      this.#epochCheck(request.nodeEpoch);
      const fingerprint = hash(JSON.stringify(request)),
        existing = this.#room;
      if (existing) {
        if (existing.request.openId !== request.openId || existing.fingerprint !== fingerprint)
          throw new NativeRoomError('conflict');
        if (existing.phase === 'closing') throw new NativeRoomError('closed');
        if (performance.now() >= existing.expires) {
          this.#closingRoom(existing);
          void this.#finishRoom(existing).catch(() => {});
          throw new NativeRoomError('closed');
        }
        if (existing.phase === 'ready') return this.#view(existing);
        if (existing.phase === 'publication_unknown') this.#publish(existing);
        if (!existing.publishTask) throw new NativeRoomError('outcome_unknown');
        await this.#wait(existing.publishTask, 1000, 'outcome_unknown');
        if (this.#view(existing).state !== 'ready') throw new NativeRoomError('closed');
        return this.#view(existing);
      }
      if (this.#lastClosed?.observation.openId === request.openId) {
        if (this.#lastClosed.fingerprint !== fingerprint) throw new NativeRoomError('conflict');
        return this.#lastClosed.observation;
      }
      if (this.#recoverId !== null) throw new NativeRoomError('recovery_required');
      if (request.expectedGeneration !== String(this.#generation) || this.#generation >= 1000000)
        throw new NativeRoomError('conflict');
      const nativeHash = hash(request.binding.nativeBearer),
        viewHash = hash(request.roomViewBearer);
      if (
        nativeHash === viewHash ||
        this.#forbidden.has(nativeHash) ||
        this.#forbidden.has(viewHash) ||
        [
          this.#lastClosed?.nativeHash,
          this.#lastClosed?.viewHash,
          this.#lastClosed?.prepareHash,
        ].some((value) => value === nativeHash || value === viewHash) ||
        request.binding.bindingId === this.#lastClosed?.observation.revocation?.bindingId
      )
        throw new NativeRoomError('invalid_input');
      const remaining = Date.parse(request.binding.expiresAt) - Date.now();
      if (remaining < 1 || remaining > 180000) throw new NativeRoomError('invalid_input');
      const room: Room = {
        request,
        generation: String(++this.#generation),
        fingerprint,
        phase: 'opening',
        expires: performance.now() + remaining,
        publication: null,
        revocation: null,
        publishTask: undefined,
        publishStarted: false,
        closeTask: undefined,
        reads: new Set(),
        timer: undefined,
        attachment: undefined,
        attachmentFingerprint: undefined,
        agent: undefined,
        contexts: new Set(),
      };
      this.#room = room;
      room.timer = setTimeout(() => {
        this.#closingRoom(room);
        void this.#finishRoom(room).catch(() => {});
      }, remaining);
      await this.#wait(this.#publish(room), 1000, 'outcome_unknown');
      if (room.phase !== 'ready') throw new NativeRoomError('closed');
      return this.#view(room);
    } catch (error) {
      throw roomFailure(error, 'outcome_unknown');
    }
  }
  observe(value: RoomCommand): RoomObservation {
    try {
      const request = parseRoomCommand(value);
      this.#admit();
      this.#epochCheck(request.nodeEpoch);
      const room = this.#room;
      if (
        room &&
        room.request.openId === request.openId &&
        room.generation === request.generation
      ) {
        const observation = this.#view(room);
        return performance.now() >= room.expires && observation.state !== 'closed'
          ? Object.freeze({ ...observation, state: 'closing' as const })
          : observation;
      }
      const last = this.#lastClosed?.observation;
      if (last && last.openId === request.openId && last.generation === request.generation)
        return last;
      throw new NativeRoomError('conflict');
    } catch (error) {
      throw roomFailure(error);
    }
  }
  async #revoke(id: string): Promise<RoomRevocation> {
    try {
      return await this.#grant(async () => {
        this.#revocations = Math.min(Number.MAX_SAFE_INTEGER, this.#revocations + 1);
        return revocationReceipt(await this.#ports.revoke(id), id);
      });
    } catch (error) {
      if (dependencyCode(error) === 'NotFound')
        return Object.freeze({ bindingId: id, state: 'absent', revokedAt: null });
      throw new NativeRoomError('cleanup_incomplete');
    }
  }
  #finishRoom(room: Room): Promise<void> {
    this.#closingRoom(room);
    if (!room.closeTask) {
      const actual = Promise.resolve().then(async () => {
        if (room.agent) await room.agent.close();
        if (room.publishTask) await room.publishTask.catch(() => {});
        await Promise.allSettled([...room.reads, ...room.contexts]);
        if (!room.revocation)
          room.revocation = room.publishStarted
            ? await this.#revoke(room.request.binding.bindingId)
            : Object.freeze({
                bindingId: room.request.binding.bindingId,
                state: 'unpublished',
                revokedAt: null,
              });
        if (this.#grants.size !== 0 || room.reads.size !== 0 || room.contexts.size !== 0)
          throw new NativeRoomError('cleanup_incomplete');
        room.phase = 'closed';
        const observation = this.#view(room);
        this.#lastClosed = Object.freeze({
          observation,
          fingerprint: room.fingerprint,
          nativeHash: hash(room.request.binding.nativeBearer),
          viewHash: hash(room.request.roomViewBearer),
          prepareHash: room.attachment ? hash(room.attachment.prepareBearer) : undefined,
        });
        if (this.#room === room) this.#room = undefined;
      });
      room.closeTask = actual;
      void actual.catch(() => {
        if (room.closeTask === actual) room.closeTask = undefined;
      });
    }
    return room.closeTask;
  }
  async closeRoom(value: RoomCommand): Promise<RoomObservation> {
    try {
      const request = parseRoomCommand(value);
      this.#admit();
      this.#epochCheck(request.nodeEpoch);
      const room = this.#room;
      if (!room) {
        const last = this.#lastClosed?.observation;
        if (last && last.openId === request.openId && last.generation === request.generation)
          return last;
        throw new NativeRoomError('conflict');
      }
      if (room.request.openId !== request.openId || room.generation !== request.generation)
        throw new NativeRoomError('conflict');
      await this.#wait(this.#finishRoom(room), 1000, 'cleanup_incomplete');
      return this.#view(room);
    } catch (error) {
      throw roomFailure(error, 'cleanup_incomplete');
    }
  }
  async #recover(request: RoomRecover): Promise<RoomRecoveryObservation> {
    if (this.#recovery) {
      const prior = this.#recovery;
      if (JSON.stringify(prior.request) !== JSON.stringify(request))
        throw new NativeRoomError('conflict');
      if (prior.observation) return prior.observation;
    } else {
      if (
        this.#room ||
        this.#recoverId === null ||
        request.bindingId !== this.#recoverId ||
        request.expectedGeneration !== String(this.#generation) ||
        this.#generation >= 1000000
      )
        throw new NativeRoomError('conflict');
      this.#recovery = { request, task: undefined, observation: undefined };
    }
    const recovery = this.#recovery;
    if (!recovery.task) {
      const task = this.#revoke(request.bindingId);
      recovery.task = task;
      void task.catch(() => {
        if (recovery.task === task) recovery.task = undefined;
      });
    }
    const revocation = await recovery.task;
    if (!recovery.observation) {
      this.#recoverId = null;
      this.#generation++;
      recovery.observation = Object.freeze({
        schemaVersion: 1,
        nodeEpoch: this.#epoch,
        generation: String(this.#generation),
        bindingId: request.bindingId,
        state: 'recovered',
        revocation,
      });
    }
    return recovery.observation;
  }
  async recover(value: RoomRecover): Promise<RoomRecoveryObservation> {
    try {
      const request = parseRoomRecover(value);
      this.#admit();
      this.#epochCheck(request.nodeEpoch);
      return await this.#wait(this.#recover(request), 1000, 'cleanup_incomplete');
    } catch (error) {
      throw roomFailure(error, 'cleanup_incomplete');
    }
  }
  async attachAgent(value: RoomAttach): Promise<RoomAttachment> {
    try {
      const request = parseRoomAttach(value);
      this.#admit();
      this.#epochCheck(request.nodeEpoch);
      if (!this.#bridge) throw new NativeRoomError('unavailable');
      const room = this.#room;
      if (
        !room ||
        room.request.openId !== request.openId ||
        room.generation !== request.generation ||
        room.request.binding.bindingId !== request.bindingId
      )
        throw new NativeRoomError('conflict');
      if (room.phase !== 'ready' || performance.now() >= room.expires)
        throw new NativeRoomError('closed');
      const fingerprint = hash(JSON.stringify(request)),
        token = hash(request.prepareBearer);
      if (room.attachmentFingerprint && room.attachmentFingerprint !== fingerprint)
        throw new NativeRoomError('conflict');
      if (
        this.#forbidden.has(token) ||
        token === hash(room.request.binding.nativeBearer) ||
        token === hash(room.request.roomViewBearer) ||
        [
          this.#lastClosed?.nativeHash,
          this.#lastClosed?.viewHash,
          this.#lastClosed?.prepareHash,
        ].includes(token)
      )
        throw new NativeRoomError('invalid_input');
      room.attachmentFingerprint = fingerprint;
      room.attachment = request;
      if (!room.agent) room.agent = new NativeRoomAgent(this.#route, this.#bridge, request);
      return Object.freeze({
        schemaVersion: 1,
        nodeEpoch: this.#epoch,
        generation: room.generation,
        openId: request.openId,
        bindingId: request.bindingId,
        state: 'attached',
      });
    } catch (error) {
      throw roomFailure(error);
    }
  }
  async prepareNative(
    input: Parameters<DispatchPorts['agent']['prepare']>[0],
    signal: AbortSignal,
    provider: ProviderScope,
  ): Promise<Awaited<ReturnType<DispatchPorts['agent']['prepare']>> | null> {
    try {
      if (!this.#bridge) return null;
      const copied = nativeBridgeInput(input, this.#route, provider),
        room = this.#room;
      if (this.#closing) throw new ChannelError('DispatchUnavailable');
      if (
        !room ||
        copied.message.event.type !== 'text.received' ||
        copied.message.event.senderId !== room.request.binding.bindingId
      )
        return null;
      this.#admit();
      const check = () => {
        this.#admit();
        if (
          this.#room !== room ||
          room.phase !== 'ready' ||
          performance.now() >= room.expires ||
          !room.agent
        )
          throw new ChannelError('DispatchUnavailable');
      };
      check();
      return await room.agent!.prepare(copied, signal, check);
    } catch (error) {
      const code = dependencyCode(error);
      throw new ChannelError(
        code === 'Overloaded'
          ? 'Overloaded'
          : code === 'AccessDenied'
            ? 'AccessDenied'
            : 'DispatchUnavailable',
      );
    }
  }
  async nativeContext(
    bearer: string,
    read: () => Promise<RehydrationContext>,
  ): Promise<RehydrationContext> {
    const selected = () => {
      if (this.#closing) throw new RehydrationError('closed');
      const room = this.#room;
      if (
        !this.#bridge ||
        !room ||
        room.phase !== 'ready' ||
        performance.now() >= room.expires ||
        typeof bearer !== 'string' ||
        !sameBearer(bearer, hash(room.request.binding.nativeBearer))
      )
        throw new RehydrationError('access_denied');
      this.#admit();
      return room;
    };
    try {
      const room = selected();
      if (room.contexts.size >= 2) throw new RehydrationError('overloaded');
      const check = () => {
        if (selected() !== room) throw new RehydrationError('access_denied');
      };
      const actual = Promise.resolve()
        .then(() => {
          check();
          return read();
        })
        .then(
          (value) => {
            check();
            return value;
          },
          (error) => {
            throw contextFailure(error);
          },
        );
      room.contexts.add(actual);
      void actual.then(
        () => room.contexts.delete(actual),
        () => room.contexts.delete(actual),
      );
      return await actual;
    } catch (error) {
      throw contextFailure(error);
    }
  }
  #readRoom(request: RoomRead, bearer: string, expected?: Room): Room {
    this.#admit();
    const room = this.#room;
    if (
      !room ||
      room !== (expected ?? room) ||
      request.nodeEpoch !== this.#epoch ||
      request.generation !== room.generation ||
      room.phase !== 'ready' ||
      performance.now() >= room.expires ||
      !sameBearer(bearer, hash(room.request.roomViewBearer))
    )
      throw new NativeRoomError('unauthorized');
    return room;
  }
  assertDisclosure(value: RoomRead, viewBearer: string): void {
    this.#readRoom(parseRoomRead(value), roomText(viewBearer, ROOM_TOKEN));
  }
  async nativeResult(value: RoomRead, viewBearer: string): Promise<ResultNativeView | null> {
    try {
      const request = parseRoomRead(value),
        bearer = roomText(viewBearer, ROOM_TOKEN),
        room = this.#readRoom(request, bearer);
      if (room.reads.size >= 1) throw new NativeRoomError('capacity');
      const actual = Promise.resolve()
        .then(async () => {
          this.#readRoom(request, bearer, room);
          const raw = await this.#ports.native(
            room.request.binding.nativeBearer,
            request.deliveryId,
          );
          this.#readRoom(request, bearer, room);
          return snapshotNativeResult(raw, this.#route, request.deliveryId);
        })
        .catch((error) => {
          const code = dependencyCode(error);
          if (code === 'Overloaded') throw new NativeRoomError('capacity');
          if (code === 'AccessDenied') throw new NativeRoomError('unauthorized');
          throw roomFailure(error);
        });
      room.reads.add(actual);
      void actual.then(
        () => room.reads.delete(actual),
        () => room.reads.delete(actual),
      );
      return await this.#wait(actual, 1000, 'unavailable');
    } catch (error) {
      const code = dependencyCode(error);
      if (code === 'Overloaded') throw new NativeRoomError('capacity');
      if (code === 'AccessDenied') throw new NativeRoomError('unauthorized');
      throw roomFailure(error);
    }
  }
  close(): Promise<void> {
    this.#closing = true;
    if (this.#room) this.#closingRoom(this.#room);
    if (this.#closed) return Promise.resolve();
    if (!this.#closeTask) {
      const actual = Promise.resolve().then(async () => {
        await this.#http.close();
        if (this.#starting) await this.#starting.catch(() => {});
        if (this.#room) await this.#finishRoom(this.#room);
        if (this.#recoverId) {
          const request =
            this.#recovery?.request ??
            Object.freeze({
              schemaVersion: 1 as const,
              nodeEpoch: this.#epoch,
              expectedGeneration: String(this.#generation),
              bindingId: this.#recoverId,
            });
          await this.#recover(request);
        }
        if (this.#grants.size || this.#room) throw new NativeRoomError('cleanup_incomplete');
        this.#closed = true;
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
    return this.#wait(this.#closeTask, 1000, 'cleanup_incomplete');
  }
}
