/** Read/revise capability only; confirmation uses a separately constructed client. */
import { LocalCaseHttpTransport, type LocalCaseDecoded } from './local-case-http.js';
import {
  RoutingError,
  allowedReferences,
  caseRevision,
  fields,
  reference,
  revisedSnapshot,
  sameReference,
  snapshot,
  type CaseAuthorityPort,
  type CaseReference,
  type CaseRevision,
  type CaseSnapshot,
} from './routing-types.js';
import type { CaseAuthorityEndpoint, CaseAuthorityHttpOptions } from './local-case-http.js';
export type { CaseAuthorityEndpoint, CaseAuthorityHttpOptions } from './local-case-http.js';
export class CaseAuthorityHttpClient implements CaseAuthorityPort {
  readonly #transport: LocalCaseHttpTransport;
  readonly #allowed: readonly CaseReference[];
  constructor(
    endpoint: CaseAuthorityEndpoint,
    authorization: string,
    allowedCases: readonly CaseReference[],
    options: CaseAuthorityHttpOptions = {},
  ) {
    this.#allowed = allowedReferences(allowedCases);
    this.#transport = new LocalCaseHttpTransport(endpoint, authorization, options);
  }
  metrics(): Readonly<Record<string, number>> {
    return this.#transport.metrics();
  }
  #require(ref: CaseReference): void {
    if (!this.#allowed.some((item) => sameReference(item, ref)))
      throw new RoutingError('AccessDenied');
  }
  #decode(
    value: unknown,
    ref: CaseReference,
    command?: CaseRevision,
  ): LocalCaseDecoded<CaseSnapshot> {
    const candidate = value as Record<string, unknown>;
    if (candidate.status === 'known') {
      const r = fields(value, ['schemaVersion', 'status', 'case']);
      if (r.schemaVersion !== 1) throw new Error();
      return {
        status: 'known',
        value: command ? revisedSnapshot(r.case, command) : snapshot(r.case, ref),
      };
    }
    const r = fields(value, ['schemaVersion', 'status', 'code']);
    if (
      r.schemaVersion === 1 &&
      r.status === 'rejected' &&
      typeof r.code === 'string' &&
      ['RevisionConflict', 'AccessDenied', 'Overloaded', 'InvalidCommand'].includes(r.code)
    )
      return {
        status: 'rejected',
        error: new RoutingError(
          r.code as 'RevisionConflict' | 'AccessDenied' | 'Overloaded' | 'InvalidCommand',
        ),
      };
    throw new Error();
  }
  inspect(input: CaseReference, signal: AbortSignal): Promise<CaseSnapshot> {
    const ref = reference(input);
    this.#require(ref);
    return this.#transport.exchange(
      '/v1/case/inspect',
      { schemaVersion: 1, ...ref },
      signal,
      false,
      (value) => this.#decode(value, ref),
    );
  }
  revise(input: CaseRevision, signal: AbortSignal): Promise<CaseSnapshot> {
    const command = caseRevision(input);
    this.#require(command);
    return this.#transport.exchange(
      '/v1/case/revise',
      { schemaVersion: 1, ...command },
      signal,
      true,
      (value) => this.#decode(value, command, command),
    );
  }
  close(): Promise<void> {
    return this.#transport.close();
  }
}
