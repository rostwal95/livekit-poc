/** Immutable response/quote associations only. This store is not a case or execution authority. */
import { createHash } from 'node:crypto';
import type { Pool, PoolClient } from 'pg';
import {
  PgClient,
  watchClient,
  PgPool,
  watchPool,
  catalog,
  config,
  digest,
  settings,
  table,
} from './database.js';
import type { DatabaseSettings } from './public-types.js';
import { checkedSignal, isAborted, fields, id, reference, sameReference } from './routing-types.js';
import {
  ConfirmationError,
  prompt,
  promptReference,
  storedPrompt,
  type ConfirmationPrompt,
  type ConfirmationPromptPort,
  type PromptReference,
  type StoredPrompt,
} from './confirmation-types.js';
export { ConfirmationError } from './confirmation-types.js';
export type { ConfirmationPrompt, StoredPrompt, PromptReference } from './confirmation-types.js';
export type { DatabaseSettings } from './public-types.js';
export type PromptPublisher = Readonly<{
  token: string;
  scope: Readonly<{ tenantId: string; accountId: string }>;
  caseId: string;
  conversationId: string;
}>;
const MARKER = 'p2-confirmation-prompt-registry-v1';
const SPEC = `CREATE TABLE prompt_metadata(singleton boolean PRIMARY KEY CHECK(singleton),version smallint NOT NULL CHECK(version=1),definition_digest text NOT NULL,catalog_snapshot jsonb NOT NULL,maximum_prompts integer NOT NULL CHECK(maximum_prompts BETWEEN 1 AND 10000));
CREATE TABLE prompt_admission(singleton boolean PRIMARY KEY CHECK(singleton),prompt_count integer NOT NULL CHECK(prompt_count>=0));
CREATE TABLE prompts(tenant_id text NOT NULL,account_id text NOT NULL,response_id text NOT NULL,case_id text NOT NULL,conversation_id text NOT NULL,canonical_payload text NOT NULL,payload_digest text NOT NULL,registered_at timestamptz NOT NULL,PRIMARY KEY(tenant_id,account_id,response_id));`;
const DEFINITION = digest(SPEC);
function configuration(input: DatabaseSettings, role: string): DatabaseSettings {
  let result: DatabaseSettings;
  try {
    result = settings(input, role);
  } catch {
    throw new ConfirmationError('InvalidCommand');
  }
  if (!/^p2_prompt_[a-z0-9_]{1,53}(?![\s\S])/.test(result.schema))
    throw new ConfirmationError('InvalidCommand');
  return result;
}
function tokenDigest(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{32,128}(?![\s\S])/.test(value))
    throw new ConfirmationError('AccessDenied');
  return createHash('sha256').update(value).digest('hex');
}
async function validate(
  client: Pick<PoolClient, 'query'>,
  database: DatabaseSettings,
  owner = false,
): Promise<number> {
  const role = await client.query(
    `SELECT current_user AS name,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) AS member,has_database_privilege(current_user,current_database(),'CREATE') AS can_create,has_database_privilege(current_user,current_database(),'TEMPORARY') AS can_temp,EXISTS(SELECT 1 FROM pg_namespace z WHERE z.nspname !~ '^pg_' AND z.nspname<>'information_schema' AND (z.nspowner=r.oid OR has_schema_privilege(current_user,z.oid,'CREATE'))) AS schema_admin FROM pg_roles r WHERE rolname=current_user`,
  );
  const who = role.rows[0];
  if (
    !who ||
    who.name !== (owner ? 'continuity_migrator' : 'livekit_lab') ||
    who.rolsuper ||
    who.rolcreatedb ||
    who.rolcreaterole ||
    who.rolreplication ||
    who.rolbypassrls ||
    who.member ||
    (!owner && (who.can_create || who.can_temp || who.schema_admin))
  )
    throw new ConfirmationError('Unavailable');
  const actual = await catalog(client, database.schema);
  const shape = actual as {
    owner?: unknown;
    relations?: {
      name?: unknown;
      kind?: unknown;
      owner?: unknown;
      rls?: unknown;
      force_rls?: unknown;
      triggers?: unknown[];
      rules?: unknown[];
      columns?: unknown[][];
    }[];
    functions?: unknown[];
  };
  const names = [
    'prompt_metadata',
    'prompt_metadata_pkey',
    'prompt_admission',
    'prompt_admission_pkey',
    'prompts',
    'prompts_pkey',
  ];
  if (
    shape.owner !== 'continuity_migrator' ||
    !Array.isArray(shape.relations) ||
    shape.relations.length !== names.length ||
    !Array.isArray(shape.functions) ||
    shape.functions.length ||
    shape.relations.some(
      (r) =>
        typeof r.name !== 'string' ||
        !names.includes(r.name) ||
        r.owner !== 'continuity_migrator' ||
        typeof r.kind !== 'string' ||
        !['r', 'i'].includes(r.kind) ||
        r.rls !== false ||
        r.force_rls !== false ||
        !Array.isArray(r.triggers) ||
        r.triggers.length ||
        !Array.isArray(r.rules) ||
        r.rules.length,
    )
  )
    throw new ConfirmationError('Unavailable');
  const metadata = shape.relations.find((r) => r.name === 'prompt_metadata');
  if (
    metadata?.kind !== 'r' ||
    JSON.stringify(metadata.columns?.map((c) => c.slice(0, 7))) !==
      JSON.stringify([
        ['singleton', 'boolean', true, '', '', null, null],
        ['version', 'smallint', true, '', '', null, null],
        ['definition_digest', 'text', true, '', '', null, null],
        ['catalog_snapshot', 'jsonb', true, '', '', null, null],
        ['maximum_prompts', 'integer', true, '', '', null, null],
      ])
  )
    throw new ConfirmationError('Unavailable');
  const result = await client.query(
    `SELECT m.*,obj_description(n.oid,'pg_namespace') AS marker FROM ${table(database.schema, 'prompt_metadata')} m JOIN pg_namespace n ON n.nspname=$1`,
    [database.schema],
  );
  const m = result.rows[0];
  if (
    result.rows.length !== 1 ||
    m.singleton !== true ||
    m.version !== 1 ||
    m.marker !== MARKER ||
    m.definition_digest !== DEFINITION ||
    !Number.isInteger(m.maximum_prompts) ||
    m.maximum_prompts < 1 ||
    m.maximum_prompts > 10000 ||
    JSON.stringify(m.catalog_snapshot) !== JSON.stringify(actual)
  )
    throw new ConfirmationError('Unavailable');
  return m.maximum_prompts as number;
}
export async function installPromptRegistry(
  input: DatabaseSettings,
  maximumPrompts = 1000,
): Promise<void> {
  const database = configuration(input, 'continuity_migrator');
  if (!Number.isInteger(maximumPrompts) || maximumPrompts < 1 || maximumPrompts > 10000)
    throw new ConfirmationError('InvalidCommand');
  const client = watchClient(new PgClient(config(database)));
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'p2-prompt-registry:' + database.schema,
    ]);
    const exists = await client.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [
      database.schema,
    ]);
    if (exists.rows.length) {
      if ((await validate(client, database, true)) !== maximumPrompts)
        throw new ConfirmationError('InvalidCommand');
    } else {
      const who = await client.query('SELECT current_user AS name');
      if (who.rows[0]?.name !== 'continuity_migrator') throw new ConfirmationError('AccessDenied');
      await client.query(
        `CREATE SCHEMA "${database.schema}" AUTHORIZATION continuity_migrator;REVOKE ALL ON SCHEMA "${database.schema}" FROM PUBLIC;GRANT USAGE ON SCHEMA "${database.schema}" TO livekit_lab;COMMENT ON SCHEMA "${database.schema}" IS '${MARKER}'`,
      );
      await client.query(
        SPEC.replace(
          /(CREATE TABLE )([a-z_]+)/g,
          (_, prefix: string, name: string) => prefix + table(database.schema, name),
        ),
      );
      await client.query(
        `REVOKE ALL ON ${table(database.schema, 'prompt_metadata')},${table(database.schema, 'prompt_admission')},${table(database.schema, 'prompts')} FROM PUBLIC,livekit_lab;GRANT SELECT ON ${table(database.schema, 'prompt_metadata')},${table(database.schema, 'prompt_admission')},${table(database.schema, 'prompts')} TO livekit_lab;GRANT INSERT ON ${table(database.schema, 'prompts')} TO livekit_lab;GRANT UPDATE(prompt_count) ON ${table(database.schema, 'prompt_admission')} TO livekit_lab`,
      );
      await client.query(
        `INSERT INTO ${table(database.schema, 'prompt_admission')} VALUES(true,0)`,
      );
      const shape = await catalog(client, database.schema);
      await client.query(
        `INSERT INTO ${table(database.schema, 'prompt_metadata')} VALUES(true,1,$1,$2::jsonb,$3)`,
        [DEFINITION, JSON.stringify(shape), maximumPrompts],
      );
      await validate(client, database, true);
    }
    await client.query('COMMIT');
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch {
      /* Always retire the actual owner connection. */
    }
    throw error instanceof ConfirmationError ? error : new ConfirmationError('Unavailable');
  } finally {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        client.end(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new ConfirmationError('CleanupIncomplete')), 2000);
        }),
      ]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
function decode(row: Record<string, unknown>, expected: PromptReference): StoredPrompt {
  try {
    if (
      typeof row.canonical_payload !== 'string' ||
      typeof row.payload_digest !== 'string' ||
      digest(row.canonical_payload) !== row.payload_digest ||
      !(row.registered_at instanceof Date)
    )
      throw new Error();
    const decoded = prompt(JSON.parse(row.canonical_payload) as unknown);
    if (
      JSON.stringify(decoded) !== row.canonical_payload ||
      decoded.scope.tenantId !== row.tenant_id ||
      decoded.scope.accountId !== row.account_id ||
      decoded.responseId !== row.response_id ||
      decoded.caseId !== row.case_id ||
      decoded.conversationId !== row.conversation_id
    )
      throw new Error();
    return storedPrompt({ ...decoded, registeredAt: row.registered_at.toISOString() }, expected);
  } catch {
    throw new ConfirmationError('Unavailable');
  }
}
type PublisherBinding = Omit<PromptPublisher, 'token'>;
export class PromptRegistry implements ConfirmationPromptPort {
  readonly #database: DatabaseSettings;
  readonly #publishers = new Map<string, PublisherBinding>();
  readonly #pool: Pool;
  readonly #calls = new Set<Promise<unknown>>();
  #closing = false;
  #ending: Promise<void> | undefined;
  #counts = { published: 0, replayed: 0, conflicts: 0, lookups: 0, rejected: 0, unknown: 0 };
  constructor(input: DatabaseSettings, publishers: readonly PromptPublisher[]) {
    this.#database = configuration(input, 'livekit_lab');
    if (!Array.isArray(publishers) || publishers.length < 1 || publishers.length > 64)
      throw new ConfirmationError('InvalidCommand');
    for (const value of publishers) {
      const p = fields(value, ['token', 'scope', 'caseId', 'conversationId']);
      const key = tokenDigest(p.token),
        ref = reference({ scope: p.scope, caseId: p.caseId });
      if (this.#publishers.has(key)) throw new ConfirmationError('InvalidCommand');
      this.#publishers.set(key, Object.freeze({ ...ref, conversationId: id(p.conversationId) }));
    }
    this.#pool = watchPool(new PgPool(config(this.#database)));
    this.#pool.on('error', () => {
      this.#counts.rejected++;
    });
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({ ...this.#counts, active: this.#calls.size });
  }
  #allowed(ref: PromptReference): void {
    if (
      ![...this.#publishers.values()].some(
        (p) => sameReference(p, ref) && p.conversationId === ref.conversationId,
      )
    )
      throw new ConfirmationError('AccessDenied');
  }
  publish(
    publisherToken: string,
    value: ConfirmationPrompt,
    signal: AbortSignal,
  ): Promise<StoredPrompt> {
    const publisher = this.#publishers.get(tokenDigest(publisherToken));
    if (!publisher) throw new ConfirmationError('AccessDenied');
    const proposed = prompt(value);
    if (!sameReference(publisher, proposed) || publisher.conversationId !== proposed.conversationId)
      throw new ConfirmationError('AccessDenied');
    let created = false;
    return this.#run(signal, true, async (client, maximum) => {
      const guard = await client.query(
        `SELECT * FROM ${table(this.#database.schema, 'prompt_admission')} WHERE singleton FOR UPDATE`,
      );
      if (
        guard.rows.length !== 1 ||
        !Number.isInteger(guard.rows[0].prompt_count) ||
        guard.rows[0].prompt_count < 0
      )
        throw new ConfirmationError('Unavailable');
      const existing = await client.query(
        `SELECT * FROM ${table(this.#database.schema, 'prompts')} WHERE tenant_id=$1 AND account_id=$2 AND response_id=$3`,
        [proposed.scope.tenantId, proposed.scope.accountId, proposed.responseId],
      );
      const canonical = JSON.stringify(proposed),
        fingerprint = digest(canonical);
      if (existing.rows.length) {
        const row = existing.rows[0];
        const original = decode(
          row,
          promptReference({
            scope: { tenantId: row.tenant_id, accountId: row.account_id },
            caseId: row.case_id,
            conversationId: row.conversation_id,
            responseId: row.response_id,
          }),
        );
        if (
          existing.rows[0].canonical_payload !== canonical ||
          existing.rows[0].payload_digest !== fingerprint
        ) {
          this.#counts.conflicts++;
          throw new ConfirmationError('IdentityConflict');
        }
        return original;
      }
      const count = await client.query(
        `SELECT count(*)::integer AS count FROM ${table(this.#database.schema, 'prompts')}`,
      );
      if (count.rows[0].count !== guard.rows[0].prompt_count)
        throw new ConfirmationError('Unavailable');
      if (guard.rows[0].prompt_count >= maximum) throw new ConfirmationError('Overloaded');
      if (isAborted(signal)) throw new ConfirmationError('Unavailable');
      const result = await client.query(
        `INSERT INTO ${table(this.#database.schema, 'prompts')} VALUES($1,$2,$3,$4,$5,$6,$7,clock_timestamp()) RETURNING *`,
        [
          proposed.scope.tenantId,
          proposed.scope.accountId,
          proposed.responseId,
          proposed.caseId,
          proposed.conversationId,
          canonical,
          fingerprint,
        ],
      );
      await client.query(
        `UPDATE ${table(this.#database.schema, 'prompt_admission')} SET prompt_count=prompt_count+1 WHERE singleton`,
      );
      created = true;
      return decode(result.rows[0], proposed);
    }).then((value) => {
      if (isAborted(signal)) {
        this.#counts.unknown++;
        throw new ConfirmationError('OutcomeUnknown');
      }
      this.#counts[created ? 'published' : 'replayed']++;
      return value;
    });
  }
  find(input: PromptReference, signal: AbortSignal): Promise<StoredPrompt | null> {
    const ref = promptReference(input);
    this.#allowed(ref);
    return this.#run(signal, false, async (client) => {
      this.#counts.lookups++;
      const result = await client.query(
        `SELECT * FROM ${table(this.#database.schema, 'prompts')} WHERE tenant_id=$1 AND account_id=$2 AND response_id=$3 AND case_id=$4 AND conversation_id=$5`,
        [ref.scope.tenantId, ref.scope.accountId, ref.responseId, ref.caseId, ref.conversationId],
      );
      return result.rows.length ? decode(result.rows[0], ref) : null;
    });
  }
  #run<T>(
    signal: AbortSignal,
    write: boolean,
    operation: (client: PoolClient, maximum: number) => Promise<T>,
  ): Promise<T> {
    try {
      checkedSignal(signal);
    } catch {
      throw new ConfirmationError('InvalidCommand');
    }
    if (this.#closing) return Promise.reject(new ConfirmationError('Closed'));
    if (this.#calls.size >= 2) return Promise.reject(new ConfirmationError('Overloaded'));
    if (isAborted(signal)) return Promise.reject(new ConfirmationError('Unavailable'));
    const work = Promise.resolve().then(async () => {
      let client: PoolClient | undefined,
        began = false,
        committing = false,
        broken = false;
      try {
        client = await this.#pool.connect();
        await client.query('BEGIN');
        began = true;
        const maximum = await validate(client, this.#database);
        if (isAborted(signal)) throw new ConfirmationError('Unavailable');
        const result = await operation(client, maximum);
        if (isAborted(signal)) throw new ConfirmationError('Unavailable');
        committing = write;
        await client.query('COMMIT');
        began = false;
        committing = false;
        if (isAborted(signal))
          throw new ConfirmationError(write ? 'OutcomeUnknown' : 'Unavailable');
        return result;
      } catch (error) {
        if (began && client)
          try {
            await client.query('ROLLBACK');
          } catch {
            broken = true;
          }
        if (committing) {
          broken = true;
          this.#counts.unknown++;
          throw new ConfirmationError('OutcomeUnknown');
        }
        this.#counts.rejected++;
        throw error instanceof ConfirmationError ? error : new ConfirmationError('Unavailable');
      } finally {
        client?.release(broken);
      }
    });
    this.#calls.add(work);
    void work.then(
      () => this.#calls.delete(work),
      () => this.#calls.delete(work),
    );
    return work;
  }
  async close(): Promise<void> {
    this.#closing = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      this.#ending ??= Promise.allSettled([...this.#calls]).then(() => this.#pool.end());
      await Promise.race([
        this.#ending,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new ConfirmationError('CleanupIncomplete')), 2000);
        }),
      ]);
      if (this.#calls.size || this.#pool.totalCount)
        throw new ConfirmationError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
