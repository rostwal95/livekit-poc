import { RehydrationHttpServer } from '@livekit-ecosystem/channel-continuity/rehydration';
import { CurrentRoomRehydrator } from './native-room-agent.js';
import {
  parseNativeBridgeConfiguration,
  type NativeBridgeConfiguration,
} from './native-bridge-contract.js';
/** Explicit joined P2 application. Imports/configuration create no I/O or authority. */
import type { AccountScope, ProviderScope } from '@livekit-ecosystem/channel-continuity';
import {
  SeededAccounts,
  type DatabaseSettings,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  ChannelGateway,
  type GatewayEndpoint,
} from '@livekit-ecosystem/channel-continuity/gateway';
import {
  NativeGateway,
  NativeChannelInbox,
  type NativeIntegration,
} from '@livekit-ecosystem/channel-continuity/native';
import type { FakeSmsIntegration } from '@livekit-ecosystem/channel-continuity/security';
import type { DispatchPorts } from '@livekit-ecosystem/channel-continuity/dispatch';
import { ChannelOutbox, type CarrierSendPort } from '@livekit-ecosystem/channel-continuity/outbox';
import {
  ChannelResultReceiver,
  ChannelResultReader,
  ResultReceiverError,
  type ResultNativeView,
} from '@livekit-ecosystem/channel-continuity/result-receiver';
import type { CurrentCasePort } from '@livekit-ecosystem/channel-continuity/rehydration';
import { ChannelPolicySourceReader } from './source-reader.js';
import { ChannelPolicyReadHttp } from './read-http.js';
import { ChannelPolicyResultHttp } from './result-http.js';
import { snapshotMethod } from './read-ports.js';
import { NativeRoomManager } from './native-room-manager.js';
import {
  parseNativeRoomOptions,
  type NativeRoomOptions,
  type RoomControlReady,
} from './native-room-contract.js';

type ApplicationCode = 'invalid_input' | 'unavailable' | 'closed' | 'cleanup_incomplete';
export class GatewayApplicationError extends Error {
  readonly code: ApplicationCode;
  constructor(code: ApplicationCode = 'unavailable') {
    const safe =
      typeof code === 'string' &&
      ['invalid_input', 'unavailable', 'closed', 'cleanup_incomplete'].includes(code)
        ? code
        : 'unavailable';
    super(safe);
    this.name = 'GatewayApplicationError';
    this.code = safe;
  }
}
export type GatewayApplicationRoute = Readonly<{
  profileId: string;
  receiverId: string;
  scope: AccountScope;
  caseId: string;
  conversationId: string;
  recipientId: string;
}>;
export type GatewayApplicationConfiguration = Readonly<{
  database: DatabaseSettings;
  route: GatewayApplicationRoute;
  accountToken: string;
  workerBearer: string;
  resultPublisherToken: string;
  nativeIntegration: NativeIntegration;
  smsIntegration: FakeSmsIntegration;
  /** Owner provisioning must establish this actual persisted cap; serving never repairs it. */
  profileInboxLimit: 16;
  startupMs?: number;
  cleanupMs?: number;
}>;
export type GatewayApplicationPorts = Readonly<{
  native: DispatchPorts;
  sms: DispatchPorts;
  cases: CurrentCasePort;
  carrier: CarrierSendPort;
}>;
export type GatewayApplicationListen = Readonly<{
  nativePort?: number;
  smsPort?: number;
  readPort?: number;
  receiverPort?: number;
}>;
export type GatewayApplicationEndpoints = Readonly<{
  native: GatewayEndpoint;
  sms: GatewayEndpoint;
  read: GatewayEndpoint;
  receiver: GatewayEndpoint;
}>;
type Tier = 'transport' | 'reader' | 'storage';
type Owner = {
  label: string;
  tier: Tier;
  close: () => Promise<void>;
  closed: boolean;
  pending: Promise<void> | undefined;
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ID = /^[a-z][a-z0-9_-]{0,63}$/;
function fields(
  input: unknown,
  required: readonly string[],
  optional: readonly string[] = [],
): Record<string, unknown> {
  if (
    !input ||
    typeof input !== 'object' ||
    Array.isArray(input) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(input))
  )
    throw new GatewayApplicationError('invalid_input');
  const keys = Reflect.ownKeys(input);
  if (
    required.some((k) => !keys.includes(k)) ||
    keys.some((k) => typeof k !== 'string' || ![...required, ...optional].includes(k))
  )
    throw new GatewayApplicationError('invalid_input');
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const k of keys) {
    const d = Object.getOwnPropertyDescriptor(input, k);
    if (!d || !('value' in d) || !d.enumerable) throw new GatewayApplicationError('invalid_input');
    result[k as string] = d.value;
  }
  return result;
}
function text(input: unknown, pattern: RegExp): string {
  if (typeof input !== 'string' || pattern.exec(input)?.[0] !== input)
    throw new GatewayApplicationError('invalid_input');
  return input;
}
function number(input: unknown, min: number, max: number): number {
  if (typeof input !== 'number' || !Number.isSafeInteger(input) || input < min || input > max)
    throw new GatewayApplicationError('invalid_input');
  return input;
}
function provider(
  integration: unknown,
  kind: 'livekit' | 'fake_sms',
  tenant: string,
): ProviderScope {
  if (!integration || typeof integration !== 'object' || !Object.isFrozen(integration))
    throw new GatewayApplicationError('invalid_input');
  const d = Object.getOwnPropertyDescriptor(integration, 'providerScope');
  if (!d || !('value' in d)) throw new GatewayApplicationError('invalid_input');
  const p = fields(d.value, ['tenantId', 'provider', 'providerAccountId']);
  if (p.tenantId !== tenant || p.provider !== kind || !Object.isFrozen(d.value))
    throw new GatewayApplicationError('invalid_input');
  return Object.freeze({
    tenantId: tenant,
    provider: kind,
    providerAccountId: text(p.providerAccountId, /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/),
  });
}
function dispatchPorts(input: unknown): DispatchPorts {
  const p = fields(input, ['cases', 'agent', 'operations']);
  const caps = Object.getOwnPropertyDescriptor(p.operations, 'capabilities');
  if (!caps || !('value' in caps) || caps.value !== 'stable_idempotency_and_lookup')
    throw new GatewayApplicationError('invalid_input');
  return Object.freeze({
    cases: Object.freeze({
      inspect: snapshotMethod<DispatchPorts['cases']['inspect']>(p.cases, 'inspect'),
    }),
    agent: Object.freeze({
      prepare: snapshotMethod<DispatchPorts['agent']['prepare']>(p.agent, 'prepare'),
    }),
    operations: Object.freeze({
      capabilities: 'stable_idempotency_and_lookup',
      lookup: snapshotMethod<DispatchPorts['operations']['lookup']>(p.operations, 'lookup'),
      accept: snapshotMethod<DispatchPorts['operations']['accept']>(p.operations, 'accept'),
    }),
  });
}
function carrierPort(input: CarrierSendPort): CarrierSendPort {
  const d = Object.getOwnPropertyDescriptor(input, 'capabilities');
  if (!d || !('value' in d)) throw new GatewayApplicationError('invalid_input');
  const send = snapshotMethod<CarrierSendPort['send']>(input, 'send');
  if (d.value === 'ordinary_fake_sms_v1')
    return Object.freeze({ capabilities: 'ordinary_fake_sms_v1', send });
  if (d.value === 'idempotent_fake_sms_v1')
    return Object.freeze({
      capabilities: 'idempotent_fake_sms_v1',
      send,
      lookup: snapshotMethod<
        Extract<CarrierSendPort, { capabilities: 'idempotent_fake_sms_v1' }>['lookup']
      >(input, 'lookup'),
    });
  throw new GatewayApplicationError('invalid_input');
}
function listenPorts(input: GatewayApplicationListen): Required<GatewayApplicationListen> {
  const p = fields(input, [], ['nativePort', 'smsPort', 'readPort', 'receiverPort']);
  return Object.freeze({
    nativePort: number(p.nativePort ?? 0, 0, 65535),
    smsPort: number(p.smsPort ?? 0, 0, 65535),
    readPort: number(p.readPort ?? 0, 0, 65535),
    receiverPort: number(p.receiverPort ?? 0, 0, 65535),
  });
}
/** Nine public owners. Close borrowed case/agent/operation/carrier clients only after this drains.
 * Construction is deferred to explicit start. Public SDK constructors allocate inert pools/servers;
 * all query/listener admission starts after every returned owner is registered.
 */
export class ChannelPolicyGatewayApplication {
  readonly #config: GatewayApplicationConfiguration;
  readonly #ports: GatewayApplicationPorts;
  readonly #providers: Readonly<{ native: ProviderScope; sms: ProviderScope }>;
  readonly #startupMs: number;
  readonly #cleanupMs: number;
  readonly #owners: Owner[] = [];
  readonly #nativeCalls = new Set<Promise<ResultNativeView | null>>();
  #starting: Promise<GatewayApplicationEndpoints> | undefined;
  #startingPending = false;
  #startupDeadline = 0;
  #closeTask: Promise<void> | undefined;
  #listen: Required<GatewayApplicationListen> | undefined;
  #endpoints: GatewayApplicationEndpoints | undefined;
  #closing = false;
  #closed = false;
  #reader: ChannelResultReader | undefined;
  #native: NativeGateway | undefined;
  #sms: ChannelGateway | undefined;
  #readHttp: ChannelPolicyReadHttp | undefined;
  #resultHttp: ChannelPolicyResultHttp | undefined;
  readonly #roomOptions: NativeRoomOptions | undefined;
  #roomManager: NativeRoomManager | undefined;
  readonly #nativeBridge: NativeBridgeConfiguration | undefined;
  #contextHttp: RehydrationHttpServer | undefined;
  #contextEndpoint: GatewayEndpoint | undefined;
  constructor(
    configuration: GatewayApplicationConfiguration,
    ports: GatewayApplicationPorts,
    roomControl?: NativeRoomOptions,
    nativeBridge?: NativeBridgeConfiguration,
  ) {
    try {
      if (nativeBridge !== undefined && !roomControl)
        throw new GatewayApplicationError('invalid_input');
      this.#nativeBridge =
        nativeBridge === undefined ? undefined : parseNativeBridgeConfiguration(nativeBridge);
      const c = fields(
        configuration,
        [
          'database',
          'route',
          'accountToken',
          'workerBearer',
          'resultPublisherToken',
          'nativeIntegration',
          'smsIntegration',
          'profileInboxLimit',
        ],
        ['startupMs', 'cleanupMs'],
      );
      const r = fields(c.route, [
        'profileId',
        'receiverId',
        'scope',
        'caseId',
        'conversationId',
        'recipientId',
      ]);
      const s = fields(r.scope, ['tenantId', 'accountId']);
      const scope = Object.freeze({
        tenantId: text(s.tenantId, ID),
        accountId: text(s.accountId, ID),
      });
      const route = Object.freeze({
        profileId: text(r.profileId, UUID),
        receiverId: text(r.receiverId, UUID),
        scope,
        caseId: text(r.caseId, ID),
        conversationId: text(r.conversationId, ID),
        recipientId: text(r.recipientId, ID),
      });
      const db = fields(c.database, ['host', 'port', 'database', 'user', 'password', 'schema']);
      if (
        db.host !== '127.0.0.1' ||
        db.database !== 'livekit_lab' ||
        db.user !== 'livekit_lab' ||
        c.profileInboxLimit !== 16
      )
        throw new GatewayApplicationError('invalid_input');
      const database = Object.freeze({
        host: '127.0.0.1',
        port: number(db.port, 1, 65535),
        database: 'livekit_lab',
        user: 'livekit_lab',
        password: text(db.password, /^[^\x00-\x20\x7f]{16,128}$/),
        schema: text(db.schema, /^[a-z][a-z0-9_]{0,62}$/),
      });
      const token = (v: unknown) => text(v, /^[A-Za-z0-9_-]{43}$/);
      const accountToken = token(c.accountToken),
        workerBearer = token(c.workerBearer),
        resultPublisherToken = token(c.resultPublisherToken);
      if (new Set([accountToken, workerBearer, resultPublisherToken]).size !== 3)
        throw new GatewayApplicationError('invalid_input');
      const providers = Object.freeze({
        native: provider(c.nativeIntegration, 'livekit', scope.tenantId),
        sms: provider(c.smsIntegration, 'fake_sms', scope.tenantId),
      });
      const p = fields(ports, ['native', 'sms', 'cases', 'carrier']);
      this.#ports = Object.freeze({
        native: dispatchPorts(p.native),
        sms: dispatchPorts(p.sms),
        cases: Object.freeze({
          inspect: snapshotMethod<CurrentCasePort['inspect']>(p.cases, 'inspect'),
        }),
        carrier: carrierPort(p.carrier as CarrierSendPort),
      });
      if (roomControl !== undefined) {
        const options = parseNativeRoomOptions(roomControl);
        if ([accountToken, workerBearer, resultPublisherToken].includes(options.publisherToken))
          throw new GatewayApplicationError('invalid_input');
        this.#roomOptions = parseNativeRoomOptions({
          configuration: options.configuration,
          publisherToken: options.publisherToken,
          forbiddenBearers: [
            ...new Set([
              ...options.forbiddenBearers,
              accountToken,
              workerBearer,
              resultPublisherToken,
            ]),
          ],
        });
      }
      this.#startupMs = number(c.startupMs ?? 5000, 20, 10000);
      this.#cleanupMs = number(c.cleanupMs ?? 1000, 20, 2000);
      this.#providers = providers;
      this.#config = Object.freeze({
        database,
        route,
        accountToken,
        workerBearer,
        resultPublisherToken,
        nativeIntegration: c.nativeIntegration as NativeIntegration,
        smsIntegration: c.smsIntegration as FakeSmsIntegration,
        profileInboxLimit: 16,
      });
    } catch {
      throw new GatewayApplicationError('invalid_input');
    }
  }
  metrics(): Readonly<{
    ownedResources: number;
    starting: number;
    closing: boolean;
    closed: boolean;
    pendingNativeReads: number;
    pendingClose: number;
  }> {
    return Object.freeze({
      ownedResources: this.#owners.filter((o) => !o.closed).length,
      starting: this.#startingPending ? 1 : 0,
      closing: this.#closing,
      closed: this.#closed,
      pendingNativeReads: this.#nativeCalls.size,
      pendingClose: this.#closeTask ? 1 : 0,
    });
  }
  #own<T extends { close(): Promise<void> }>(label: string, tier: Tier, value: T): T {
    this.#owners.push({
      label,
      tier,
      close: snapshotMethod<T['close']>(value, 'close'),
      closed: false,
      pending: undefined,
    });
    return value;
  }
  #check(): void {
    if (this.#closing) throw new GatewayApplicationError('closed');
  }
  nativeBridgeReady(): Readonly<{
    prepareEndpoint: GatewayEndpoint;
    rehydrationEndpoint: GatewayEndpoint;
  }> | null {
    return this.#nativeBridge && this.#contextEndpoint && this.#endpoints && !this.#closing
      ? Object.freeze({
          prepareEndpoint: this.#nativeBridge.prepareEndpoint,
          rehydrationEndpoint: this.#contextEndpoint,
        })
      : null;
  }
  roomControlReady(): RoomControlReady | null {
    return this.#roomManager?.ready() ?? null;
  }
  #checkStarting(): void {
    this.#check();
    if (performance.now() >= this.#startupDeadline)
      throw new GatewayApplicationError('unavailable');
  }
  #construct(): void {
    const c = this.#config,
      r = c.route;
    const seed = Object.freeze({
      token: c.accountToken,
      ...r.scope,
      caseId: r.caseId,
      conversationId: r.conversationId,
    });
    const accounts = new SeededAccounts([seed]);
    const inbox = this.#own(
      'history',
      'storage',
      new NativeChannelInbox(c.database, c.nativeIntegration, accounts, {}, () => {}),
    );
    const outbox = this.#own(
      'outbox',
      'storage',
      new ChannelOutbox(
        c.database,
        c.smsIntegration,
        accounts,
        [
          {
            token: c.resultPublisherToken,
            scope: r.scope,
            caseId: r.caseId,
            conversationId: r.conversationId,
          },
        ],
        this.#ports.carrier,
        { observer: () => {}, cleanupMs: this.#cleanupMs },
      ),
    );
    const route = Object.freeze({
      scope: r.scope,
      caseId: r.caseId,
      conversationId: r.conversationId,
      recipientId: r.recipientId,
    });
    const receiver = this.#own(
      'result_receiver',
      'reader',
      new ChannelResultReceiver(
        outbox,
        {
          receiverId: r.receiverId,
          bindings: [{ ...route, publisherToken: c.resultPublisherToken }],
        },
        { observer: () => {}, cleanupMs: this.#cleanupMs },
      ),
    );
    this.#reader = this.#own(
      'result_reader',
      'reader',
      new ChannelResultReader(
        outbox,
        inbox,
        this.#ports.cases,
        { receiverId: r.receiverId, bindings: [route] },
        { observer: () => {}, cleanupMs: this.#cleanupMs },
      ),
    );
    // SMS and native input reach P1 through the same loopback bridges, so both
    // gateways get the native step deadline rather than the standalone default.
    const options = {
      observer: () => {},
      batchSize: 16,
      idlePollMs: 500,
      dispatchTimeoutMs: 5000,
      cleanupMs: this.#cleanupMs,
      startupMs: this.#startupMs,
    };
    const native = (this.#native = this.#own(
      'native_gateway',
      'storage',
      new NativeGateway({
        database: c.database,
        integration: c.nativeIntegration,
        accounts: [seed],
        ports: this.#nativeBridge
          ? Object.freeze({
              ...this.#ports.native,
              agent: Object.freeze({
                prepare: async (
                  input: Parameters<DispatchPorts['agent']['prepare']>[0],
                  signal: AbortSignal,
                ) => {
                  if (!this.#roomManager) throw new GatewayApplicationError('unavailable');
                  const routed = await this.#roomManager.prepareNative(
                    input,
                    signal,
                    this.#providers.native,
                  );
                  return routed ?? this.#ports.native.agent.prepare(input, signal);
                },
              }),
            })
          : this.#ports.native,
        options,
      }),
    ));
    const sms = (this.#sms = this.#own(
      'sms_gateway',
      'storage',
      new ChannelGateway({
        database: c.database,
        integration: c.smsIntegration,
        accounts: [seed],
        ports: this.#ports.sms,
        options,
      }),
    ));
    const source = this.#own(
      'source_reader',
      'reader',
      new ChannelPolicySourceReader(
        {
          profileId: r.profileId,
          scope: r.scope,
          caseId: r.caseId,
          conversationId: r.conversationId,
          accountToken: c.accountToken,
          inbox,
          sources: {
            native: {
              providerScope: this.#providers.native,
              dispatch: { inspect: native.inspectDispatch.bind(native) },
              prepared: native,
            },
            sms: {
              providerScope: this.#providers.sms,
              dispatch: { inspect: sms.inspectDispatch.bind(sms) },
              prepared: sms,
            },
          },
        },
        2000,
        this.#cleanupMs,
      ),
    );
    this.#readHttp = this.#own(
      'read_http',
      'transport',
      new ChannelPolicyReadHttp(source, c.workerBearer, this.#cleanupMs),
    );
    this.#resultHttp = this.#own(
      'result_http',
      'transport',
      new ChannelPolicyResultHttp(receiver, c.resultPublisherToken, this.#cleanupMs),
    );
    if (this.#roomOptions) {
      const options = this.#roomOptions;
      const publishNative = snapshotMethod<NativeChannelInbox['bind']>(inbox, 'bind');
      const revokeNative = snapshotMethod<NativeChannelInbox['revoke']>(inbox, 'revoke');
      const readNative = snapshotMethod<ChannelPolicyGatewayApplication['nativeResult']>(
        this,
        'nativeResult',
      );
      this.#roomManager = this.#own(
        'room_manager',
        'transport',
        new NativeRoomManager(
          r,
          options,
          {
            publish: (input) => publishNative(options.publisherToken, input),
            revoke: (id) => revokeNative(options.publisherToken, id),
            native: (bearer, id) => readNative(bearer, id),
            ready: () => !this.#closing && this.#endpoints !== undefined,
          },
          this.#nativeBridge,
        ),
      );
      if (this.#nativeBridge) {
        const guard = snapshotMethod<NativeRoomManager['nativeContext']>(
          this.#roomManager,
          'nativeContext',
        );
        const context = this.#own(
          'context_reader',
          'reader',
          new CurrentRoomRehydrator(
            inbox,
            this.#ports.cases,
            c.smsIntegration,
            { timeoutMs: 3000, cleanupMs: this.#cleanupMs, maxActive: 2, observer: () => {} },
            guard,
          ),
        );
        this.#contextHttp = this.#own(
          'context_http',
          'transport',
          new RehydrationHttpServer(context),
        );
      }
    }
  }
  async #bounded<T>(
    actual: Promise<T>,
    duration: number,
    code: 'unavailable' | 'cleanup_incomplete',
  ): Promise<T> {
    const until = performance.now() + duration;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const value = await Promise.race([
        actual,
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(() => reject(new GatewayApplicationError(code)), duration);
        }),
      ]);
      if (performance.now() >= until) throw new GatewayApplicationError(code);
      return value;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  start(request: GatewayApplicationListen = {}): Promise<GatewayApplicationEndpoints> {
    let ports: Required<GatewayApplicationListen>;
    try {
      ports = listenPorts(request);
      if (
        this.#nativeBridge &&
        Object.values(ports).some(
          (p) =>
            p !== 0 &&
            (p === this.#nativeBridge!.prepareEndpoint.port ||
              p === this.#nativeBridge!.rehydrationPort),
        )
      )
        throw new GatewayApplicationError('invalid_input');
      this.#check();
    } catch {
      return Promise.reject(
        new GatewayApplicationError(this.#closing ? 'closed' : 'invalid_input'),
      );
    }
    if (this.#listen && JSON.stringify(ports) !== JSON.stringify(this.#listen))
      return Promise.reject(new GatewayApplicationError('invalid_input'));
    if (!this.#starting) {
      this.#listen = ports;
      this.#startingPending = true;
      this.#startupDeadline = performance.now() + this.#startupMs;
      const actual = Promise.resolve().then(async () => {
        this.#checkStarting();
        this.#construct();
        this.#checkStarting();
        // Recovered pending input may auto-dispatch immediately on gateway.listen.
        // The original-source attestation and stable result receiver must already be reachable.
        const read = await this.#readHttp!.start(ports.readPort);
        this.#checkStarting();
        const receiver = await this.#resultHttp!.start(ports.receiverPort);
        this.#checkStarting();
        if (this.#roomManager) {
          await this.#roomManager.start();
          this.#checkStarting();
        }
        if (this.#contextHttp) {
          this.#contextEndpoint = await this.#contextHttp.start(
            this.#nativeBridge!.rehydrationPort,
          );
          this.#checkStarting();
        }
        const native = await this.#native!.listen(ports.nativePort);
        this.#checkStarting();
        const sms = await this.#sms!.listen(ports.smsPort);
        this.#checkStarting();
        return (this.#endpoints = Object.freeze({ native, sms, read, receiver }));
      });
      this.#starting = actual;
      void actual.then(
        () => {
          this.#startingPending = false;
        },
        () => {
          this.#startingPending = false;
        },
      );
      void actual.catch(() => {
        this.#closing = true;
        void this.close().catch(() => {});
      });
    }
    return this.#bounded(
      this.#starting,
      this.#endpoints ? this.#startupMs : Math.max(0, this.#startupDeadline - performance.now()),
      'unavailable',
    ).catch(() => {
      this.#closing = true;
      void this.close().catch(() => {});
      throw new GatewayApplicationError('unavailable');
    });
  }
  /** Trusted room-owner call only. No HTTP route accepts a browser-selected bearer or scope. */
  nativeResult(
    bindingBearer: string,
    deliveryId: string,
    signal?: AbortSignal,
  ): Promise<ResultNativeView | null> {
    if (this.#closing || !this.#endpoints || !this.#reader)
      return Promise.reject(new GatewayApplicationError(this.#closing ? 'closed' : 'unavailable'));
    if (this.#nativeCalls.size >= 1) return Promise.reject(new ResultReceiverError('Overloaded'));
    const actual = Promise.resolve().then(() => {
      this.#check();
      return this.#reader!.native(bindingBearer, deliveryId, signal).then((view) => {
        this.#check();
        return view;
      });
    });
    this.#nativeCalls.add(actual);
    void actual.then(
      () => this.#nativeCalls.delete(actual),
      () => this.#nativeCalls.delete(actual),
    );
    return actual;
  }
  async #tier(tier: Tier): Promise<void> {
    const owners = this.#owners.filter((o) => o.tier === tier && !o.closed);
    const tasks = owners.map((owner) => {
      if (!owner.pending) {
        const actual = Promise.resolve()
          .then(() => owner.close())
          .then(() => {
            owner.closed = true;
          });
        owner.pending = actual;
        void actual.then(
          () => {
            owner.pending = undefined;
          },
          () => {
            owner.pending = undefined;
          },
        );
      }
      return owner.pending;
    });
    const result = await Promise.allSettled(tasks);
    if (result.some((r) => r.status === 'rejected'))
      throw new GatewayApplicationError('cleanup_incomplete');
  }
  close(): Promise<void> {
    this.#closing = true;
    if (this.#closed) return Promise.resolve();
    if (!this.#closeTask) {
      const actual = Promise.resolve().then(async () => {
        if (this.#starting) await this.#starting.catch(() => {});
        await this.#tier('transport');
        await this.#tier('reader');
        await Promise.allSettled([...this.#nativeCalls]);
        await this.#tier('storage');
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
    return this.#bounded(this.#closeTask, this.#cleanupMs, 'cleanup_incomplete').catch(() => {
      throw new GatewayApplicationError('cleanup_incomplete');
    });
  }
}
