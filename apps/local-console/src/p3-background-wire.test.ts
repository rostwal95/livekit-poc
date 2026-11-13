import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  nativeErrorCode,
  parseNativeBinding,
  parseNativeJson,
  parseNativeObservation,
  parseNativeSession,
  projectNativeObservation,
} from './p3-background-wire';
const hash = (n: number) => String(n).repeat(64);
function fixture() {
  const binding = {
    scope: { tenant_id: 'tenant_demo', account_id: 'account_demo' },
    case_id: 'case_demo',
    delegation_id: 'delegation_demo',
    request_revision: 1,
    input_fingerprint: hash(3),
    sources: [
      {
        role: 'policy',
        source_id: 'policy_source',
        version: 'record_v9',
        sha256: hash(1),
        byte_length: 128,
      },
      {
        role: 'facts',
        source_id: 'facts_source',
        version: 'record_v7',
        sha256: hash(2),
        byte_length: 96,
      },
    ],
  };
  const session = {
    schema_version: 1,
    kind: 'native-policy.session',
    session_id: '33333333-3333-4333-8333-333333333333',
    binding,
    server_url: 'ws://127.0.0.1:17880',
    room_name: 'p3_native_demo',
    participant_identity: 'p3_viewer_demo',
    agent_identity: 'p3_agent_demo',
    rtc_token: 'aaa.bbb.ccc',
    profile: 'p3_native_policy_text_v1',
    inference_mode: 'scripted',
    expires_at_ms: 1794480060000,
  };
  const attempt = { attempt_id: '22222222-2222-4222-8222-222222222222', number: 1 };
  const result = {
    ...attempt,
    wire_attempt_id: 'attempt_22222222222242228222222222222222',
    sha256: hash(5),
    recorded_at_ms: 1794480000100,
    disposition: 'eligible_at_commit',
    eligible: true as boolean | null,
    uncertainty: 'none',
    fact_refs: [
      {
        source_id: 'facts_source',
        version: 'record_v7',
        sha256: hash(2),
        fact_id: 'notice_primary',
        days_before_arrival: 8,
      },
    ],
    rule_refs: [
      {
        source_id: 'policy_source',
        version: 'record_v9',
        sha256: hash(1),
        rule_id: 'notice_minimum_days',
        minimum_notice_days: 7,
      },
    ],
  };
  const { number: _number, ...onlyResult } = result;
  void _number;
  const observation = {
    schema_version: 1,
    kind: 'native-policy.observation',
    binding,
    state: 'result',
    work: {
      work_id: '11111111-1111-4111-8111-111111111111',
      request_sha256: hash(4),
      accepted_at_ms: 1794480000000,
      status: 'result_recorded',
      cancel_requested: false,
    },
    attempt,
    result: onlyResult,
    applicability: 'candidate',
    tool_waiter: 'returned',
    owned_run: false,
    error: null as string | null,
    consistency: 'as_of_non_atomic',
    app_read_completed_at_ms: 1794480000101,
  };
  return { session, observation };
}
function decode(value: unknown, max = 4096) {
  return parseNativeJson(JSON.stringify(value), max);
}
describe('closed P3 native wire', () => {
  it('joins the full result and every source witness to the mint binding, preserving independent record versions', () => {
    const f = fixture(),
      session = parseNativeSession(decode(f.session, 8192)),
      observation = parseNativeObservation(decode(f.observation), session.binding);
    expect(observation).toEqual(f.observation);
    expect(Object.isFrozen(observation.result?.fact_refs[0])).toBe(true);
    expect(projectNativeObservation(observation).facts).toContainEqual({
      label: 'Application read completed',
      value: '2026-11-12T10:40:00.101Z',
    });
  });
  it.each(['missing', 'conflicting'] as const)(
    'preserves valid %s clarification with null eligibility',
    (uncertainty) => {
      const f = fixture();
      f.observation.result.eligible = null;
      f.observation.result.uncertainty = uncertainty;
      f.observation.applicability = 'clarification';
      if (uncertainty === 'missing') f.observation.result.fact_refs = [];
      else
        f.observation.result.fact_refs.push({
          ...f.observation.result.fact_refs[0]!,
          fact_id: 'notice_second',
          days_before_arrival: 6,
        });
      expect(
        parseNativeObservation(decode(f.observation), parseNativeSession(f.session).binding).result
          ?.eligible,
      ).toBeNull();
    },
  );
  it('preserves original result/disposition when applicability is outdated without inventing a current revision', () => {
    const f = fixture();
    f.observation.state = 'outdated';
    f.observation.applicability = 'outdated';
    const parsed = parseNativeObservation(
      decode(f.observation),
      parseNativeSession(f.session).binding,
    );
    expect(parsed.binding.request_revision).toBe(1);
    expect(parsed.result).toEqual(f.observation.result);
    expect(projectNativeObservation(parsed).heading).toBe('Historical result · outdated');
  });
  it.each([
    (v: ReturnType<typeof fixture>) => {
      v.observation.binding.case_id = 'foreign';
    },
    (v: ReturnType<typeof fixture>) => {
      v.observation.result.fact_refs[0]!.sha256 = hash(9);
    },
    (v: ReturnType<typeof fixture>) => {
      v.observation.result.fact_refs[0]!.version = 'foreign';
    },
    (v: ReturnType<typeof fixture>) => {
      v.observation.result.wire_attempt_id = 'attempt_foreign';
    },
    (v: ReturnType<typeof fixture>) => {
      v.observation.attempt.attempt_id = '44444444-4444-4444-8444-444444444444';
    },
  ])('rejects a foreign source, binding or attempt correlation', (change) => {
    const f = fixture(),
      expected = parseNativeSession(structuredClone(f.session)).binding;
    change(f);
    expect(() => parseNativeObservation(decode(f.observation), expected)).toThrowError('invalid');
  });
  it('rejects malformed clarification and duplicate witnesses', () => {
    const f = fixture();
    f.observation.result.eligible = null;
    expect(() =>
      parseNativeObservation(decode(f.observation), parseNativeSession(f.session).binding),
    ).toThrowError('invalid');
    f.observation.result.eligible = true;
    f.observation.result.fact_refs.push({ ...f.observation.result.fact_refs[0]! });
    expect(() =>
      parseNativeObservation(decode(f.observation), parseNativeSession(f.session).binding),
    ).toThrowError('invalid');
  });
  it('accepts a fresh unknown capacity observation only with no fresh workflow facts', () => {
    const f = fixture(),
      value = {
        ...f.observation,
        state: 'unknown',
        error: 'capacity',
        work: null,
        attempt: null,
        result: null,
        applicability: null,
      };
    expect(parseNativeObservation(decode(value), parseNativeSession(f.session).binding).error).toBe(
      'capacity',
    );
    expect(() =>
      parseNativeObservation(
        decode({ ...value, result: f.observation.result }),
        parseNativeSession(f.session).binding,
      ),
    ).toThrowError('invalid');
  });
  it.each([
    '{"a":1,"a":2}',
    '{"a":1,"\\u0061":2}',
    '{"a":"\\ud800"}',
    '{"a":1e999}',
    '['.repeat(9) + '0' + ']'.repeat(9),
    JSON.stringify(Array.from({ length: 257 }, () => 0)),
  ])('rejects duplicate, invalid unicode/nonfinite or excessive shape', (wire) => {
    expect(() => parseNativeJson(wire, 4096)).toThrowError('invalid');
  });
  it('accepts equivalent key ordering and whitespace, while enforcing total UTF-8 bytes', () => {
    expect(parseNativeJson(' { "b": 2, "a": 1 } ', 32)).toEqual({ b: 2, a: 1 });
    expect(() => parseNativeJson('"' + 'é'.repeat(2048) + '"', 4096)).toThrowError('invalid');
  });
  it('rejects getters before evaluating them and never reflects a sentinel', () => {
    const f = fixture(),
      getter = Object.defineProperty({ ...f.session }, 'rtc_token', {
        get: () => {
          throw new Error('PRIVATE_SENTINEL');
        },
        enumerable: true,
      });
    expect(() => parseNativeSession(getter)).toThrowError('invalid');
    expect(() => parseNativeSession({ ...f.session, extra: 'PRIVATE_SENTINEL' })).toThrowError(
      'invalid',
    );
  });
  it.each([
    'ws://example.com:7880',
    'wss://localhost:7880',
    'ws://127.0.0.1:99999',
    'ws://localhost:7880/?token=secret',
    'ws://localhost:7880/path',
  ])('rejects a foreign or malformed RTC endpoint without a raw URL error', (server_url) => {
    expect(() => parseNativeSession({ ...fixture().session, server_url })).toThrowError('invalid');
  });
  it.each([
    [401, 'unauthorized', 'access_denied'],
    [403, 'forbidden', 'access_denied'],
    [400, 'invalid_request', 'invalid'],
    [404, 'invalid_request', 'invalid'],
    [405, 'invalid_request', 'invalid'],
    [503, 'closed', 'closed'],
    [503, 'unavailable', 'unavailable'],
  ] as const)('joins safe HTTP status %i to %s', (status, code, expected) => {
    expect(nativeErrorCode({ schema_version: 1, kind: 'native-policy.error', code }, status)).toBe(
      expected,
    );
  });
  it('rejects wrong HTTP status/code pairs and unknown response fields', () => {
    expect(() =>
      nativeErrorCode(
        { schema_version: 1, kind: 'native-policy.error', code: 'unauthorized' },
        200,
      ),
    ).toThrowError('invalid');
    expect(() =>
      parseNativeObservation(
        { ...fixture().observation, extra: 1 },
        parseNativeSession(fixture().session).binding,
      ),
    ).toThrowError('invalid');
  });
});

// Shared actual deterministic producer rows; these are contract examples, not PG/RTC evidence.
const shared = JSON.parse(
  readFileSync(
    new URL('../../../contracts/delegation/native-policy-view-v1.json', import.meta.url),
    'utf8',
  ),
) as { session: unknown; observations: Record<string, { binding: unknown }> };
describe('shared NativePolicyApplication wire examples', () => {
  for (const name of ['candidate', 'missing', 'conflicting', 'no_work'])
    it(`consumes actual producer ${name} row without adapting it`, () => {
      const value = shared.observations[name]!;
      expect(
        parseNativeObservation(
          parseNativeJson(JSON.stringify(value), 4096),
          parseNativeBinding(value.binding),
        ),
      ).toEqual(value);
    });
  it('joins the shared synthetic mint binding to the actual candidate row', () => {
    const session = parseNativeSession(parseNativeJson(JSON.stringify(shared.session), 8192));
    expect(parseNativeObservation(shared.observations.candidate, session.binding).binding).toEqual(
      session.binding,
    );
  });
});

describe('Python NativePolicyObservation literal parity', () => {
  it.each([
    [10, false],
    [6, true],
  ] as const)('rejects contradictory notice days%i / eligible%s', (days, eligible) => {
    const f = fixture();
    f.observation.result.fact_refs[0]!.days_before_arrival = days;
    f.observation.result.eligible = eligible;
    expect(() =>
      parseNativeObservation(decode(f.observation), parseNativeSession(f.session).binding),
    ).toThrowError('invalid');
  });
  it('rejects a result_recorded work observation with no result', () => {
    const f = fixture();
    const value = { ...f.observation, state: 'work', result: null, applicability: 'missing' };
    expect(() =>
      parseNativeObservation(decode(value), parseNativeSession(f.session).binding),
    ).toThrowError('invalid');
  });
  it('rejects result_recorded paired with a noneligible original disposition', () => {
    const f = fixture();
    f.observation.result.disposition = 'expired';
    expect(() =>
      parseNativeObservation(decode(f.observation), parseNativeSession(f.session).binding),
    ).toThrowError('invalid');
  });
});
