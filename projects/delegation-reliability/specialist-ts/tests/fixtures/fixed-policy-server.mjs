/** Qualification-only literal policy cases; production capabilities remain read-only. */
import {
  constants,
  openSync,
  closeSync,
  fstatSync,
  readFileSync,
  writeSync,
  fsyncSync,
  linkSync,
  unlinkSync,
  lstatSync,
  realpathSync,
  existsSync,
} from 'node:fs';
import { resolve, join, isAbsolute } from 'node:path';
import { createHash } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import {
  ERROR_CODES,
  ContractError,
  canonical,
  parseRequest,
  parseResult,
  encodeRequest,
  encodeResult,
  EvidenceRegistry,
  LocalTrust,
  tokenDigest,
  SpecialistServer,
  SpecialistHttpError,
} from '@livekit-ecosystem/delegation-specialist';
import {
  FixedPolicyHandler,
  encodeFixedPolicyRequest,
  encodeFixedPolicyResult,
  parseFixedPolicyRequest,
  parseFixedPolicyResult,
  produceFixedPolicyRequest,
  verifyFixedPolicyFacts,
} from '@livekit-ecosystem/delegation-specialist/fixed-policy';
import {
  DocumentHandler,
  createScriptedDocumentProvider,
  DOCUMENT_CAPABILITY,
  DOCUMENT_FIELDS,
  parseDocumentRequest,
  parseDocumentResult,
  encodeDocumentRequest,
  encodeDocumentResult,
} from '@livekit-ecosystem/delegation-specialist/document';
import { evaluateFixedPolicy } from '../../examples/fixed-policy.mjs';
const sha = (raw) => createHash('sha256').update(raw).digest('hex');
let DIRECTORY, FIXTURES, fixed, legacy, enrollment;
let mode,
  stage = 'setup',
  cleanup = false;
function directory(path) {
  if (
    typeof path !== 'string' ||
    !isAbsolute(path) ||
    resolve(path) !== path ||
    realpathSync(path) !== path
  )
    throw Error('unsafe_path');
  const s = lstatSync(path);
  if (!s.isDirectory() || s.uid !== process.getuid() || (s.mode & 0o777) !== 0o700)
    throw Error('unsafe_path');
  return path;
}

function read(path, max = 32768) {
  const s = lstatSync(path);
  if (
    !s.isFile() ||
    s.isSymbolicLink() ||
    s.uid !== process.getuid() ||
    s.nlink !== 1 ||
    (s.mode & 0o777) !== 0o600 ||
    s.size < 1 ||
    s.size > max
  )
    throw Error('unsafe_input');
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const actual = fstatSync(fd);
    if (actual.ino !== s.ino || actual.dev !== s.dev || actual.size !== s.size)
      throw Error('unsafe_input');
    const raw = readFileSync(fd);
    if (raw.length !== s.size) throw Error('unsafe_input');
    return raw;
  } finally {
    closeSync(fd);
  }
}
function input(name, max = name === 'v1.json' ? 65536 : 32768) {
  // Only the complete historical setup corpus has this file ceiling.
  return read(join(FIXTURES, name), max);
}
function save(name, value, max = 32768) {
  if (!/^[a-z][a-z0-9-]*\.json$/.test(name)) throw Error('unsafe_output');
  const raw = Buffer.from(JSON.stringify(value) + '\n');
  if (raw.length > max) throw Error('proof_limit');
  const fd = openSync(
    join(DIRECTORY, name),
    constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
    0o600,
  );
  try {
    writeSync(fd, raw);
  } finally {
    closeSync(fd);
  }
  return raw;
}
function arrived(name) {
  const target = join(DIRECTORY, name + '.reached');
  const pending = target + '.' + process.pid + '.pending';
  let owned = false;
  try {
    const fd = openSync(
      pending,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
      0o600,
    );
    owned = true;
    try {
      const raw = Buffer.from(process.pid + '\n');
      if (writeSync(fd, raw) !== raw.length) throw Error('marker_write_failed');
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
    // Never expose an empty marker and never replace an original arrival.
    linkSync(pending, target);
  } finally {
    if (owned) unlinkSync(pending);
  }
}
function publicationPending(path, pending) {
  const info = lstatSync(path);
  let other;
  try {
    other = lstatSync(pending);
  } catch (error) {
    if (error?.code === 'ENOENT') return false;
    throw error;
  }
  return (
    info.isFile() &&
    other.isFile() &&
    info.uid === process.getuid() &&
    other.uid === info.uid &&
    (info.mode & 0o777) === 0o600 &&
    (other.mode & 0o777) === 0o600 &&
    info.nlink === 2 &&
    other.nlink === 2 &&
    info.ino === other.ino &&
    info.dev === other.dev
  );
}
async function released(name, seconds = 15) {
  const until = performance.now() + seconds * 1000;
  const path = join(DIRECTORY, name + '.released');
  const pending = path + '.' + process.pid + '.pending';
  while (true) {
    if (existsSync(path) && !publicationPending(path, pending)) {
      if (read(path, 32).toString() !== process.pid + '\n') throw Error('wrong_release');
      return;
    }
    if (performance.now() >= until) throw Error('barrier_timeout');
    await delay(5);
  }
}

function record(scope, reference, body) {
  return { scope, reference, body: Buffer.from(body) };
}
function exactKeys(value, keys) {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.keys(value).length !== keys.length ||
    Object.keys(value).some((key) => !keys.includes(key))
  )
    throw Error('invalid_fixture');
}
function snapshot(request) {
  return request.capability === DOCUMENT_CAPABILITY
    ? parseDocumentRequest(encodeDocumentRequest(request))
    : parseFixedPolicyRequest(encodeFixedPolicyRequest(request));
}
function loadedRecords() {
  exactKeys(enrollment, ['schema_version', 'kind', 'records', 'cases']);
  if (
    enrollment.schema_version !== 1 ||
    enrollment.kind !== 'fixed-policy.fixture-enrollment' ||
    !Array.isArray(enrollment.records) ||
    enrollment.records.length !== 14 ||
    !Array.isArray(enrollment.cases) ||
    enrollment.cases.length !== 16
  )
    throw Error('invalid_enrollment');
  const names = new Set();
  return enrollment.records.map((row) => {
    const image = Object.hasOwn(row, 'png_file');
    exactKeys(
      row,
      image
        ? ['name', 'scope', 'reference', 'png_file']
        : ['name', 'scope', 'reference', 'body_utf8'],
    );
    if (typeof row.name !== 'string' || names.has(row.name)) throw Error('invalid_enrollment');
    names.add(row.name);
    if (image && row.png_file !== 'documents/adversarial.png') throw Error('invalid_enrollment');
    if (!image && typeof row.body_utf8 !== 'string') throw Error('invalid_enrollment');
    const body = image ? input(row.png_file, 2097152) : Buffer.from(row.body_utf8, 'utf8');
    if (body.length !== row.reference.byte_length || sha(body) !== row.reference.sha256)
      throw Error('invalid_enrollment');
    return record(row.scope, row.reference, body);
  });
}
function selectedRecords(request, records) {
  return request.evidence.map((ref) => {
    const found = records.filter(
      (row) =>
        row.scope.tenant_id === request.scope.tenant_id &&
        row.scope.account_id === request.scope.account_id &&
        row.reference.source_id === ref.source_id,
    );
    if (
      found.length !== 1 ||
      !Buffer.from(canonical(found[0].reference)).equals(Buffer.from(canonical(ref)))
    )
      throw Error('invalid_enrollment');
    return found[0];
  });
}
function policyCase(name) {
  const found = enrollment.cases.filter((row) => row.name === name);
  if (found.length !== 1) throw Error('invalid_enrollment');
  return produceFixedPolicyRequest(found[0].request_input);
}
async function producer() {
  stage = 'producer';
  const records = loadedRecords(),
    rows = [];
  new EvidenceRegistry(records);
  for (const name of [
    'eligible',
    'ineligible',
    'threshold',
    'missing',
    'conflicting',
    'adversarial',
    'wrong_rule',
    'wrong_fact',
  ]) {
    const request = policyCase(['wrong_rule', 'wrong_fact'].includes(name) ? 'eligible' : name);
    const evidence = selectedRecords(request, records),
      handler = new FixedPolicyHandler();
    let result = handler.evaluate(request, evidence, fixed.result.completed_at_ms);
    if (name === 'wrong_rule')
      result = parseFixedPolicyResult(
        canonical({
          ...result,
          rule_refs: [{ ...result.rule_refs[0], rule_id: 'invented_override' }],
        }),
      );
    if (name === 'wrong_fact')
      result = parseFixedPolicyResult(
        canonical({
          ...result,
          fact_refs: result.fact_refs.map((ref) => ({ ...ref, days_before_arrival: 11 })),
        }),
      );
    let semantic_verdict;
    try {
      semantic_verdict = verifyFixedPolicyFacts(request, result, evidence, fixed.observed_at_ms);
    } catch (error) {
      if (
        !(error instanceof ContractError) ||
        error.code !== 'unsupported_facts' ||
        !['wrong_rule', 'wrong_fact'].includes(name)
      )
        throw error;
      semantic_verdict = error.code;
    }
    const request_utf8 = Buffer.from(encodeFixedPolicyRequest(request)).toString('utf8'),
      result_utf8 = Buffer.from(encodeFixedPolicyResult(result)).toString('utf8');
    if (name === 'eligible') {
      if (request_utf8 !== fixed.request_canonical || result_utf8 !== fixed.result_canonical)
        throw Error('fixture_wire_mismatch');
      const caller = structuredClone(request),
        owned = evidence.map((row) => ({ ...row, body: Buffer.from(row.body) }));
      const fromExample = await evaluateFixedPolicy(
        {
          invoke: async (supplied) => {
            caller.scope.account_id = 'changed_after_snapshot';
            owned[0].body.fill(0);
            if (supplied.scope.account_id !== request.scope.account_id)
              throw Error('snapshot_changed');
            return result;
          },
        },
        caller,
        owned,
      );
      if (Buffer.from(encodeFixedPolicyResult(fromExample)).toString() !== result_utf8)
        throw Error('example_mismatch');
    }
    if (name === 'adversarial' && result.eligible !== false)
      throw Error('adversarial_fact_mismatch');
    rows.push({
      name,
      request_utf8,
      result_utf8,
      structural_verdict: 'accepted',
      semantic_verdict,
    });
  }
  const legacyRequest = Buffer.from(
    encodeRequest(parseRequest(Buffer.from(legacy.request_canonical))),
  );
  const legacyResult = Buffer.from(encodeResult(parseResult(Buffer.from(legacy.result_canonical))));
  if (
    legacyRequest.toString() !== legacy.request_canonical ||
    legacyResult.toString() !== legacy.result_canonical
  )
    throw Error('legacy_wire_changed');
  const document = JSON.parse(input('document-v1.json'));
  if (
    Buffer.from(
      encodeDocumentRequest(parseDocumentRequest(Buffer.from(document.canonical.request_utf8))),
    ).toString() !== document.canonical.request_utf8 ||
    Buffer.from(
      encodeDocumentResult(parseDocumentResult(Buffer.from(document.canonical.result_utf8))),
    ).toString() !== document.canonical.result_utf8
  )
    throw Error('legacy_document_changed');
  const proof = {
    schema_version: 1,
    kind: 'fixed-policy.contract-proof',
    node_version: process.versions.node,
    fixture_input_sha256: sha(input('fixed-policy-v2.json')),
    legacy_request_sha256: sha(legacyRequest),
    legacy_result_sha256: sha(legacyResult),
    rows,
  };
  save('fixed-policy-contract-proof.json', proof);
  cleanup = true;
  return proof;
}
const SAFE_CODES = new Set([
  ...ERROR_CODES,
  'invalid_http',
  'body_limit',
  'body_timeout',
  'request_aborted',
  'deadline_exceeded',
  'closing',
  'internal_error',
  'cleanup_incomplete',
  'invalid_response',
  'connection_failed',
  'client_closed',
  'client_capacity',
]);
function code(error) {
  return (error instanceof ContractError || error instanceof SpecialistHttpError) &&
    typeof error.code === 'string' &&
    SAFE_CODES.has(error.code)
    ? error.code
    : 'fixture_failed';
}
function same(actual, expected) {
  if (!Buffer.from(canonical(actual)).equals(Buffer.from(canonical(expected))))
    throw Error('proof_mismatch');
}
async function serve() {
  stage = 'registry';
  const tokens = JSON.parse(process.env.P3_FIXED_POLICY_TOKENS);
  if (
    !Array.isArray(tokens) ||
    tokens.length !== 6 ||
    new Set(tokens).size !== 6 ||
    tokens.some((token) => typeof token !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(token))
  )
    throw Error('invalid_config');
  const records = loadedRecords(),
    templates = new Map();
  for (const row of enrollment.cases) {
    exactKeys(row, ['name', 'principal', 'request_input']);
    if (
      typeof row.name !== 'string' ||
      !['primary', 'secondary'].includes(row.principal) ||
      templates.has(row.name)
    )
      throw Error('invalid_enrollment');
    templates.set(row.name, row);
  }
  const primary = enrollment.cases.find((row) => row.name === 'eligible')?.request_input.scope,
    secondary = enrollment.cases.find((row) => row.name === 'secondary_progress')?.request_input
      .scope;
  if (!primary || !secondary || JSON.stringify(primary) === JSON.stringify(secondary))
    throw Error('invalid_enrollment');
  const grant = (name, token, scope, blocked) => ({
    principal_id: name,
    token_sha256: tokenDigest(token),
    scopes: [
      {
        scope,
        invoke_capabilities:
          blocked === 'invoke' ? [] : ['booking.evaluate_policy', DOCUMENT_CAPABILITY],
        result_capabilities:
          blocked === 'result' ? [] : ['booking.evaluate_policy', DOCUMENT_CAPABILITY],
        cancel_capabilities:
          blocked === 'cancel' ? [] : ['booking.evaluate_policy', DOCUMENT_CAPABILITY],
        evidence_sources:
          blocked === 'evidence'
            ? []
            : [
                ...new Set(
                  records
                    .filter(
                      (row) =>
                        row.scope.tenant_id === scope.tenant_id &&
                        row.scope.account_id === scope.account_id,
                    )
                    .map((row) => row.reference.source_id),
                ),
                'not_registered',
              ],
      },
    ],
  });
  const trust = new LocalTrust([
    grant('primary', tokens[0], primary),
    grant('secondary', tokens[1], secondary),
    ...['invoke', 'result', 'cancel', 'evidence'].map((name, i) =>
      grant('no_' + name, tokens[i + 2], primary, name),
    ),
  ]);
  let lastResolved;
  const queue = [],
    observations = [],
    attempts = new Map();
  function bound(request) {
    const current = snapshot(request),
      wire = Buffer.from(
        current.capability === DOCUMENT_CAPABILITY
          ? encodeDocumentRequest(current)
          : encodeFixedPolicyRequest(current),
      );
    const candidates = enrollment.cases.filter(
      (row) =>
        row.request_input.delegation_id === current.delegation_id &&
        row.request_input.scope.tenant_id === current.scope.tenant_id &&
        row.request_input.scope.account_id === current.scope.account_id,
    );
    if (candidates.length !== 1) throw Error('unenrolled_attempt');
    const raw = JSON.parse(wire.toString()),
      template = structuredClone(candidates[0].request_input);
    delete raw.input_fingerprint;
    delete raw.deadline_at_ms;
    delete template.deadline_at_ms;
    same(raw, template);
    return { name: candidates[0].name, request: current, wire };
  }
  class RecordingRegistry extends EvidenceRegistry {
    resolve(authorization, request, configuredTrust) {
      const result = super.resolve(authorization, request, configuredTrust);
      lastResolved = snapshot(request);
      return result;
    }
  }
  function entry(request) {
    const value = attempts.get(request.attempt.attempt_id);
    if (!value || value.input_fingerprint !== request.input_fingerprint)
      throw Error('unbound_attempt');
    return value;
  }
  class RecordingPolicy extends FixedPolicyHandler {
    evaluate(request, evidence, now) {
      const current = entry(request);
      try {
        const result = super.evaluate(request, evidence, now);
        current.outcome_code = 'ok';
        return result;
      } catch (error) {
        current.outcome_code = code(error);
        throw error;
      }
    }
  }
  class RecordingDocument extends DocumentHandler {
    async evaluate(request, ...args) {
      const current = entry(request);
      try {
        const result = await super.evaluate(request, ...args);
        current.outcome_code = 'ok';
        return result;
      } catch (error) {
        current.outcome_code = code(error);
        throw error;
      }
    }
  }
  const expected = JSON.parse(input('documents/expected-v1.json')).fixtures.adversarial;
  const image = records.find((row) => row.reference.source_id === 'document_adversarial');
  if (!image || !expected) throw Error('invalid_enrollment');
  same(image.reference, expected.source);
  const fields = Object.fromEntries(
    DOCUMENT_FIELDS.map((name) => [
      name,
      {
        state: expected.fields[name].state,
        value: expected.fields[name].value,
        evidence_refs: expected.fields[name].regions.map((region) => ({
          source_id: image.reference.source_id,
          version: image.reference.version,
          sha256: image.reference.sha256,
          region,
        })),
      },
    ]),
  );
  const baseProvider = createScriptedDocumentProvider([
    {
      sha256: image.reference.sha256,
      pixel_sha256: expected.pixel_sha256,
      outcome: 'extracted',
      fields,
    },
  ]);
  const policy = new RecordingPolicy(),
    document = new RecordingDocument(baseProvider);
  let server,
    closeHeld = false,
    closeIncomplete = false;
  const observer = (event) => {
    exactKeys(event, ['event', 'operation', 'code']);
    if (
      observations.length >= 128 ||
      ![
        'request_rejected',
        'attempt_started',
        'attempt_finished',
        'observation',
        'closed',
      ].includes(event.event) ||
      !['invoke', 'status', 'cancel', 'http'].includes(event.operation) ||
      !(event.code === 'ok' || SAFE_CODES.has(event.code))
    )
      throw Error('invalid_event');
    observations.push({ ...event });
    if (event.event === 'attempt_started') {
      if (!lastResolved) throw Error('unbound_attempt');
      const value = bound(lastResolved);
      lastResolved = undefined;
      if (attempts.has(value.request.attempt.attempt_id)) throw Error('duplicate_attempt');
      const row = {
        name: value.name,
        scope: value.request.scope,
        delegation_id: value.request.delegation_id,
        attempt_id: value.request.attempt.attempt_id,
        input_fingerprint: value.request.input_fingerprint,
        request_sha256: sha(value.wire),
        outcome_code: null,
      };
      attempts.set(row.attempt_id, row);
      queue.push(value);
    }
  };
  const holds = new Map([
    ['expiry_held', 'fixed_policy_expiry_held'],
    ['timeout_held', 'fixed_policy_timeout_held'],
    ['cancel_held', 'fixed_policy_cancel_held'],
    ['secondary_progress', 'fixed_policy_secondary_held'],
    ['close_held', 'fixed_policy_close_held'],
  ]);
  const held = new Set();
  server = new SpecialistServer({
    trust,
    evidence: new RecordingRegistry(records),
    fixedPolicy: policy,
    document,
    observer,
    limits: { maxActive: 3, maxPerPrincipal: 2, closeMs: 40 },
    hooks: {
      beforeEvaluate: async ({ signal }) => {
        const current = queue.shift();
        if (!current) throw Error('unbound_attempt');
        const barrier = holds.get(current.name);
        if (!barrier) return;
        if (held.has(current.name)) throw Error('duplicate_hold');
        held.add(current.name);
        if (current.name === 'expiry_held')
          save('fixed-policy-phase.json', {
            schema_version: 1,
            name: 'expiry_held',
            deadline_at_ms: current.request.deadline_at_ms,
          });
        if (current.name === 'close_held') closeHeld = true;
        arrived(barrier);
        try {
          await released(barrier, 15);
          if (signal.aborted) throw signal.reason;
        } catch (error) {
          entry(current.request).outcome_code = code(error);
          throw error;
        }
      },
    },
  });
  let stopped = false;
  const stop = () => {
    stopped = true;
  };
  process.once('SIGTERM', stop);
  process.once('SIGINT', stop);
  try {
    stage = 'listen';
    const endpoint = await server.listen();
    save('endpoint.json', { schema_version: 1, ...endpoint, node_version: process.versions.node });
    arrived('fixed_policy_server_ready');
    stage = 'serve';
    const settledMarkers = new Set();
    function observeSettlement(name, cases, expectedCode) {
      if (settledMarkers.has(name) || server.metrics().active !== 0) return;
      for (const kind of cases) {
        const barrier = holds.get(kind);
        const row = [...attempts.values()].find((value) => value.name === kind);
        const path = join(DIRECTORY, barrier + '.released');
        if (
          !held.has(kind) ||
          !row ||
          row.outcome_code !== expectedCode ||
          !existsSync(path) ||
          publicationPending(path, path + '.' + process.pid + '.pending')
        )
          return;
        if (read(path, 32).toString() !== process.pid + '\n') throw Error('wrong_release');
      }
      arrived(name);
      settledMarkers.add(name);
    }
    const until = performance.now() + 90000;
    const stopPath = join(DIRECTORY, 'fixed-policy-server.stop');
    while (
      !stopped &&
      (!existsSync(stopPath) || publicationPending(stopPath, stopPath + '.publishing'))
    ) {
      if (performance.now() >= until) throw Error('server_budget');
      observeSettlement('fixed_policy_expiry_settled', ['expiry_held'], 'deadline_exceeded');
      observeSettlement(
        'fixed_policy_pair_settled',
        ['timeout_held', 'cancel_held'],
        'request_aborted',
      );
      await delay(5);
    }
    if (stopped || read(stopPath, 32).toString() !== process.pid + '\n') throw Error('wrong_stop');
    stage = 'close';
    try {
      await server.close();
    } catch (error) {
      if (
        !(error instanceof SpecialistHttpError) ||
        error.code !== 'cleanup_incomplete' ||
        !closeHeld
      )
        throw error;
      closeIncomplete = true;
      arrived('fixed_policy_close_incomplete');
      await released('fixed_policy_close_held', 15);
      await server.close();
    }
    const observerUntil = performance.now() + 3000;
    while (
      server.metrics().observerPending !== 0 ||
      document.metrics().workerObserverPending !== 0
    ) {
      if (performance.now() >= observerUntil) throw Error('observer_pending');
      await delay(1);
    }
    stage = 'proof_records';
    const ordered = enrollment.cases.map((row) => {
      const match = [...attempts.values()].filter((value) => value.name === row.name);
      if (
        match.length !== 1 ||
        typeof match[0].outcome_code !== 'string' ||
        match[0].outcome_code === 'fixture_failed'
      )
        throw Error('missing_attempt');
      return match[0];
    });
    save('fixed-policy-node-observations.json', {
      schema_version: 1,
      kind: 'fixed-policy.node-observations',
      server_metrics: server.metrics(),
      policy_metrics: policy.metrics(),
      document_metrics: document.metrics(),
      records: ordered,
      events: observations,
    });
    stage = 'proof_wires';
    const wirePath = join(DIRECTORY, 'fixed-policy-http-wires.json'),
      proofPath = join(DIRECTORY, 'fixed-policy-http-proof.json'),
      wireUntil = performance.now() + 5000;
    while (
      !existsSync(wirePath) ||
      !existsSync(proofPath) ||
      publicationPending(wirePath, wirePath + '.publishing') ||
      publicationPending(proofPath, proofPath + '.publishing')
    ) {
      if (performance.now() >= wireUntil) throw Error('missing_wires');
      await delay(5);
    }
    const wires = read(wirePath),
      client = JSON.parse(read(proofPath));
    if (
      client.wire_descriptor?.path !== 'fixed-policy-http-wires.json' ||
      client.wire_descriptor.bytes !== wires.length ||
      client.wire_descriptor.sha256 !== sha(wires) ||
      client.cleanup_complete !== true
    )
      throw Error('invalid_wires');
    const publicWires = JSON.parse(wires);
    exactKeys(publicWires, ['schema_version', 'kind', 'records']);
    if (
      publicWires.schema_version !== 1 ||
      publicWires.kind !== 'fixed-policy.canonical-http-wires' ||
      publicWires.records.length !== 8
    )
      throw Error('invalid_wires');
    for (const wire of publicWires.records) {
      exactKeys(wire, ['name', 'request_utf8', 'result_utf8']);
      const imageWire = wire.name === 'image_adversarial',
        request = imageWire
          ? parseDocumentRequest(Buffer.from(wire.request_utf8))
          : parseFixedPolicyRequest(Buffer.from(wire.request_utf8)),
        result = imageWire
          ? parseDocumentResult(Buffer.from(wire.result_utf8))
          : parseFixedPolicyResult(Buffer.from(wire.result_utf8));
      const observed = entry(request);
      if (
        observed.name !== wire.name ||
        observed.request_sha256 !== sha(Buffer.from(wire.request_utf8)) ||
        observed.outcome_code !== 'ok'
      )
        throw Error('invalid_wires');
      if (!imageWire)
        verifyFixedPolicyFacts(
          request,
          result,
          selectedRecords(request, records),
          result.completed_at_ms,
        );
      if (
        Buffer.from(
          imageWire ? encodeDocumentResult(result) : encodeFixedPolicyResult(result),
        ).toString() !== wire.result_utf8
      )
        throw Error('invalid_wires');
    }
    if (queue.length || held.size !== 5 || settledMarkers.size !== 2 || !closeIncomplete)
      throw Error('owner_proof_mismatch');
    stage = 'proof_counts';
    same(server.metrics(), {
      invoked: 16,
      completed: 8,
      rejected: 25,
      cancellations: 1,
      expirations: 1,
      disconnects: 1,
      observerFailures: 0,
      observerDropped: 0,
      active: 0,
      requests: 0,
      sockets: 0,
      observerPending: 0,
    });
    same(policy.metrics(), { evaluated: 7, clarified: 2 });
    same(document.metrics(), {
      providerStarted: 1,
      providerSettled: 1,
      providerFailed: 0,
      workersStarted: 1,
      workersSettled: 1,
      workersActive: 0,
      observerFailures: 0,
      workerObserverPending: 0,
      workerObserverDropped: 0,
      providerActive: 0,
      active: 0,
    });
    const finished = observations.filter((row) => row.event === 'attempt_finished');
    same(finished.map((row) => row.code).sort(), ordered.map((row) => row.outcome_code).sort());
    const proof = {
      schema_version: 1,
      kind: 'fixed-policy.server-proof',
      node_version: process.versions.node,
      enrollment_sha256: sha(input('enrollment.json')),
      server_metrics: server.metrics(),
      policy_metrics: policy.metrics(),
      document_metrics: document.metrics(),
      records: ordered,
      events: observations,
      close_incomplete: true,
      cleanup_complete: true,
    };
    save('fixed-policy-server-proof.json', proof);
    cleanup = true;
    return proof;
  } finally {
    process.off('SIGTERM', stop);
    process.off('SIGINT', stop);
    if (!cleanup) {
      try {
        await server.close();
      } catch {
        /* Parent preserves actual ownership and private work on incomplete close. */
      }
    }
  }
}
async function main() {
  mode = process.argv[2];
  if (!['producer', 'serve'].includes(mode)) throw Error('invalid_mode');
  const base = [
    'PATH',
    'LANG',
    'CI',
    'NO_COLOR',
    'COREPACK_HOME',
    'COREPACK_ENABLE_NETWORK',
    '__CF_USER_TEXT_ENCODING',
  ];
  const allowed = new Set([
    ...base,
    'P3_FIXED_POLICY_DIRECTORY',
    'P3_FIXED_POLICY_INPUTS',
    ...(mode === 'serve' ? ['P3_FIXED_POLICY_TOKENS'] : []),
  ]);
  if (Object.keys(process.env).some((key) => !allowed.has(key))) throw Error('invalid_environment');
  DIRECTORY = directory(process.env.P3_FIXED_POLICY_DIRECTORY);
  FIXTURES = directory(process.env.P3_FIXED_POLICY_INPUTS);
  fixed = JSON.parse(input('fixed-policy-v2.json'));
  legacy = JSON.parse(input('v1.json'));
  enrollment = JSON.parse(input('enrollment.json'));
  return mode === 'producer' ? producer() : serve();
}
try {
  console.log(JSON.stringify(await main()));
} catch (error) {
  try {
    if (DIRECTORY)
      save('fixed-policy-node-failure.json', {
        schema_version: 1,
        status: 'failed',
        mode: ['producer', 'serve'].includes(mode) ? mode : 'invalid',
        stage,
        code: code(error),
        cleanup_complete: cleanup,
      });
  } catch {
    /* Diagnostics cannot replace the original failure. */
  }
  console.log(
    JSON.stringify({
      schema_version: 1,
      status: 'failed',
      code: code(error),
      cleanup_complete: cleanup,
    }),
  );
  process.exitCode = 1;
}
