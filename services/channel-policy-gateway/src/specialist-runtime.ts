/** One genuine public scripted specialist owner. No execution queue, SQL or effect ports. */
import {
  CAPABILITY,
  EvidenceRegistry,
  LocalTrust,
  SpecialistServer,
  tokenDigest,
  type Endpoint,
} from '@livekit-ecosystem/delegation-specialist';
import { FixedPolicyHandler } from '@livekit-ecosystem/delegation-specialist/fixed-policy';
import {
  SpecialistRuntimeError,
  parseSpecialistConfiguration,
  parseSpecialistCredentials,
  type SpecialistConfiguration,
  type SpecialistCredentials,
} from './specialist-config.js';
export const SCRIPTED_SPECIALIST_LIMITS = Object.freeze({
  maxConnections: 8,
  maxRequests: 8,
  maxActive: 4,
  maxPerPrincipal: 2,
  headerBytes: 4096,
  headerFields: 8,
  headerMs: 1000,
  bodyMs: 1000,
  invokeMs: 5000,
  responseMs: 1000,
  closeMs: 2000,
});
export class ScriptedPolicySpecialistRuntime {
  readonly #configuration: SpecialistConfiguration;
  readonly #credentials: SpecialistCredentials;
  #server: SpecialistServer | undefined;
  #handler: FixedPolicyHandler | undefined;
  #startup: Promise<Endpoint> | undefined;
  #startupPending = false;
  #startupDeadline = 0;
  #endpoint: Endpoint | undefined;
  #closeTask: Promise<void> | undefined;
  #serverClose: Promise<void> | undefined;
  #closing = false;
  #closed = false;
  #events = 0;
  constructor(configuration: SpecialistConfiguration, credentials: SpecialistCredentials) {
    this.#configuration = parseSpecialistConfiguration(configuration);
    this.#credentials = parseSpecialistCredentials(credentials);
  }
  metrics(): Readonly<Record<string, number | boolean>> {
    const s = this.#server?.metrics(),
      h = this.#handler?.metrics();
    return Object.freeze({
      starting: this.#startupPending ? 1 : 0,
      closing: this.#closing,
      closed: this.#closed,
      serverOwners: this.#server && !this.#closed ? 1 : 0,
      active: s?.active ?? 0,
      requests: s?.requests ?? 0,
      sockets: s?.sockets ?? 0,
      observerPending: s?.observerPending ?? 0,
      events: this.#events,
      evaluated: h?.evaluated ?? 0,
      clarified: h?.clarified ?? 0,
    });
  }
  #check(): void {
    if (this.#closing) throw new SpecialistRuntimeError('closed');
  }
  async #bounded<T>(
    actual: Promise<T>,
    deadline: number,
    code: 'unavailable' | 'cleanup_incomplete',
  ): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const result = await Promise.race([
        actual,
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(
            () => reject(new SpecialistRuntimeError(code)),
            Math.max(0, deadline - performance.now()),
          );
        }),
      ]);
      if (performance.now() >= deadline) throw new SpecialistRuntimeError(code);
      return result;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  start(): Promise<Endpoint> {
    if (this.#closing) return Promise.reject(new SpecialistRuntimeError('closed'));
    if (!this.#startup) {
      this.#startupPending = true;
      const deadline = (this.#startupDeadline = performance.now() + 2000);
      const actual = Promise.resolve().then(async () => {
        this.#check();
        const c = this.#configuration,
          scope = { tenant_id: c.scope.tenantId, account_id: c.scope.accountId };
        const trust = new LocalTrust([
          {
            principal_id: 'joined_policy_executor',
            token_sha256: tokenDigest(this.#credentials.bearer),
            scopes: [
              {
                scope,
                invoke_capabilities: [CAPABILITY],
                result_capabilities: [CAPABILITY],
                cancel_capabilities: [CAPABILITY],
                evidence_sources: c.evidence.map((e) => e.reference.source_id),
              },
            ],
          },
        ]);
        const evidence = new EvidenceRegistry(
          c.evidence.map((e) => ({
            scope,
            reference: e.reference,
            body: Buffer.from(e.bodyBase64, 'base64'),
          })),
        );
        const fixedPolicy = (this.#handler = new FixedPolicyHandler());
        const server = (this.#server = new SpecialistServer({
          trust,
          evidence,
          fixedPolicy,
          limits: SCRIPTED_SPECIALIST_LIMITS,
          observer: () => {
            this.#events = Math.min(Number.MAX_SAFE_INTEGER, this.#events + 1);
          },
        }));
        this.#check();
        const endpoint = await server.listen(c.port);
        this.#check();
        if (
          performance.now() >= deadline ||
          endpoint.host !== '127.0.0.1' ||
          endpoint.port !== c.port
        )
          throw new SpecialistRuntimeError('unavailable');
        return (this.#endpoint = Object.freeze({ host: '127.0.0.1', port: endpoint.port }));
      });
      this.#startup = actual;
      void actual.then(
        () => {
          this.#startupPending = false;
        },
        () => {
          this.#startupPending = false;
          this.#closing = true;
          void this.close().catch(() => {});
        },
      );
    }
    return this.#bounded(
      this.#startup,
      this.#endpoint ? performance.now() + 2000 : this.#startupDeadline,
      'unavailable',
    ).catch(() => {
      this.#closing = true;
      void this.close().catch(() => {});
      throw new SpecialistRuntimeError('unavailable');
    });
  }
  #observeServerClose(): Promise<void> {
    if (!this.#server) return Promise.resolve();
    if (!this.#serverClose) {
      const actual = this.#server.close();
      this.#serverClose = actual;
      void actual.catch(() => {
        if (this.#serverClose === actual) this.#serverClose = undefined;
      });
    }
    return this.#serverClose;
  }
  close(): Promise<void> {
    this.#closing = true;
    if (this.#closed) return Promise.resolve();
    // Notify an already returned server before waiting for a late listen callback.
    if (this.#server) void this.#observeServerClose().catch(() => {});
    if (!this.#closeTask) {
      const actual = Promise.resolve().then(async () => {
        if (this.#startup) await this.#startup.catch(() => {});
        await this.#observeServerClose();
        const m = this.#server?.metrics();
        if (m && (m.active !== 0 || m.requests !== 0 || m.sockets !== 0 || m.observerPending !== 0))
          throw new SpecialistRuntimeError('cleanup_incomplete');
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
    return this.#bounded(this.#closeTask, performance.now() + 2000, 'cleanup_incomplete').catch(
      () => {
        throw new SpecialistRuntimeError('cleanup_incomplete');
      },
    );
  }
}
