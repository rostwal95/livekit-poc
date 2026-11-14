/** Explicit owner-only v1 installation; runtime never executes DDL or repairs drift. */
import {
  DEFAULT_LIMITS,
  MARKER,
  PgClient,
  watchClient,
  catalog,
  config,
  digest,
  limits as checkLimits,
  settings,
  table,
  validate,
} from './database.js';
import { ChannelError } from './public-types.js';
import type { ChannelLimits, DatabaseSettings } from './public-types.js';
export type { ChannelLimits, DatabaseSettings } from './public-types.js';
const SPEC = `
CREATE TABLE schema_metadata(singleton boolean PRIMARY KEY CHECK(singleton),version smallint NOT NULL CHECK(version=1),runtime_role text NOT NULL,definition_digest text NOT NULL,catalog_snapshot jsonb NOT NULL,max_inbox integer NOT NULL CHECK(max_inbox BETWEEN 1 AND 10000),max_challenges integer NOT NULL CHECK(max_challenges BETWEEN 1 AND 10000),max_associations integer NOT NULL CHECK(max_associations BETWEEN 1 AND 10000),max_senders integer NOT NULL CHECK(max_senders BETWEEN 1 AND 10000));
CREATE TABLE admission(singleton boolean PRIMARY KEY CHECK(singleton),inbox_count integer NOT NULL DEFAULT 0 CHECK(inbox_count>=0),challenge_count integer NOT NULL DEFAULT 0 CHECK(challenge_count>=0),association_count integer NOT NULL DEFAULT 0 CHECK(association_count>=0),sender_count integer NOT NULL DEFAULT 0 CHECK(sender_count>=0));
CREATE TABLE sender_heads(tenant_id text NOT NULL,provider text NOT NULL,provider_account_id text NOT NULL,sender_id text NOT NULL,epoch bigint NOT NULL DEFAULT 0 CHECK(epoch>=0),active_epoch bigint CHECK(active_epoch>0 AND active_epoch<=epoch),PRIMARY KEY(tenant_id,provider,provider_account_id,sender_id));
CREATE TABLE associations(tenant_id text NOT NULL,provider text NOT NULL,provider_account_id text NOT NULL,sender_id text NOT NULL,epoch bigint NOT NULL CHECK(epoch>0),account_id text NOT NULL,conversation_id text NOT NULL,case_id text,activated_at timestamptz NOT NULL,revoked_at timestamptz,PRIMARY KEY(tenant_id,provider,provider_account_id,sender_id,epoch),FOREIGN KEY(tenant_id,provider,provider_account_id,sender_id) REFERENCES sender_heads(tenant_id,provider,provider_account_id,sender_id));
CREATE UNIQUE INDEX associations_active ON associations(tenant_id,provider,provider_account_id,sender_id) WHERE revoked_at IS NULL;
CREATE TABLE challenges(challenge_id uuid PRIMARY KEY,secret_digest text NOT NULL,tenant_id text NOT NULL,provider text NOT NULL,provider_account_id text NOT NULL,sender_id text NOT NULL,account_id text NOT NULL,conversation_id text NOT NULL,case_id text,expected_epoch bigint NOT NULL CHECK(expected_epoch>=0),issued_at timestamptz NOT NULL,expires_at timestamptz NOT NULL CHECK(expires_at>issued_at),attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),consumed_at timestamptz,FOREIGN KEY(tenant_id,provider,provider_account_id,sender_id) REFERENCES sender_heads(tenant_id,provider,provider_account_id,sender_id));
CREATE TABLE conversations(tenant_id text NOT NULL,account_id text NOT NULL,conversation_id text NOT NULL,last_sequence bigint NOT NULL DEFAULT 0 CHECK(last_sequence>=0),PRIMARY KEY(tenant_id,account_id,conversation_id));
CREATE TABLE inbox(receipt_id uuid PRIMARY KEY,tenant_id text NOT NULL,provider text NOT NULL,provider_account_id text NOT NULL,event_id text NOT NULL,message_id text NOT NULL,account_id text NOT NULL,conversation_id text NOT NULL,association_epoch bigint NOT NULL,canonical_payload text NOT NULL,wire_json text NOT NULL,acceptance_sequence bigint NOT NULL CHECK(acceptance_sequence>0),accepted_at timestamptz NOT NULL,UNIQUE(tenant_id,provider,provider_account_id,event_id),UNIQUE(tenant_id,account_id,conversation_id,acceptance_sequence),FOREIGN KEY(tenant_id,account_id,conversation_id) REFERENCES conversations(tenant_id,account_id,conversation_id));
CREATE TABLE processing_intents(receipt_id uuid PRIMARY KEY REFERENCES inbox(receipt_id),operation_key uuid NOT NULL UNIQUE,state text NOT NULL CHECK(state='pending'));
`;
export const DEFINITION_DIGEST = digest(SPEC);
export async function installChannelSchema(
  input: DatabaseSettings,
  proposed: ChannelLimits = DEFAULT_LIMITS,
): Promise<void> {
  const value = settings(input, 'continuity_migrator');
  const bound = checkLimits(proposed);
  const client = watchClient(new PgClient(config(value)));
  let primary: ChannelError | undefined;
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'channel-schema:' + value.schema,
    ]);
    const existing = await client.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [
      value.schema,
    ]);
    if (existing.rows.length) {
      const actual = await validate(
        client,
        value,
        DEFINITION_DIGEST,
        true,
        DISPATCH_DEFINITION_DIGEST,
        OUTBOX_DEFINITION_DIGEST,
        CALLBACK_DEFINITION_DIGEST,
        SEND_POLICY_DEFINITION_DIGEST,
        NATIVE_DEFINITION_DIGEST,
        COMMUNICATION_DEFINITION_DIGEST,
        RESULT_RECEIVER_DEFINITION_DIGEST,
        INDEX_DEFINITION_DIGEST,
      );
      if (JSON.stringify(actual) !== JSON.stringify(bound))
        throw new ChannelError('SchemaMismatch');
    } else {
      const who = await client.query('SELECT current_user AS name');
      if (who.rows[0]?.name !== 'continuity_migrator') throw new ChannelError('AccessDenied');
      await client.query(`CREATE SCHEMA "${value.schema}" AUTHORIZATION continuity_migrator`);
      await client.query(
        `REVOKE ALL ON SCHEMA "${value.schema}" FROM PUBLIC; GRANT USAGE ON SCHEMA "${value.schema}" TO livekit_lab; COMMENT ON SCHEMA "${value.schema}" IS '${MARKER}'`,
      );
      // Fixed DDL identifiers are qualified before execution; no untrusted values enter SQL.
      const ddl = SPEC.replace(
        /(CREATE TABLE |REFERENCES | ON )([a-z_]+)/g,
        (_all, prefix: string, name: string) => prefix + table(value.schema, name),
      );
      await client.query(ddl);
      await client.query(`INSERT INTO ${table(value.schema, 'admission')}(singleton) VALUES(true)`);
      await client.query(
        `INSERT INTO ${table(value.schema, 'schema_metadata')} VALUES(true,1,'livekit_lab',$1,'{}'::jsonb,$2,$3,$4,$5)`,
        [
          DEFINITION_DIGEST,
          bound.maxInbox,
          bound.maxChallenges,
          bound.maxAssociations,
          bound.maxSenders,
        ],
      );
      for (const name of [
        'schema_metadata',
        'admission',
        'sender_heads',
        'associations',
        'challenges',
        'conversations',
        'inbox',
        'processing_intents',
      ]) {
        await client.query(
          `REVOKE ALL ON ${table(value.schema, name)} FROM PUBLIC,livekit_lab; GRANT SELECT ON ${table(value.schema, name)} TO livekit_lab`,
        );
      }
      for (const name of [
        'sender_heads',
        'associations',
        'challenges',
        'conversations',
        'inbox',
        'processing_intents',
      ])
        await client.query(`GRANT INSERT ON ${table(value.schema, name)} TO livekit_lab`);
      for (const [name, columns] of [
        ['admission', 'inbox_count,challenge_count,association_count,sender_count'],
        ['sender_heads', 'epoch,active_epoch'],
        ['associations', 'revoked_at'],
        ['challenges', 'attempts,consumed_at'],
        ['conversations', 'last_sequence'],
      ])
        await client.query(
          `GRANT UPDATE(${columns}) ON ${table(value.schema, name!)} TO livekit_lab`,
        );
      const snapshot = await catalog(client, value.schema);
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET catalog_snapshot=$1::jsonb`,
        [JSON.stringify(snapshot)],
      );
      await validate(
        client,
        value,
        DEFINITION_DIGEST,
        true,
        DISPATCH_DEFINITION_DIGEST,
        OUTBOX_DEFINITION_DIGEST,
        CALLBACK_DEFINITION_DIGEST,
        SEND_POLICY_DEFINITION_DIGEST,
        NATIVE_DEFINITION_DIGEST,
        COMMUNICATION_DEFINITION_DIGEST,
        RESULT_RECEIVER_DEFINITION_DIGEST,
        INDEX_DEFINITION_DIGEST,
      );
    }
    await client.query('COMMIT');
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch {
      /* Connection is discarded below. */
    }
    primary = error instanceof ChannelError ? error : new ChannelError('SchemaMismatch');
    throw primary;
  } finally {
    await closeMigrationClient(client, primary);
  }
}

/** Owner jobs must observe bounded cleanup, including when installation failed. */
export async function closeMigrationClient(
  client: { end(): Promise<void> },
  primary?: ChannelError,
): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      client.end(),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new ChannelError('CleanupIncomplete')), 1500);
      }),
    ]);
  } catch {
    if (primary) primary.cause = new ChannelError('CleanupIncomplete');
    else throw new ChannelError('CleanupIncomplete');
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export type DispatchLimits = Readonly<{
  maxActive: number;
  maxAttempts: number;
  leaseMs: number;
  retryDelayMs: number;
}>;
export const DEFAULT_DISPATCH_LIMITS: DispatchLimits = Object.freeze({
  maxActive: 2,
  maxAttempts: 3,
  leaseMs: 5000,
  retryDelayMs: 250,
});
const DISPATCH_SPEC = `
ALTER TABLE processing_intents DROP CONSTRAINT processing_intents_state_check;
ALTER TABLE processing_intents ADD CONSTRAINT processing_intents_state_check CHECK(state IN('pending','running','dispatched','blocked','exhausted','uncertain'));
ALTER TABLE processing_intents ADD COLUMN claim_epoch bigint NOT NULL DEFAULT 0 CHECK(claim_epoch>=0),ADD COLUMN claim_owner uuid,ADD COLUMN claim_until timestamptz,ADD COLUMN claim_kind text CHECK(claim_kind IN('dispatch','reconcile')),ADD COLUMN attempt_count smallint NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 5),ADD COLUMN next_attempt_at timestamptz,ADD COLUMN possible_external boolean NOT NULL DEFAULT false,ADD COLUMN external_receipt_id uuid,ADD COLUMN last_code text NOT NULL DEFAULT 'none' CHECK(last_code IN('none','association_required','adapter_invalid','adapter_unavailable','operation_conflict','claim_lost','accepted','lookup_absent'));
ALTER TABLE processing_intents ADD CONSTRAINT processing_claim_shape CHECK((claim_owner IS NULL)=(claim_until IS NULL) AND (claim_owner IS NULL)=(claim_kind IS NULL)),ADD CONSTRAINT processing_possible_state CHECK(NOT possible_external OR state IN('uncertain','dispatched')),ADD CONSTRAINT processing_dispatched_receipt CHECK((state='dispatched')=(external_receipt_id IS NOT NULL)),ADD CONSTRAINT processing_identity_pair UNIQUE(receipt_id,operation_key);
CREATE INDEX dispatch_active ON processing_intents(claim_until) WHERE claim_owner IS NOT NULL;
CREATE TABLE dispatch_settings(singleton boolean PRIMARY KEY CHECK(singleton),max_active smallint NOT NULL CHECK(max_active BETWEEN 1 AND 4),max_attempts smallint NOT NULL CHECK(max_attempts BETWEEN 1 AND 5),lease_ms integer NOT NULL CHECK(lease_ms BETWEEN 500 AND 30000),retry_delay_ms integer NOT NULL CHECK(retry_delay_ms BETWEEN 20 AND 5000));
CREATE TABLE dispatch_plans(receipt_id uuid PRIMARY KEY,operation_key uuid NOT NULL UNIQUE,payload_json text NOT NULL CHECK(octet_length(payload_json)<=32768),payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),prepared_at timestamptz NOT NULL,association_epoch bigint NOT NULL CHECK(association_epoch>0),FOREIGN KEY(receipt_id,operation_key) REFERENCES processing_intents(receipt_id,operation_key));
CREATE TABLE dispatch_attempts(receipt_id uuid NOT NULL REFERENCES processing_intents(receipt_id),epoch bigint NOT NULL CHECK(epoch>0),owner_id uuid NOT NULL,started_at timestamptz NOT NULL,finished_at timestamptz,disposition text NOT NULL CHECK(disposition IN('started','accepted','timeout','adapter_unavailable','adapter_invalid','association_required','operation_conflict','lease_expired')),PRIMARY KEY(receipt_id,epoch),CHECK((disposition='started')=(finished_at IS NULL)));
`;
export const DISPATCH_DEFINITION_DIGEST = digest(SPEC + DISPATCH_SPEC);
export function dispatchLimits(value: DispatchLimits): DispatchLimits {
  if (
    !value ||
    Object.keys(value).sort().join(',') !== 'leaseMs,maxActive,maxAttempts,retryDelayMs' ||
    !Number.isSafeInteger(value.maxActive) ||
    value.maxActive < 1 ||
    value.maxActive > 4 ||
    !Number.isSafeInteger(value.maxAttempts) ||
    value.maxAttempts < 1 ||
    value.maxAttempts > 5 ||
    !Number.isSafeInteger(value.leaseMs) ||
    value.leaseMs < 500 ||
    value.leaseMs > 30000 ||
    !Number.isSafeInteger(value.retryDelayMs) ||
    value.retryDelayMs < 20 ||
    value.retryDelayMs > 5000
  )
    throw new ChannelError('SchemaMismatch');
  return Object.freeze({ ...value });
}
/** Explicit quiescing owner upgrade; serving code never installs or repairs v2. */
export async function upgradeChannelSchemaV2(
  input: DatabaseSettings,
  proposed: DispatchLimits = DEFAULT_DISPATCH_LIMITS,
): Promise<void> {
  const value = settings(input, 'continuity_migrator');
  const bound = dispatchLimits(proposed);
  const client = watchClient(new PgClient(config(value)));
  let primary: ChannelError | undefined;
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'channel-schema:' + value.schema,
    ]);
    await validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
    // Metadata-first lock order drains old runtime transactions before DDL without
    // holding admission while a metadata reader is waiting for it.
    await client.query(
      `LOCK TABLE ${['schema_metadata', 'admission', 'sender_heads', 'associations', 'challenges', 'conversations', 'inbox', 'processing_intents'].map((name) => table(value.schema, name)).join(',')} IN ACCESS EXCLUSIVE MODE`,
    );
    await validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
    const version = (
      await client.query(
        `SELECT version FROM ${table(value.schema, 'schema_metadata')} WHERE singleton`,
      )
    ).rows[0]?.version;
    if (version === 2 || version === 3 || version === 4 || version >= 5) {
      const row = (
        await client.query(
          `SELECT max_active,max_attempts,lease_ms,retry_delay_ms FROM ${table(value.schema, 'dispatch_settings')} WHERE singleton`,
        )
      ).rows[0];
      if (
        !row ||
        JSON.stringify(
          dispatchLimits({
            maxActive: row.max_active,
            maxAttempts: row.max_attempts,
            leaseMs: row.lease_ms,
            retryDelayMs: row.retry_delay_ms,
          }),
        ) !== JSON.stringify(bound)
      )
        throw new ChannelError('SchemaMismatch');
    } else if (version === 1) {
      const ddl = DISPATCH_SPEC.replace(
        /(ALTER TABLE |CREATE TABLE |REFERENCES | ON )([a-z_]+)/g,
        (_all, prefix: string, name: string) => prefix + table(value.schema, name),
      );
      await client.query(ddl);
      await client.query(
        `INSERT INTO ${table(value.schema, 'dispatch_settings')} VALUES(true,$1,$2,$3,$4)`,
        [bound.maxActive, bound.maxAttempts, bound.leaseMs, bound.retryDelayMs],
      );
      for (const name of ['dispatch_settings', 'dispatch_plans', 'dispatch_attempts'])
        await client.query(
          `REVOKE ALL ON ${table(value.schema, name)} FROM PUBLIC,livekit_lab; GRANT SELECT ON ${table(value.schema, name)} TO livekit_lab`,
        );
      for (const name of ['dispatch_plans', 'dispatch_attempts'])
        await client.query(`GRANT INSERT ON ${table(value.schema, name)} TO livekit_lab`);
      await client.query(
        `GRANT UPDATE(state,claim_epoch,claim_owner,claim_until,claim_kind,attempt_count,next_attempt_at,possible_external,external_receipt_id,last_code) ON ${table(value.schema, 'processing_intents')} TO livekit_lab`,
      );
      await client.query(
        `GRANT UPDATE(finished_at,disposition) ON ${table(value.schema, 'dispatch_attempts')} TO livekit_lab`,
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} DROP CONSTRAINT schema_metadata_version_check`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET version=2,definition_digest=$1`,
        [DISPATCH_DEFINITION_DIGEST],
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} ADD CONSTRAINT schema_metadata_version_check CHECK(version=2)`,
      );
      await client.query(`COMMENT ON SCHEMA "${value.schema}" IS 'p2-channel-schema-v2'`);
      const snapshot = await catalog(client, value.schema);
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET catalog_snapshot=$1::jsonb`,
        [JSON.stringify(snapshot)],
      );
      await validate(
        client,
        value,
        DEFINITION_DIGEST,
        true,
        DISPATCH_DEFINITION_DIGEST,
        OUTBOX_DEFINITION_DIGEST,
        CALLBACK_DEFINITION_DIGEST,
        SEND_POLICY_DEFINITION_DIGEST,
        NATIVE_DEFINITION_DIGEST,
        COMMUNICATION_DEFINITION_DIGEST,
        RESULT_RECEIVER_DEFINITION_DIGEST,
        INDEX_DEFINITION_DIGEST,
      );
    } else throw new ChannelError('SchemaMismatch');
    await client.query('COMMIT');
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch {
      /* Owned client cleanup below. */
    }
    primary = error instanceof ChannelError ? error : new ChannelError('SchemaMismatch');
    throw primary;
  } finally {
    await closeMigrationClient(client, primary);
  }
}

/** Explicit outbox v3; recipient and possible-send permission share the inbox guard. */
import { randomUUID } from 'node:crypto';
import { DEFAULT_OUTBOX_LIMITS, outboxLimits, type OutboxLimits } from './outbox-types.js';
export type { OutboxLimits } from './outbox-types.js';
export { DEFAULT_OUTBOX_LIMITS } from './outbox-types.js';
const OUTBOX_SPEC = `
CREATE TABLE outbox_settings(singleton boolean PRIMARY KEY CHECK(singleton),receiver_id uuid NOT NULL UNIQUE,max_replies integer NOT NULL CHECK(max_replies BETWEEN 1 AND 10000),max_routes integer NOT NULL CHECK(max_routes BETWEEN 1 AND 10000),max_attempts smallint NOT NULL CHECK(max_attempts BETWEEN 1 AND 5));
CREATE TABLE outbox_admission(singleton boolean PRIMARY KEY CHECK(singleton),reply_count integer NOT NULL CHECK(reply_count>=0),route_count integer NOT NULL CHECK(route_count>=0));
CREATE TABLE reply_intents(tenant_id text NOT NULL,account_id text NOT NULL,outbound_id uuid NOT NULL,receipt_id uuid NOT NULL UNIQUE,conversation_id text NOT NULL,case_id text NOT NULL,response_id text NOT NULL,canonical_payload text NOT NULL CHECK(octet_length(canonical_payload)<=32768),intent_digest text NOT NULL CHECK(intent_digest ~ '^[0-9a-f]{64}$'),body_digest text NOT NULL CHECK(body_digest ~ '^[0-9a-f]{64}$'),accepted_at timestamptz NOT NULL,PRIMARY KEY(tenant_id,account_id,outbound_id));
CREATE INDEX reply_pending ON reply_intents(tenant_id,account_id,conversation_id,case_id,accepted_at,outbound_id);
CREATE TABLE outbound_routes(tenant_id text NOT NULL,account_id text NOT NULL,conversation_id text NOT NULL,case_id text NOT NULL,provider text NOT NULL,provider_account_id text NOT NULL,version bigint NOT NULL CHECK(version>0),sender_id text,association_epoch bigint CHECK(association_epoch>0),suppressed boolean NOT NULL,CHECK((sender_id IS NULL)=(association_epoch IS NULL)),PRIMARY KEY(tenant_id,account_id,conversation_id));
CREATE TABLE send_attempts(attempt_id uuid PRIMARY KEY,tenant_id text NOT NULL,account_id text NOT NULL,outbound_id uuid NOT NULL,ordinal smallint NOT NULL CHECK(ordinal BETWEEN 1 AND 5),provider_operation_key uuid NOT NULL UNIQUE,canonical_request text NOT NULL CHECK(octet_length(canonical_request)<=32768),request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),reserved_at timestamptz NOT NULL,UNIQUE(tenant_id,account_id,outbound_id,ordinal),FOREIGN KEY(tenant_id,account_id,outbound_id) REFERENCES reply_intents(tenant_id,account_id,outbound_id));
CREATE TABLE send_results(attempt_id uuid PRIMARY KEY REFERENCES send_attempts(attempt_id),canonical_result text NOT NULL CHECK(octet_length(canonical_result)<=8192),observed_at timestamptz NOT NULL);
`;
export const OUTBOX_DEFINITION_DIGEST = digest(SPEC + DISPATCH_SPEC + OUTBOX_SPEC);
export async function upgradeChannelSchemaV3(
  input: DatabaseSettings,
  proposed: OutboxLimits = DEFAULT_OUTBOX_LIMITS,
): Promise<void> {
  const value = settings(input, 'continuity_migrator'),
    bound = outboxLimits(proposed),
    client = watchClient(new PgClient(config(value)));
  let primary: ChannelError | undefined;
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'channel-schema:' + value.schema,
    ]);
    await validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
    if (
      (
        await client.query(
          `SELECT version FROM ${table(value.schema, 'schema_metadata')} WHERE singleton`,
        )
      ).rows[0]?.version === 1
    )
      throw new ChannelError('UpgradeRequired');
    await client.query(
      `LOCK TABLE ${['schema_metadata', 'admission', 'sender_heads', 'associations', 'challenges', 'conversations', 'inbox', 'processing_intents', 'dispatch_settings', 'dispatch_plans', 'dispatch_attempts'].map((n) => table(value.schema, n)).join(',')} IN ACCESS EXCLUSIVE MODE`,
    );
    await validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
    const version = (
      await client.query(
        `SELECT version FROM ${table(value.schema, 'schema_metadata')} WHERE singleton`,
      )
    ).rows[0]?.version;
    if (version === 3 || version === 4 || version >= 5) {
      const x = (
        await client.query(
          `SELECT max_replies,max_routes,max_attempts FROM ${table(value.schema, 'outbox_settings')} WHERE singleton`,
        )
      ).rows[0];
      if (
        !x ||
        JSON.stringify(
          outboxLimits({
            maxReplies: x.max_replies,
            maxRoutes: x.max_routes,
            maxAttempts: x.max_attempts,
          }),
        ) !== JSON.stringify(bound)
      )
        throw new ChannelError('SchemaMismatch');
    } else if (version === 2) {
      await client.query(
        OUTBOX_SPEC.replace(
          /(CREATE TABLE |REFERENCES | ON )([a-z_]+)/g,
          (_a, prefix: string, name: string) => prefix + table(value.schema, name),
        ),
      );
      await client.query(
        `INSERT INTO ${table(value.schema, 'outbox_settings')} VALUES(true,$1,$2,$3,$4)`,
        [randomUUID(), bound.maxReplies, bound.maxRoutes, bound.maxAttempts],
      );
      await client.query(`INSERT INTO ${table(value.schema, 'outbox_admission')} VALUES(true,0,0)`);
      for (const name of [
        'outbox_settings',
        'outbox_admission',
        'reply_intents',
        'outbound_routes',
        'send_attempts',
        'send_results',
      ])
        await client.query(
          `REVOKE ALL ON ${table(value.schema, name)} FROM PUBLIC,livekit_lab;GRANT SELECT ON ${table(value.schema, name)} TO livekit_lab`,
        );
      for (const name of ['reply_intents', 'outbound_routes', 'send_attempts', 'send_results'])
        await client.query(`GRANT INSERT ON ${table(value.schema, name)} TO livekit_lab`);
      await client.query(
        `GRANT UPDATE(reply_count,route_count) ON ${table(value.schema, 'outbox_admission')} TO livekit_lab;GRANT UPDATE(version,sender_id,association_epoch,suppressed) ON ${table(value.schema, 'outbound_routes')} TO livekit_lab`,
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} DROP CONSTRAINT schema_metadata_version_check`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET version=3,definition_digest=$1`,
        [OUTBOX_DEFINITION_DIGEST],
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} ADD CONSTRAINT schema_metadata_version_check CHECK(version=3);COMMENT ON SCHEMA "${value.schema}" IS 'p2-channel-schema-v3'`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET catalog_snapshot=$1::jsonb`,
        [JSON.stringify(await catalog(client, value.schema))],
      );
      await validate(
        client,
        value,
        DEFINITION_DIGEST,
        true,
        DISPATCH_DEFINITION_DIGEST,
        OUTBOX_DEFINITION_DIGEST,
        CALLBACK_DEFINITION_DIGEST,
        SEND_POLICY_DEFINITION_DIGEST,
        NATIVE_DEFINITION_DIGEST,
        COMMUNICATION_DEFINITION_DIGEST,
        RESULT_RECEIVER_DEFINITION_DIGEST,
        INDEX_DEFINITION_DIGEST,
      );
    } else throw new ChannelError('UpgradeRequired');
    await client.query('COMMIT');
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch {
      /* retire owner */
    }
    primary = error instanceof ChannelError ? error : new ChannelError('SchemaMismatch');
    throw primary;
  } finally {
    await closeMigrationClient(client, primary);
  }
}

/** Quiesced owner upgrade: original attempts/results remain immutable. */
import { DEFAULT_CALLBACK_LIMITS, callbackLimits, type CallbackLimits } from './callback-types.js';
export { DEFAULT_CALLBACK_LIMITS } from './callback-types.js';
export type { CallbackLimits } from './callback-types.js';
const CALLBACK_SPEC = `
CREATE TABLE callback_settings(singleton boolean PRIMARY KEY CHECK(singleton),rule_version smallint NOT NULL CHECK(rule_version=1),max_global integer NOT NULL CHECK(max_global BETWEEN 1 AND 100000),max_per_attempt smallint NOT NULL CHECK(max_per_attempt BETWEEN 1 AND 32));
CREATE TABLE callback_admission(singleton boolean PRIMARY KEY CHECK(singleton),callback_count integer NOT NULL CHECK(callback_count>=0));
CREATE TABLE callback_observations(tenant_id text NOT NULL,provider text NOT NULL,provider_account_id text NOT NULL,event_id text NOT NULL,receipt_id uuid NOT NULL UNIQUE,attempt_id uuid NOT NULL REFERENCES send_attempts(attempt_id),ordinal smallint NOT NULL CHECK(ordinal BETWEEN 1 AND 32),canonical_payload text NOT NULL CHECK(octet_length(canonical_payload)<=4096),payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),first_wire text NOT NULL CHECK(octet_length(first_wire)<=4096),accepted_at timestamptz NOT NULL,PRIMARY KEY(tenant_id,provider,provider_account_id,event_id),UNIQUE(attempt_id,ordinal));
`;
export const CALLBACK_DEFINITION_DIGEST = digest(
  SPEC + DISPATCH_SPEC + OUTBOX_SPEC + CALLBACK_SPEC,
);
export async function upgradeChannelSchemaV4(
  input: DatabaseSettings,
  proposed: CallbackLimits = DEFAULT_CALLBACK_LIMITS,
): Promise<void> {
  const value = settings(input, 'continuity_migrator'),
    bound = callbackLimits(proposed),
    client = watchClient(new PgClient(config(value)));
  let primary: ChannelError | undefined;
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'channel-schema:' + value.schema,
    ]);
    await validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
    const version = (
      await client.query(
        `SELECT version FROM ${table(value.schema, 'schema_metadata')} WHERE singleton`,
      )
    ).rows[0]?.version;
    if (
      version !== 3 &&
      version !== 4 &&
      version !== 5 &&
      version !== 6 &&
      version !== 7 &&
      version !== 8 &&
      version !== 9
    )
      throw new ChannelError('UpgradeRequired');
    // Metadata first, then all existing v3 relations. This owner operation requires quiescence.
    await client.query(
      `LOCK TABLE ${['schema_metadata', 'admission', 'sender_heads', 'associations', 'challenges', 'conversations', 'inbox', 'processing_intents', 'dispatch_settings', 'dispatch_plans', 'dispatch_attempts', 'outbox_settings', 'outbox_admission', 'reply_intents', 'outbound_routes', 'send_attempts', 'send_results'].map((n) => table(value.schema, n)).join(',')} IN ACCESS EXCLUSIVE MODE`,
    );
    await validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
    if (version === 4 || version >= 5) {
      const r = (
        await client.query(
          `SELECT rule_version,max_global,max_per_attempt FROM ${table(value.schema, 'callback_settings')} WHERE singleton`,
        )
      ).rows;
      if (
        r.length !== 1 ||
        r[0].rule_version !== 1 ||
        JSON.stringify(
          callbackLimits({ maxGlobal: r[0].max_global, maxPerAttempt: r[0].max_per_attempt }),
        ) !== JSON.stringify(bound)
      )
        throw new ChannelError('SchemaMismatch');
    } else {
      await client.query(
        CALLBACK_SPEC.replace(
          /(CREATE TABLE |REFERENCES | ON )([a-z_]+)/g,
          (_a, prefix: string, name: string) => prefix + table(value.schema, name),
        ),
      );
      await client.query(
        `INSERT INTO ${table(value.schema, 'callback_settings')} VALUES(true,1,$1,$2)`,
        [bound.maxGlobal, bound.maxPerAttempt],
      );
      await client.query(`INSERT INTO ${table(value.schema, 'callback_admission')} VALUES(true,0)`);
      for (const name of ['callback_settings', 'callback_admission', 'callback_observations'])
        await client.query(
          `REVOKE ALL ON ${table(value.schema, name)} FROM PUBLIC,livekit_lab;GRANT SELECT ON ${table(value.schema, name)} TO livekit_lab`,
        );
      await client.query(
        `GRANT INSERT ON ${table(value.schema, 'callback_observations')} TO livekit_lab;GRANT UPDATE(callback_count) ON ${table(value.schema, 'callback_admission')} TO livekit_lab`,
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} DROP CONSTRAINT schema_metadata_version_check`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET version=4,definition_digest=$1`,
        [CALLBACK_DEFINITION_DIGEST],
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} ADD CONSTRAINT schema_metadata_version_check CHECK(version=4);COMMENT ON SCHEMA "${value.schema}" IS 'p2-channel-schema-v4'`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET catalog_snapshot=$1::jsonb`,
        [JSON.stringify(await catalog(client, value.schema))],
      );
      await validate(
        client,
        value,
        DEFINITION_DIGEST,
        true,
        DISPATCH_DEFINITION_DIGEST,
        OUTBOX_DEFINITION_DIGEST,
        CALLBACK_DEFINITION_DIGEST,
        SEND_POLICY_DEFINITION_DIGEST,
        NATIVE_DEFINITION_DIGEST,
        COMMUNICATION_DEFINITION_DIGEST,
        RESULT_RECEIVER_DEFINITION_DIGEST,
        INDEX_DEFINITION_DIGEST,
      );
    }
    await client.query('COMMIT');
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch {
      /*discard owned connection*/
    }
    primary = error instanceof ChannelError ? error : new ChannelError('SchemaMismatch');
    throw primary;
  } finally {
    await closeMigrationClient(client, primary);
  }
}

/** Explicit v5 recovery policy. Historic sends remain permanently ordinary. */
import {
  DEFAULT_SEND_POLICY_LIMITS,
  sendPolicyLimits,
  operationFrom,
  operationDigest,
  admission,
  type SendPolicyLimits,
} from './send-policy-types.js';
import { sendRequest, sha, envelope, carrierResult, timestamp } from './outbox-types.js';
export { DEFAULT_SEND_POLICY_LIMITS } from './send-policy-types.js';
export type { SendPolicyLimits } from './send-policy-types.js';
const SEND_POLICY_SPEC = `
CREATE TABLE send_policy_settings(singleton boolean PRIMARY KEY CHECK(singleton),ordinary_unknown text NOT NULL CHECK(ordinary_unknown='hold_no_resend'),idempotent_unknown text NOT NULL CHECK(idempotent_unknown='explicit_same_key_only'),max_recovery_commands integer NOT NULL CHECK(max_recovery_commands BETWEEN 1 AND 100000),max_per_operation smallint NOT NULL CHECK(max_per_operation BETWEEN 1 AND 32),recovery_count integer NOT NULL CHECK(recovery_count>=0));
CREATE TABLE send_operations(provider_operation_key uuid PRIMARY KEY,tenant_id text NOT NULL,account_id text NOT NULL,outbound_id uuid NOT NULL,provider text NOT NULL,provider_account_id text NOT NULL,first_attempt_id uuid NOT NULL UNIQUE REFERENCES send_attempts(attempt_id) DEFERRABLE INITIALLY DEFERRED,capability text NOT NULL CHECK(capability IN('ordinary_fake_sms_v1','idempotent_fake_sms_v1')),canonical_operation text NOT NULL CHECK(octet_length(canonical_operation)<=32768),operation_digest text NOT NULL CHECK(operation_digest ~ '^[0-9a-f]{64}$'),first_request_digest text NOT NULL CHECK(first_request_digest ~ '^[0-9a-f]{64}$'),admission_proof text NOT NULL CHECK(octet_length(admission_proof)<=4096),admission_digest text NOT NULL CHECK(admission_digest ~ '^[0-9a-f]{64}$'),created_at timestamptz NOT NULL,UNIQUE(tenant_id,account_id,outbound_id,provider_operation_key),FOREIGN KEY(tenant_id,account_id,outbound_id) REFERENCES reply_intents(tenant_id,account_id,outbound_id));
CREATE TABLE send_recovery_commands(command_id uuid PRIMARY KEY,provider_operation_key uuid NOT NULL REFERENCES send_operations(provider_operation_key),tenant_id text NOT NULL,account_id text NOT NULL,outbound_id uuid NOT NULL,source_attempt_id uuid NOT NULL REFERENCES send_attempts(attempt_id),kind text NOT NULL CHECK(kind IN('reconcile','retry')),canonical_command text NOT NULL CHECK(octet_length(canonical_command)<=4096),command_digest text NOT NULL CHECK(command_digest ~ '^[0-9a-f]{64}$'),receipt_json text NOT NULL CHECK(octet_length(receipt_json)<=4096),receipt_digest text NOT NULL CHECK(receipt_digest ~ '^[0-9a-f]{64}$'),new_attempt_id uuid UNIQUE REFERENCES send_attempts(attempt_id) DEFERRABLE INITIALLY DEFERRED,accepted_at timestamptz NOT NULL,FOREIGN KEY(tenant_id,account_id,outbound_id,provider_operation_key) REFERENCES send_operations(tenant_id,account_id,outbound_id,provider_operation_key));
CREATE INDEX recovery_operation ON send_recovery_commands(provider_operation_key,accepted_at,command_id);
CREATE TABLE send_recovery_observations(command_id uuid PRIMARY KEY REFERENCES send_recovery_commands(command_id),canonical_observation text NOT NULL CHECK(octet_length(canonical_observation)<=2048),observation_digest text NOT NULL CHECK(observation_digest ~ '^[0-9a-f]{64}$'),observed_at timestamptz NOT NULL);
`;
const SEND_POLICY_FK = `ALTER TABLE send_attempts DROP CONSTRAINT send_attempts_provider_operation_key_key;ALTER TABLE send_attempts ADD CONSTRAINT send_attempts_operation_key FOREIGN KEY(tenant_id,account_id,outbound_id,provider_operation_key) REFERENCES send_operations(tenant_id,account_id,outbound_id,provider_operation_key);`;
export const SEND_POLICY_DEFINITION_DIGEST = digest(
  SPEC + DISPATCH_SPEC + OUTBOX_SPEC + CALLBACK_SPEC + SEND_POLICY_SPEC + SEND_POLICY_FK,
);
export async function upgradeChannelSchemaV5(
  input: DatabaseSettings,
  proposed: SendPolicyLimits = DEFAULT_SEND_POLICY_LIMITS,
): Promise<void> {
  const value = settings(input, 'continuity_migrator'),
    bound = sendPolicyLimits(proposed),
    client = watchClient(new PgClient(config(value)));
  let primary: ChannelError | undefined;
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'channel-schema:' + value.schema,
    ]);
    await validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
    const version = (
      await client.query(
        `SELECT version FROM ${table(value.schema, 'schema_metadata')} WHERE singleton`,
      )
    ).rows[0]?.version;
    if (
      version !== 4 &&
      version !== 5 &&
      version !== 6 &&
      version !== 7 &&
      version !== 8 &&
      version !== 9
    )
      throw new ChannelError('UpgradeRequired');
    await client.query(
      `LOCK TABLE ${['schema_metadata', 'admission', 'sender_heads', 'associations', 'challenges', 'conversations', 'inbox', 'processing_intents', 'dispatch_settings', 'dispatch_plans', 'dispatch_attempts', 'outbox_settings', 'outbox_admission', 'reply_intents', 'outbound_routes', 'send_attempts', 'send_results', 'callback_settings', 'callback_admission', 'callback_observations'].map((n) => table(value.schema, n)).join(',')} IN ACCESS EXCLUSIVE MODE`,
    );
    await validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
    if (version >= 5) {
      const count = (
        await client.query(
          `SELECT count(*)::integer AS count FROM ${table(value.schema, 'send_recovery_commands')}`,
        )
      ).rows[0]?.count;
      const perOperation = (
        await client.query(
          `SELECT max(n)::integer AS maximum FROM (SELECT count(*) AS n FROM ${table(value.schema, 'send_recovery_commands')} GROUP BY provider_operation_key) c`,
        )
      ).rows[0]?.maximum;
      const r = (
        await client.query(
          `SELECT * FROM ${table(value.schema, 'send_policy_settings')} WHERE singleton`,
        )
      ).rows;
      if (
        r.length !== 1 ||
        !Number.isSafeInteger(r[0].recovery_count) ||
        r[0].recovery_count !== count ||
        r[0].recovery_count < 0 ||
        r[0].recovery_count > bound.maxRecoveryCommands ||
        (perOperation !== null &&
          (!Number.isSafeInteger(perOperation) || perOperation > bound.maxPerOperation)) ||
        r[0].ordinary_unknown !== 'hold_no_resend' ||
        r[0].idempotent_unknown !== 'explicit_same_key_only' ||
        JSON.stringify(
          sendPolicyLimits({
            maxRecoveryCommands: r[0].max_recovery_commands,
            maxPerOperation: r[0].max_per_operation,
          }),
        ) !== JSON.stringify(bound)
      )
        throw new ChannelError('SchemaMismatch');
    } else {
      await client.query(
        SEND_POLICY_SPEC.replace(
          /(CREATE TABLE |REFERENCES | ON )([a-z_]+)/g,
          (_a, prefix: string, name: string) => prefix + table(value.schema, name),
        ),
      );
      await client.query(
        `INSERT INTO ${table(value.schema, 'send_policy_settings')} VALUES(true,'hold_no_resend','explicit_same_key_only',$1,$2,0)`,
        [bound.maxRecoveryCommands, bound.maxPerOperation],
      );
      const bounds = (
          await client.query(
            `SELECT max_replies,max_routes,max_attempts FROM ${table(value.schema, 'outbox_settings')} WHERE singleton`,
          )
        ).rows[0],
        guard = (
          await client.query(
            `SELECT reply_count,route_count FROM ${table(value.schema, 'outbox_admission')} WHERE singleton FOR UPDATE`,
          )
        ).rows[0],
        counts = (
          await client.query(
            `SELECT (SELECT count(*)::integer FROM ${table(value.schema, 'reply_intents')}) AS replies,(SELECT count(*)::integer FROM ${table(value.schema, 'outbound_routes')}) AS routes,(SELECT max(n)::integer FROM (SELECT count(*) AS n FROM ${table(value.schema, 'send_attempts')} GROUP BY tenant_id,account_id,outbound_id) g) AS per_reply`,
          )
        ).rows[0];
      if (
        !bounds ||
        !guard ||
        !counts ||
        !Number.isSafeInteger(guard.reply_count) ||
        !Number.isSafeInteger(guard.route_count) ||
        guard.reply_count !== counts.replies ||
        guard.route_count !== counts.routes ||
        guard.reply_count < 0 ||
        guard.route_count < 0 ||
        guard.reply_count > bounds.max_replies ||
        guard.route_count > bounds.max_routes ||
        (counts.per_reply !== null && counts.per_reply > bounds.max_attempts)
      )
        throw new ChannelError('SchemaMismatch');
      let after: string | null = null,
        count = 0;
      const maximum = Number(bounds.max_replies) * Number(bounds.max_attempts);
      if (!Number.isSafeInteger(maximum) || maximum < 1 || maximum > 50000)
        throw new ChannelError('SchemaMismatch');
      while (true) {
        const rows: {
          canonical_request: string;
          request_digest: string;
          attempt_id: string;
          provider_operation_key: string;
          tenant_id: string;
          account_id: string;
          outbound_id: string;
          ordinal: number;
          reply_payload: string;
          reply_digest: string;
          reply_body_digest: string;
          canonical_result: string | null;
          observed_at: Date | null;
          prior_attempt_id: string | null;
          prior_key: string | null;
          prior_request: string | null;
          prior_request_digest: string | null;
          prior_result: string | null;
        }[] = (
          await client.query(
            `SELECT a.*,i.canonical_payload AS reply_payload,i.intent_digest AS reply_digest,i.body_digest AS reply_body_digest,r.canonical_result,r.observed_at,p.attempt_id AS prior_attempt_id,p.provider_operation_key AS prior_key,p.canonical_request AS prior_request,p.request_digest AS prior_request_digest,pr.canonical_result AS prior_result FROM ${table(value.schema, 'send_attempts')} a JOIN ${table(value.schema, 'reply_intents')} i USING(tenant_id,account_id,outbound_id) LEFT JOIN ${table(value.schema, 'send_results')} r USING(attempt_id) LEFT JOIN ${table(value.schema, 'send_attempts')} p ON p.tenant_id=a.tenant_id AND p.account_id=a.account_id AND p.outbound_id=a.outbound_id AND p.ordinal=a.ordinal-1 LEFT JOIN ${table(value.schema, 'send_results')} pr ON pr.attempt_id=p.attempt_id WHERE ($1::uuid IS NULL OR a.attempt_id>$1::uuid) ORDER BY a.attempt_id LIMIT 64`,
            [after],
          )
        ).rows;
        if (!rows.length) break;
        for (const row of rows) {
          const request = sendRequest(JSON.parse(row.canonical_request)),
            reply = envelope(JSON.parse(row.reply_payload)),
            replyFromRequest = envelope({
              schemaVersion: 1,
              outboundId: request.outboundId,
              responseId: request.responseId,
              body: request.body,
              scope: request.scope,
              caseId: request.caseId,
              conversationId: request.conversationId,
            });
          if (
            JSON.stringify(request) !== row.canonical_request ||
            sha(row.canonical_request) !== row.request_digest ||
            request.attemptId !== row.attempt_id ||
            request.providerOperationKey !== row.provider_operation_key ||
            request.scope.tenantId !== row.tenant_id ||
            request.scope.accountId !== row.account_id ||
            request.outboundId !== row.outbound_id ||
            !Number.isSafeInteger(row.ordinal) ||
            row.ordinal < 1 ||
            row.ordinal > bounds.max_attempts ||
            JSON.stringify(reply) !== row.reply_payload ||
            sha(row.reply_payload) !== row.reply_digest ||
            sha(reply.body) !== row.reply_body_digest ||
            JSON.stringify(replyFromRequest) !== row.reply_payload ||
            ++count > maximum
          )
            throw new ChannelError('SchemaMismatch');
          if (row.canonical_result !== null) {
            const result = carrierResult(JSON.parse(row.canonical_result), request);
            if (JSON.stringify(result) !== row.canonical_result || row.observed_at === null)
              throw new ChannelError('SchemaMismatch');
            timestamp(row.observed_at);
          } else if (row.observed_at !== null) throw new ChannelError('SchemaMismatch');
          let proof = admission({ schemaVersion: 1, kind: 'first_operation' });
          if (row.ordinal > 1) {
            if (
              row.prior_attempt_id === null ||
              row.prior_key === null ||
              row.prior_request === null ||
              row.prior_request_digest === null ||
              row.prior_result === null
            )
              throw new ChannelError('SchemaMismatch');
            const previous = sendRequest(JSON.parse(row.prior_request)),
              result = carrierResult(JSON.parse(row.prior_result), previous);
            if (
              JSON.stringify(previous) !== row.prior_request ||
              sha(row.prior_request) !== row.prior_request_digest ||
              previous.attemptId !== row.prior_attempt_id ||
              previous.providerOperationKey !== row.prior_key ||
              JSON.stringify(
                envelope({
                  schemaVersion: 1,
                  outboundId: previous.outboundId,
                  responseId: previous.responseId,
                  body: previous.body,
                  scope: previous.scope,
                  caseId: previous.caseId,
                  conversationId: previous.conversationId,
                }),
              ) !== row.reply_payload ||
              JSON.stringify(result) !== row.prior_result ||
              result.status !== 'definitive_not_accepted'
            )
              throw new ChannelError('SchemaMismatch');
            proof = admission({
              schemaVersion: 1,
              kind: 'prior_send_nonacceptance',
              predecessorAttemptId: previous.attemptId,
              predecessorOperationKey: previous.providerOperationKey,
              evidenceAttemptId: previous.attemptId,
              evidenceDigest: sha(row.prior_result),
            });
          }
          const op = operationFrom(request, 'ordinary_fake_sms_v1'),
            rawProof = JSON.stringify(proof);
          await client.query(
            `INSERT INTO ${table(value.schema, 'send_operations')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,clock_timestamp())`,
            [
              op.providerOperationKey,
              op.scope.tenantId,
              op.scope.accountId,
              op.outboundId,
              op.providerScope.provider,
              op.providerScope.providerAccountId,
              request.attemptId,
              op.capability,
              JSON.stringify(op),
              operationDigest(op),
              row.request_digest,
              rawProof,
              sha(rawProof),
            ],
          );
          after = request.attemptId;
        }
      }
      await client.query(
        SEND_POLICY_FK.replace(
          /(ALTER TABLE |REFERENCES )([a-z_]+)/g,
          (_a, prefix: string, name: string) => prefix + table(value.schema, name),
        ),
      );
      for (const name of [
        'send_policy_settings',
        'send_operations',
        'send_recovery_commands',
        'send_recovery_observations',
      ])
        await client.query(
          `REVOKE ALL ON ${table(value.schema, name)} FROM PUBLIC,livekit_lab;GRANT SELECT ON ${table(value.schema, name)} TO livekit_lab`,
        );
      for (const name of [
        'send_operations',
        'send_recovery_commands',
        'send_recovery_observations',
      ])
        await client.query(`GRANT INSERT ON ${table(value.schema, name)} TO livekit_lab`);
      await client.query(
        `GRANT UPDATE(recovery_count) ON ${table(value.schema, 'send_policy_settings')} TO livekit_lab`,
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} DROP CONSTRAINT schema_metadata_version_check`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET version=5,definition_digest=$1`,
        [SEND_POLICY_DEFINITION_DIGEST],
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} ADD CONSTRAINT schema_metadata_version_check CHECK(version=5);COMMENT ON SCHEMA "${value.schema}" IS 'p2-channel-schema-v5'`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET catalog_snapshot=$1::jsonb`,
        [JSON.stringify(await catalog(client, value.schema))],
      );
      await validate(
        client,
        value,
        DEFINITION_DIGEST,
        true,
        DISPATCH_DEFINITION_DIGEST,
        OUTBOX_DEFINITION_DIGEST,
        CALLBACK_DEFINITION_DIGEST,
        SEND_POLICY_DEFINITION_DIGEST,
        NATIVE_DEFINITION_DIGEST,
        COMMUNICATION_DEFINITION_DIGEST,
        RESULT_RECEIVER_DEFINITION_DIGEST,
        INDEX_DEFINITION_DIGEST,
      );
    }
    await client.query('COMMIT');
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch {
      /*discard owned connection*/
    }
    primary = error instanceof ChannelError ? error : new ChannelError('SchemaMismatch');
    throw primary;
  } finally {
    await closeMigrationClient(client, primary);
  }
}

import { DEFAULT_NATIVE_LIMITS, nativeLimits, type NativeLimits } from './native-types.js';
export { DEFAULT_NATIVE_LIMITS } from './native-types.js';
export type { NativeLimits } from './native-types.js';
const NATIVE_SPEC = `
CREATE TABLE native_settings(singleton boolean PRIMARY KEY CHECK(singleton),max_bindings integer NOT NULL CHECK(max_bindings BETWEEN 1 AND 1024),binding_count integer NOT NULL CHECK(binding_count>=0));
CREATE TABLE native_bindings(binding_id uuid PRIMARY KEY,tenant_id text NOT NULL,provider text NOT NULL CHECK(provider='livekit'),provider_account_id text NOT NULL,account_id text NOT NULL,conversation_id text NOT NULL,case_id text NOT NULL,room_id text NOT NULL,participant_id text NOT NULL,bearer_digest text NOT NULL UNIQUE CHECK(bearer_digest ~ '^[0-9a-f]{64}$'),canonical_binding text NOT NULL CHECK(octet_length(canonical_binding)<=4096),binding_digest text NOT NULL CHECK(binding_digest ~ '^[0-9a-f]{64}$'),published_at timestamptz NOT NULL,expires_at timestamptz NOT NULL CHECK(expires_at>published_at),revoked_at timestamptz,FOREIGN KEY(tenant_id,account_id,conversation_id) REFERENCES conversations(tenant_id,account_id,conversation_id));
`;
export const NATIVE_DEFINITION_DIGEST = digest(
  SPEC +
    DISPATCH_SPEC +
    OUTBOX_SPEC +
    CALLBACK_SPEC +
    SEND_POLICY_SPEC +
    SEND_POLICY_FK +
    NATIVE_SPEC,
);
export async function upgradeChannelSchemaV6(
  input: DatabaseSettings,
  proposed: NativeLimits = DEFAULT_NATIVE_LIMITS,
  hooks: Readonly<{ harnessAfterTables?: () => void | Promise<void> }> = {},
): Promise<void> {
  if (!hooks || typeof hooks !== 'object') throw new ChannelError('InvalidConfiguration');
  const hookKeys = Reflect.ownKeys(hooks);
  if (
    Object.getPrototypeOf(hooks) !== Object.prototype ||
    hookKeys.some((k) => k !== 'harnessAfterTables')
  )
    throw new ChannelError('InvalidConfiguration');
  const hook = Object.getOwnPropertyDescriptor(hooks, 'harnessAfterTables');
  if (hook && (!('value' in hook) || !hook.enumerable || typeof hook.value !== 'function'))
    throw new ChannelError('InvalidConfiguration');
  const afterTables = hook?.value as (() => void | Promise<void>) | undefined;
  const value = settings(input, 'continuity_migrator'),
    bound = nativeLimits(proposed),
    client = watchClient(new PgClient(config(value)));
  let primary: ChannelError | undefined;
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'channel-schema:' + value.schema,
    ]);
    await validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
    const version = (
      await client.query(
        `SELECT version FROM ${table(value.schema, 'schema_metadata')} WHERE singleton`,
      )
    ).rows[0]?.version;
    if (version !== 5 && version !== 6 && version !== 7 && version !== 8 && version !== 9)
      throw new ChannelError('UpgradeRequired');
    await client.query(
      `LOCK TABLE ${['schema_metadata', 'admission', 'inbox', 'processing_intents', 'conversations'].map((n) => table(value.schema, n)).join(',')} IN ACCESS EXCLUSIVE MODE`,
    );
    await validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
    if (version >= 6) {
      const row = (
        await client.query(
          `SELECT *, (SELECT count(*)::integer FROM ${table(value.schema, 'native_bindings')}) AS actual FROM ${table(value.schema, 'native_settings')} WHERE singleton`,
        )
      ).rows[0];
      if (
        !row ||
        row.binding_count !== row.actual ||
        row.binding_count > bound.maxBindings ||
        row.max_bindings !== bound.maxBindings
      )
        throw new ChannelError('SchemaMismatch');
    } else {
      await client.query(
        NATIVE_SPEC.replace(
          /(CREATE TABLE |REFERENCES )([a-z_]+)/g,
          (_all, prefix: string, name: string) => prefix + table(value.schema, name),
        ),
      );
      await afterTables?.();
      await client.query(
        `INSERT INTO ${table(value.schema, 'native_settings')} VALUES(true,$1,0)`,
        [bound.maxBindings],
      );
      for (const name of ['native_settings', 'native_bindings'])
        await client.query(
          `REVOKE ALL ON ${table(value.schema, name)} FROM PUBLIC,livekit_lab;GRANT SELECT,INSERT ON ${table(value.schema, name)} TO livekit_lab`,
        );
      await client.query(
        `REVOKE INSERT ON ${table(value.schema, 'native_settings')} FROM livekit_lab;GRANT UPDATE(binding_count) ON ${table(value.schema, 'native_settings')} TO livekit_lab;GRANT UPDATE(revoked_at) ON ${table(value.schema, 'native_bindings')} TO livekit_lab`,
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} DROP CONSTRAINT schema_metadata_version_check`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET version=6,definition_digest=$1`,
        [NATIVE_DEFINITION_DIGEST],
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} ADD CONSTRAINT schema_metadata_version_check CHECK(version=6);COMMENT ON SCHEMA "${value.schema}" IS 'p2-channel-schema-v6'`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET catalog_snapshot=$1::jsonb`,
        [JSON.stringify(await catalog(client, value.schema))],
      );
      await validate(
        client,
        value,
        DEFINITION_DIGEST,
        true,
        DISPATCH_DEFINITION_DIGEST,
        OUTBOX_DEFINITION_DIGEST,
        CALLBACK_DEFINITION_DIGEST,
        SEND_POLICY_DEFINITION_DIGEST,
        NATIVE_DEFINITION_DIGEST,
        COMMUNICATION_DEFINITION_DIGEST,
        RESULT_RECEIVER_DEFINITION_DIGEST,
        INDEX_DEFINITION_DIGEST,
      );
    }
    await client.query('COMMIT');
  } catch (error) {
    primary = error instanceof ChannelError ? error : new ChannelError('SchemaMismatch');
    try {
      await client.query('ROLLBACK');
    } catch {
      /*owner cleanup*/
    }
    throw primary;
  } finally {
    try {
      await client.end();
    } catch {
      if (!primary) throw new ChannelError('CleanupIncomplete');
    }
  }
}

import {
  communicationLimits,
  DEFAULT_COMMUNICATION_LIMITS,
  type CommunicationLimits,
} from './communication-types.js';
export { DEFAULT_COMMUNICATION_LIMITS } from './communication-types.js';
export type { CommunicationLimits } from './communication-types.js';
const COMMUNICATION_SPEC = `
CREATE TABLE communication_settings(singleton boolean PRIMARY KEY CHECK(singleton),profile_id uuid NOT NULL UNIQUE,max_responses integer NOT NULL CHECK(max_responses BETWEEN 1 AND 10000),max_observations integer NOT NULL CHECK(max_observations BETWEEN 1 AND 100000),max_observations_per_response integer NOT NULL CHECK(max_observations_per_response BETWEEN 1 AND 64),response_count integer NOT NULL CHECK(response_count>=0),observation_count integer NOT NULL CHECK(observation_count>=0));
CREATE TABLE native_responses(response_id uuid PRIMARY KEY,generation_id uuid NOT NULL,sdk_speech_id text NOT NULL,binding_id uuid NOT NULL REFERENCES native_bindings(binding_id),input_receipt_id uuid NOT NULL,operation_key uuid NOT NULL,tenant_id text NOT NULL,account_id text NOT NULL,conversation_id text NOT NULL,case_id text NOT NULL,canonical_anchor text NOT NULL CHECK(octet_length(canonical_anchor)<=8192),anchor_digest text NOT NULL CHECK(anchor_digest ~ '^[0-9a-f]{64}$'),receipt_id uuid NOT NULL UNIQUE,response_sequence bigint NOT NULL CHECK(response_sequence>0),accepted_at timestamptz NOT NULL,UNIQUE(binding_id,generation_id),UNIQUE(binding_id,sdk_speech_id),UNIQUE(response_id,binding_id),UNIQUE(tenant_id,account_id,conversation_id,response_sequence),FOREIGN KEY(input_receipt_id,operation_key) REFERENCES processing_intents(receipt_id,operation_key));
CREATE TABLE native_observations(binding_id uuid NOT NULL,source text NOT NULL CHECK(source IN('agent_sdk','browser_client')),event_id uuid NOT NULL,response_id uuid NOT NULL,canonical_payload text NOT NULL CHECK(octet_length(canonical_payload)<=32768),payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),receipt_id uuid NOT NULL UNIQUE,observation_sequence bigint NOT NULL CHECK(observation_sequence>0),accepted_at timestamptz NOT NULL,PRIMARY KEY(binding_id,source,event_id),UNIQUE(response_id,observation_sequence),FOREIGN KEY(response_id,binding_id) REFERENCES native_responses(response_id,binding_id));
CREATE INDEX native_responses_scope ON native_responses(tenant_id,account_id,conversation_id,response_sequence);
CREATE INDEX native_observations_response ON native_observations(response_id,observation_sequence);
`;
export const COMMUNICATION_DEFINITION_DIGEST = digest(
  SPEC +
    DISPATCH_SPEC +
    OUTBOX_SPEC +
    CALLBACK_SPEC +
    SEND_POLICY_SPEC +
    SEND_POLICY_FK +
    NATIVE_SPEC +
    COMMUNICATION_SPEC,
);
/** Explicit maintenance-only upgrade; no serving DDL or historical data adoption. */
export async function upgradeChannelSchemaV7(
  input: DatabaseSettings,
  proposed: CommunicationLimits = DEFAULT_COMMUNICATION_LIMITS,
  hooks: Readonly<{ harnessAfterTables?: () => void | Promise<void> }> = {},
): Promise<void> {
  const value = settings(input, 'continuity_migrator'),
    bound = communicationLimits(proposed),
    client = watchClient(new PgClient(config(value)));
  if (
    !hooks ||
    Object.getPrototypeOf(hooks) !== Object.prototype ||
    Reflect.ownKeys(hooks).some((k) => k !== 'harnessAfterTables')
  )
    throw new ChannelError('InvalidConfiguration');
  const hook = Object.getOwnPropertyDescriptor(hooks, 'harnessAfterTables');
  if (hook && (!('value' in hook) || !hook.enumerable || typeof hook.value !== 'function'))
    throw new ChannelError('InvalidConfiguration');
  let primary: ChannelError | undefined;
  const check = () =>
    validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'channel-schema:' + value.schema,
    ]);
    await check();
    const version = (
      await client.query(
        `SELECT version FROM ${table(value.schema, 'schema_metadata')} WHERE singleton`,
      )
    ).rows[0]?.version;
    if (version !== 6 && version !== 7 && version !== 8 && version !== 9)
      throw new ChannelError('UpgradeRequired');
    await client.query(
      `LOCK TABLE ${['schema_metadata', 'admission', 'inbox', 'processing_intents', 'conversations', 'native_settings', 'native_bindings'].map((n) => table(value.schema, n)).join(',')} IN ACCESS EXCLUSIVE MODE`,
    );
    await check();
    const old = (
      await client.query(
        `SELECT s.*,(SELECT count(*)::integer FROM ${table(value.schema, 'native_bindings')}) AS actual_bindings,(SELECT count(*)::integer FROM ${table(value.schema, 'inbox')}) AS actual_inbox,(SELECT inbox_count FROM ${table(value.schema, 'admission')} WHERE singleton) AS inbox_count FROM ${table(value.schema, 'native_settings')} s WHERE singleton`,
      )
    ).rows;
    if (
      old.length !== 1 ||
      !Number.isSafeInteger(old[0].binding_count) ||
      old[0].binding_count !== old[0].actual_bindings ||
      old[0].binding_count > old[0].max_bindings ||
      old[0].actual_inbox !== old[0].inbox_count
    )
      throw new ChannelError('SchemaMismatch');
    if (version >= 7) {
      const rows = (
        await client.query(
          `SELECT s.*,(SELECT count(*)::integer FROM ${table(value.schema, 'native_responses')}) AS actual_responses,(SELECT count(*)::integer FROM ${table(value.schema, 'native_observations')}) AS actual_observations,(SELECT COALESCE(max(n),0)::integer FROM(SELECT count(*) n FROM ${table(value.schema, 'native_observations')} GROUP BY response_id)t) AS actual_per_response FROM ${table(value.schema, 'communication_settings')} s WHERE singleton`,
        )
      ).rows;
      if (rows.length !== 1) throw new ChannelError('SchemaMismatch');
      const r = rows[0];
      if (
        r.max_responses !== bound.maxResponses ||
        r.max_observations !== bound.maxObservations ||
        r.max_observations_per_response !== bound.maxObservationsPerResponse ||
        r.response_count !== r.actual_responses ||
        r.observation_count !== r.actual_observations ||
        r.response_count > bound.maxResponses ||
        r.observation_count > bound.maxObservations ||
        r.actual_per_response > bound.maxObservationsPerResponse
      )
        throw new ChannelError('SchemaMismatch');
    } else {
      await client.query(
        COMMUNICATION_SPEC.replace(
          /(CREATE TABLE |REFERENCES | ON )([a-z_]+)/g,
          (_all, prefix: string, name: string) => prefix + table(value.schema, name),
        ).replace(/CREATE INDEX ([a-z_]+)/g, (_all, name: string) => 'CREATE INDEX "' + name + '"'),
      );
      await (hook?.value as (() => void | Promise<void>) | undefined)?.();
      await client.query(
        `INSERT INTO ${table(value.schema, 'communication_settings')} VALUES(true,$1,$2,$3,$4,0,0)`,
        [randomUUID(), bound.maxResponses, bound.maxObservations, bound.maxObservationsPerResponse],
      );
      for (const name of ['communication_settings', 'native_responses', 'native_observations'])
        await client.query(
          `REVOKE ALL ON ${table(value.schema, name)} FROM PUBLIC,livekit_lab;GRANT SELECT,INSERT ON ${table(value.schema, name)} TO livekit_lab`,
        );
      await client.query(
        `REVOKE INSERT ON ${table(value.schema, 'communication_settings')} FROM livekit_lab;GRANT UPDATE(response_count,observation_count) ON ${table(value.schema, 'communication_settings')} TO livekit_lab`,
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} DROP CONSTRAINT schema_metadata_version_check`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET version=7,definition_digest=$1`,
        [COMMUNICATION_DEFINITION_DIGEST],
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} ADD CONSTRAINT schema_metadata_version_check CHECK(version=7)`,
      );
      await client.query(`COMMENT ON SCHEMA "${value.schema}" IS 'p2-channel-schema-v7'`);
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET catalog_snapshot=$1::jsonb`,
        [JSON.stringify(await catalog(client, value.schema))],
      );
      await check();
    }
    await client.query('COMMIT');
  } catch (error) {
    primary = error instanceof ChannelError ? error : new ChannelError('SchemaMismatch');
    try {
      await client.query('ROLLBACK');
    } catch {
      /*owner disposal*/
    }
    throw primary;
  } finally {
    try {
      await client.end();
    } catch {
      if (!primary) throw new ChannelError('CleanupIncomplete');
    }
  }
}

/** Immutable P1 result references linked to ordinary notices; never an execution ledger. */
const RESULT_RECEIVER_SPEC = `
CREATE TABLE result_receipts(delivery_id uuid PRIMARY KEY,tenant_id text NOT NULL,account_id text NOT NULL,work_id uuid NOT NULL,attempt_id uuid NOT NULL,result_sha256 text NOT NULL CHECK(result_sha256 ~ '^[0-9a-f]{64}$'),recipient_id text NOT NULL,case_id text NOT NULL,conversation_id text NOT NULL,outbound_id uuid NOT NULL,canonical_intent text NOT NULL CHECK(octet_length(canonical_intent) BETWEEN 1 AND 16384),UNIQUE(tenant_id,account_id,outbound_id),FOREIGN KEY(tenant_id,account_id,outbound_id) REFERENCES reply_intents(tenant_id,account_id,outbound_id));
`;
export const RESULT_RECEIVER_DEFINITION_DIGEST = digest(
  SPEC +
    DISPATCH_SPEC +
    OUTBOX_SPEC +
    CALLBACK_SPEC +
    SEND_POLICY_SPEC +
    SEND_POLICY_FK +
    NATIVE_SPEC +
    COMMUNICATION_SPEC +
    RESULT_RECEIVER_SPEC,
);
/** Explicit quiescent owner upgrade; preserves the existing receiver UUID and all prior rows. */
export async function upgradeChannelSchemaV8(
  input: DatabaseSettings,
  hooks: Readonly<{ harnessAfterTables?: () => void | Promise<void> }> = {},
): Promise<string> {
  const value = settings(input, 'continuity_migrator'),
    client = watchClient(new PgClient(config(value)));
  if (
    !hooks ||
    Object.getPrototypeOf(hooks) !== Object.prototype ||
    Reflect.ownKeys(hooks).some((k) => k !== 'harnessAfterTables')
  )
    throw new ChannelError('InvalidConfiguration');
  const hook = Object.getOwnPropertyDescriptor(hooks, 'harnessAfterTables');
  if (hook && (!('value' in hook) || !hook.enumerable || typeof hook.value !== 'function'))
    throw new ChannelError('InvalidConfiguration');
  let primary: ChannelError | undefined;
  const check = () =>
    validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'channel-schema:' + value.schema,
    ]);
    await check();
    const version = (
      await client.query(
        `SELECT version FROM ${table(value.schema, 'schema_metadata')} WHERE singleton`,
      )
    ).rows[0]?.version;
    if (version !== 7 && version !== 8 && version !== 9) throw new ChannelError('UpgradeRequired');
    await client.query(
      `LOCK TABLE ${['schema_metadata', 'admission', 'outbox_settings', 'outbox_admission', 'reply_intents', 'native_settings', 'native_bindings'].map((n) => table(value.schema, n)).join(',')} IN ACCESS EXCLUSIVE MODE`,
    );
    await check();
    const rows = (
      await client.query(
        `SELECT s.receiver_id::text,s.max_replies,a.reply_count,(SELECT count(*)::integer FROM ${table(value.schema, 'reply_intents')}) AS actual FROM ${table(value.schema, 'outbox_settings')} s CROSS JOIN ${table(value.schema, 'outbox_admission')} a WHERE s.singleton AND a.singleton`,
      )
    ).rows;
    if (
      rows.length !== 1 ||
      !Number.isSafeInteger(rows[0].reply_count) ||
      rows[0].reply_count !== rows[0].actual ||
      rows[0].actual > rows[0].max_replies ||
      typeof rows[0].receiver_id !== 'string'
    )
      throw new ChannelError('SchemaMismatch');
    const receiverId = rows[0].receiver_id as string;
    if (version === 7) {
      await client.query(
        RESULT_RECEIVER_SPEC.replace(
          /(CREATE TABLE |REFERENCES )([a-z_]+)/g,
          (_a, prefix: string, name: string) => prefix + table(value.schema, name),
        ),
      );
      await (hook?.value as (() => void | Promise<void>) | undefined)?.();
      await client.query(
        `REVOKE ALL ON ${table(value.schema, 'result_receipts')} FROM PUBLIC,livekit_lab;GRANT SELECT,INSERT ON ${table(value.schema, 'result_receipts')} TO livekit_lab`,
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} DROP CONSTRAINT schema_metadata_version_check`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET version=8,definition_digest=$1`,
        [RESULT_RECEIVER_DEFINITION_DIGEST],
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} ADD CONSTRAINT schema_metadata_version_check CHECK(version=8);COMMENT ON SCHEMA "${value.schema}" IS 'p2-channel-schema-v8'`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET catalog_snapshot=$1::jsonb`,
        [JSON.stringify(await catalog(client, value.schema))],
      );
    }
    const count = (
      await client.query(
        `SELECT count(*)::integer AS count FROM ${table(value.schema, 'result_receipts')}`,
      )
    ).rows[0]?.count;
    if (!Number.isSafeInteger(count) || count > rows[0].actual)
      throw new ChannelError('SchemaMismatch');
    await check();
    await client.query('COMMIT');
    return receiverId;
  } catch (error) {
    primary = error instanceof ChannelError ? error : new ChannelError('SchemaMismatch');
    try {
      await client.query('ROLLBACK');
    } catch {
      /* Original failure retained. */
    }
    throw primary;
  } finally {
    try {
      await client.end();
    } catch {
      if (!primary) throw new ChannelError('CleanupIncomplete');
    }
  }
}

/** Operating indexes for due dispatch selection and send-history lookups; no row changes. */
const INDEX_SPEC = `
CREATE INDEX dispatch_due ON processing_intents(receipt_id) WHERE state IN ('pending','running','uncertain');
CREATE INDEX attempts_operation ON send_attempts(provider_operation_key,ordinal);
CREATE INDEX recovery_outbound ON send_recovery_commands(tenant_id,account_id,outbound_id);
`;
export const INDEX_DEFINITION_DIGEST = digest(
  SPEC +
    DISPATCH_SPEC +
    OUTBOX_SPEC +
    CALLBACK_SPEC +
    SEND_POLICY_SPEC +
    SEND_POLICY_FK +
    NATIVE_SPEC +
    COMMUNICATION_SPEC +
    RESULT_RECEIVER_SPEC +
    INDEX_SPEC,
);
/** Explicit quiescent owner upgrade from v8; replaying a complete v9 only revalidates it. */
export async function upgradeChannelSchemaV9(
  input: DatabaseSettings,
  hooks: Readonly<{ harnessAfterIndexes?: () => void | Promise<void> }> = {},
): Promise<void> {
  const value = settings(input, 'continuity_migrator'),
    client = watchClient(new PgClient(config(value)));
  if (
    !hooks ||
    Object.getPrototypeOf(hooks) !== Object.prototype ||
    Reflect.ownKeys(hooks).some((k) => k !== 'harnessAfterIndexes')
  )
    throw new ChannelError('InvalidConfiguration');
  const hook = Object.getOwnPropertyDescriptor(hooks, 'harnessAfterIndexes');
  if (hook && (!('value' in hook) || !hook.enumerable || typeof hook.value !== 'function'))
    throw new ChannelError('InvalidConfiguration');
  let primary: ChannelError | undefined;
  const check = () =>
    validate(
      client,
      value,
      DEFINITION_DIGEST,
      true,
      DISPATCH_DEFINITION_DIGEST,
      OUTBOX_DEFINITION_DIGEST,
      CALLBACK_DEFINITION_DIGEST,
      SEND_POLICY_DEFINITION_DIGEST,
      NATIVE_DEFINITION_DIGEST,
      COMMUNICATION_DEFINITION_DIGEST,
      RESULT_RECEIVER_DEFINITION_DIGEST,
      INDEX_DEFINITION_DIGEST,
    );
  try {
    await client.connect();
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [
      'channel-schema:' + value.schema,
    ]);
    await check();
    const version = (
      await client.query(
        `SELECT version FROM ${table(value.schema, 'schema_metadata')} WHERE singleton`,
      )
    ).rows[0]?.version;
    if (version !== 8 && version !== 9) throw new ChannelError('UpgradeRequired');
    if (version === 8) {
      await client.query(
        INDEX_SPEC.replace(
          / ON ([a-z_]+)/g,
          (_all, name: string) => ' ON ' + table(value.schema, name),
        ).replace(/CREATE INDEX ([a-z_]+)/g, (_all, name: string) => 'CREATE INDEX "' + name + '"'),
      );
      await (hook?.value as (() => void | Promise<void>) | undefined)?.();
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} DROP CONSTRAINT schema_metadata_version_check`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET version=9,definition_digest=$1`,
        [INDEX_DEFINITION_DIGEST],
      );
      await client.query(
        `ALTER TABLE ${table(value.schema, 'schema_metadata')} ADD CONSTRAINT schema_metadata_version_check CHECK(version=9);COMMENT ON SCHEMA "${value.schema}" IS 'p2-channel-schema-v9'`,
      );
      await client.query(
        `UPDATE ${table(value.schema, 'schema_metadata')} SET catalog_snapshot=$1::jsonb`,
        [JSON.stringify(await catalog(client, value.schema))],
      );
    }
    await check();
    await client.query('COMMIT');
  } catch (error) {
    primary = error instanceof ChannelError ? error : new ChannelError('SchemaMismatch');
    try {
      await client.query('ROLLBACK');
    } catch {
      /* Original failure retained. */
    }
    throw primary;
  } finally {
    try {
      await client.end();
    } catch {
      if (!primary) throw new ChannelError('CleanupIncomplete');
    }
  }
}
