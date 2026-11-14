/** Local PostgreSQL connection policy and finite, payload-free failures. */
import { createHash } from 'node:crypto';
import pg from 'pg';
import type { PoolClient, PoolConfig, Client } from 'pg';
import { ChannelError } from './public-types.js';
import type { DatabaseSettings, ChannelLimits } from './public-types.js';
export { ChannelError, DEFAULT_LIMITS } from './public-types.js';
export type { DatabaseSettings, ChannelLimits, ChannelErrorCode } from './public-types.js';
export const MARKER = 'p2-channel-schema-v1';
export function identifier(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length > 128 ||
    !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}(?![\s\S])/.test(value)
  )
    throw new ChannelError('AccessDenied');
  return value;
}
export function settings(input: DatabaseSettings, role: string): DatabaseSettings {
  if (
    !input ||
    typeof input !== 'object' ||
    !['127.0.0.1', 'localhost'].includes(input.host) ||
    !Number.isSafeInteger(input.port) ||
    input.port < 1 ||
    input.port > 65535 ||
    input.database !== 'livekit_lab' ||
    input.user !== role ||
    typeof input.password !== 'string' ||
    input.password.length < 32 ||
    input.password.length > 128 ||
    typeof input.schema !== 'string' ||
    !/^[a-z][a-z0-9_]{0,62}(?![\s\S])/.test(input.schema)
  )
    throw new ChannelError('AccessDenied');
  return Object.freeze({
    host: input.host,
    port: input.port,
    database: input.database,
    user: input.user,
    password: input.password,
    schema: input.schema,
  });
}
export function limits(value: ChannelLimits): ChannelLimits {
  if (
    !value ||
    Object.keys(value).sort().join(',') !== 'maxAssociations,maxChallenges,maxInbox,maxSenders' ||
    Object.values(value).some((v) => !Number.isSafeInteger(v) || v < 1 || v > 10000)
  )
    throw new ChannelError('SchemaMismatch');
  return Object.freeze({
    maxInbox: value.maxInbox,
    maxChallenges: value.maxChallenges,
    maxAssociations: value.maxAssociations,
    maxSenders: value.maxSenders,
  });
}
export function config(value: DatabaseSettings): PoolConfig {
  return {
    host: value.host,
    port: value.port,
    database: value.database,
    user: value.user,
    password: value.password,
    ssl: false,
    application_name: 'channel-continuity',
    connectionTimeoutMillis: 1500,
    query_timeout: 5000,
    max: 2,
    idleTimeoutMillis: 1000,
    allowExitOnIdle: true,
    options:
      '-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500 -c idle_in_transaction_session_timeout=5000',
  };
}
export function table(schema: string, name: string): string {
  return `"${schema}"."${name}"`;
}
export type Connection = Pick<PoolClient, 'query'> | Pick<Client, 'query'>;
export function digest(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}
export const PgClient = pg.Client;
export const PgPool = pg.Pool;
/**
 * pg emits 'error' on a client whose connection drops, even mid-query, and
 * pg-pool removes its idle listener while a client is checked out. Without a
 * listener that event would crash the process; the failed query still rejects.
 */
function tolerateDisconnect(client: pg.ClientBase): void {
  client.on('error', () => undefined);
}
export function watchPool(pool: pg.Pool): pg.Pool {
  pool.on('connect', tolerateDisconnect);
  return pool;
}
export function watchClient(client: pg.Client): pg.Client {
  tolerateDisconnect(client);
  return client;
}

/** One catalog read, including column-level grants and every relation/function. */
export async function catalog(client: Connection, schema: string): Promise<unknown> {
  const result = await client.query(
    `SELECT jsonb_build_object(
    'owner',pg_get_userbyid(n.nspowner),'acl',n.nspacl::text,
    'relations',COALESCE((SELECT jsonb_agg(jsonb_build_object('name',c.relname,'kind',c.relkind,'owner',pg_get_userbyid(c.relowner),'acl',c.relacl::text,'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity,
      'triggers',COALESCE((SELECT jsonb_agg(pg_get_triggerdef(t.oid) ORDER BY t.tgname) FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal),'[]'::jsonb),
      'rules',COALESCE((SELECT jsonb_agg(pg_get_ruledef(w.oid) ORDER BY w.rulename) FROM pg_rewrite w WHERE w.ev_class=c.oid),'[]'::jsonb),
      'columns',COALESCE((SELECT jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid),a.attacl::text,cn.nspname,co.collname,co.collprovider,co.collisdeterministic) ORDER BY a.attnum) FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum LEFT JOIN pg_collation co ON co.oid=a.attcollation LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),'[]'::jsonb),
      'constraints',COALESCE((SELECT jsonb_agg(jsonb_build_array(k.conname,pg_get_constraintdef(k.oid)) ORDER BY k.conname) FROM pg_constraint k WHERE k.conrelid=c.oid),'[]'::jsonb),
      'indexes',COALESCE((SELECT jsonb_agg(pg_get_indexdef(i.indexrelid) ORDER BY i.indexrelid::regclass::text) FROM pg_index i WHERE i.indrelid=c.oid),'[]'::jsonb)) ORDER BY c.relname) FROM pg_class c WHERE c.relnamespace=n.oid),'[]'::jsonb),
    'functions',COALESCE((SELECT jsonb_agg(jsonb_build_array(p.proname,p.prokind,p.prosecdef,p.proacl::text) ORDER BY p.proname,p.oid) FROM pg_proc p WHERE p.pronamespace=n.oid),'[]'::jsonb)) AS snapshot
    FROM pg_namespace n WHERE n.nspname=$1`,
    [schema],
  );
  if (result.rows.length !== 1) throw new ChannelError('SchemaMismatch');
  return result.rows[0].snapshot as unknown;
}
export async function validate(
  client: Connection,
  value: DatabaseSettings,
  definition: string,
  owner = false,
  dispatchDefinition?: string,
  outboxDefinition?: string,
  callbackDefinition?: string,
  sendPolicyDefinition?: string,
  nativeDefinition?: string,
  communicationDefinition?: string,
  resultReceiverDefinition?: string,
  indexDefinition?: string,
): Promise<ChannelLimits> {
  const role =
    await client.query(`SELECT current_user AS name,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,
    EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) AS member,
    has_database_privilege(current_user,current_database(),'CREATE') AS can_create,
    has_database_privilege(current_user,current_database(),'TEMPORARY') AS can_temp,
    EXISTS(SELECT 1 FROM pg_namespace z WHERE z.nspname !~ '^pg_' AND z.nspname<>'information_schema' AND (z.nspowner=r.oid OR has_schema_privilege(current_user,z.oid,'CREATE'))) AS schema_admin,
    EXISTS(SELECT 1 FROM pg_class z WHERE z.relowner=r.oid) AS object_owner
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
    (!owner && (who.can_create || who.can_temp || who.schema_admin || who.object_owner))
  )
    throw new ChannelError('SchemaMismatch');
  // Never select metadata rows until catalog-only checks prove a plain safe table.
  const preflight = await client.query(
    `SELECT c.relkind,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) AS owner,
    pg_get_userbyid(n.nspowner) AS schema_owner,
    EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal) AS user_triggers,
    EXISTS(SELECT 1 FROM pg_rewrite w WHERE w.ev_class=c.oid) AS rules,
    EXISTS(SELECT 1 FROM aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a WHERE a.grantee NOT IN(c.relowner,(SELECT oid FROM pg_roles WHERE rolname='livekit_lab')) OR (a.grantee=(SELECT oid FROM pg_roles WHERE rolname='livekit_lab') AND (a.privilege_type<>'SELECT' OR a.is_grantable))) AS unsafe_acl,
    EXISTS(SELECT 1 FROM pg_index i WHERE i.indrelid=c.oid AND (i.indexprs IS NOT NULL OR i.indpred IS NOT NULL OR EXISTS(SELECT 1 FROM unnest(i.indclass) op JOIN pg_opclass oc ON oc.oid=op WHERE oc.opcnamespace<>'pg_catalog'::regnamespace))) AS unsafe_index,
    EXISTS(SELECT 1 FROM pg_constraint k JOIN pg_depend d ON d.classid='pg_constraint'::regclass AND d.objid=k.oid AND d.refclassid='pg_proc'::regclass JOIN pg_proc p ON p.oid=d.refobjid WHERE k.conrelid=c.oid AND p.pronamespace<>'pg_catalog'::regnamespace) AS unsafe_constraint,
    (SELECT jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid),a.attacl::text) ORDER BY a.attnum) FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped) AS columns
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=$1 AND c.relname='schema_metadata'`,
    [value.schema],
  );
  const shape = preflight.rows[0];
  const expected = [
    ['singleton', 'boolean'],
    ['version', 'smallint'],
    ['runtime_role', 'text'],
    ['definition_digest', 'text'],
    ['catalog_snapshot', 'jsonb'],
    ['max_inbox', 'integer'],
    ['max_challenges', 'integer'],
    ['max_associations', 'integer'],
    ['max_senders', 'integer'],
  ].map(([name, type]) => [name, type, true, '', '', null, null]);
  if (
    preflight.rowCount !== 1 ||
    !shape ||
    shape.relkind !== 'r' ||
    shape.owner !== 'continuity_migrator' ||
    shape.schema_owner !== 'continuity_migrator' ||
    shape.relrowsecurity ||
    shape.relforcerowsecurity ||
    shape.user_triggers ||
    shape.rules ||
    shape.unsafe_acl ||
    shape.unsafe_index ||
    shape.unsafe_constraint ||
    JSON.stringify(shape.columns) !== JSON.stringify(expected)
  )
    throw new ChannelError('SchemaMismatch');
  const current = await catalog(client, value.schema);
  const meta = await client.query(
    `SELECT m.singleton,m.version,m.runtime_role,m.definition_digest,m.catalog_snapshot,m.max_inbox,m.max_challenges,m.max_associations,m.max_senders,obj_description(n.oid,'pg_namespace') AS marker FROM ${table(value.schema, 'schema_metadata')} m JOIN pg_namespace n ON n.nspname=$1 WHERE singleton`,
    [value.schema],
  );
  const row = meta.rows[0];
  if (
    meta.rows.length !== 1 ||
    ![1, 2, 3, 4, 5, 6, 7, 8, 9].includes(row.version) ||
    row.runtime_role !== 'livekit_lab' ||
    row.definition_digest !==
      [
        definition,
        dispatchDefinition,
        outboxDefinition,
        callbackDefinition,
        sendPolicyDefinition,
        nativeDefinition,
        communicationDefinition,
        resultReceiverDefinition,
        indexDefinition,
      ][row.version - 1] ||
    row.marker !== (row.version === 1 ? MARKER : 'p2-channel-schema-v' + row.version)
  )
    throw new ChannelError('SchemaMismatch');
  if (JSON.stringify(current) !== JSON.stringify(row.catalog_snapshot))
    throw new ChannelError('SchemaMismatch');
  return limits({
    maxInbox: row.max_inbox,
    maxChallenges: row.max_challenges,
    maxAssociations: row.max_associations,
    maxSenders: row.max_senders,
  });
}
