/** Independent static-image factual oracle tests; reviewed 12 November 2026. */
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { ContractError, canonical } from '../src/contracts.js';
import {
  DOCUMENT_FIELDS,
  encodeDocumentRequest,
  encodeDocumentResult,
  matchDocumentResult,
  parseDocumentRequest,
  parseDocumentResult,
  produceDocumentRequest,
} from '../src/document-contracts.js';
import type { DocumentResult } from '../src/document-contracts.js';

const root = fileURLToPath(new URL('../../../../', import.meta.url));
const directory = new URL('../../../../contracts/delegation/', import.meta.url);
const load = (name: string): unknown => JSON.parse(readFileSync(new URL(name, directory), 'utf8'));
type Region = Readonly<{ x: number; y: number; width: number; height: number }>;
type Expected = Readonly<{
  outcome: string;
  source: Readonly<{ source_id: string; version: string; sha256: string }>;
  fields: Readonly<
    Record<string, Readonly<{ state: string; value: string | null; regions: readonly Region[] }>>
  >;
}>;
type Patch = Readonly<{
  op: 'set' | 'copy';
  path: readonly string[];
  value?: unknown;
  from?: readonly string[];
}>;
type Adversarial = Readonly<{
  name: string;
  phase: 'request' | 'result' | 'match' | 'facts';
  patches: readonly Patch[];
  code: string;
}>;
const fixture = load('document-v1.json') as {
  observed_at_ms: number;
  producer_input: Record<string, unknown>;
  request: Record<string, unknown>;
  result: Record<string, unknown>;
  canonical: { request_utf8: string; result_utf8: string };
};
const corpus = load('document-adversarial-v1.json') as {
  schema_version: number;
  cases: readonly Adversarial[];
};
const expected = load('documents/expected-v1.json') as {
  fixtures: Readonly<Record<string, Expected>>;
};
const fieldNames = ['booking_reference', 'property_name', 'check_in', 'check_out'] as const;

function changed(base: unknown, patches: readonly Patch[]): Record<string, unknown> {
  const result = structuredClone(base) as Record<string, unknown>;
  const get = (path: readonly string[]): unknown => {
    let node: unknown = result;
    for (const key of path) {
      if (node === null || typeof node !== 'object') throw new Error('invalid_test_patch');
      node = (node as Record<string, unknown>)[key];
    }
    return node;
  };
  for (const patch of patches) {
    const node = get(patch.path.slice(0, -1));
    if (node === null || typeof node !== 'object' || !patch.path.length)
      throw new Error('invalid_test_patch');
    const replacement = structuredClone(patch.op === 'set' ? patch.value : get(patch.from!));
    (node as Record<string, unknown>)[patch.path.at(-1)!] = replacement;
  }
  return result;
}

/** Test-only literal witness comparison; no model reasoning or business authority. */
function assertFixtureFacts(result: DocumentResult, literal: Expected): void {
  const fail = (): never => {
    throw new ContractError('unsupported_facts');
  };
  if (result.outcome !== literal.outcome) fail();
  if (Object.keys(result.fields).sort().join('|') !== [...fieldNames].sort().join('|')) fail();
  for (const name of fieldNames) {
    const actual = result.fields[name],
      truth = literal.fields[name]!;
    if (
      actual.state !== truth.state ||
      actual.value !== truth.value ||
      actual.evidence_refs.length !== truth.regions.length
    )
      fail();
    for (let index = 0; index < truth.regions.length; index++) {
      const witness = actual.evidence_refs[index]!,
        region = truth.regions[index]!;
      if (
        witness.source_id !== literal.source.source_id ||
        witness.version !== literal.source.version ||
        witness.sha256 !== literal.source.sha256
      )
        fail();
      if (Object.keys(witness.region).sort().join('|') !== 'height|width|x|y') fail();
      for (const key of ['x', 'y', 'width', 'height'] as const)
        if (!Number.isInteger(witness.region[key]) || witness.region[key] !== region[key]) fail();
    }
  }
}
function code(action: () => unknown): string {
  try {
    action();
  } catch (error) {
    expect(error).toBeInstanceOf(ContractError);
    return (error as ContractError).code;
  }
  throw new Error('expected_public_rejection');
}

describe('independent document fixture facts and shared adversarial data', () => {
  it('keeps the exact four-field request and literal complete-image facts', () => {
    expect(DOCUMENT_FIELDS).toEqual(fieldNames);
    const request = produceDocumentRequest(structuredClone(fixture.producer_input));
    const result = parseDocumentResult(canonical(fixture.result));
    expect(Buffer.from(encodeDocumentRequest(request)).toString('utf8')).toBe(
      fixture.canonical.request_utf8,
    );
    expect(Buffer.from(encodeDocumentResult(result)).toString('utf8')).toBe(
      fixture.canonical.result_utf8,
    );
    expect(matchDocumentResult(request, result, fixture.observed_at_ms)).toBe('candidate');
    assertFixtureFacts(result, expected.fixtures.complete!);
  });

  it('sends actual TypeScript producer bytes to the public Python consumer', () => {
    const request = produceDocumentRequest(structuredClone(fixture.producer_input));
    const consumed = execFileSync(
      root + '.venv/bin/python',
      [
        '-I',
        '-c',
        'import sys;from delegation_reliability.document_contracts import parse_document_request,encode_document_request;sys.stdout.buffer.write(encode_document_request(parse_document_request(sys.stdin.buffer.read())))',
      ],
      {
        input: Buffer.from(encodeDocumentRequest(request)),
        timeout: 20000,
        maxBuffer: 32768,
        env: { PATH: process.env.PATH ?? '' },
      },
    );
    expect(consumed.toString('utf8')).toBe(fixture.canonical.request_utf8);
  }, 25000);

  it('retains distinct structural, correlation and factual negative phases', () => {
    expect(corpus.schema_version).toBe(1);
    expect(corpus.cases.length).toBeGreaterThanOrEqual(29);
    expect(new Set(corpus.cases.map((item) => item.name)).size).toBe(corpus.cases.length);
    expect(new Set(corpus.cases.map((item) => item.phase))).toEqual(
      new Set(['request', 'result', 'match', 'facts']),
    );
    expect(Object.keys(expected.fixtures).sort()).toEqual([
      'adversarial',
      'ambiguous',
      'complete',
      'missing',
      'other-source',
    ]);
  });

  it.each(corpus.cases)('rejects $name at its declared public/test-only boundary', (item) => {
    const value = changed(
      item.phase === 'request' ? fixture.request : fixture.result,
      item.patches,
    );
    expect(
      code(() => {
        if (item.phase === 'request') return parseDocumentRequest(canonical(value));
        const result = parseDocumentResult(canonical(value));
        if (item.phase === 'match')
          return matchDocumentResult(
            parseDocumentRequest(canonical(fixture.request)),
            result,
            fixture.observed_at_ms,
          );
        if (item.phase === 'facts') return assertFixtureFacts(result, expected.fixtures.complete!);
        return result;
      }),
    ).toBe(item.code);
  });

  it.each(corpus.cases.filter((item) => item.phase === 'facts'))(
    'structurally parses $name before the independent factual verdict',
    (item) => {
      const result = parseDocumentResult(canonical(changed(fixture.result, item.patches)));
      if (
        [
          'schema_valid_wrong_value_is_not_factual',
          'schema_valid_swapped_region_is_not_factual',
        ].includes(item.name)
      ) {
        expect(
          matchDocumentResult(
            parseDocumentRequest(canonical(fixture.request)),
            result,
            fixture.observed_at_ms,
          ),
        ).toBe('candidate');
      }
      expect(code(() => assertFixtureFacts(result, expected.fixtures.complete!))).toBe(
        'unsupported_facts',
      );
    },
  );
});
