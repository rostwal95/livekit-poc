/** Fixed local experiment data, never a production queue, credential service or authority. */
import { createHash, createHmac } from 'node:crypto';
import type { AccountSeed } from '../src/postgres.js';
import type { FakeSmsMessage } from '../src/security.js';
export const WORKLOAD_SEED = 39;
export const PERFORMANCE_BUDGETS = Object.freeze({
  nodeRssBytes: 536870912,
  eventLoopMaxMs: 1000,
  acceptedAdmissionMaxMs: 5000,
  usefulCompletionMaxMs: 15000,
});
export const SCHEMA_TABLES = Object.freeze([
  'admission',
  'associations',
  'callback_admission',
  'callback_observations',
  'callback_settings',
  'challenges',
  'communication_settings',
  'conversations',
  'dispatch_attempts',
  'dispatch_plans',
  'dispatch_settings',
  'inbox',
  'native_bindings',
  'native_observations',
  'native_responses',
  'native_settings',
  'outbound_routes',
  'outbox_admission',
  'outbox_settings',
  'processing_intents',
  'reply_intents',
  'schema_metadata',
  'send_attempts',
  'send_operations',
  'send_policy_settings',
  'send_recovery_commands',
  'send_recovery_observations',
  'send_results',
  'sender_heads',
]);
export const CASE_NAMES = Object.freeze([
  'frozen_profile_catalog_and_roles',
  'steady_rate_exact_acceptance',
  'burst_http_preacceptance_rejection',
  'sql_pending_pool_and_waiter_bounds',
  'abandoned_http_request_late_committed_receipt',
  'changed_payload_conflict_under_load',
  'two_equal_text_messages_remain_distinct',
  'persisted_claim_capacity_across_gateways',
  'ignored_agent_cancellation_retains_capacity',
  'second_admitted_tenant_progress',
  'retained_limit_rejects_no_reclamation',
  'equal_replay_and_history_at_full_limit',
  'display_window_eviction_late_replay',
  'bounded_observer_outage_with_business_progress',
  'malformed_oversize_and_auth_rejection_under_load',
  'graceful_shutdown_dependent_close',
  'same_schema_fresh_process_restart',
  'original_prepared_operation_reconciliation',
  'dormant_0_64_256_1000_resource_observations',
  'every_dormant_receipt_inspectable_in_64_windows',
  'dormant_no_per_case_room_or_agent_allocation',
  'dormant_two_case_wakeup_progress',
  'populated_dump_restore_original_replay',
  'final_source_proof_roles_resource_cleanup',
] as const);
export const POPULATIONS = Object.freeze([0, 64, 256, 1000] as const);
export const OWNER_LIMITS = Object.freeze({
  capacity: Object.freeze({ maxInbox: 64, maxChallenges: 4, maxAssociations: 4, maxSenders: 4 }),
  dormant: Object.freeze({
    maxInbox: 1024,
    maxChallenges: 1024,
    maxAssociations: 1024,
    maxSenders: 1024,
  }),
});
export type Experiment = Readonly<{ schemaVersion: 1; runId: string; seedHex: string }>;
export type Profile = 'capacity' | 'dormant';
export type Tenant = 0 | 1;
export type CaseData = Readonly<{
  seed: AccountSeed;
  senderId: string;
  tenant: Tenant;
  index: number;
}>;
export class ModelError extends Error {
  constructor() {
    super('invalid_workload_model');
  }
}
export function experiment(value: unknown): Experiment {
  if (
    !value ||
    typeof value !== 'object' ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw new ModelError();
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (
    Reflect.ownKeys(descriptors).length !== 3 ||
    !['schemaVersion', 'runId', 'seedHex'].every(
      (k) => descriptors[k] && 'value' in descriptors[k]! && descriptors[k]!.enumerable,
    )
  )
    throw new ModelError();
  const version = descriptors.schemaVersion!.value as unknown,
    runId = descriptors.runId!.value as unknown,
    seedHex = descriptors.seedHex!.value as unknown;
  if (
    version !== 1 ||
    typeof runId !== 'string' ||
    !/^[a-f0-9]{32}(?![\s\S])/.test(runId) ||
    typeof seedHex !== 'string' ||
    !/^[a-f0-9]{64}(?![\s\S])/.test(seedHex)
  )
    throw new ModelError();
  return Object.freeze({ schemaVersion: 1, runId, seedHex });
}
export function tenant(value: number): Tenant {
  if (value !== 0 && value !== 1) throw new ModelError();
  return value;
}
function integer(value: number, maximum: number): number {
  if (!Number.isSafeInteger(value) || value < 0 || value >= maximum) throw new ModelError();
  return value;
}
export function schema(config: Experiment, profile: Profile): string {
  if (profile !== 'capacity' && profile !== 'dormant') throw new ModelError();
  return 'p2_workload_' + experiment(config).runId + '_' + profile;
}
export function provider(selected: Tenant) {
  tenant(selected);
  return Object.freeze({
    tenantId: 'workload-tenant-' + selected,
    provider: 'fake_sms',
    providerAccountId: 'workload-carrier-' + selected,
  });
}
export function secret(config: Experiment, purpose: string): Buffer {
  if (!/^[a-z0-9:_-]{1,96}(?![\s\S])/.test(purpose)) throw new ModelError();
  const copied = experiment(config);
  return createHmac('sha256', Buffer.from(copied.seedHex, 'hex'))
    .update('p2.workload.v1\n')
    .update(copied.runId)
    .update('\n')
    .update(purpose)
    .digest();
}
export function uuid(config: Experiment, purpose: string): string {
  const bytes = secret(config, purpose).subarray(0, 16);
  bytes[6] = (bytes[6]! & 15) | 64;
  bytes[8] = (bytes[8]! & 63) | 128;
  const s = bytes.toString('hex');
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`;
}
export function capacityTenant(index: number): Tenant {
  integer(index, 64);
  return index < 16
    ? tenant(index % 2)
    : index < 20 || index === 20
      ? 0
      : index < 24
        ? 1
        : tenant(index % 2);
}
export function caseData(config: Experiment, profile: Profile, index: number): CaseData {
  const count = profile === 'capacity' ? 2 : profile === 'dormant' ? 1000 : 0;
  integer(index, count);
  const selected = profile === 'capacity' ? tenant(index) : tenant(Math.floor(index / 500));
  const suffix = profile + '-' + index.toString().padStart(4, '0');
  return Object.freeze({
    tenant: selected,
    index,
    senderId: 'sender-' + suffix,
    seed: Object.freeze({
      token: secret(config, 'account:' + suffix).toString('base64url'),
      tenantId: provider(selected).tenantId,
      accountId: 'account-' + suffix,
      conversationId: 'conversation-' + suffix,
      caseId: 'case-' + suffix,
    }),
  });
}
export function message(
  config: Experiment,
  kind: Profile | 'wake' | 'rejected',
  index: number,
): Readonly<{ case: CaseData; value: FakeSmsMessage }> {
  const c =
    kind === 'capacity'
      ? caseData(config, 'capacity', capacityTenant(index))
      : kind === 'dormant'
        ? caseData(config, 'dormant', integer(index, 1000))
        : kind === 'wake'
          ? caseData(config, 'dormant', integer(index, 2) * 500)
          : kind === 'rejected'
            ? caseData(config, 'capacity', 0)
            : undefined;
  if (!c) throw new ModelError();
  const id = uuid(
    config,
    kind +
      ':event:' +
      integer(
        index,
        kind === 'capacity' ? 64 : kind === 'dormant' ? 1000 : kind === 'wake' ? 2 : 16,
      ),
  );
  return Object.freeze({
    case: c,
    value: Object.freeze({
      schemaVersion: 1,
      eventId: id,
      messageId: id,
      senderId: c.senderId,
      body:
        kind === 'capacity' && (index === 0 || index === 2)
          ? 'yes'
          : `Read-only workload${WORKLOAD_SEED} ${kind} ${index.toString().padStart(4, '0')}.`,
      occurredAt: '2030-01-01T00:00:00.000Z',
    }),
  });
}
export function windows(config: Experiment, selected: Tenant): readonly (readonly CaseData[])[] {
  tenant(selected);
  const result: (readonly CaseData[])[] = [];
  for (let offset = 0; offset < 500; offset += 64)
    result.push(
      Object.freeze(
        Array.from({ length: Math.min(64, 500 - offset) }, (_, index) =>
          caseData(config, 'dormant', selected * 500 + offset + index),
        ),
      ),
    );
  return Object.freeze(result);
}
export type Latencies = Readonly<{
  count: number;
  p50Ms: number | null;
  maximumMs: number | null;
  p95Ms?: number;
}>;
export function latencies(values: readonly number[]): Latencies {
  if (
    !Array.isArray(values) ||
    Object.getPrototypeOf(values) !== Array.prototype ||
    values.length > 2000
  )
    throw new ModelError();
  const samples: number[] = [];
  for (let index = 0; index < values.length; index++) {
    const d = Object.getOwnPropertyDescriptor(values, String(index));
    if (
      !d ||
      !('value' in d) ||
      typeof d.value !== 'number' ||
      !Number.isFinite(d.value) ||
      d.value < 0 ||
      d.value > 360000
    )
      throw new ModelError();
    samples.push(d.value);
  }
  samples.sort((a, b) => a - b);
  const count = samples.length;
  return Object.freeze({
    count,
    p50Ms: count ? samples[Math.ceil(count / 2) - 1]! : null,
    maximumMs: count ? samples[count - 1]! : null,
    ...(count >= 20 ? { p95Ms: samples[Math.ceil(count * 0.95) - 1]! } : {}),
  });
}
export function fingerprint(value: unknown): string {
  return createHash('sha256').update(JSON.stringify(value)).digest('hex');
}
