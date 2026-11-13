import {
  parseNativeBridgeConfiguration,
  type NativeBridgeConfiguration,
} from './native-bridge-contract.js';
/** Runtime-owned public clients around the frozen application; startup is explicit. */
import { parseEventJson } from '@livekit-ecosystem/channel-continuity';
import { ChannelError } from '@livekit-ecosystem/channel-continuity/postgres';
import { CurrentCaseHttpClient } from '@livekit-ecosystem/channel-continuity/rehydration';
import { createNativeIntegration } from '@livekit-ecosystem/channel-continuity/native';
import { createFakeSmsIntegration } from '@livekit-ecosystem/channel-continuity/security';
import { OutboxError } from '@livekit-ecosystem/channel-continuity/outbox';
import type { DispatchPorts } from '@livekit-ecosystem/channel-continuity/dispatch';
import type { ResultNativeView } from '@livekit-ecosystem/channel-continuity/result-receiver';
import {
  ChannelPolicyGatewayApplication,
  type GatewayApplicationEndpoints,
} from './application.js';
import { ChannelPolicyOperationBridge } from './operation-bridge.js';
import {
  parseRoomControlConfiguration,
  type RoomControlConfiguration,
  type RoomControlReady,
} from './native-room-contract.js';
import {
  GatewayRuntimeError,
  parseRuntimeConfiguration,
  parseRuntimeCredentials,
  publicSimulationHmacKey,
  runtimeFields,
  type RuntimeConfiguration,
  type RuntimeCredentials,
} from './runtime-config.js';
type ChannelErrorCode = ChannelError['code'];
const CHANNEL_ERROR_CODES = new Set<ChannelErrorCode>([
  'InvalidConfiguration',
  'InvalidEvent',
  'AccessDenied',
  'AssociationRequired',
  'AssociationRejected',
  'IdentityConflict',
  'Overloaded',
  'NotFound',
  'StorageUnavailable',
  'AcknowledgementUnknown',
  'SchemaMismatch',
  'CleanupIncomplete',
  'UpgradeRequired',
  'DispatchClaimLost',
  'DispatchUnavailable',
  'OperationConflict',
]);
/** Dependencies may mutate error messages or code accessors; only copy a finite own data code. */
function publicChannelError(error: unknown, fallback: ChannelErrorCode): ChannelError {
  try {
    if (error instanceof ChannelError) {
      const descriptor = Object.getOwnPropertyDescriptor(error, 'code');
      if (
        descriptor &&
        'value' in descriptor &&
        typeof descriptor.value === 'string' &&
        CHANNEL_ERROR_CODES.has(descriptor.value as ChannelErrorCode)
      )
        return new ChannelError(descriptor.value as ChannelErrorCode);
    }
  } catch {
    // A malformed dependency object must not replace the finite port failure.
  }
  return new ChannelError(fallback);
}
/** Caller owns this runtime; borrowed dependencies are owned here only after app drains.
 * No constructor starts I/O. No owner schema, credentials, new deadline or receipt is invented.
 */
export class ChannelPolicyGatewayRuntime {
  readonly #config: RuntimeConfiguration;
  readonly #credentials: RuntimeCredentials;
  readonly #roomControl: RoomControlConfiguration | undefined;
  readonly #nativeBridge: NativeBridgeConfiguration | undefined;
  #case: CurrentCaseHttpClient | undefined;
  #bridge: ChannelPolicyOperationBridge | undefined;
  #app: ChannelPolicyGatewayApplication | undefined;
  #starting: Promise<GatewayApplicationEndpoints> | undefined;
  #startingPending = false;
  #startupDeadline = 0;
  #closeTask: Promise<void> | undefined;
  #endpoints: GatewayApplicationEndpoints | undefined;
  #closing = false;
  #closed = false;
  #carrierCalls = 0;
  constructor(
    configuration: RuntimeConfiguration,
    credentials: RuntimeCredentials,
    roomControl?: RoomControlConfiguration,
    nativeBridge?: NativeBridgeConfiguration,
  ) {
    this.#config = parseRuntimeConfiguration(configuration);
    this.#credentials = parseRuntimeCredentials(credentials);
    if (roomControl !== undefined) {
      try {
        this.#roomControl = parseRoomControlConfiguration(roomControl);
        const c = this.#config;
        if (
          [
            c.caseEndpoint.port,
            c.originEndpoints.native.port,
            c.originEndpoints.sms.port,
            ...Object.values(c.listen),
          ].includes(this.#roomControl.port)
        )
          throw new GatewayRuntimeError('invalid_configuration');
      } catch {
        throw new GatewayRuntimeError('invalid_configuration');
      }
    }
    if (nativeBridge !== undefined) {
      try {
        if (!this.#roomControl) throw new Error();
        this.#nativeBridge = parseNativeBridgeConfiguration(nativeBridge);
        const c = this.#config,
          occupied = [
            c.caseEndpoint.port,
            c.originEndpoints.native.port,
            c.originEndpoints.sms.port,
            ...Object.values(c.listen),
            this.#roomControl.port,
          ];
        if (
          occupied.includes(this.#nativeBridge.prepareEndpoint.port) ||
          occupied.includes(this.#nativeBridge.rehydrationPort)
        )
          throw new Error();
      } catch {
        throw new GatewayRuntimeError('invalid_configuration');
      }
    }
  }
  nativeBridgeReady() {
    return this.#app?.nativeBridgeReady() ?? null;
  }
  roomControlReady(): RoomControlReady | null {
    return this.#app?.roomControlReady() ?? null;
  }
  metrics(): Readonly<{
    starting: number;
    closing: boolean;
    closed: boolean;
    applicationOwners: number;
    bridgeCalls: number;
    caseCalls: number;
    disabledCarrierCalls: number;
  }> {
    return Object.freeze({
      starting: this.#startingPending ? 1 : 0,
      closing: this.#closing,
      closed: this.#closed,
      applicationOwners: this.#app?.metrics().ownedResources ?? 0,
      bridgeCalls: this.#bridge?.metrics().active ?? 0,
      caseCalls: this.#case?.metrics().active ?? 0,
      disabledCarrierCalls: this.#carrierCalls,
    });
  }
  #check(): void {
    if (this.#closing) throw new GatewayRuntimeError('closed');
  }
  #dispatch(source: 'native' | 'sms'): DispatchPorts {
    const c = this.#config,
      r = c.route,
      ref = Object.freeze({ scope: r.scope, caseId: r.caseId, conversationId: r.conversationId });
    const inspect: DispatchPorts['cases']['inspect'] = async (value, signal) => {
      this.#check();
      try {
        const p = runtimeFields(value, ['scope', 'caseId']),
          s = runtimeFields(p.scope, ['tenantId', 'accountId']);
        if (
          s.tenantId !== r.scope.tenantId ||
          s.accountId !== r.scope.accountId ||
          p.caseId !== r.caseId
        )
          throw new ChannelError('AccessDenied');
        const observed = await this.#case!.inspect(ref, signal);
        this.#check();
        if (
          observed.source !== 'p1_public_v4' ||
          !/^[1-9][0-9]{0,6}$/.test(observed.revision) ||
          BigInt(observed.revision) > 1000000n
        )
          throw new ChannelError('DispatchUnavailable');
        // Public DispatchCase retains this legacy tag. The read above is actual public P1.
        return Object.freeze({
          scope: r.scope,
          caseId: r.caseId,
          revision: observed.revision,
          source: 'synthetic_read_only' as const,
        });
      } catch (error) {
        throw publicChannelError(error, 'DispatchUnavailable');
      }
    };
    const prepare: DispatchPorts['agent']['prepare'] = async (input, signal) => {
      this.#check();
      if (signal.aborted) throw new ChannelError('DispatchUnavailable');
      try {
        const decoded = parseEventJson(JSON.stringify(input.message.event), {
          providerScope: c.providers[source],
          accountScope: r.scope,
        }).event;
        if (
          decoded.type !== 'text.received' ||
          decoded.caseId !== r.caseId ||
          decoded.conversationId !== r.conversationId ||
          input.currentCase.caseId !== r.caseId ||
          input.currentCase.scope.tenantId !== r.scope.tenantId ||
          input.currentCase.scope.accountId !== r.scope.accountId ||
          input.currentCase.source !== 'synthetic_read_only'
        )
          throw new ChannelError('AccessDenied');
        if (
          source === 'native'
            ? !['web_chat', 'voice_transcript'].includes(decoded.channel)
            : decoded.channel !== 'sms'
        )
          throw new ChannelError('AccessDenied');
        if (
          !/^[1-9][0-9]{0,6}$/.test(input.currentCase.revision) ||
          BigInt(input.currentCase.revision) > 1000000n
        )
          throw new ChannelError('DispatchUnavailable');
        return Object.freeze({
          kind: 'investigation' as const,
          source: 'scripted' as const,
          caseRevision: input.currentCase.revision,
        });
      } catch (error) {
        throw publicChannelError(error, 'OperationConflict');
      }
    };
    return Object.freeze({
      cases: Object.freeze({ inspect }),
      agent: Object.freeze({ prepare }),
      operations: this.#bridge![source],
    });
  }
  async #bounded<T>(
    actual: Promise<T>,
    milliseconds: number,
    code: 'unavailable' | 'cleanup_incomplete',
  ): Promise<T> {
    const deadline = performance.now() + milliseconds;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const result = await Promise.race([
        actual,
        new Promise<never>((_r, reject) => {
          timer = setTimeout(() => reject(new GatewayRuntimeError(code)), milliseconds);
        }),
      ]);
      if (performance.now() >= deadline) throw new GatewayRuntimeError(code);
      return result;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  start(): Promise<GatewayApplicationEndpoints> {
    if (this.#closing) return Promise.reject(new GatewayRuntimeError('closed'));
    if (!this.#starting) {
      this.#startingPending = true;
      const deadline = (this.#startupDeadline = performance.now() + 5000);
      const actual = Promise.resolve().then(async () => {
        this.#check();
        const c = this.#config,
          k = this.#credentials,
          r = c.route;
        const cases = (this.#case = new CurrentCaseHttpClient(
          c.caseEndpoint,
          k.caseAuthorization,
          [{ scope: r.scope, caseId: r.caseId, conversationId: r.conversationId }],
          { maxActive: 2, timeoutMs: 1000, cleanupMs: 1000 },
        ));
        this.#bridge = new ChannelPolicyOperationBridge({
          profileId: r.profileId,
          scope: r.scope,
          caseId: r.caseId,
          conversationId: r.conversationId,
          worker: {
            endpoint: { host: '127.0.0.1', port: c.listen.readPort },
            bearer: k.workerBearer,
          },
          origins: {
            native: { endpoint: c.originEndpoints.native, bearer: k.nativeOriginBearer },
            sms: { endpoint: c.originEndpoints.sms, bearer: k.smsOriginBearer },
          },
        });
        const ready = await cases.inspect(
          { scope: r.scope, caseId: r.caseId, conversationId: r.conversationId },
          new AbortController().signal,
        );
        this.#check();
        if (performance.now() >= deadline || ready.source !== 'p1_public_v4')
          throw new GatewayRuntimeError('unavailable');
        const nativeIntegration = createNativeIntegration(c.providers.native, [
          {
            token: k.nativePublisherToken,
            scope: r.scope,
            caseId: r.caseId,
            conversationId: r.conversationId,
          },
        ]);
        const smsIntegration = createFakeSmsIntegration(c.providers.sms, publicSimulationHmacKey());
        const remaining = Math.floor(deadline - performance.now());
        if (remaining < 20) throw new GatewayRuntimeError('unavailable');
        this.#app = new ChannelPolicyGatewayApplication(
          {
            database: { ...c.postgres, password: k.postgresPassword },
            route: r,
            accountToken: k.accountToken,
            workerBearer: k.workerBearer,
            resultPublisherToken: k.resultPublisherToken,
            nativeIntegration,
            smsIntegration,
            profileInboxLimit: 16,
            startupMs: Math.min(5000, remaining),
            cleanupMs: 1000,
          },
          {
            native: this.#dispatch('native'),
            sms: this.#dispatch('sms'),
            cases,
            carrier: {
              capabilities: 'ordinary_fake_sms_v1',
              send: async () => {
                this.#carrierCalls = Math.min(Number.MAX_SAFE_INTEGER, this.#carrierCalls + 1);
                throw new OutboxError('Unavailable');
              },
            },
          },
          this.#roomControl
            ? {
                configuration: this.#roomControl,
                publisherToken: k.nativePublisherToken,
                forbiddenBearers: [
                  k.accountToken,
                  k.nativePublisherToken,
                  k.resultPublisherToken,
                  k.workerBearer,
                  k.nativeOriginBearer,
                  k.smsOriginBearer,
                  k.caseAuthorization.slice(7),
                ],
              }
            : undefined,
          this.#nativeBridge,
        );
        this.#check();
        const endpoints = await this.#app.start(c.listen);
        this.#check();
        if (performance.now() >= deadline) throw new GatewayRuntimeError('unavailable');
        return (this.#endpoints = endpoints);
      });
      this.#starting = actual;
      void actual.then(
        () => {
          this.#startingPending = false;
        },
        () => {
          this.#startingPending = false;
          this.#closing = true;
          void this.close().catch(() => {});
        },
      );
    }
    return this.#bounded(
      this.#starting,
      this.#endpoints ? 5000 : Math.max(0, this.#startupDeadline - performance.now()),
      'unavailable',
    ).catch(() => {
      this.#closing = true;
      void this.close().catch(() => {});
      throw new GatewayRuntimeError('unavailable');
    });
  }
  /** Trusted server-side room owner only; no browser-controlled grant/scope route. */
  nativeResult(
    bindingBearer: string,
    deliveryId: string,
    signal?: AbortSignal,
  ): Promise<ResultNativeView | null> {
    if (this.#closing || !this.#endpoints || !this.#app)
      return Promise.reject(new GatewayRuntimeError(this.#closing ? 'closed' : 'unavailable'));
    return this.#app.nativeResult(bindingBearer, deliveryId, signal);
  }
  close(): Promise<void> {
    this.#closing = true;
    if (this.#closed) return Promise.resolve();
    // Signal the constructed app immediately, including while start is still awaited.
    // This blocks later gateway business admission before any dependent ownership wait.
    if (this.#app) void this.#app.close().catch(() => {});
    if (!this.#closeTask) {
      const actual = Promise.resolve().then(async () => {
        if (this.#starting) await this.#starting.catch(() => {});
        if (this.#app) await this.#app.close();
        if (this.#bridge) await this.#bridge.close();
        if (this.#case) await this.#case.close();
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
    return this.#bounded(this.#closeTask, 2000, 'cleanup_incomplete').catch(() => {
      throw new GatewayRuntimeError('cleanup_incomplete');
    });
  }
}
