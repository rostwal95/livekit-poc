/** Explicit native ingress/dispatcher composition; imports start no network or media. */
import {
  ChannelInbox,
  SeededAccounts,
  type DatabaseSettings,
  type InboxHooks,
  type InboxObserver,
} from './postgres.js';
import { ChannelGateway, type ChannelGatewayOptions } from './gateway.js';
import { ChannelError } from './public-types.js';
import {
  LocalCaseHttpTransport,
  type CaseAuthorityEndpoint,
  type CaseAuthorityHttpOptions,
} from './local-case-http.js';
import {
  prepareDispatch,
  dispatchFields,
  dispatchScope,
  type DispatchPorts,
} from './dispatch-types.js';
import { request, decision } from './agent-protocol.js';
import {
  nativeConfig,
  nativeFields,
  nativeUuid,
  nativeId,
  type NativeIntegration,
  type NativeInput,
  type NativePublication,
  type NativeBindingReceipt,
  type NativeAcceptance,
} from './native-types.js';
export { createNativeIntegration, NativeError, DEFAULT_NATIVE_LIMITS } from './native-types.js';
export type {
  NativeIntegration,
  NativePublisher,
  NativePublication,
  NativeInput,
  NativeAcceptance,
  NativeAcknowledgement,
  NativeBindingReceipt,
  NativeCode,
  NativeLimits,
} from './native-types.js';
export class NativeChannelInbox extends ChannelInbox {
  constructor(
    database: DatabaseSettings,
    integration: NativeIntegration,
    accounts: SeededAccounts,
    hooks: InboxHooks = {},
    observer?: InboxObserver,
  ) {
    nativeConfig(integration);
    super(database, integration, accounts, hooks, observer);
  }
  bind(token: string, input: NativePublication): Promise<NativeBindingReceipt> {
    return this.bindNative(token, input);
  }
  revoke(
    token: string,
    bindingId: string,
  ): Promise<Readonly<{ bindingId: string; revokedAt: string }>> {
    return this.revokeNative(token, bindingId);
  }
  accept(token: string, input: NativeInput): Promise<NativeAcceptance> {
    return this.acceptNative(token, input);
  }
}
export type NativeGatewayOptions = Omit<ChannelGatewayOptions, 'inputMode' | 'integration'> &
  Readonly<{ integration: NativeIntegration }>;
export class NativeGateway extends ChannelGateway {
  constructor(options: NativeGatewayOptions) {
    const copied = dispatchFields(options, [
      'database',
      'integration',
      'accounts',
      'ports',
      ...(Object.hasOwn(options, 'options') ? ['options'] : []),
    ]);
    nativeConfig(copied.integration as NativeIntegration);
    super({ ...(copied as NativeGatewayOptions), inputMode: 'native_livekit' });
  }
}
export type NativeAllowedBinding = Readonly<{
  bindingId: string;
  scope: Readonly<{ tenantId: string; accountId: string }>;
  caseId: string;
  conversationId: string;
}>;
export class NativeAgentHttpClient {
  readonly #transport: LocalCaseHttpTransport;
  readonly #bindings: readonly NativeAllowedBinding[];
  readonly port: DispatchPorts['agent'];
  constructor(
    endpoint: CaseAuthorityEndpoint,
    authorization: string,
    bindings: readonly NativeAllowedBinding[],
    options: CaseAuthorityHttpOptions = {},
  ) {
    try {
      if (
        !Array.isArray(bindings) ||
        Object.getPrototypeOf(bindings) !== Array.prototype ||
        bindings.length < 1 ||
        bindings.length > 64
      )
        throw Error();
      const descriptors = Object.getOwnPropertyDescriptors(bindings);
      if (Reflect.ownKeys(descriptors).length !== bindings.length + 1) throw Error();
      const copied: NativeAllowedBinding[] = [];
      for (let n = 0; n < bindings.length; n++) {
        const entry = descriptors[String(n)];
        if (!entry || !('value' in entry) || !entry.enumerable) throw Error();
        const x = nativeFields(entry.value, ['bindingId', 'scope', 'caseId', 'conversationId']);
        copied.push(
          Object.freeze({
            bindingId: nativeUuid(x.bindingId),
            scope: dispatchScope(x.scope),
            caseId: nativeId(x.caseId),
            conversationId: nativeId(x.conversationId),
          }),
        );
      }
      if (new Set(copied.map((x) => x.bindingId)).size !== copied.length) throw Error();
      this.#bindings = Object.freeze(copied);
      const safeOptions = dispatchFields(options, Object.keys(options));
      this.#transport = new LocalCaseHttpTransport(
        endpoint,
        authorization,
        { timeoutMs: 4000, maxActive: 1, ...safeOptions },
        32768,
      );
      this.port = Object.freeze({ prepare: this.prepare.bind(this) });
    } catch {
      throw new ChannelError('InvalidConfiguration');
    }
  }
  async prepare(input: Parameters<DispatchPorts['agent']['prepare']>[0], signal: AbortSignal) {
    const context = prepareDispatch(input.message, input.currentCase, {
      kind: 'investigation',
      source: 'scripted',
      caseRevision: input.currentCase.revision,
    }).submission;
    if (
      input.message.event.type !== 'text.received' ||
      !['web_chat', 'voice_transcript'].includes(input.message.event.channel) ||
      input.message.event.providerScope.provider !== 'livekit' ||
      !this.#bindings.some(
        (x) =>
          x.bindingId === context.message.senderId &&
          x.scope.tenantId === context.scope.tenantId &&
          x.scope.accountId === context.scope.accountId &&
          x.caseId === context.caseId &&
          x.conversationId === context.conversationId,
      )
    )
      throw new ChannelError('AccessDenied');
    const wire = request(context),
      body: unknown = JSON.parse(wire.raw.toString('utf8'));
    try {
      return await this.#transport.exchange('/v1/native/prepare', body, signal, false, (value) => {
        const r = dispatchFields(value, ['schemaVersion', 'kind', 'inputDigest', 'decision']);
        if (
          r.schemaVersion !== 1 ||
          r.kind !== 'agent.prepared' ||
          r.inputDigest !== wire.inputDigest
        )
          throw new ChannelError('OperationConflict');
        return { status: 'known', value: decision(r.decision, context.caseRevision) };
      });
    } catch {
      throw new ChannelError('DispatchUnavailable');
    }
  }
  metrics(): Readonly<Record<string, number>> {
    return this.#transport.metrics();
  }
  async close(): Promise<void> {
    try {
      await this.#transport.close();
    } catch {
      throw new ChannelError('CleanupIncomplete');
    }
  }
}
