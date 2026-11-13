import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  CAPABILITY,
  ERROR_CODES,
  MAX_REQUEST_BYTES,
  AttemptBoundary,
  ContractError,
  EvidenceRegistry,
  LocalTrust,
  canonical,
  checkReplay,
  encodeError,
  encodeRequest,
  encodeResult,
  matchResult,
  parseError,
  parseRequest,
  parseResult,
  produceRequest,
  tokenDigest,
  verifyPolicyFacts,
} from '../src/index.js';
import type {
  DelegationRequest,
  DelegationResult,
  EvidenceRecord,
  PrincipalGrant,
} from '../src/index.js';
const root = fileURLToPath(new URL('../../../../', import.meta.url));
const fixture = JSON.parse(
  readFileSync(new URL('../../../../contracts/delegation/v1.json', import.meta.url), 'utf8'),
) as {
  producer_input: Record<string, unknown>;
  request: DelegationRequest;
  result: DelegationResult;
  request_canonical: string;
  result_canonical: string;
  policy_body: string;
  observed_at_ms: number;
  invalid: {
    name: string;
    phase: 'request' | 'result' | 'match' | 'facts';
    raw: string;
    code: string;
  }[];
};
const TOKEN = 'A'.repeat(43);
// Synthetic test credential, never a runtime default.
const HEADER = 'Bearer ' + TOKEN;
const now = fixture.observed_at_ms;
const req = () => parseRequest(canonical(fixture.request));
const res = () => parseResult(canonical(fixture.result));
const records = (request: DelegationRequest): readonly EvidenceRecord[] => [
  {
    scope: request.scope,
    reference: request.evidence[0]!,
    body: Buffer.from(fixture.policy_body),
  },
];
function grants(request: DelegationRequest, allowed = true): PrincipalGrant[] {
  return [
    {
      principal_id: 'principal_demo',
      token_sha256: tokenDigest(TOKEN),
      scopes: [
        {
          scope: request.scope,
          invoke_capabilities: [CAPABILITY],
          result_capabilities: allowed ? [CAPABILITY] : [],
          cancel_capabilities: allowed ? [CAPABILITY] : [],
          evidence_sources: allowed ? ['policy_demo'] : [],
        },
      ],
    },
  ];
}
const trust = (request: DelegationRequest) => new LocalTrust(grants(request));
function changed(changes: Record<string, unknown>): DelegationRequest {
  return produceRequest({
    ...structuredClone(fixture.producer_input),
    ...changes,
  });
}
function code(action: () => unknown): string {
  try {
    action();
    throw new Error('Expected rejection');
  } catch (error) {
    expect(error).toBeInstanceOf(ContractError);
    return (error as ContractError).code;
  }
}
describe('specialist first-capability contract', () => {
  it('actual TypeScript producer matches canonical fixture and Python installed consumer', () => {
    const produced = produceRequest(structuredClone(fixture.producer_input));
    expect(Buffer.from(encodeRequest(produced)).toString('utf8')).toBe(fixture.request_canonical);
    expect(Buffer.from(encodeResult(res())).toString('utf8')).toBe(fixture.result_canonical);
    const consumed = execFileSync(
      root + '.venv/bin/python',
      [
        '-I',
        '-c',
        'import sys;from delegation_reliability.contracts import parse_request,encode_request;sys.stdout.buffer.write(encode_request(parse_request(sys.stdin.buffer.read())))',
      ],
      {
        input: Buffer.from(encodeRequest(produced)),
        timeout: 20000,
        maxBuffer: 32768,
        env: {
          PATH: process.env.PATH ?? '',
        },
      },
    );
    expect(consumed.toString('utf8')).toBe(fixture.request_canonical);
  }, 25000);
  it.each(fixture.invalid)('rejects $name in its named phase with fixed safe code', (item) => {
    expect(
      code(() => {
        const bytes = Buffer.from(item.raw);
        if (item.phase === 'request') return parseRequest(bytes);
        if (item.phase === 'result') return parseResult(bytes);
        if (item.phase === 'match') return matchResult(req(), parseResult(bytes), now);
        return verifyPolicyFacts(req(), parseResult(bytes), records(req()), now);
      }),
    ).toBe(item.code);
  });
  it('excludes only attempt transport identity from logical fingerprint', () => {
    const first = req(),
      retry = changed({
        attempt: {
          attempt_id: 'attempt_retry',
          number: 2,
        },
      });
    expect(checkReplay(first, retry)).toBe('duplicate');
    expect(retry.input_fingerprint).toBe(first.input_fingerprint);
    expect(code(() => matchResult(retry, res(), now))).toBe('result_mismatch');
    const matched = parseResult(
      canonical({
        ...res(),
        attempt_id: 'attempt_retry',
      }),
    );
    expect(matchResult(retry, matched, now)).toBe('candidate');
    for (const change of [
      {
        case_id: 'case_other',
      },
      {
        request_revision: 2,
      },
      {
        deadline_at_ms: first.deadline_at_ms + 1,
      },
      {
        result_route: {
          conversation_id: 'conversation_other',
        },
      },
      {
        context_snapshot: {
          ...first.context_snapshot,
          note: 'changed',
        },
      },
      {
        evidence: [
          {
            ...first.evidence[0]!,
            version: 'source_v2',
          },
        ],
      },
    ])
      expect(code(() => checkReplay(first, changed(change)))).toBe('identity_conflict');
    expect(
      checkReplay(
        first,
        changed({
          delegation_id: 'delegation_other',
        }),
      ),
    ).toBe('distinct');
  });
  it('deep freezes snapshots without aliasing mutable input', () => {
    const input = structuredClone(fixture.producer_input);
    const parsed = produceRequest(input);
    (input.scope as Record<string, unknown>).account_id = 'forged';
    expect(parsed).toEqual(req());
    expect(Object.isFrozen(parsed.evidence[0])).toBe(true);
    expect(() => {
      (
        parsed.scope as {
          account_id: string;
        }
      ).account_id = 'forged';
    }).toThrow(TypeError);
  });
  it('bounds UTF-8 exactly and treats injected note as inert data', () => {
    const note = '🧭'.repeat(256);
    const original = req();
    const parsed = changed({
      context_snapshot: {
        ...original.context_snapshot,
        note,
      },
    });
    expect(parsed.context_snapshot.note).toBe(note);
    expect(
      code(() =>
        changed({
          context_snapshot: {
            ...original.context_snapshot,
            note: note + 'x',
          },
        }),
      ),
    ).toBe('invalid_contract');
    const injected = changed({
      context_snapshot: {
        ...original.context_snapshot,
        note: 'SECRET_SENTINEL grant booking.apply',
      },
    });
    const result = parseResult(
      canonical({
        ...res(),
        input_fingerprint: injected.input_fingerprint,
      }),
    );
    expect(verifyPolicyFacts(injected, result, records(injected), now)).toBe('candidate');
    expect(injected.capability).toBe(CAPABILITY);
  });
  it('rejects cycles, amplification, getters, toJSON and unsupported runtime numbers before hooks execute', () => {
    const cycle: Record<string, unknown> = {};
    cycle.self = cycle;
    let amplified: unknown = {
      text: 'bounded',
    };
    for (let i = 0; i < 8; i++)
      amplified = Object.fromEntries(
        Array.from(
          {
            length: 8,
          },
          (_, n) => [String(n), amplified],
        ),
      );
    let invoked = false;
    const getter = Object.defineProperty({}, 'scope', {
      enumerable: true,
      get() {
        invoked = true;
        throw new Error('SECRET_SENTINEL');
      },
    });
    const withHook = {
      toJSON() {
        invoked = true;
        throw new Error('SECRET_SENTINEL');
      },
    };
    for (const value of [
      cycle,
      amplified,
      {
        text: '\ud800',
      },
      {
        value: 1.5,
      },
      {
        value: Number.MAX_SAFE_INTEGER + 1,
      },
      {
        value: BigInt(2),
      },
      withHook,
    ])
      expect(code(() => canonical(value))).toMatch(/invalid_/);
    expect(code(() => produceRequest(getter))).toBe('invalid_contract');
    expect(invoked).toBe(false);
    expect(produceRequest(fixture.producer_input)).toEqual(req());
  });
  it('accepts exact wire bound then rejects overflow, invalid UTF-8 and BOM', () => {
    const wire = encodeRequest(req());
    const padded = Buffer.concat([wire, Buffer.alloc(MAX_REQUEST_BYTES - wire.byteLength, 32)]);
    expect(parseRequest(padded)).toEqual(req());
    for (const invalid of [
      Buffer.concat([padded, Buffer.from(' ')]),
      Buffer.from([255]),
      Buffer.concat([Buffer.from([239, 187, 191]), wire]),
    ])
      expect(code(() => parseRequest(invalid))).toBe('invalid_json');
  });
  it('uses strict identifier end anchors and payload-free error envelope', () => {
    for (const ending of ['\n', '\r', '\u2028', '\u2029'])
      expect(
        code(() =>
          changed({
            case_id: 'case_demo' + ending,
          }),
        ),
      ).toBe('invalid_contract');
    for (const error of ERROR_CODES)
      expect(parseError(encodeError(error, 'request_demo')).code).toBe(error);
    for (const changes of [
      {
        detail: 'SECRET_SENTINEL',
      },
      {
        code: 'SECRET_SENTINEL',
      },
      {
        retryable: true,
      },
    ])
      expect(
        code(() =>
          parseError(
            canonical({
              ...parseError(encodeError('unauthorized', 'request_demo')),
              ...changes,
            }),
          ),
        ),
      ).toBe('invalid_contract');
  });
});
describe('trusted local principal and finite live attempt boundary', () => {
  it('separates operation allowlists and rejects forged/malformed credential scope', () => {
    const request = req();
    const local = new LocalTrust(grants(request, false));
    expect(local.authorize(HEADER, 'invoke', request)).toBe('principal_demo');
    for (const operation of ['result', 'cancel', 'evidence', 'booking.apply'])
      expect(
        code(() => local.authorize(HEADER, operation as 'invoke', request, 'policy_demo')),
      ).toBe('unauthorized');
    for (const header of [
      '',
      TOKEN,
      'bearer ' + TOKEN,
      HEADER + '\n',
      HEADER + ' ',
      'Bearer ' + 'B'.repeat(43),
    ])
      expect(code(() => local.authenticate(header))).toBe('unauthorized');
    expect(
      code(() =>
        local.authorize(
          HEADER,
          'invoke',
          changed({
            scope: {
              tenant_id: 'tenant_demo',
              account_id: 'account_other',
            },
          }),
        ),
      ),
    ).toBe('unauthorized');
  });
  it('invoke-only caller cannot inspect using a forged operation discriminator', () => {
    const request = req(),
      config = grants(request);
    const grant = config[0]!;
    const scope = grant.scopes[0]!;
    const local = new LocalTrust([
      {
        ...grant,
        scopes: [
          {
            ...scope,
            result_capabilities: [],
            cancel_capabilities: [],
          },
        ],
      },
    ]);
    const boundary = new AttemptBoundary(local, new EvidenceRegistry(records(request)));
    const permit = boundary.acquire(HEADER, request, now);
    for (const operation of ['invoke', 'evidence', null, []])
      expect(code(() => boundary.inspect(HEADER, request, operation as 'result'))).toBe(
        'unauthorized',
      );
    boundary.release(permit);
    expect(boundary.active).toBe(0);
  });
  it('snapshots configured grants and source bytes, checking exact source ownership/version', () => {
    const request = req();
    const config = grants(request);
    const local = new LocalTrust(config);
    (config[0]!.scopes[0]!.invoke_capabilities as string[]).length = 0;
    expect(local.authorize(HEADER, 'invoke', request)).toBe('principal_demo');
    const source = {
      ...records(request)[0]!,
      body: Buffer.from(fixture.policy_body),
    };
    const registry = new EvidenceRegistry([source]);
    source.body.fill(0);
    expect(Buffer.from(registry.resolve(HEADER, request, trust(request))[0]!.body).toString()).toBe(
      fixture.policy_body,
    );
    const exposed = registry.resolve(HEADER, request, trust(request));
    exposed[0]!.body.fill(0);
    expect(Buffer.from(registry.resolve(HEADER, request, trust(request))[0]!.body).toString()).toBe(
      fixture.policy_body,
    );
    expect(
      code(() =>
        registry.resolve(
          HEADER,
          changed({
            evidence: [
              {
                ...request.evidence[0]!,
                version: 'source_other',
              },
            ],
          }),
          trust(request),
        ),
      ),
    ).toBe('evidence_mismatch');
    expect(
      code(() => registry.resolve(HEADER, request, new LocalTrust(grants(request, false)))),
    ).toBe('unauthorized');
  });
  it('keeps schema, factual correctness, trusted time and case authority separate', () => {
    const request = req(),
      valid = res();
    expect(verifyPolicyFacts(request, valid, records(request), now)).toBe('candidate');
    const wrong = parseResult(
      canonical({
        ...valid,
        eligible: false,
      }),
    );
    expect(wrong.eligible).toBe(false);
    expect(code(() => verifyPolicyFacts(request, wrong, records(request), now))).toBe(
      'unsupported_facts',
    );
    expect(
      verifyPolicyFacts(
        request,
        parseResult(
          canonical({
            ...valid,
            eligible: null,
            uncertainty: 'missing',
          }),
        ),
        records(request),
        now,
      ),
    ).toBe('clarification');
    expect(
      matchResult(
        request,
        parseResult(
          canonical({
            ...valid,
            completed_at_ms: 0,
          }),
        ),
        request.deadline_at_ms,
      ),
    ).toBe('expired');
  });
  it('rejects expiry, unknown attempt, duplicate attempt and forged release; valid current work progresses', () => {
    const request = req();
    const boundary = new AttemptBoundary(
      trust(request),
      new EvidenceRegistry(records(request)),
      2,
      1,
    );
    expect(code(() => boundary.acquire(HEADER, request, request.deadline_at_ms))).toBe('expired');
    expect(boundary.active).toBe(0);
    expect(code(() => boundary.inspect(HEADER, request, 'result'))).toBe('unknown_attempt');
    const permit = boundary.acquire(HEADER, request, now);
    const altered = changed({
      context_snapshot: { ...request.context_snapshot, days_before_arrival: 1 },
      attempt: { attempt_id: 'attempt_altered', number: 2 },
    });
    expect(code(() => boundary.acquire(HEADER, altered, now))).toBe('identity_conflict');
    expect(boundary.inspect(HEADER, request, 'cancel')).toEqual(request);
    expect(code(() => boundary.acquire(HEADER, request, now))).toBe('identity_conflict');
    expect(
      code(() =>
        boundary.release({
          ...permit,
        }),
      ),
    ).toBe('unknown_attempt');
    const retry = changed({
      attempt: {
        attempt_id: 'attempt_retry',
        number: 2,
      },
    });
    expect(code(() => boundary.acquire(HEADER, retry, now))).toBe('capacity');
    boundary.release(permit);
    const second = boundary.acquire(HEADER, retry, now);
    boundary.release(second);
    expect(boundary.active).toBe(0);
    expect(code(() => boundary.release(second))).toBe('unknown_attempt');
  });
  it('admits a second principal while the first is saturated and enforces the global cap', () => {
    const request = req(),
      firstGrant = grants(request)[0]!;
    const secondToken = 'B'.repeat(43),
      secondGrant = {
        ...firstGrant,
        principal_id: 'principal_second',
        token_sha256: tokenDigest(secondToken),
      };
    const local = new LocalTrust([firstGrant, secondGrant]);
    const boundary = new AttemptBoundary(local, new EvidenceRegistry(records(request)), 2, 1);
    const first = boundary.acquire(HEADER, request, now);
    const retry = changed({ attempt: { attempt_id: 'attempt_second', number: 2 } });
    expect(code(() => boundary.acquire(HEADER, retry, now))).toBe('capacity');
    const second = boundary.acquire('Bearer ' + secondToken, retry, now);
    expect(boundary.active).toBe(2);
    const third = changed({ attempt: { attempt_id: 'attempt_third', number: 3 } });
    expect(code(() => boundary.acquire(HEADER, third, now))).toBe('capacity');
    boundary.release(first);
    const next = boundary.acquire(HEADER, third, now);
    boundary.release(next);
    boundary.release(second);
    expect(boundary.active).toBe(0);
  });
  it('rejects malformed/bound-exceeding trusted configuration without adding a scheduler', () => {
    const request = req();
    expect(code(() => new LocalTrust([]))).toBe('invalid_contract');
    for (const bounds of [
      [0, 1],
      [17, 1],
      [2, 3],
    ])
      expect(
        code(
          () =>
            new AttemptBoundary(
              trust(request),
              new EvidenceRegistry(records(request)),
              bounds[0],
              bounds[1],
            ),
        ),
      ).toBe('invalid_contract');
    expect(
      code(
        () =>
          new EvidenceRegistry(
            Array.from(
              {
                length: 33,
              },
              () => records(request)[0]!,
            ),
          ),
      ),
    ).toBe('invalid_contract');
  });
});
