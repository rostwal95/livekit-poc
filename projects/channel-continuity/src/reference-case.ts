/** Explicit standalone-only case authority. Integrated mode uses P1 instead of this store. */
import type { Pool, PoolClient } from 'pg';
import { PgClient, PgPool, catalog, config, digest, settings, table } from './database.js';
import type { DatabaseSettings } from './public-types.js';
import {
  RoutingError,
  allowedReferences,
  caseRevision,
  reference,
  sameReference,
  snapshot,
  checkedSignal,
  isAborted,
  type CaseAuthorityPort,
  type CaseReference,
  type CaseRevision,
  type CaseSnapshot,
} from './routing-types.js';
export { RoutingError } from './routing-types.js';
export type {
  CaseReference,
  CaseRevision,
  CaseSnapshot,
  InvestigationRequest,
} from './routing-types.js';
export type { DatabaseSettings } from './public-types.js';
const MARKER = 'p2-reference-case-v1';
const SPEC = `CREATE TABLE case_metadata(singleton boolean PRIMARY KEY CHECK(singleton),version smallint NOT NULL CHECK(version=1),definition_digest text NOT NULL,catalog_snapshot jsonb NOT NULL,maximum_cases integer NOT NULL CHECK(maximum_cases BETWEEN 1 AND 64));
CREATE TABLE cases(tenant_id text NOT NULL,account_id text NOT NULL,case_id text NOT NULL,revision bigint NOT NULL CHECK(revision>=0),request_json text NOT NULL,cancelled boolean NOT NULL,committed boolean NOT NULL,PRIMARY KEY(tenant_id,account_id,case_id));`;
const DEFINITION = digest(SPEC);
function configuration(input: DatabaseSettings, role: string): DatabaseSettings {
  const result = settings(input, role);
  if (!/^p2_case_[a-z0-9_]{1,55}(?![\s\S])/.test(result.schema))
    throw new RoutingError('InvalidCommand');
  return result;
}
async function validate(
  client: Pick<PoolClient, 'query'>,
  database: DatabaseSettings,
  owner = false,
): Promise<void> {
  const role =
    await client.query(`SELECT current_user AS name,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,
    EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) AS member,
    has_database_privilege(current_user,current_database(),'CREATE') AS can_create,
    has_database_privilege(current_user,current_database(),'TEMPORARY') AS can_temp,
    EXISTS(SELECT 1 FROM pg_namespace z WHERE z.nspname !~ '^pg_' AND z.nspname<>'information_schema' AND (z.nspowner=r.oid OR has_schema_privilege(current_user,z.oid,'CREATE'))) AS schema_admin
    FROM pg_roles r WHERE rolname=current_user`);
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
    throw new RoutingError('Unavailable');
  const actual = await catalog(client, database.schema);
  const shape = actual as {
    owner?: unknown;
    relations?: {
      name?: unknown;
      kind?: unknown;
      owner?: unknown;
      triggers?: unknown[];
      rules?: unknown[];
      columns?: unknown[][];
    }[];
    functions?: unknown[];
  };
  const expected = ['case_metadata', 'case_metadata_pkey', 'cases', 'cases_pkey'];
  if (
    shape.owner !== 'continuity_migrator' ||
    !Array.isArray(shape.relations) ||
    shape.relations.length !== expected.length ||
    !Array.isArray(shape.functions) ||
    shape.functions.length ||
    shape.relations.some(
      (r) =>
        !expected.includes(String(r.name)) ||
        r.owner !== 'continuity_migrator' ||
        (r.kind !== 'r' && r.kind !== 'i') ||
        !Array.isArray(r.triggers) ||
        r.triggers.length ||
        !Array.isArray(r.rules) ||
        r.rules.length,
    )
  )
    throw new RoutingError('Unavailable');
  const metadata = shape.relations.find((r) => r.name === 'case_metadata');
  if (
    metadata?.kind !== 'r' ||
    JSON.stringify(metadata.columns?.map((c) => c.slice(0, 7))) !==
      JSON.stringify([
        ['singleton', 'boolean', true, '', '', null, null],
        ['version', 'smallint', true, '', '', null, null],
        ['definition_digest', 'text', true, '', '', null, null],
        ['catalog_snapshot', 'jsonb', true, '', '', null, null],
        ['maximum_cases', 'integer', true, '', '', null, null],
      ])
  )
    throw new RoutingError('Unavailable');
  const result = await client.query(
    `SELECT m.*,obj_description(n.oid,'pg_namespace') AS marker FROM ${table(database.schema, 'case_metadata')} m JOIN pg_namespace n ON n.nspname=$1`,
    [database.schema],
  );
  const meta = result.rows[0];
  if (
    result.rows.length !== 1 ||
    meta.version !== 1 ||
    meta.singleton !== true ||
    meta.marker !== MARKER ||
    meta.definition_digest !== DEFINITION ||
    !Number.isInteger(meta.maximum_cases) ||
    meta.maximum_cases < 1 ||
    meta.maximum_cases > 64 ||
    JSON.stringify(meta.catalog_snapshot) !== JSON.stringify(actual)
  )
    throw new RoutingError('Unavailable');
  const rows = await client.query(
    `SELECT count(*)::integer AS count FROM ${table(database.schema, 'cases')}`,
  );
  if (rows.rows[0].count < 1 || rows.rows[0].count > meta.maximum_cases)
    throw new RoutingError('Unavailable');
}
export async function installReferenceCaseSchema(
  input: DatabaseSettings,
  seeds: readonly CaseSnapshot[],
): Promise<void> {
  const database = configuration(input, 'continuity_migrator');
  if (!Array.isArray(seeds) || seeds.length < 1 || seeds.length > 64)
    throw new RoutingError('InvalidCommand');
  const checked = seeds.map((seed) =>
    snapshot(seed, reference({ scope: seed.scope, caseId: seed.caseId })),
  );
  const refs = allowedReferences(
    checked.map((seed) => ({ scope: seed.scope, caseId: seed.caseId })),
  );
  const client = new PgClient(config(database));
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'p2-reference-schema:' + database.schema,
    ]);
    const exists = await client.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [
      database.schema,
    ]);
    if (exists.rows.length) {
      await validate(client, database, true);
      const rows = await client.query(
        `SELECT tenant_id,account_id,case_id FROM ${table(database.schema, 'cases')}`,
      );
      if (
        rows.rows.length !== refs.length ||
        rows.rows.some(
          (row) =>
            !refs.some(
              (ref) =>
                ref.scope.tenantId === row.tenant_id &&
                ref.scope.accountId === row.account_id &&
                ref.caseId === row.case_id,
            ),
        )
      )
        throw new RoutingError('InvalidCommand');
    } else {
      const who = await client.query('SELECT current_user AS name');
      if (who.rows[0]?.name !== 'continuity_migrator') throw new RoutingError('AccessDenied');
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
        `REVOKE ALL ON ${table(database.schema, 'case_metadata')},${table(database.schema, 'cases')} FROM PUBLIC,livekit_lab;GRANT SELECT ON ${table(database.schema, 'case_metadata')},${table(database.schema, 'cases')} TO livekit_lab;GRANT UPDATE(revision,request_json) ON ${table(database.schema, 'cases')} TO livekit_lab`,
      );
      for (const seed of checked)
        await client.query(
          `INSERT INTO ${table(database.schema, 'cases')} VALUES($1,$2,$3,$4,$5,$6,$7)`,
          [
            seed.scope.tenantId,
            seed.scope.accountId,
            seed.caseId,
            seed.revision,
            JSON.stringify(seed.request),
            seed.cancelled,
            seed.committed,
          ],
        );
      const shape = await catalog(client, database.schema);
      await client.query(
        `INSERT INTO ${table(database.schema, 'case_metadata')} VALUES(true,1,$1,$2::jsonb,$3)`,
        [DEFINITION, JSON.stringify(shape), checked.length],
      );
      await validate(client, database, true);
    }
    await client.query('COMMIT');
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch {
      /* Still close actual connection below. */
    }
    throw error instanceof RoutingError ? error : new RoutingError('Unavailable');
  } finally {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        client.end(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new RoutingError('CleanupIncomplete')), 2000);
        }),
      ]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
export class ReferenceCaseAuthority implements CaseAuthorityPort {
  readonly #database: DatabaseSettings;
  readonly #allowed: readonly CaseReference[];
  readonly #pool: Pool;
  readonly #calls = new Set<Promise<unknown>>();
  #closing = false;
  #ending: Promise<void> | undefined;
  #counts = { started: 0, revised: 0, unchanged: 0, conflicts: 0, unknown: 0, failed: 0 };
  constructor(input: DatabaseSettings, allowedCases: readonly CaseReference[]) {
    this.#database = configuration(input, 'livekit_lab');
    this.#allowed = allowedReferences(allowedCases);
    this.#pool = new PgPool(config(this.#database));
    this.#pool.on('error', () => {
      this.#counts.failed++;
    });
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({ ...this.#counts, active: this.#calls.size });
  }
  inspect(input: CaseReference, signal: AbortSignal): Promise<CaseSnapshot> {
    const ref = reference(input);
    return this.#run(ref, signal);
  }
  revise(input: CaseRevision, signal: AbortSignal): Promise<CaseSnapshot> {
    const proposed = caseRevision(input);
    return this.#run(
      reference({ scope: proposed.scope, caseId: proposed.caseId }),
      signal,
      proposed,
    );
  }
  #run(ref: CaseReference, signal: AbortSignal, proposed?: CaseRevision): Promise<CaseSnapshot> {
    checkedSignal(signal);
    if (this.#closing) return Promise.reject(new RoutingError('Closed'));
    if (!this.#allowed.some((item) => sameReference(item, ref)))
      return Promise.reject(new RoutingError('AccessDenied'));
    if (this.#calls.size >= 2) return Promise.reject(new RoutingError('Overloaded'));
    if (isAborted(signal)) return Promise.reject(new RoutingError('Unavailable'));
    this.#counts.started++;
    const work = Promise.resolve().then(async () => {
      let client: PoolClient | undefined,
        committing = false,
        began = false,
        discard = false;
      try {
        client = await this.#pool.connect();
        await validate(client, this.#database);
        if (isAborted(signal)) throw new RoutingError('Unavailable');
        await client.query('BEGIN');
        began = true;
        const rows = await client.query(
          `SELECT * FROM ${table(this.#database.schema, 'cases')} WHERE tenant_id=$1 AND account_id=$2 AND case_id=$3${proposed ? ' FOR UPDATE' : ''}`,
          [ref.scope.tenantId, ref.scope.accountId, ref.caseId],
        );
        if (rows.rows.length !== 1) throw new RoutingError('AccessDenied');
        const row = rows.rows[0];
        let current = snapshot(
          {
            ...ref,
            revision: row.revision,
            request: JSON.parse(String(row.request_json)) as unknown,
            cancelled: row.cancelled,
            committed: row.committed,
          },
          ref,
        );
        if (isAborted(signal)) throw new RoutingError('Unavailable');
        if (proposed) {
          if (
            current.revision !== proposed.expectedRevision ||
            current.cancelled ||
            current.committed
          ) {
            this.#counts.conflicts++;
            throw new RoutingError('RevisionConflict');
          }
          if (JSON.stringify(current.request) !== JSON.stringify(proposed.request)) {
            if (BigInt(current.revision) === 9223372036854775807n)
              throw new RoutingError('Overloaded');
            await client.query(
              `UPDATE ${table(this.#database.schema, 'cases')} SET revision=revision+1,request_json=$4 WHERE tenant_id=$1 AND account_id=$2 AND case_id=$3`,
              [
                ref.scope.tenantId,
                ref.scope.accountId,
                ref.caseId,
                JSON.stringify(proposed.request),
              ],
            );
            current = Object.freeze({
              ...current,
              revision: String(BigInt(current.revision) + 1n),
              request: proposed.request,
            });
          }
          if (isAborted(signal)) throw new RoutingError('Unavailable');
        }
        committing = Boolean(proposed);
        await client.query('COMMIT');
        began = false;
        committing = false;
        if (isAborted(signal)) throw new RoutingError(proposed ? 'OutcomeUnknown' : 'Unavailable');
        if (proposed)
          this.#counts[current.revision === proposed.expectedRevision ? 'unchanged' : 'revised']++;
        return current;
      } catch (error) {
        if (began && client)
          try {
            await client.query('ROLLBACK');
          } catch {
            discard = true;
          }
        if (committing) {
          this.#counts.unknown++;
          throw new RoutingError('OutcomeUnknown');
        }
        if (error instanceof RoutingError && error.code === 'OutcomeUnknown')
          this.#counts.unknown++;
        else this.#counts.failed++;
        throw error instanceof RoutingError ? error : new RoutingError('Unavailable');
      } finally {
        client?.release(discard || committing);
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
          timer = setTimeout(() => reject(new RoutingError('CleanupIncomplete')), 2000);
        }),
      ]);
      if (this.#calls.size || this.#pool.totalCount) throw new RoutingError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
