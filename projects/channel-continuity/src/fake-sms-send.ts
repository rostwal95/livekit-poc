/** Explicit authenticated loopback fake carrier; no real-provider or delivery guarantee. */
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
  type SendRequest,
  type CarrierResult,
  type OrdinaryCarrierSendPort,
} from './outbox-types.js';
export type { SendRequest, CarrierResult, CarrierSendPort } from './outbox-types.js';
export type FakeSmsSendEndpoint = CaseAuthorityEndpoint;
export type FakeSmsSendOptions = CaseAuthorityHttpOptions;
export class FakeSmsSendClient implements OrdinaryCarrierSendPort {
  readonly capabilities = 'ordinary_fake_sms_v1' as const;
  readonly #transport: LocalCaseHttpTransport;
  readonly #scope: ProviderScope;
  constructor(
    endpoint: FakeSmsSendEndpoint,
    authorization: string,
    providerScope: ProviderScope,
    options: FakeSmsSendOptions = {},
  ) {
    const p = record(providerScope, ['tenantId', 'provider', 'providerAccountId']);
    this.#scope = Object.freeze({
      tenantId: identifier(p.tenantId),
      provider: identifier(p.provider),
      providerAccountId: identifier(p.providerAccountId),
    });
    try {
      this.#transport = new LocalCaseHttpTransport(endpoint, authorization, options, 32768);
    } catch {
      throw new OutboxError('InvalidCommand');
    }
  }
  async send(input: SendRequest, signal: AbortSignal): Promise<CarrierResult> {
    const request = sendRequest(input);
    if (JSON.stringify(request.providerScope) !== JSON.stringify(this.#scope))
      throw new OutboxError('AccessDenied');
    try {
      return await this.#transport.exchange('/v1/sms/send', request, signal, true, (value) => {
        const p = record(value, ['schemaVersion', 'status', 'result']);
        if (p.schemaVersion !== 1 || p.status !== 'known') throw new OutboxError('OutcomeUnknown');
        return { status: 'known', value: carrierResult(p.result, request) };
      });
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
