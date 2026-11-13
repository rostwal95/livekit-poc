/** Synthetic external acceptance facts. This schema is not a workflow or retry authority. */
import pg from 'pg';
import type { PoolClient } from 'pg';
import { randomUUID } from 'node:crypto';
import type {
  OperationReceipt,
  OperationLookup,
  PreparedDispatch,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import type { CarrierResult, SendRequest } from '@livekit-ecosystem/channel-continuity/outbox';
import type {
  ProviderOperation,
  ProviderLookup,
} from '@livekit-ecosystem/channel-continuity/idempotent-fake-sms';
import {
  StarterError,
  STARTER_LIMITS,
  parseConfig,
  parseCredentials,
  database,
  digest,
  canonicalJson,
  profileDigest,
  CloseObservation,
  type StarterConfig,
  type OwnerCredentials,
  type ExternalCredentials,
} from './config.js';

const SPEC = `CREATE TABLE receipt_metadata(singleton boolean PRIMARY KEY CHECK(singleton),version smallint NOT NULL CHECK(version=1),profile_id uuid NOT NULL,config_digest text NOT NULL,definition_digest text NOT NULL,catalog_snapshot jsonb NOT NULL,max_receipts integer NOT NULL CHECK(max_receipts=16),investigation_count integer NOT NULL CHECK(investigation_count BETWEEN 0 AND 16),idempotent_count integer NOT NULL CHECK(idempotent_count BETWEEN 0 AND 16),ordinary_count integer NOT NULL CHECK(ordinary_count BETWEEN 0 AND 16));
CREATE TABLE investigation_receipts(tenant_id text NOT NULL,account_id text NOT NULL,operation_key uuid NOT NULL,payload_digest text NOT NULL CHECK(length(payload_digest)=64),canonical_payload text NOT NULL CHECK(octet_length(canonical_payload)<=32768),receipt_id uuid NOT NULL,accepted_at timestamptz NOT NULL,PRIMARY KEY(tenant_id,account_id,operation_key));
CREATE TABLE idempotent_sms_receipts(tenant_id text NOT NULL,provider text NOT NULL CHECK(provider='fake_sms'),provider_account_id text NOT NULL,provider_operation_key uuid NOT NULL,operation_digest text NOT NULL CHECK(length(operation_digest)=64),canonical_operation text NOT NULL CHECK(octet_length(canonical_operation)<=32768),provider_message_id uuid NOT NULL,accepted_at timestamptz NOT NULL,PRIMARY KEY(tenant_id,provider,provider_account_id,provider_operation_key));
CREATE TABLE ordinary_sms_attempts(external_call_id uuid PRIMARY KEY,tenant_id text NOT NULL,provider text NOT NULL CHECK(provider='fake_sms'),provider_account_id text NOT NULL,provider_operation_key uuid NOT NULL,attempt_id uuid NOT NULL,request_digest text NOT NULL CHECK(length(request_digest)=64),canonical_request text NOT NULL CHECK(octet_length(canonical_request)<=32768),provider_message_id uuid NOT NULL,accepted_at timestamptz NOT NULL);`;
export const EXTERNAL_DEFINITION_DIGEST = digest(SPEC);
export const EXTERNAL_TABLES = Object.freeze([
  'idempotent_sms_receipts',
  'investigation_receipts',
  'ordinary_sms_attempts',
  'receipt_metadata',
]);
const expectedRelations = Object.freeze(EXTERNAL_TABLES.flatMap((n) => [n, n + '_pkey']).sort());
function q(schema: string, name: string): string {
  return `"${schema}"."${name}"`;
}
function connection(config: StarterConfig, credentials: OwnerCredentials | ExternalCredentials) {
  const d = database(config, credentials, 'external');
  return {
    host: d.host,
    port: d.port,
    database: d.database,
    user: d.user,
    password: d.password,
    ssl: false as const,
    application_name: 'p2-starter-external',
    max: 1,
    allowExitOnIdle: true,
    idleTimeoutMillis: 1000,
    connectionTimeoutMillis: 1000,
    query_timeout: 4000,
    options:
      '-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500 -c idle_in_transaction_session_timeout=5000',
  };
}
type Connection = Pick<PoolClient, 'query'>;
async function role(client: Connection, owner: boolean): Promise<void> {
  const rows =
    await client.query(`SELECT current_user AS name,r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,r.rolbypassrls,
    EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) AS member,
    has_database_privilege(current_user,current_database(),'CREATE') AS can_create,
    has_database_privilege(current_user,current_database(),'TEMPORARY') AS can_temp,
    EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND (n.nspowner=r.oid OR has_schema_privilege(current_user,n.oid,'CREATE'))) AS schema_admin
    FROM pg_roles r WHERE rolname=current_user`);
  const r = rows.rows[0];
  if (
    !r ||
    r.name !== (owner ? 'continuity_migrator' : 'livekit_lab') ||
    r.rolsuper ||
    r.rolcreatedb ||
    r.rolcreaterole ||
    r.rolreplication ||
    r.rolbypassrls ||
    r.member ||
    (!owner && (r.can_create || r.can_temp || r.schema_admin))
  )
    throw new StarterError('AccessDenied');
}
async function catalog(client: Connection, schema: string): Promise<unknown> {
  const s = await client.query(
    'SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=$1',
    [schema],
  );
  const relations = await client.query(
    `SELECT c.relname AS name,c.relkind AS kind,pg_get_userbyid(c.relowner) AS owner,
    COALESCE((SELECT jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,pg_get_expr(d.adbin,d.adrelid)) ORDER BY a.attnum)
      FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),'[]'::jsonb) AS columns,
    COALESCE((SELECT jsonb_agg(pg_get_constraintdef(z.oid) ORDER BY z.conname) FROM pg_constraint z WHERE z.conrelid=c.oid),'[]'::jsonb) AS constraints,
    COALESCE((SELECT jsonb_agg(pg_get_triggerdef(t.oid) ORDER BY t.tgname) FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal),'[]'::jsonb) AS triggers,
    COALESCE((SELECT jsonb_agg(pg_get_ruledef(r.oid) ORDER BY r.rulename) FROM pg_rewrite r WHERE r.ev_class=c.oid),'[]'::jsonb) AS rules,
    c.relrowsecurity AS row_security,c.relforcerowsecurity AS force_row_security
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=$1 ORDER BY c.relname`,
    [schema],
  );
  const functions = await client.query(
    'SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=$1 ORDER BY p.proname',
    [schema],
  );
  return { owner: s.rows[0]?.owner ?? null, relations: relations.rows, functions: functions.rows };
}
async function validate(client: Connection, config: StarterConfig, owner = false): Promise<void> {
  await role(client, owner);
  const actual = (await catalog(client, config.schemas.external)) as {
    owner: unknown;
    relations: Record<string, unknown>[];
    functions: unknown[];
  };
  if (
    actual.owner !== 'continuity_migrator' ||
    actual.functions.length ||
    JSON.stringify(actual.relations.map((r) => r.name)) !== JSON.stringify(expectedRelations) ||
    actual.relations.some(
      (r) =>
        r.owner !== 'continuity_migrator' ||
        (r.kind !== 'r' && r.kind !== 'i') ||
        r.row_security ||
        r.force_row_security ||
        JSON.stringify(r.triggers) !== '[]' ||
        JSON.stringify(r.rules) !== '[]',
    )
  )
    throw new StarterError('SchemaMismatch');
  const rows = await client.query(
    `SELECT * FROM ${q(config.schemas.external, 'receipt_metadata')} WHERE singleton`,
  );
  const m = rows.rows[0];
  if (
    rows.rows.length !== 1 ||
    !m ||
    m.version !== 1 ||
    m.profile_id !== config.profileId ||
    m.config_digest !== profileDigest(config) ||
    m.definition_digest !== EXTERNAL_DEFINITION_DIGEST ||
    m.max_receipts !== 16 ||
    canonicalJson(m.catalog_snapshot) !== canonicalJson(actual)
  )
    throw new StarterError('SchemaMismatch');
  for (const [table, field] of [
    ['investigation_receipts', 'investigation_count'],
    ['idempotent_sms_receipts', 'idempotent_count'],
    ['ordinary_sms_attempts', 'ordinary_count'],
  ] as const) {
    const count = await client.query(
      `SELECT count(*)::integer AS count FROM ${q(config.schemas.external, table)}`,
    );
    if (
      !Number.isInteger(m[field]) ||
      m[field] < 0 ||
      m[field] > 16 ||
      count.rows[0]?.count !== m[field]
    )
      throw new StarterError('SchemaMismatch');
  }
  const grants = await client.query(
    `SELECT c.relname,
    has_table_privilege('livekit_lab',c.oid,'SELECT') AS can_select,
    has_table_privilege('livekit_lab',c.oid,'INSERT') AS can_insert,
    has_table_privilege('livekit_lab',c.oid,'UPDATE') AS can_update,
    has_table_privilege('livekit_lab',c.oid,'DELETE') AS can_delete,
    has_table_privilege('livekit_lab',c.oid,'TRUNCATE') AS can_truncate,
    has_schema_privilege('livekit_lab',n.oid,'CREATE') AS schema_create
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=$1 AND c.relkind='r' ORDER BY c.relname`,
    [config.schemas.external],
  );
  if (
    grants.rows.length !== 4 ||
    grants.rows.some(
      (r) =>
        !r.can_select ||
        r.can_delete ||
        r.can_truncate ||
        r.schema_create ||
        (r.relname === 'receipt_metadata'
          ? r.can_update || r.can_insert
          : !r.can_insert || r.can_update),
    )
  )
    throw new StarterError('SchemaMismatch');
  const columnGrants = await client.query(
    `SELECT a.attname,has_column_privilege('livekit_lab',c.oid,a.attname,'UPDATE') AS can_update
    FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname=$1 AND c.relname='receipt_metadata' AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum`,
    [config.schemas.external],
  );
  const mutable = ['investigation_count', 'idempotent_count', 'ordinary_count'];
  if (
    columnGrants.rows.length !== 10 ||
    columnGrants.rows.some((r) => r.can_update !== mutable.includes(String(r.attname)))
  )
    throw new StarterError('SchemaMismatch');
}
export class ExternalSchemaOwner {
  readonly #config: StarterConfig;
  readonly #client: pg.Client;
  #work: Promise<void> | undefined;
  #end: Promise<void> | undefined;
  constructor(configInput: StarterConfig, credentialsInput: OwnerCredentials) {
    this.#config = parseConfig(configInput);
    const credentials = parseCredentials(credentialsInput, this.#config);
    if (credentials.role !== 'owner') throw new StarterError('AccessDenied');
    this.#client = new pg.Client(connection(this.#config, credentials));
    this.#client.on('error', () => undefined);
  }
  install(): Promise<void> {
    this.#work ??= Promise.resolve().then(async () => {
      const config = this.#config,
        c = this.#client;
      let primary: unknown,
        began = false;
      try {
        await c.connect();
        await c.query('BEGIN');
        began = true;
        await role(c, true);
        await c.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
          'p2-starter-owner:' + config.schemas.external,
        ]);
        const exists = await c.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [
          config.schemas.external,
        ]);
        if (exists.rows.length) await validate(c, config, true);
        else {
          const schema = config.schemas.external;
          await c.query(`CREATE SCHEMA "${schema}" AUTHORIZATION continuity_migrator`);
          await c.query(`REVOKE ALL ON SCHEMA "${schema}" FROM PUBLIC`);
          for (const statement of SPEC.split('\n'))
            await c.query(statement.replaceAll('CREATE TABLE ', `CREATE TABLE "${schema}".`));
          await c.query(`GRANT USAGE ON SCHEMA "${schema}" TO livekit_lab`);
          await c.query(`GRANT SELECT ON ${q(schema, 'receipt_metadata')} TO livekit_lab`);
          await c.query(
            `GRANT UPDATE(investigation_count,idempotent_count,ordinary_count) ON ${q(schema, 'receipt_metadata')} TO livekit_lab`,
          );
          for (const t of EXTERNAL_TABLES.filter((n) => n !== 'receipt_metadata'))
            await c.query(`GRANT SELECT,INSERT ON ${q(schema, t)} TO livekit_lab`);
          const snapshot = await catalog(c, schema);
          await c.query(
            `INSERT INTO ${q(schema, 'receipt_metadata')}(singleton,version,profile_id,config_digest,definition_digest,catalog_snapshot,max_receipts,investigation_count,idempotent_count,ordinary_count) VALUES(true,1,$1,$2,$3,$4::jsonb,16,0,0,0)`,
            [
              config.profileId,
              profileDigest(config),
              EXTERNAL_DEFINITION_DIGEST,
              JSON.stringify(snapshot),
            ],
          );
          await c.query(
            `COMMENT ON SCHEMA "${schema}" IS 'p2-starter-external-v1:${config.profileId}'`,
          );
          await validate(c, config, true);
        }
        await c.query('COMMIT');
        began = false;
      } catch (e) {
        primary = e;
        if (began)
          try {
            await c.query('ROLLBACK');
          } catch {
            /* preserve first failure */
          }
      }
      if (primary)
        throw primary instanceof StarterError ? primary : new StarterError('Unavailable');
    });
    void this.#work.catch(() => undefined);
    return this.#work;
  }
  close(): Promise<void> {
    this.#end ??= Promise.resolve().then(async () => {
      if (this.#work) await this.#work.catch(() => undefined);
      try {
        await this.#client.end();
      } catch {
        throw new StarterError('CleanupIncomplete');
      }
    });
    void this.#end.catch(() => undefined);
    return this.#end;
  }
}
/** Methods receive values already validated by the closed authenticated HTTP boundary. */
export class ExternalReceiptStore {
  readonly #config: StarterConfig;
  readonly #pool: pg.Pool;
  readonly #calls = new Set<Promise<unknown>>();
  #closing = false;
  #drain: Promise<void> | undefined;
  readonly #closeObservation = new CloseObservation();
  constructor(configInput: StarterConfig, credentialsInput: ExternalCredentials) {
    const config = parseConfig(configInput),
      credentials = parseCredentials(credentialsInput, config);
    if (credentials.role !== 'external') throw new StarterError('AccessDenied');
    this.#config = config;
    this.#pool = new pg.Pool(connection(config, credentials));
    this.#pool.on('error', () => undefined);
  }
  metrics(): Readonly<{ active: number; closing: boolean }> {
    return Object.freeze({ active: this.#calls.size, closing: this.#closing });
  }
  #run<T>(action: (client: PoolClient) => Promise<T>): Promise<T> {
    if (this.#closing) return Promise.reject(new StarterError('Closed'));
    if (this.#calls.size >= STARTER_LIMITS.externalActive)
      return Promise.reject(new StarterError('Overloaded'));
    const work = Promise.resolve().then(async () => {
      let client: PoolClient | undefined,
        began = false,
        primary: unknown,
        result: T | undefined;
      try {
        client = await this.#pool.connect();
        await client.query('BEGIN');
        began = true;
        await client.query(
          `SELECT singleton FROM ${q(this.#config.schemas.external, 'receipt_metadata')} WHERE singleton FOR UPDATE`,
        );
        await validate(client, this.#config);
        result = await action(client);
        await client.query('COMMIT');
        began = false;
      } catch (e) {
        primary = e;
        if (client && began)
          try {
            await client.query('ROLLBACK');
          } catch {
            /* owned query settles before release */
          }
      } finally {
        client?.release(primary !== undefined);
      }
      if (primary)
        throw primary instanceof StarterError ? primary : new StarterError('Unavailable');
      return result as T;
    });
    this.#calls.add(work);
    void work.then(
      () => this.#calls.delete(work),
      () => this.#calls.delete(work),
    );
    return work;
  }
  preflight(): Promise<void> {
    return this.#run(async () => undefined);
  }
  lookup(
    input: OperationLookup,
  ): Promise<
    Readonly<{ status: 'absent' }> | Readonly<{ status: 'accepted'; receipt: OperationReceipt }>
  > {
    return this.#run(async (c) => {
      const r = await c.query(
        `SELECT * FROM ${q(this.#config.schemas.external, 'investigation_receipts')} WHERE tenant_id=$1 AND account_id=$2 AND operation_key=$3`,
        [input.scope.tenantId, input.scope.accountId, input.operationKey],
      );
      if (!r.rows.length) return Object.freeze({ status: 'absent' });
      const row = r.rows[0]!;
      if (row.payload_digest !== input.payloadDigest) throw new StarterError('IdentityConflict');
      return Object.freeze({
        status: 'accepted',
        receipt: Object.freeze({ ...input, receiptId: String(row.receipt_id) }),
      });
    });
  }
  accept(input: PreparedDispatch): Promise<OperationReceipt> {
    return this.#run(async (c) => {
      const s = input.submission;
      const prior = await c.query(
        `SELECT * FROM ${q(this.#config.schemas.external, 'investigation_receipts')} WHERE tenant_id=$1 AND account_id=$2 AND operation_key=$3`,
        [s.scope.tenantId, s.scope.accountId, s.operationKey],
      );
      if (prior.rows.length) {
        const row = prior.rows[0]!;
        if (
          row.payload_digest !== input.payloadDigest ||
          row.canonical_payload !== input.canonicalPayload
        )
          throw new StarterError('IdentityConflict');
        return Object.freeze({
          operationKey: s.operationKey,
          scope: s.scope,
          payloadDigest: input.payloadDigest,
          receiptId: String(row.receipt_id),
        });
      }
      await this.#capacity(c, 'investigation_count');
      const receiptId = randomUUID();
      await c.query(
        `INSERT INTO ${q(this.#config.schemas.external, 'investigation_receipts')} VALUES($1,$2,$3,$4,$5,$6,clock_timestamp())`,
        [
          s.scope.tenantId,
          s.scope.accountId,
          s.operationKey,
          input.payloadDigest,
          input.canonicalPayload,
          receiptId,
        ],
      );
      await this.#increment(c, 'investigation_count');
      return Object.freeze({
        operationKey: s.operationKey,
        scope: s.scope,
        payloadDigest: input.payloadDigest,
        receiptId,
      });
    });
  }
  idempotentLookup(
    scope: ProviderOperation['providerScope'],
    key: string,
    operationDigest: string,
  ): Promise<ProviderLookup> {
    return this.#run(async (c) => {
      const found = await c.query(
        `SELECT * FROM ${q(this.#config.schemas.external, 'idempotent_sms_receipts')} WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND provider_operation_key=$4`,
        [scope.tenantId, scope.provider, scope.providerAccountId, key],
      );
      const r = found.rows[0];
      if (r && r.operation_digest !== operationDigest) throw new StarterError('IdentityConflict');
      return Object.freeze({
        schemaVersion: 1,
        providerScope: scope,
        providerOperationKey: key,
        operationDigest,
        state: r ? 'accepted_by_provider' : 'absent',
        providerMessageId: r ? String(r.provider_message_id) : null,
      });
    });
  }
  idempotentSend(
    operation: ProviderOperation,
    operationDigest: string,
    attemptId: string,
    requestDigest: string,
  ): Promise<CarrierResult> {
    return this.#run(async (c) => {
      const s = operation.providerScope,
        canonical = JSON.stringify(operation);
      const found = await c.query(
        `SELECT * FROM ${q(this.#config.schemas.external, 'idempotent_sms_receipts')} WHERE tenant_id=$1 AND provider=$2 AND provider_account_id=$3 AND provider_operation_key=$4`,
        [s.tenantId, s.provider, s.providerAccountId, operation.providerOperationKey],
      );
      let providerMessageId: string;
      if (found.rows.length) {
        const r = found.rows[0]!;
        if (r.operation_digest !== operationDigest || r.canonical_operation !== canonical)
          throw new StarterError('IdentityConflict');
        providerMessageId = String(r.provider_message_id);
      } else {
        await this.#capacity(c, 'idempotent_count');
        providerMessageId = randomUUID();
        await c.query(
          `INSERT INTO ${q(this.#config.schemas.external, 'idempotent_sms_receipts')} VALUES($1,$2,$3,$4,$5,$6,$7,clock_timestamp())`,
          [
            s.tenantId,
            s.provider,
            s.providerAccountId,
            operation.providerOperationKey,
            operationDigest,
            canonical,
            providerMessageId,
          ],
        );
        await this.#increment(c, 'idempotent_count');
      }
      return Object.freeze({
        schemaVersion: 1,
        attemptId,
        requestDigest,
        status: 'accepted_by_provider',
        providerMessageId,
      });
    });
  }
  ordinarySend(request: SendRequest): Promise<CarrierResult> {
    return this.#run(async (c) => {
      await this.#capacity(c, 'ordinary_count');
      const providerMessageId = randomUUID(),
        s = request.providerScope,
        canonical = JSON.stringify(request),
        requestDigest = digest(canonical);
      // Every invocation appends a NEW physical call, including equal attempt/key replay.
      await c.query(
        `INSERT INTO ${q(this.#config.schemas.external, 'ordinary_sms_attempts')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,clock_timestamp())`,
        [
          randomUUID(),
          s.tenantId,
          s.provider,
          s.providerAccountId,
          request.providerOperationKey,
          request.attemptId,
          requestDigest,
          canonical,
          providerMessageId,
        ],
      );
      await this.#increment(c, 'ordinary_count');
      return Object.freeze({
        schemaVersion: 1,
        attemptId: request.attemptId,
        requestDigest,
        status: 'accepted_by_provider',
        providerMessageId,
      });
    });
  }
  #capacity(
    c: Connection,
    field: 'investigation_count' | 'idempotent_count' | 'ordinary_count',
  ): Promise<void> {
    return c
      .query(
        `SELECT ${field} AS count FROM ${q(this.#config.schemas.external, 'receipt_metadata')} WHERE singleton`,
      )
      .then((r) => {
        if (r.rows[0]?.count >= 16) throw new StarterError('Overloaded');
      });
  }
  async #increment(
    c: Connection,
    field: 'investigation_count' | 'idempotent_count' | 'ordinary_count',
  ): Promise<void> {
    await c.query(
      `UPDATE ${q(this.#config.schemas.external, 'receipt_metadata')} SET ${field}=${field}+1 WHERE singleton`,
    );
  }
  close(): Promise<void> {
    this.#closing = true;
    this.#drain ??= Promise.allSettled([...this.#calls]).then(async () => {
      await this.#pool.end();
    });
    void this.#drain.catch(() => undefined);
    return this.#closeObservation.observe(async () => {
      await this.#drain;
    });
  }
}
