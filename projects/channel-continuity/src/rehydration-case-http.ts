/** One source-qualified current-case read; no revision, quote or confirmation methods. */
import {
  LocalCaseHttpTransport,
  type CaseAuthorityEndpoint,
  type CaseAuthorityHttpOptions,
} from './local-case-http.js';
import { type CaseAuthorityPort, snapshot } from './routing-types.js';
import {
  RehydrationError,
  currentReference,
  currentCase,
  rehydrationFields,
  strictArray,
  sameCurrentReference,
  sha256,
  type CurrentCaseReference,
  type CurrentCasePort,
  type CurrentCase,
} from './rehydration-types.js';
export class CurrentCaseHttpClient implements CurrentCasePort {
  readonly #transport: LocalCaseHttpTransport;
  readonly #allowed: readonly CurrentCaseReference[];
  constructor(
    endpoint: CaseAuthorityEndpoint,
    authorization: string,
    allowed: readonly CurrentCaseReference[],
    options: CaseAuthorityHttpOptions = {},
  ) {
    try {
      this.#allowed = Object.freeze(strictArray(allowed, 64).map(currentReference));
      if (
        !this.#allowed.length ||
        new Set(this.#allowed.map((x) => JSON.stringify(x))).size !== this.#allowed.length
      )
        throw Error();
      const names = Reflect.ownKeys(options);
      if (
        names.some(
          (k) => typeof k !== 'string' || !['timeoutMs', 'cleanupMs', 'maxActive'].includes(k),
        )
      )
        throw Error();
      const copied = rehydrationFields(options, names as string[]) as CaseAuthorityHttpOptions;
      this.#transport = new LocalCaseHttpTransport(endpoint, authorization, copied);
    } catch {
      throw new RehydrationError('invalid_query');
    }
  }
  metrics() {
    return this.#transport.metrics();
  }
  async inspect(value: CurrentCaseReference, signal: AbortSignal): Promise<CurrentCase> {
    const ref = currentReference(value);
    if (!this.#allowed.some((x) => sameCurrentReference(x, ref)))
      throw new RehydrationError('access_denied');
    try {
      return await this.#transport.exchange(
        '/v1/current-case/inspect',
        { schemaVersion: 1, ...ref },
        signal,
        false,
        (v) => {
          const first = rehydrationFields(
            v,
            typeof v === 'object' &&
              v !== null &&
              Object.getOwnPropertyDescriptor(v, 'status')?.value === 'known'
              ? ['schemaVersion', 'status', 'case']
              : ['schemaVersion', 'status', 'code'],
          );
          if (first.schemaVersion !== 1) throw Error();
          if (first.status === 'known')
            return { status: 'known', value: currentCase(first.case, ref) };
          if (
            first.status === 'unavailable' &&
            typeof first.code === 'string' &&
            ['AccessDenied', 'InvalidCommand', 'Overloaded', 'Unavailable'].includes(first.code)
          )
            return {
              status: 'rejected',
              error: new RehydrationError(
                first.code === 'AccessDenied'
                  ? 'access_denied'
                  : first.code === 'Overloaded'
                    ? 'overloaded'
                    : first.code === 'InvalidCommand'
                      ? 'invalid_query'
                      : 'context_unavailable',
              ),
            };
          throw Error();
        },
      );
    } catch (error) {
      throw error instanceof RehydrationError ? error : new RehydrationError();
    }
  }
  close() {
    return this.#transport.close();
  }
}
/** Reference authority stays the only standalone case state; committed identities are never invented. */
export function referenceCurrentCase(
  authority: Pick<CaseAuthorityPort, 'inspect'>,
): CurrentCasePort {
  return Object.freeze({
    async inspect(ref: CurrentCaseReference, signal: AbortSignal) {
      const expected = currentReference(ref),
        value = snapshot(
          await authority.inspect({ scope: expected.scope, caseId: expected.caseId }, signal),
          expected,
        );
      if (value.committed) throw new RehydrationError();
      const result = {
        schemaVersion: 1,
        source: 'standalone_reference_v1',
        ...expected,
        revision: value.revision,
        request: value.request,
        workflow: null,
        intent: { state: 'not_committed', intentId: null },
        mutation: {
          state: 'not_observed',
          outcome: 'not_observed',
          cancellation: 'not_observed',
          effectId: null,
          outcomeEventId: null,
        },
        supplierResult: null,
        sourceRevision: '',
      };
      result.sourceRevision = sha256(JSON.stringify({ ...result, sourceRevision: undefined }));
      return currentCase(result, expected);
    },
  });
}
