/** Explicit confirmation capability over the shared bounded local transport. */
import {
  LocalCaseHttpTransport,
  type CaseAuthorityEndpoint,
  type CaseAuthorityHttpOptions,
  type LocalCaseDecoded,
} from './local-case-http.js';
import {
  allowedReferences,
  fields,
  sameReference,
  safeRoutingCode,
  type CaseReference,
} from './routing-types.js';
import {
  ConfirmationError,
  confirmationReceipt,
  exactConfirmation,
  safeConfirmationCode,
  type ConfirmationAuthorityPort,
  type ConfirmationReceipt,
  type ExactConfirmation,
} from './confirmation-types.js';
export class ConfirmationHttpClient implements ConfirmationAuthorityPort {
  readonly #transport: LocalCaseHttpTransport;
  readonly #allowed: readonly CaseReference[];
  constructor(
    endpoint: CaseAuthorityEndpoint,
    authorization: string,
    allowedCases: readonly CaseReference[],
    options: CaseAuthorityHttpOptions = {},
  ) {
    try {
      this.#allowed = allowedReferences(allowedCases);
      this.#transport = new LocalCaseHttpTransport(endpoint, authorization, options);
    } catch {
      throw new ConfirmationError('InvalidCommand');
    }
  }
  metrics(): Readonly<Record<string, number>> {
    return this.#transport.metrics();
  }
  #decode(value: unknown, command: ExactConfirmation): LocalCaseDecoded<ConfirmationReceipt> {
    const candidate = value as Record<string, unknown>;
    if (candidate.status === 'known') {
      const r = fields(value, ['schemaVersion', 'status', 'confirmation']);
      if (r.schemaVersion !== 1) throw new Error();
      return { status: 'known', value: confirmationReceipt(r.confirmation, command) };
    }
    const r = fields(value, ['schemaVersion', 'status', 'code']);
    if (
      r.schemaVersion === 1 &&
      r.status === 'rejected' &&
      typeof r.code === 'string' &&
      [
        'RevisionConflict',
        'IdentityConflict',
        'AccessDenied',
        'Overloaded',
        'InvalidCommand',
      ].includes(r.code)
    )
      return {
        status: 'rejected',
        error: new ConfirmationError(
          r.code as
            | 'RevisionConflict'
            | 'IdentityConflict'
            | 'AccessDenied'
            | 'Overloaded'
            | 'InvalidCommand',
        ),
      };
    throw new Error();
  }
  async confirm(input: ExactConfirmation, signal: AbortSignal): Promise<ConfirmationReceipt> {
    const command = exactConfirmation(input);
    if (!this.#allowed.some((item) => sameReference(item, command)))
      throw new ConfirmationError('AccessDenied');
    try {
      return await this.#transport.exchange(
        '/v1/case/confirm',
        { schemaVersion: 1, ...command },
        signal,
        true,
        (value) => this.#decode(value, command),
      );
    } catch (error) {
      throw new ConfirmationError(
        safeConfirmationCode(error) ?? safeRoutingCode(error) ?? 'OutcomeUnknown',
      );
    }
  }
  async close(): Promise<void> {
    try {
      await this.#transport.close();
    } catch {
      throw new ConfirmationError('CleanupIncomplete');
    }
  }
}
