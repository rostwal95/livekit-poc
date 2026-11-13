/** Public installed starter application. Importing it performs no setup, DDL or listen. */
import pg from 'pg';
import {
  ChannelInbox,
  SeededAccounts,
  ChannelError,
  type AccountSeed,
  type StoredMessage,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  createFakeSmsIntegration,
  WebhookError,
  type WebhookHeaders,
} from '@livekit-ecosystem/channel-continuity/security';
import {
  installChannelSchema,
  upgradeChannelSchemaV2,
  upgradeChannelSchemaV3,
  upgradeChannelSchemaV4,
  upgradeChannelSchemaV5,
  upgradeChannelSchemaV6,
  upgradeChannelSchemaV7,
} from '@livekit-ecosystem/channel-continuity/migrations';
import {
  ReferenceCaseAuthority,
  installReferenceCaseSchema,
} from '@livekit-ecosystem/channel-continuity/reference-case';
import { RevisionRouter, RoutingError } from '@livekit-ecosystem/channel-continuity/routing';
import {
  ChannelDispatcher,
  type DispatchObservation,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  ChannelGateway,
  GatewayError,
  type GatewayEndpoint,
} from '@livekit-ecosystem/channel-continuity/gateway';
import {
  ChannelOutbox,
  OutboxError,
  type ReplyDraft,
  type RecoveryCommandView,
} from '@livekit-ecosystem/channel-continuity/outbox';
import { FakeSmsSendClient } from '@livekit-ecosystem/channel-continuity/fake-sms-send';
import { IdempotentFakeSmsClient } from '@livekit-ecosystem/channel-continuity/idempotent-fake-sms';
import {
  CallbackInbox,
  CallbackError,
  createFakeSmsCallbackIntegration,
} from '@livekit-ecosystem/channel-continuity/callbacks';
import {
  StarterError,
  safeStarterCode,
  STARTER_CODES,
  fields,
  id,
  uuid,
  parseConfig,
  parseCredentials,
  database,
  profileDigest,
  CloseObservation,
  type StarterCode,
  type StarterConfig,
  type StarterCredentials,
  type RuntimeCredentials,
  type OwnerCredentials,
} from './config.js';
import { EXTERNAL_DEFINITION_DIGEST, ExternalSchemaOwner } from './receipt-store.js';
import { ExternalOperationClient } from './external-http.js';
export {
  StarterError,
  safeStarterCode,
  STARTER_CODES,
  STARTER_LIMITS,
  parseConfig,
  parseCredentials,
  readPrivateJson,
  writePrivateJson,
} from './config.js';
export type {
  StarterCode,
  StarterConfig,
  StarterBinding,
  StarterCredentials,
  RuntimeCredentials,
  OwnerCredentials,
  ExternalCredentials,
} from './config.js';
export { ExternalHttpServer, ExternalOperationClient } from './external-http.js';
export type {
  ExternalEndpoint,
  ExternalLedgerPort,
  OperationClientConfig,
  OperationClientBinding,
} from './external-http.js';
export type StarterOptions = Readonly<{ harnessAfterAcknowledgement?: () => void | Promise<void> }>;
export type StarterCarrier = 'ordinary_fake_sms_v1' | 'idempotent_fake_sms_v1';
export const STARTER_MANIFEST_SHA256 =
  '496e1682ec9e16d8171234b01a3b9b047fcadfadbd25b4217a24e1e948937a87';
export const STARTER_GROUPS = Object.freeze([
  'archive_bin_exports_and_strict_types_without_repository',
  'pure_plan_and_import_without_implicit_setup',
  'invalid_missing_foreign_config_fails_closed',
  'owner_bootstrap_then_runtime_no_ddl',
  'verified_association_and_foreign_scope_denial',
  'explicit_structured_case_revision_known_while_quiescent',
  'stale_revision_and_unlinked_input_do_not_authorize_mutation',
  'sms_commit_before_ack_with_original_receipt',
  'equal_replay_and_changed_payload_conflict',
  'distinct_equal_text_inputs_remain_distinct',
  'bounded_original_history_cursor_and_restart',
  'external_receipt_replay_conflict_before_capacity',
  'kill_after_ack_before_dispatch_fresh_recovery',
  'external_commit_ack_loss_lookup_no_duplicate',
  'fake_provider_acceptance_distinct_from_delivery',
  'ordinary_send_unknown_has_no_automatic_resend',
  'callback_replay_and_reorder_preserve_attempt_source',
  'explicit_recovery_known_only_replay_zero_io',
  'fresh_process_original_case_work_reply_facts',
  'actual_stop_dependent_ownership_and_useful_reopen',
] as const);
function safe(error: unknown): StarterError {
  try {
    const own = safeStarterCode(error);
    if (own) return new StarterError(own);
    if (
      error instanceof ChannelError ||
      error instanceof RoutingError ||
      error instanceof OutboxError ||
      error instanceof CallbackError
    ) {
      const d = Object.getOwnPropertyDescriptor(error, 'code');
      if (d && 'value' in d) {
        if (d.value === 'WebhookRejected') return new StarterError('AccessDenied');
        if (d.value === 'StorageUnavailable') return new StarterError('Unavailable');
        if (STARTER_CODES.includes(d.value as StarterCode))
          return new StarterError(d.value as StarterCode);
      }
    }
    if (error instanceof WebhookError) return new StarterError('AccessDenied');
    if (error instanceof GatewayError) {
      const d = Object.getOwnPropertyDescriptor(error, 'code');
      if (d && 'value' in d) {
        if (d.value === 'capacity') return new StarterError('Overloaded');
        if (d.value === 'acknowledgement_unknown')
          return new StarterError('AcknowledgementUnknown');
        if (d.value === 'cleanup_incomplete') return new StarterError('CleanupIncomplete');
      }
    }
    return new StarterError('Unavailable');
  } catch {
    return new StarterError('Unavailable');
  }
}

function migrationCleanupUnknown(error: unknown): boolean {
  try {
    const cleanup = (value: unknown): boolean => {
      if (safeStarterCode(value) === 'CleanupIncomplete') return true;
      if (!(value instanceof ChannelError)) return false;
      const code = Object.getOwnPropertyDescriptor(value, 'code');
      return Boolean(code && 'value' in code && code.value === 'CleanupIncomplete');
    };
    if (cleanup(error)) return true;
    if (!(error instanceof ChannelError)) return false;
    const cause = Object.getOwnPropertyDescriptor(error, 'cause');
    return Boolean(cause && 'value' in cause && cleanup(cause.value));
  } catch {
    return true;
  }
}
type Closeable = Readonly<{ close(): Promise<void> }>;
class OwnedGraph {
  readonly #tiers = new Map<number, Set<Closeable>>();
  #pass: Promise<void> | undefined;
  add<T extends Closeable>(tier: number, resource: T): T {
    let group = this.#tiers.get(tier);
    if (!group) {
      group = new Set();
      this.#tiers.set(tier, group);
    }
    group.add(resource);
    return resource;
  }
  get empty(): boolean {
    return this.#tiers.size === 0;
  }
  close(): Promise<void> {
    if (!this.#pass) {
      const actual = Promise.resolve().then(async () => {
        for (const tier of [...this.#tiers.keys()].sort((a, b) => a - b)) {
          const group = this.#tiers.get(tier)!;
          const resources = [...group];
          const outcomes = await Promise.allSettled(
            resources.map((r) => Promise.resolve().then(() => r.close())),
          );
          outcomes.forEach((o, i) => {
            if (o.status === 'fulfilled') group.delete(resources[i]!);
          });
          if (group.size) throw new StarterError('CleanupIncomplete');
          this.#tiers.delete(tier);
        }
      });
      this.#pass = actual;
      void actual.then(
        () => {
          if (this.#pass === actual) this.#pass = undefined;
        },
        () => {
          if (this.#pass === actual) this.#pass = undefined;
        },
      );
    }
    return this.#pass;
  }
}
/** Session mutex coordinates app modes only; it owns no work/lease or transaction across ports. */
class ModeMutex {
  readonly #config: StarterConfig;
  readonly #credentials: StarterCredentials;
  readonly #client: pg.Client;
  #starting: Promise<void> | undefined;
  #ending: Promise<void> | undefined;
  #acquired = false;
  #closed = false;
  constructor(config: StarterConfig, credentials: StarterCredentials) {
    this.#config = config;
    this.#credentials = credentials;
    const d = database(config, credentials, 'external');
    this.#client = new pg.Client({
      host: d.host,
      port: d.port,
      database: d.database,
      user: d.user,
      password: d.password,
      ssl: false,
      application_name: 'p2-starter-mode',
      connectionTimeoutMillis: 1000,
      query_timeout: 4000,
      options:
        '-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500 -c idle_in_transaction_session_timeout=5000',
    });
    this.#client.on('error', () => undefined);
  }
  #key(): string {
    return 'p2-starter-mode:' + this.#config.postgres.database + ':' + this.#config.schemas.inbox;
  }
  acquire(): Promise<void> {
    this.#starting ??= Promise.resolve().then(async () => {
      await this.#client.connect();
      const r = await this.#client.query('SELECT current_user AS name');
      if (
        r.rows[0]?.name !==
        (this.#credentials.role === 'owner' ? 'continuity_migrator' : 'livekit_lab')
      )
        throw new StarterError('AccessDenied');
      if (this.#credentials.role !== 'owner') {
        const schema = this.#config.schemas.external;
        const meta = await this.#client.query(
          `SELECT version,profile_id,config_digest,definition_digest FROM "${schema}".receipt_metadata WHERE singleton`,
        );
        const m = meta.rows[0];
        if (
          meta.rows.length !== 1 ||
          m?.version !== 1 ||
          m.profile_id !== this.#config.profileId ||
          m.config_digest !== profileDigest(this.#config) ||
          m.definition_digest !== EXTERNAL_DEFINITION_DIGEST
        )
          throw new StarterError('SchemaMismatch');
      }
      const lock = await this.#client.query(
        'SELECT pg_try_advisory_lock(hashtextextended($1,0)) AS acquired',
        [this.#key()],
      );
      if (lock.rows[0]?.acquired !== true) throw new StarterError('ApplicationBusy');
      this.#acquired = true;
    });
    void this.#starting.catch(() => undefined);
    return this.#starting;
  }
  close(): Promise<void> {
    if (this.#closed) return Promise.resolve();
    if (!this.#ending) {
      const actual = Promise.resolve().then(async () => {
        if (this.#starting) await this.#starting.catch(() => undefined);
        // Closing the actual session also releases its advisory lock. No stale-PID/TTL steal exists.
        let primary: unknown;
        if (this.#acquired)
          try {
            await this.#client.query('SELECT pg_advisory_unlock(hashtextextended($1,0))', [
              this.#key(),
            ]);
            this.#acquired = false;
          } catch (e) {
            primary = e;
          }
        try {
          await this.#client.end();
          this.#closed = true;
          this.#acquired = false;
        } catch {
          throw new StarterError('CleanupIncomplete');
        }
        // An observed session end proves mutex release even if the explicit unlock response was lost.
        if (primary && !this.#closed) throw new StarterError('CleanupIncomplete');
      });
      this.#ending = actual;
      void actual.catch(() => {
        if (this.#ending === actual) this.#ending = undefined;
      });
    }
    return this.#ending;
  }
}
function seeds(config: StarterConfig, credentials: RuntimeCredentials): readonly AccountSeed[] {
  return Object.freeze(
    config.bindings.map((b) =>
      Object.freeze({
        token: credentials.bindings.find((c) => c.alias === b.alias)!.accountToken,
        ...b.accountScope,
        conversationId: b.conversationId,
        caseId: b.caseId,
      }),
    ),
  );
}
function integration(config: StarterConfig, credentials: RuntimeCredentials) {
  return createFakeSmsIntegration(
    config.bindings[0]!.providerScope,
    Buffer.from(credentials.providerHmac, 'base64url'),
  );
}
function signalOrDefault(value?: AbortSignal): AbortSignal {
  if (value === undefined) return new AbortController().signal;
  try {
    const get = Object.getOwnPropertyDescriptor(AbortSignal.prototype, 'aborted')!.get!;
    get.call(value);
    return value;
  } catch {
    throw new StarterError('InvalidCommand');
  }
}
function webhook(
  raw: Uint8Array,
  input: WebhookHeaders,
): Readonly<{ raw: Buffer; headers: WebhookHeaders }> {
  if (!(raw instanceof Uint8Array) || raw.length < 1 || raw.length > 32768)
    throw new StarterError('InvalidCommand');
  const h = fields(input, ['timestamp', 'signature']);
  if (
    typeof h.timestamp !== 'string' ||
    typeof h.signature !== 'string' ||
    h.timestamp.length > 32 ||
    h.signature.length > 256
  )
    throw new StarterError('InvalidCommand');
  return Object.freeze({
    raw: Buffer.from(raw),
    headers: Object.freeze({ timestamp: h.timestamp, signature: h.signature }),
  });
}
export class StandaloneOwner {
  readonly #config: StarterConfig;
  readonly #credentials: OwnerCredentials;
  readonly #graph = new OwnedGraph();
  #work: Promise<Readonly<{ inboxVersion: 7; caseVersion: 1; externalVersion: 1 }>> | undefined;
  #closing = false;
  #migrationOwnerUnknown = false;
  readonly #closeObservation = new CloseObservation();
  constructor(configInput: unknown, credentialsInput: unknown) {
    this.#config = parseConfig(configInput);
    const c = parseCredentials(credentialsInput, this.#config);
    if (c.role !== 'owner') throw new StarterError('AccessDenied');
    this.#credentials = c;
  }
  bootstrap(): Promise<Readonly<{ inboxVersion: 7; caseVersion: 1; externalVersion: 1 }>> {
    if (this.#closing) return Promise.reject(new StarterError('Closed'));
    this.#work ??= Promise.resolve().then(async () => {
      const config = this.#config,
        credentials = this.#credentials;
      const mutex = this.#graph.add(3, new ModeMutex(config, credentials));
      await mutex.acquire();
      try {
        const d = database(config, credentials, 'inbox');
        await installChannelSchema(d, {
          maxInbox: 64,
          maxChallenges: 64,
          maxAssociations: 64,
          maxSenders: 64,
        });
        await upgradeChannelSchemaV2(d);
        await upgradeChannelSchemaV3(d, { maxReplies: 64, maxRoutes: 64, maxAttempts: 3 });
        await upgradeChannelSchemaV4(d, { maxGlobal: 128, maxPerAttempt: 8 });
        await upgradeChannelSchemaV5(d, { maxRecoveryCommands: 128, maxPerOperation: 8 });
        await upgradeChannelSchemaV6(d);
        await upgradeChannelSchemaV7(d);
        await installReferenceCaseSchema(
          database(config, credentials, 'case'),
          config.bindings.map((b) =>
            Object.freeze({
              scope: b.accountScope,
              caseId: b.caseId,
              ...b.initialCase,
              cancelled: false,
              committed: false,
            }),
          ),
        );
      } catch (e) {
        if (migrationCleanupUnknown(e)) this.#migrationOwnerUnknown = true;
        throw safe(e);
      }
      await this.#graph.add(0, new ExternalSchemaOwner(config, credentials)).install();
      return Object.freeze({
        inboxVersion: 7 as const,
        caseVersion: 1 as const,
        externalVersion: 1 as const,
      });
    });
    void this.#work.catch(() => undefined);
    return this.#work;
  }
  close(): Promise<void> {
    this.#closing = true;
    return this.#closeObservation.observe(async () => {
      if (this.#work) await this.#work.catch(() => undefined);
      if (this.#migrationOwnerUnknown) throw new StarterError('CleanupIncomplete');
      await this.#graph.close();
    });
  }
}
export function createStandaloneOwner(config: unknown, credentials: unknown): StandaloneOwner {
  return new StandaloneOwner(config, credentials);
}
export class StandaloneApplication {
  readonly #config: StarterConfig;
  readonly #credentials: RuntimeCredentials;
  readonly #options: StarterOptions;
  readonly #commands = new Set<Promise<unknown>>();
  readonly #graphs = new Set<OwnedGraph>();
  #gatewayGraph: OwnedGraph | undefined;
  #gateway: ChannelGateway | undefined;
  #gatewayStarting: Promise<GatewayEndpoint> | undefined;
  #gatewayResult: Promise<GatewayEndpoint> | undefined;
  #lastGatewayMetrics: Readonly<Record<string, number>> | null = null;
  #closing = false;
  readonly #closeObservation = new CloseObservation();
  constructor(configInput: unknown, credentialsInput: unknown, options: StarterOptions = {}) {
    this.#config = parseConfig(configInput);
    const c = parseCredentials(credentialsInput, this.#config);
    if (c.role !== 'runtime') throw new StarterError('AccessDenied');
    this.#credentials = c;
    const hook =
      options && typeof options === 'object'
        ? Object.getOwnPropertyDescriptor(options, 'harnessAfterAcknowledgement')
        : undefined;
    const p = fields(options, hook ? ['harnessAfterAcknowledgement'] : []);
    if (
      p.harnessAfterAcknowledgement !== undefined &&
      typeof p.harnessAfterAcknowledgement !== 'function'
    )
      throw new StarterError('InvalidConfiguration');
    this.#options = Object.freeze({
      ...(p.harnessAfterAcknowledgement
        ? {
            harnessAfterAcknowledgement:
              p.harnessAfterAcknowledgement as () => void | Promise<void>,
          }
        : {}),
    });
  }
  metrics(): Readonly<{
    commandsActive: number;
    retainedGraphs: number;
    gatewayActive: boolean;
    closing: boolean;
  }> {
    return Object.freeze({
      commandsActive: this.#commands.size,
      retainedGraphs: this.#graphs.size,
      gatewayActive: this.#gateway !== undefined,
      closing: this.#closing,
    });
  }
  gatewayMetrics(): Readonly<Record<string, number>> | null {
    return this.#gateway?.metrics() ?? this.#lastGatewayMetrics;
  }
  #binding(alias: string) {
    const b = this.#config.bindings.find((b) => b.alias === id(alias));
    if (!b) throw new StarterError('AccessDenied');
    return Object.freeze({
      binding: b,
      credentials: this.#credentials.bindings.find((c) => c.alias === b.alias)!,
    });
  }
  #inbox(graph: OwnedGraph): ChannelInbox {
    return graph.add(
      1,
      new ChannelInbox(
        database(this.#config, this.#credentials, 'inbox'),
        integration(this.#config, this.#credentials),
        new SeededAccounts(seeds(this.#config, this.#credentials)),
        {},
        () => undefined,
      ),
    );
  }
  #case(graph: OwnedGraph): ReferenceCaseAuthority {
    return graph.add(
      1,
      new ReferenceCaseAuthority(
        database(this.#config, this.#credentials, 'case'),
        this.#config.bindings.map((b) => ({ scope: b.accountScope, caseId: b.caseId })),
      ),
    );
  }
  #run<T>(mutating: boolean, action: (g: OwnedGraph) => Promise<T>): Promise<T> {
    if (this.#closing) return Promise.reject(new StarterError('Closed'));
    if (this.#commands.size || [...this.#graphs].some((g) => g !== this.#gatewayGraph))
      return Promise.reject(new StarterError('Overloaded'));
    const graph = new OwnedGraph();
    this.#graphs.add(graph);
    const actual = Promise.resolve().then(async () => {
      let failed = false,
        primary: unknown,
        result: T | undefined;
      try {
        if (mutating) {
          const mode = graph.add(3, new ModeMutex(this.#config, this.#credentials));
          await mode.acquire();
        }
        if (this.#closing) throw new StarterError('Closed');
        result = await action(graph);
      } catch (e) {
        failed = true;
        primary = e;
      } finally {
        try {
          await graph.close();
          this.#graphs.delete(graph);
        } catch (e) {
          if (!failed) {
            failed = true;
            primary = e;
          }
        }
      }
      if (failed) throw safe(primary);
      return result as T;
    });
    this.#commands.add(actual);
    void actual.then(
      () => this.#commands.delete(actual),
      () => this.#commands.delete(actual),
    );
    return actual;
  }
  challenge(alias: string) {
    const { binding: b, credentials: c } = this.#binding(alias);
    return this.#run(true, (g) => this.#inbox(g).createChallenge(c.accountToken, b.senderId));
  }
  associate(raw: Uint8Array, headers: WebhookHeaders) {
    const wire = webhook(raw, headers);
    return this.#run(true, (g) => this.#inbox(g).completeAssociation(wire.raw, wire.headers));
  }
  accept(raw: Uint8Array, headers: WebhookHeaders) {
    const wire = webhook(raw, headers);
    return this.#run(true, (g) => this.#inbox(g).acceptSms(wire.raw, wire.headers));
  }
  inspect(alias: string, receiptId: string): Promise<StoredMessage> {
    const { credentials: c } = this.#binding(alias),
      receipt = uuid(receiptId);
    return this.#run(false, (g) => this.#inbox(g).inspect(c.accountToken, receipt));
  }
  history(alias: string, query: Readonly<{ after?: string; limit?: number }> = {}) {
    const { credentials: c } = this.#binding(alias);
    if (!query || typeof query !== 'object') throw new StarterError('InvalidCommand');
    const p = fields(query, [
      ...(Object.hasOwn(query, 'after') ? ['after'] : []),
      ...(Object.hasOwn(query, 'limit') ? ['limit'] : []),
    ]);
    const after = p.after ?? '0',
      limit = p.limit ?? 8;
    if (
      typeof after !== 'string' ||
      !/^(0|[1-9][0-9]{0,18})$/.test(after) ||
      BigInt(after) > 9223372036854775807n ||
      !Number.isSafeInteger(limit) ||
      (limit as number) < 1 ||
      (limit as number) > 8
    )
      throw new StarterError('InvalidCommand');
    return this.#run(false, (g) =>
      this.#inbox(g).history(c.accountToken, { after, limit: limit as number }),
    );
  }
  currentCase(alias: string, signal?: AbortSignal) {
    const { binding: b } = this.#binding(alias),
      s = signalOrDefault(signal);
    return this.#run(false, (g) =>
      this.#case(g).inspect({ scope: b.accountScope, caseId: b.caseId }, s),
    );
  }
  route(alias: string, receiptId: string, signal?: AbortSignal) {
    const { binding: b, credentials: c } = this.#binding(alias),
      receipt = uuid(receiptId),
      s = signalOrDefault(signal);
    return this.#run(true, (g) => {
      const router = g.add(
        0,
        new RevisionRouter(
          this.#inbox(g),
          this.#case(g),
          [{ scope: b.accountScope, caseId: b.caseId }],
          { observer: () => undefined },
        ),
      );
      return router.route(c.accountToken, receipt, s);
    });
  }
  #ports(
    graph: OwnedGraph,
    authority?: ReferenceCaseAuthority,
    operationClient?: ExternalOperationClient,
  ) {
    let cases = authority;
    const operations =
      operationClient ?? graph.add(1, new ExternalOperationClient(this.#config, this.#credentials));
    return {
      cases: {
        inspect: async (
          ref: Parameters<ReferenceCaseAuthority['inspect']>[0],
          signal: AbortSignal,
        ) => {
          cases ??= this.#case(graph);
          const c = await cases.inspect(ref, signal);
          return Object.freeze({
            scope: c.scope,
            caseId: c.caseId,
            revision: c.revision,
            source: 'synthetic_read_only' as const,
          });
        },
      },
      agent: {
        prepare: async (
          input: Readonly<{ currentCase: Readonly<{ revision: string }> }>,
          signal: AbortSignal,
        ) => {
          if (signal.aborted) throw new StarterError('Unavailable');
          return Object.freeze({
            kind: 'investigation' as const,
            source: 'scripted' as const,
            caseRevision: input.currentCase.revision,
          });
        },
      },
      operations: {
        capabilities: operations.capabilities,
        lookup: operations.lookup.bind(operations),
        accept: operations.accept.bind(operations),
      },
    };
  }
  startGateway(): Promise<GatewayEndpoint> {
    if (this.#closing) return Promise.reject(new StarterError('Closed'));
    if (this.#commands.size || [...this.#graphs].some((g) => g !== this.#gatewayGraph))
      return Promise.reject(new StarterError('Overloaded'));
    if (!this.#gatewayResult) {
      const graph = new OwnedGraph();
      this.#graphs.add(graph);
      this.#gatewayGraph = graph;
      const deadline = performance.now() + 5000;
      const controller = new AbortController();
      const check = () => {
        if (this.#closing || performance.now() >= deadline) throw new StarterError('Unavailable');
      };
      this.#gatewayStarting = Promise.resolve()
        .then(async () => {
          const mode = graph.add(3, new ModeMutex(this.#config, this.#credentials));
          await mode.acquire();
          check();
          const operations = graph.add(
            1,
            new ExternalOperationClient(this.#config, this.#credentials),
          );
          for (const binding of this.#config.bindings) {
            check();
            await operations.preflight(binding.alias, controller.signal);
            check();
          }
          const authority = this.#case(graph);
          for (const binding of this.#config.bindings) {
            check();
            const current = await authority.inspect(
              { scope: binding.accountScope, caseId: binding.caseId },
              controller.signal,
            );
            check();
            if (current.revision === '0') throw new StarterError('OperationConflict');
          }
          const remaining = Math.floor(deadline - performance.now());
          if (remaining < 20) throw new StarterError('Unavailable');
          this.#gateway = graph.add(
            0,
            new ChannelGateway({
              database: database(this.#config, this.#credentials, 'inbox'),
              integration: integration(this.#config, this.#credentials),
              accounts: seeds(this.#config, this.#credentials),
              ports: this.#ports(graph, authority, operations),
              options: {
                startupMs: remaining,
                observer: () => undefined,
                ...(this.#options.harnessAfterAcknowledgement
                  ? { harnessAfterAcknowledgement: this.#options.harnessAfterAcknowledgement }
                  : {}),
              },
            }),
          );
          const endpoint = await this.#gateway.listen(this.#config.endpoints.gateway);
          check();
          return endpoint;
        })
        .catch((e) => {
          throw safe(e);
        });
      this.#gatewayResult = new Promise<GatewayEndpoint>((resolve, reject) => {
        const timer = setTimeout(() => {
          controller.abort();
          reject(new StarterError('Unavailable'));
          void this.close().catch(() => undefined);
        }, 5000);
        void this.#gatewayStarting!.then(
          (endpoint) => {
            clearTimeout(timer);
            resolve(endpoint);
          },
          (e) => {
            clearTimeout(timer);
            reject(safe(e));
          },
        );
      });
      void this.#gatewayResult.catch(() => undefined);
    }
    return this.#gatewayResult;
  }
  processing(alias: string, receiptId: string): Promise<DispatchObservation> {
    const { credentials: c } = this.#binding(alias),
      receipt = uuid(receiptId);
    return this.#run(false, (g) =>
      g
        .add(
          0,
          new ChannelDispatcher(
            database(this.#config, this.#credentials, 'inbox'),
            integration(this.#config, this.#credentials),
            new SeededAccounts(seeds(this.#config, this.#credentials)),
            this.#ports(g),
            { observer: () => undefined },
          ),
        )
        .inspect(c.accountToken, receipt),
    );
  }
  dispatch(alias: string, receiptId: string, reconcileOnly = false) {
    const { credentials: c } = this.#binding(alias),
      receipt = uuid(receiptId);
    return this.#run(true, async (g) => {
      const operations = g.add(1, new ExternalOperationClient(this.#config, this.#credentials));
      await operations.preflight(alias, new AbortController().signal);
      if (this.#closing) throw new StarterError('Closed');
      const d = g.add(
        0,
        new ChannelDispatcher(
          database(this.#config, this.#credentials, 'inbox'),
          integration(this.#config, this.#credentials),
          new SeededAccounts(seeds(this.#config, this.#credentials)),
          this.#ports(g, undefined, operations),
          { observer: () => undefined },
        ),
      );
      return reconcileOnly ? d.reconcile(c.accountToken, receipt) : d.step(c.accountToken, receipt);
    });
  }

  #outbox(graph: OwnedGraph, capability: StarterCarrier, alias: string): ChannelOutbox {
    if (capability !== 'ordinary_fake_sms_v1' && capability !== 'idempotent_fake_sms_v1')
      throw new StarterError('InvalidCommand');
    // A one-shot command selects its fixed source capability before construction; no fallback exists.
    const binding = this.#binding(alias).binding;
    const bearer = this.#credentials.externalBearers.find((b) => b.alias === binding.alias)!;
    const client =
      capability === 'ordinary_fake_sms_v1'
        ? new FakeSmsSendClient(
            { host: '127.0.0.1', port: this.#config.endpoints.external },
            'Bearer ' + bearer.ordinary,
            binding.providerScope,
          )
        : new IdempotentFakeSmsClient(
            { host: '127.0.0.1', port: this.#config.endpoints.external },
            'Bearer ' + bearer.idempotent,
            binding.providerScope,
          );
    graph.add(1, client);
    return graph.add(
      0,
      new ChannelOutbox(
        database(this.#config, this.#credentials, 'inbox'),
        integration(this.#config, this.#credentials),
        new SeededAccounts(seeds(this.#config, this.#credentials)),
        this.#config.bindings.map((b) => ({
          token: this.#credentials.bindings.find((c) => c.alias === b.alias)!.publisherToken,
          scope: b.accountScope,
          caseId: b.caseId,
          conversationId: b.conversationId,
        })),
        client,
        {
          observer: () => undefined,
          recoveryControllers: this.#config.bindings.map((b) => ({
            token: this.#credentials.bindings.find((c) => c.alias === b.alias)!.recoveryToken,
            scope: b.accountScope,
            caseId: b.caseId,
            conversationId: b.conversationId,
          })),
        },
      ),
    );
  }
  reply(alias: string, draft: ReplyDraft) {
    const { credentials: c } = this.#binding(alias);
    const p = fields(draft, ['schemaVersion', 'outboundId', 'responseId', 'body']);
    if (
      p.schemaVersion !== 1 ||
      typeof p.body !== 'string' ||
      Buffer.byteLength(p.body, 'utf8') > 4096
    )
      throw new StarterError('InvalidCommand');
    const copy: ReplyDraft = Object.freeze({
      schemaVersion: 1,
      outboundId: uuid(p.outboundId),
      responseId: id(p.responseId),
      body: p.body,
    });
    return this.#run(true, (g) =>
      this.#outbox(g, 'ordinary_fake_sms_v1', alias).enqueue(c.publisherToken, copy),
    );
  }
  selectRoute(
    alias: string,
    input: Readonly<{ senderId: string; associationVersion: string; expectedRouteVersion: string }>,
  ) {
    const { binding: b, credentials: c } = this.#binding(alias),
      p = fields(input, ['senderId', 'associationVersion', 'expectedRouteVersion']);
    if (
      p.senderId !== b.senderId ||
      typeof p.associationVersion !== 'string' ||
      typeof p.expectedRouteVersion !== 'string'
    )
      throw new StarterError('InvalidCommand');
    const copy = {
      senderId: b.senderId,
      associationVersion: p.associationVersion,
      expectedRouteVersion: p.expectedRouteVersion,
    };
    return this.#run(true, (g) =>
      this.#outbox(g, 'ordinary_fake_sms_v1', alias).selectRoute(c.accountToken, copy),
    );
  }
  send(alias: string, outboundId: string, capability: StarterCarrier, signal?: AbortSignal) {
    const { credentials: c } = this.#binding(alias),
      outbound = uuid(outboundId),
      s = signalOrDefault(signal);
    return this.#run(true, (g) =>
      this.#outbox(g, capability, alias).send(c.accountToken, outbound, s),
    );
  }
  inspectReply(
    alias: string,
    outboundId: string,
    capability: StarterCarrier = 'ordinary_fake_sms_v1',
  ) {
    const { credentials: c } = this.#binding(alias),
      outbound = uuid(outboundId);
    return this.#run(false, (g) =>
      this.#outbox(g, capability, alias).inspect(c.accountToken, outbound),
    );
  }
  callback(raw: Uint8Array, headers: WebhookHeaders) {
    const wire = webhook(raw, headers);
    return this.#run(true, (g) =>
      g
        .add(
          0,
          new CallbackInbox(
            database(this.#config, this.#credentials, 'inbox'),
            createFakeSmsCallbackIntegration(
              this.#config.bindings[0]!.providerScope,
              Buffer.from(this.#credentials.callbackHmac, 'base64url'),
            ),
            new SeededAccounts(seeds(this.#config, this.#credentials)),
            { observer: () => undefined },
          ),
        )
        .accept(wire.raw, wire.headers),
    );
  }
  inspectCallbacks(alias: string, outboundId: string, attemptId: string) {
    const { credentials: c } = this.#binding(alias),
      outbound = uuid(outboundId),
      attempt = uuid(attemptId);
    return this.#run(false, (g) =>
      g
        .add(
          0,
          new CallbackInbox(
            database(this.#config, this.#credentials, 'inbox'),
            createFakeSmsCallbackIntegration(
              this.#config.bindings[0]!.providerScope,
              Buffer.from(this.#credentials.callbackHmac, 'base64url'),
            ),
            new SeededAccounts(seeds(this.#config, this.#credentials)),
            { observer: () => undefined },
          ),
        )
        .inspectAttempt(c.accountToken, { outboundId: outbound, attemptId: attempt }),
    );
  }
  reconcile(
    alias: string,
    capability: StarterCarrier,
    input: Readonly<{ commandId: string; outboundId: string; attemptId: string }>,
  ): Promise<RecoveryCommandView> {
    const { credentials: c } = this.#binding(alias),
      p = fields(input, ['commandId', 'outboundId', 'attemptId']);
    const copy = {
      commandId: uuid(p.commandId),
      outboundId: uuid(p.outboundId),
      attemptId: uuid(p.attemptId),
    };
    return this.#run(true, (g) =>
      this.#outbox(g, capability, alias).reconcile(c.recoveryToken, copy),
    );
  }
  retry(
    alias: string,
    capability: StarterCarrier,
    input: Readonly<{ commandId: string; outboundId: string; expectedAttemptId: string }>,
  ): Promise<RecoveryCommandView> {
    const { credentials: c } = this.#binding(alias),
      p = fields(input, ['commandId', 'outboundId', 'expectedAttemptId']);
    const copy = {
      commandId: uuid(p.commandId),
      outboundId: uuid(p.outboundId),
      expectedAttemptId: uuid(p.expectedAttemptId),
    };
    return this.#run(true, (g) => this.#outbox(g, capability, alias).retry(c.recoveryToken, copy));
  }
  close(): Promise<void> {
    this.#closing = true;
    return this.#closeObservation.observe(async () => {
      await Promise.allSettled([...this.#commands]);
      if (this.#gatewayStarting) await this.#gatewayStarting.catch(() => undefined);
      let failed = false;
      for (const graph of [...this.#graphs]) {
        try {
          await graph.close();
          this.#graphs.delete(graph);
        } catch {
          failed = true;
        }
      }
      if (failed || this.#graphs.size) throw new StarterError('CleanupIncomplete');
      this.#lastGatewayMetrics = this.#gateway?.metrics() ?? this.#lastGatewayMetrics;
      this.#gateway = undefined;
    });
  }
}
export function createStandaloneApplication(
  config: unknown,
  credentials: unknown,
  options: StarterOptions = {},
): StandaloneApplication {
  return new StandaloneApplication(config, credentials, options);
}
