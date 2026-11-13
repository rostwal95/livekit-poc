/** Public synthetic immutable evidence for component tests only. */
import { createHash } from 'node:crypto';
import type { SpecialistConfiguration, SpecialistEvidence } from '../src/specialist-config.js';
export function evidence(source: string, value: object): SpecialistEvidence {
  const body = Buffer.from(JSON.stringify(value));
  return {
    reference: {
      source_id: source,
      version: 'source_v1',
      sha256: createHash('sha256').update(body).digest('hex'),
      media_type: 'application/json',
      byte_length: body.length,
      width: null,
      height: null,
    },
    bodyBase64: body.toString('base64'),
  };
}
export function configuration(port = 11028): SpecialistConfiguration {
  return {
    schemaVersion: 1,
    label: 'scripted',
    scope: { tenantId: 'tenant_demo', accountId: 'account_demo' },
    port,
    evidence: [
      evidence('policy_notice', {
        schema_version: 1,
        kind: 'booking.notice_policy',
        policy_version: 'notice_v1',
        rule_id: 'notice_minimum_days',
        minimum_notice_days: 7,
        note: 'Fixed scripted seven-day rule.',
      }),
      evidence('facts_notice_r1', {
        schema_version: 1,
        kind: 'booking.notice_facts',
        observations: [{ fact_id: 'notice_days', days_before_arrival: 10 }],
        note: 'Inert source prose; no authority.',
      }),
    ],
  };
}
export const bearer = 's'.repeat(43);
export function deferred<T = void>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
