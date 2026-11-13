/** Explicit synthetic provider contract: immutable operation key plus separately correlated attempts. */
import type { ProviderScope } from './index.js';
import {
  LocalCaseHttpTransport,
  type CaseAuthorityEndpoint,
  type CaseAuthorityHttpOptions,
} from './local-case-http.js';
import {
  OutboxError,
  record,
  identifier,
  sendRequest,
  carrierResult,
  sha,
  type SendRequest,
  type CarrierResult,
  type IdempotentCarrierSendPort,
} from './outbox-types.js';
import {
  operation,
  operationFrom,
  operationDigest,
  lookup,
  type ProviderOperation,
  type ProviderLookup,
} from './send-policy-types.js';
export type { ProviderOperation, ProviderLookup } from './send-policy-types.js';
export class IdempotentFakeSmsClient implements IdempotentCarrierSendPort {
  readonly capabilities = 'idempotent_fake_sms_v1' as const;
  readonly #transport: LocalCaseHttpTransport;
  readonly #scope: ProviderScope;
  constructor(
    endpoint: CaseAuthorityEndpoint,
    authorization: string,
    providerScope: ProviderScope,
    options: CaseAuthorityHttpOptions = {},
  ) {
    const s = record(providerScope, ['tenantId', 'provider', 'providerAccountId']);
    this.#scope = Object.freeze({
      tenantId: identifier(s.tenantId),
      provider: identifier(s.provider),
      providerAccountId: identifier(s.providerAccountId),
    });
    if (this.#scope.provider !== 'fake_sms') throw new OutboxError('InvalidCommand');
    try {
      const keys = Object.keys(options);
      if (keys.some((k) => !['timeoutMs', 'cleanupMs', 'maxActive'].includes(k))) throw Error();
      const copied = record(options, keys) as CaseAuthorityHttpOptions;
      this.#transport = new LocalCaseHttpTransport(endpoint, authorization, copied, 32768);
    } catch {
      throw new OutboxError('InvalidCommand');
    }
  }
  #checked(input: ProviderOperation): ProviderOperation {
    const op = operation(input);
    if (
      op.capability !== 'idempotent_fake_sms_v1' ||
      JSON.stringify(op.providerScope) !== JSON.stringify(this.#scope)
    )
      throw new OutboxError('AccessDenied');
    return op;
  }
  async send(input: SendRequest, signal: AbortSignal): Promise<CarrierResult> {
    const request = sendRequest(input),
      op = this.#checked(operationFrom(request, this.capabilities)),
      digest = operationDigest(op),
      wire = Object.freeze({
        schemaVersion: 1,
        operation: op,
        operationDigest: digest,
        attempt: Object.freeze({
          attemptId: request.attemptId,
          requestDigest: sha(JSON.stringify(request)),
          associationVersion: request.associationVersion,
          routeVersion: request.routeVersion,
        }),
      });
    try {
      return await this.#transport.exchange(
        '/v1/idempotent-sms/send',
        wire,
        signal,
        true,
        (value) => {
          const r = record(value, [
            'schemaVersion',
            'status',
            'providerOperationKey',
            'operationDigest',
            'result',
          ]);
          if (
            r.schemaVersion !== 1 ||
            r.status !== 'known' ||
            r.providerOperationKey !== op.providerOperationKey ||
            r.operationDigest !== digest
          )
            throw new OutboxError('OutcomeUnknown');
          return { status: 'known', value: carrierResult(r.result, request) };
        },
      );
    } catch {
      throw new OutboxError('OutcomeUnknown');
    }
  }
  async lookup(input: ProviderOperation, signal: AbortSignal): Promise<ProviderLookup> {
    const op = this.#checked(input),
      wire = Object.freeze({
        schemaVersion: 1,
        providerScope: op.providerScope,
        providerOperationKey: op.providerOperationKey,
        operationDigest: operationDigest(op),
      });
    try {
      return await this.#transport.exchange(
        '/v1/idempotent-sms/lookup',
        wire,
        signal,
        false,
        (value) => {
          const r = record(value, ['schemaVersion', 'status', 'observation']);
          if (r.schemaVersion !== 1 || r.status !== 'known')
            throw new OutboxError('OutcomeUnknown');
          return { status: 'known', value: lookup(r.observation, op) };
        },
      );
    } catch {
      throw new OutboxError('OutcomeUnknown');
    }
  }
  metrics(): Readonly<Record<string, number>> {
    return this.#transport.metrics();
  }
  async close(): Promise<void> {
    try {
      await this.#transport.close();
    } catch {
      throw new OutboxError('CleanupIncomplete');
    }
  }
}
