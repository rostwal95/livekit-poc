/** Install the complete channel schema under the one-shot database owner role. */
import { randomUUID } from 'node:crypto';
import {
  type Connection,
  DEFINITION_DIGEST,
  DEFAULT_LIMITS,
  PgClient,
  catalog,
  config,
  limits as checkLimits,
  settings,
  table,
  validate,
  watchClient,
} from './database.js';
import { ChannelError, type ChannelLimits, type DatabaseSettings } from './public-types.js';
import {
  CHANNEL_SCHEMA_MARKER,
  CHANNEL_SCHEMA_SQL,
  CHANNEL_SCHEMA_VERSION,
} from './channel-schema.js';
import { callbackLimits, DEFAULT_CALLBACK_LIMITS, type CallbackLimits } from './callback-types.js';
import {
  communicationLimits,
  DEFAULT_COMMUNICATION_LIMITS,
  type CommunicationLimits,
} from './communication-types.js';
import { nativeLimits, DEFAULT_NATIVE_LIMITS, type NativeLimits } from './native-types.js';
import { outboxLimits, uuid, DEFAULT_OUTBOX_LIMITS, type OutboxLimits } from './outbox-types.js';
import {
  sendPolicyLimits,
  DEFAULT_SEND_POLICY_LIMITS,
  type SendPolicyLimits,
} from './send-policy-types.js';

export type { ChannelLimits, DatabaseSettings } from './public-types.js';
export { DEFINITION_DIGEST } from './database.js';

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

export type ChannelSchemaOptions = Readonly<{
  inbox?: ChannelLimits;
  dispatch?: DispatchLimits;
  outbox?: OutboxLimits;
  callback?: CallbackLimits;
  sendPolicy?: SendPolicyLimits;
  native?: NativeLimits;
  communication?: CommunicationLimits;
}>;

function configuration(options: ChannelSchemaOptions) {
  if (!options || Object.getPrototypeOf(options) !== Object.prototype)
    throw new ChannelError('InvalidConfiguration');
  const allowed = new Set([
    'inbox',
    'dispatch',
    'outbox',
    'callback',
    'sendPolicy',
    'native',
    'communication',
  ]);
  for (const key of Reflect.ownKeys(options)) {
    const item = Object.getOwnPropertyDescriptor(options, key);
    if (typeof key !== 'string' || !allowed.has(key) || !item?.enumerable || !('value' in item))
      throw new ChannelError('InvalidConfiguration');
  }
  return {
    inbox: checkLimits(options.inbox === undefined ? DEFAULT_LIMITS : options.inbox),
    dispatch: dispatchLimits(
      options.dispatch === undefined ? DEFAULT_DISPATCH_LIMITS : options.dispatch,
    ),
    outbox: outboxLimits(options.outbox === undefined ? DEFAULT_OUTBOX_LIMITS : options.outbox),
    callback: callbackLimits(
      options.callback === undefined ? DEFAULT_CALLBACK_LIMITS : options.callback,
    ),
    sendPolicy: sendPolicyLimits(
      options.sendPolicy === undefined ? DEFAULT_SEND_POLICY_LIMITS : options.sendPolicy,
    ),
    native: nativeLimits(options.native === undefined ? DEFAULT_NATIVE_LIMITS : options.native),
    communication: communicationLimits(
      options.communication === undefined ? DEFAULT_COMMUNICATION_LIMITS : options.communication,
    ),
  };
}

type ProfileSettings = ReturnType<typeof configuration>;

const insertable = [
  'sender_heads',
  'associations',
  'challenges',
  'conversations',
  'inbox',
  'processing_intents',
  'dispatch_plans',
  'dispatch_attempts',
  'reply_intents',
  'outbound_routes',
  'send_attempts',
  'send_results',
  'callback_observations',
  'send_operations',
  'send_recovery_commands',
  'send_recovery_observations',
  'native_bindings',
  'native_responses',
  'native_observations',
  'result_receipts',
] as const;

const updatable = {
  admission: 'inbox_count,challenge_count,association_count,sender_count',
  sender_heads: 'epoch,active_epoch',
  associations: 'revoked_at',
  challenges: 'attempts,consumed_at',
  conversations: 'last_sequence',
  processing_intents:
    'state,claim_epoch,claim_owner,claim_until,claim_kind,attempt_count,next_attempt_at,possible_external,external_receipt_id,last_code',
  dispatch_attempts: 'finished_at,disposition',
  outbox_admission: 'reply_count,route_count',
  outbound_routes: 'version,sender_id,association_epoch,suppressed',
  callback_admission: 'callback_count',
  send_policy_settings: 'recovery_count',
  native_settings: 'binding_count',
  native_bindings: 'revoked_at',
  communication_settings: 'response_count,observation_count',
} as const;

async function createProfile(client: Connection, schema: string, profile: ProfileSettings) {
  const who = await client.query('SELECT current_user AS name');
  if (who.rows[0]?.name !== 'continuity_migrator') throw new ChannelError('AccessDenied');
  await client.query(
    `CREATE SCHEMA "${schema}" AUTHORIZATION continuity_migrator;
     REVOKE ALL ON SCHEMA "${schema}" FROM PUBLIC;
     GRANT USAGE ON SCHEMA "${schema}" TO livekit_lab;
     COMMENT ON SCHEMA "${schema}" IS '${CHANNEL_SCHEMA_MARKER}'`,
  );
  await client.query(`SET LOCAL search_path TO "${schema}",pg_catalog`);
  await client.query(CHANNEL_SCHEMA_SQL);
  await client.query(`SET LOCAL search_path TO pg_catalog`);

  const q = (name: string) => table(schema, name);
  const updates = Object.entries(updatable)
    .map(([name, columns]) => `GRANT UPDATE(${columns}) ON ${q(name)} TO livekit_lab`)
    .join(';');
  await client.query(
    `REVOKE ALL ON ALL TABLES IN SCHEMA "${schema}" FROM PUBLIC,livekit_lab;
     GRANT SELECT ON ALL TABLES IN SCHEMA "${schema}" TO livekit_lab;
     GRANT INSERT ON ${insertable.map(q).join(',')} TO livekit_lab;
     ${updates}`,
  );

  const { inbox, dispatch, outbox, callback, sendPolicy, native, communication } = profile;
  await client.query(
    `INSERT INTO ${q('schema_metadata')} VALUES(true,$1,'livekit_lab',$2,$3::jsonb,$4,$5,$6,$7)`,
    [
      CHANNEL_SCHEMA_VERSION,
      DEFINITION_DIGEST,
      JSON.stringify(await catalog(client, schema)),
      inbox.maxInbox,
      inbox.maxChallenges,
      inbox.maxAssociations,
      inbox.maxSenders,
    ],
  );
  await client.query(
    `INSERT INTO ${q('admission')}(singleton) VALUES(true);
     INSERT INTO ${q('outbox_admission')} VALUES(true,0,0);
     INSERT INTO ${q('callback_admission')} VALUES(true,0)`,
  );
  await client.query(`INSERT INTO ${q('dispatch_settings')} VALUES(true,$1,$2,$3,$4)`, [
    dispatch.maxActive,
    dispatch.maxAttempts,
    dispatch.leaseMs,
    dispatch.retryDelayMs,
  ]);
  await client.query(`INSERT INTO ${q('outbox_settings')} VALUES(true,$1,$2,$3,$4)`, [
    randomUUID(),
    outbox.maxReplies,
    outbox.maxRoutes,
    outbox.maxAttempts,
  ]);
  await client.query(`INSERT INTO ${q('callback_settings')} VALUES(true,1,$1,$2)`, [
    callback.maxGlobal,
    callback.maxPerAttempt,
  ]);
  await client.query(
    `INSERT INTO ${q('send_policy_settings')} VALUES(true,'hold_no_resend','explicit_same_key_only',$1,$2,0)`,
    [sendPolicy.maxRecoveryCommands, sendPolicy.maxPerOperation],
  );
  await client.query(`INSERT INTO ${q('native_settings')} VALUES(true,$1,0)`, [native.maxBindings]);
  await client.query(`INSERT INTO ${q('communication_settings')} VALUES(true,$1,$2,$3,$4,0,0)`, [
    randomUUID(),
    communication.maxResponses,
    communication.maxObservations,
    communication.maxObservationsPerResponse,
  ]);
}

async function verifyProfile(
  client: Connection,
  value: DatabaseSettings,
  profile: ProfileSettings,
) {
  const inbox = await validate(client, value, true);
  const q = (name: string) => table(value.schema, name);
  const result = await client.query(
    `SELECT o.receiver_id,c.profile_id,ARRAY[
        d.max_active,d.max_attempts,d.lease_ms,d.retry_delay_ms,
        o.max_replies,o.max_routes,o.max_attempts,k.max_global,k.max_per_attempt,
        s.max_recovery_commands,s.max_per_operation,n.max_bindings,
        c.max_responses,c.max_observations,c.max_observations_per_response] AS bounds
     FROM ${q('dispatch_settings')} d CROSS JOIN ${q('outbox_settings')} o
       CROSS JOIN ${q('callback_settings')} k CROSS JOIN ${q('send_policy_settings')} s
       CROSS JOIN ${q('native_settings')} n CROSS JOIN ${q('communication_settings')} c
     WHERE d.singleton AND o.singleton AND k.singleton AND s.singleton AND n.singleton AND c.singleton`,
  );
  const row = result.rows[0];
  const { dispatch, outbox, callback, sendPolicy, native, communication } = profile;
  const bounds = [
    dispatch.maxActive,
    dispatch.maxAttempts,
    dispatch.leaseMs,
    dispatch.retryDelayMs,
    outbox.maxReplies,
    outbox.maxRoutes,
    outbox.maxAttempts,
    callback.maxGlobal,
    callback.maxPerAttempt,
    sendPolicy.maxRecoveryCommands,
    sendPolicy.maxPerOperation,
    native.maxBindings,
    communication.maxResponses,
    communication.maxObservations,
    communication.maxObservationsPerResponse,
  ];
  if (
    result.rows.length !== 1 ||
    JSON.stringify(inbox) !== JSON.stringify(profile.inbox) ||
    JSON.stringify(row.bounds) !== JSON.stringify(bounds)
  )
    throw new ChannelError('SchemaMismatch');
  uuid(row.profile_id);
  return uuid(row.receiver_id);
}

/** Create a fresh profile atomically, or validate an existing profile without writes. */
export async function installChannelSchema(
  input: DatabaseSettings,
  proposed: ChannelSchemaOptions = {},
): Promise<string> {
  const value = settings(input, 'continuity_migrator');
  const profile = configuration(proposed);
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
    if (!existing.rows.length) await createProfile(client, value.schema, profile);
    const receiver = await verifyProfile(client, value, profile);
    await client.query('COMMIT');
    return receiver;
  } catch (error) {
    primary = error instanceof ChannelError ? error : new ChannelError('SchemaMismatch');
    try {
      await client.query('ROLLBACK');
    } catch {
      // Keep the original failure when the connection also fails to roll back.
    }
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
