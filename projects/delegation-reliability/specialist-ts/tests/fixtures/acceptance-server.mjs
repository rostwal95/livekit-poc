/** Explicit bounded acceptance fixture: product server plus intentionally invalid peer. */
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import {
  CAPABILITY,
  ContractError,
  EvidenceRegistry,
  LocalTrust,
  SpecialistServer,
  canonical,
  encodeResult,
  matchResult,
  parseRequest,
  parseResult,
  produceRequest,
  tokenDigest,
  verifyPolicyFacts,
} from '@livekit-ecosystem/delegation-specialist';
const CODEC_CASES = [
  'malformed_output',
  'wrong_revision',
  'unsupported_schema',
  'mismatched_tenant',
  'oversized_result',
  'oversized_context',
  'oversized_request',
  'oversized_image',
  'evidence_facts',
];
function expectFailure(run, expected) {
  try {
    run();
  } catch (error) {
    if (!(error instanceof ContractError) || error.code !== expected || error.message !== expected)
      throw new Error('unsafe_rejection');
    return;
  }
  throw new Error('missing_rejection');
}
function checks(fixture) {
  const request = parseRequest(Buffer.from(fixture.request_canonical));
  const result = parseResult(Buffer.from(fixture.result_canonical));
  expectFailure(() => parseResult(Buffer.from('{"SECRET_SENTINEL":')), 'invalid_json');
  expectFailure(
    () =>
      matchResult(
        request,
        parseResult(canonical({ ...result, request_revision: 2 })),
        fixture.observed_at_ms,
      ),
    'result_mismatch',
  );
  expectFailure(
    () => parseResult(canonical({ ...result, result_schema_version: 2 })),
    'unsupported_version',
  );
  expectFailure(
    () => produceRequest({ ...fixture.producer_input, input_schema_version: 2 }),
    'unsupported_version',
  );
  expectFailure(
    () =>
      matchResult(
        request,
        parseResult(
          canonical({
            ...result,
            scope: { tenant_id: 'tenant_other', account_id: request.scope.account_id },
          }),
        ),
        fixture.observed_at_ms,
      ),
    'result_mismatch',
  );
  expectFailure(() => parseResult(Buffer.alloc(8193, 32)), 'invalid_json');
  expectFailure(
    () =>
      produceRequest({
        ...fixture.producer_input,
        context_snapshot: { ...request.context_snapshot, note: 'x'.repeat(1025) },
      }),
    'invalid_contract',
  );
  expectFailure(() => parseRequest(Buffer.alloc(16385, 32)), 'invalid_json');
  const image = {
    source_id: 'image_demo',
    version: 'source_v1',
    sha256: 'a'.repeat(64),
    media_type: 'image/png',
    byte_length: 2097153,
    width: 1,
    height: 1,
  };
  expectFailure(
    () => produceRequest({ ...fixture.producer_input, evidence: [image] }),
    'invalid_contract',
  );
  expectFailure(
    () =>
      produceRequest({
        ...fixture.producer_input,
        evidence: [{ ...image, byte_length: 1, width: 2049 }],
      }),
    'invalid_contract',
  );
  expectFailure(
    () =>
      new EvidenceRegistry([
        { scope: request.scope, reference: image, body: Buffer.alloc(2097153) },
      ]),
    'invalid_contract',
  );
  const records = [
    {
      scope: request.scope,
      reference: request.evidence[0],
      body: Buffer.from(fixture.policy_body),
    },
  ];
  expectFailure(
    () =>
      verifyPolicyFacts(
        request,
        parseResult(canonical({ ...result, eligible: false })),
        records,
        fixture.observed_at_ms,
      ),
    'unsupported_facts',
  );
  expectFailure(
    () =>
      verifyPolicyFacts(
        request,
        parseResult(
          canonical({
            ...result,
            evidence_refs: [{ ...result.evidence_refs[0], sha256: 'a'.repeat(64) }],
          }),
        ),
        records,
        fixture.observed_at_ms,
      ),
    'evidence_mismatch',
  );
  if (verifyPolicyFacts(request, result, records, fixture.observed_at_ms) !== 'candidate')
    throw new Error('positive_failed');
  return CODEC_CASES;
}
async function main() {
  const token = process.env.P3_ACCEPT_TOKEN;
  const ready = process.env.P3_ACCEPT_READY;
  const endpointFile = process.env.P3_ACCEPT_ENDPOINT_FILE;
  const stop = process.env.P3_ACCEPT_STOP;
  const fixturePath = process.env.P3_ACCEPT_FIXTURE;
  const selected = process.env.P3_ACCEPT_CASE_ID;
  if (
    !/^[A-Za-z0-9_-]{43}$/.test(token ?? '') ||
    !['P3-03', 'P3-11'].includes(selected) ||
    [ready, endpointFile, stop, fixturePath].some((v) => !v || v.length > 4096)
  )
    throw new Error('fixture_configuration');
  const fixture = JSON.parse(readFileSync(fixturePath, 'utf8'));
  const codecCases = selected === 'P3-11' ? checks(fixture) : [];
  const scope = Object.freeze({ tenant_id: 'tenant_p3', account_id: 'account_p3' });
  const body = canonical({ minimum_notice_days: 7, policy_version: 'policy_v1' });
  const reference = Object.freeze({
    source_id: 'policy_demo',
    version: 'source_v1',
    sha256: createHash('sha256').update(body).digest('hex'),
    media_type: 'application/json',
    byte_length: body.length,
    width: null,
    height: null,
  });
  const trust = new LocalTrust([
    {
      principal_id: 'acceptance_service',
      token_sha256: tokenDigest(token),
      scopes: [
        {
          scope,
          invoke_capabilities: [CAPABILITY],
          result_capabilities: [CAPABILITY],
          cancel_capabilities: [CAPABILITY],
          evidence_sources: [reference.source_id],
        },
      ],
    },
  ]);
  let evaluations = 0,
    invalidResponses = 0,
    rawRequests = 0;
  const sockets = new Set();
  const invalidCases = [];
  const server = new SpecialistServer({
    trust,
    evidence: new EvidenceRegistry([{ scope, reference, body }]),
    observer: () => {},
    hooks: {
      beforeEvaluate: async () => {
        evaluations++;
      },
    },
  });
  const invalid = createServer({ maxHeaderSize: 8192 }, (request, response) => {
    rawRequests++;
    let size = 0;
    const chunks = [];
    request.on('data', (chunk) => {
      size += chunk.length;
      if (size > 16384) request.destroy();
      else chunks.push(chunk);
    });
    request.on('end', () => {
      if (
        request.headers.authorization !== 'Bearer ' + token ||
        request.url !== '/v1/invoke' ||
        request.method !== 'POST'
      ) {
        response.writeHead(403, { Connection: 'close', 'Content-Length': '0' });
        response.end();
        return;
      }
      const incoming = parseRequest(Buffer.concat(chunks));
      const result = {
        ...fixture.result,
        scope: incoming.scope,
        delegation_id: incoming.delegation_id,
        case_id: incoming.case_id,
        request_revision: incoming.request_revision,
        attempt_id: incoming.attempt.attempt_id,
        input_fingerprint: incoming.input_fingerprint,
        completed_at_ms: Date.now(),
      };
      const index = invalidResponses++;
      if (incoming.delegation_id !== `delegation_negative_${index}`)
        throw new Error('wrong_variant_binding');
      invalidCases.push(CODEC_CASES[index]);
      let wire;
      if (index === 0) wire = Buffer.from('{"SECRET_SENTINEL":');
      else if (index === 1)
        wire = encodeResult(
          parseResult(canonical({ ...result, request_revision: incoming.request_revision + 1 })),
        );
      else if (index === 2) wire = canonical({ ...result, result_schema_version: 2 });
      else if (index === 3)
        wire = encodeResult(
          parseResult(
            canonical({ ...result, scope: { ...incoming.scope, tenant_id: 'tenant_other' } }),
          ),
        );
      else if (index === 4) wire = Buffer.alloc(8193, 32);
      else throw new Error('unexpected_invalid_request');
      response.writeHead(200, {
        'Content-Type': 'application/json',
        'Content-Length': String(wire.length),
        Connection: 'close',
      });
      response.end(wire);
    });
  });
  invalid.requestTimeout = 2000;
  invalid.headersTimeout = 2000;
  invalid.maxConnections = 4;
  invalid.on('connection', (socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });
  try {
    const endpoint = await server.listen();
    await new Promise((resolve, reject) => {
      invalid.once('error', reject);
      invalid.listen(0, '127.0.0.1', resolve);
    });
    const address = invalid.address();
    if (!address || typeof address === 'string') throw new Error('listen_failed');
    writeFileSync(
      endpointFile,
      JSON.stringify({
        port: endpoint.port,
        bad_port: address.port,
        node_version: process.versions.node,
      }),
      { flag: 'wx', mode: 0o600 },
    );
    writeFileSync(ready, String(process.pid) + '\n', { flag: 'wx', mode: 0o600 });
    const deadline = performance.now() + 160000;
    while (!existsSync(stop)) {
      if (performance.now() >= deadline) throw new Error('stop_timeout');
      await delay(20);
    }
  } finally {
    await server.close();
    invalid.closeAllConnections();
    await new Promise((resolve) => invalid.close(resolve));
  }
  const metrics = server.metrics();
  if (metrics.active !== 0 || metrics.requests !== 0 || metrics.sockets !== 0 || sockets.size !== 0)
    throw new Error('cleanup_failed');
  console.log(
    JSON.stringify({
      status: 'passed',
      cleanup_complete: true,
      evaluations,
      invalid_responses: invalidResponses,
      invalid_cases: invalidCases,
      raw_requests: rawRequests,
      codec_cases: codecCases,
      active: 0,
      requests: 0,
      sockets: 0,
      node_version: process.versions.node,
    }),
  );
}
main().catch(() => {
  console.error(JSON.stringify({ status: 'failed', code: 'fixture_failed' }));
  process.exitCode = 1;
});
