/** Qualification-only fixed inputs/holds; production image handler stays read-only. */
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
import { deflateSync } from 'node:zlib';
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
  DOCUMENT_CAPABILITY,
  DOCUMENT_FIELDS,
  DocumentHandler,
  createScriptedDocumentProvider,
  parseDocumentRequest,
  parseDocumentResult,
  encodeDocumentRequest,
  encodeDocumentResult,
  matchDocumentResult,
} from '@livekit-ecosystem/delegation-specialist/document';
import { extractDocument } from '../../examples/document-http.mjs';
const CASES = [
  'cross_language_document_schema_canonical_fingerprint_and_exact_correlation',
  'legacy_policy_wire_defaults_and_public_types_unchanged',
  'strict_document_shape_dates_status_nullability_and_region_bounds',
  'schema_valid_wrong_extracted_value_fails_independent_fixture_verdict',
  'schema_valid_swapped_region_source_version_or_digest_fails_verdict',
  'actual_fixture_manifest_and_decoded_pixel_hash_parity',
  'imports_no_IO_no_mutation_send_or_policy_eligible_surface',
  'nested_request_provider_result_snapshots_before_await',
];
const mode = process.argv[2];
const DIRECTORY = process.env.P3_DOCUMENT_DIRECTORY,
  FIXTURES = process.env.P3_DOCUMENT_FIXTURES;
const sha = (b) => createHash('sha256').update(b).digest('hex');
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

let positive, legacy, manifest;
const scope = { tenant_id: 'tenant_document', account_id: 'account_document' },
  other = { tenant_id: 'tenant_document', account_id: 'account_document_other' };
let stage = 'setup',
  cleanup = false;
const primaryToken = process.env.P3_DOCUMENT_TOKEN,
  otherToken = process.env.P3_DOCUMENT_OTHER_TOKEN;
const roleToken = (name) =>
  createHash('sha256')
    .update(primaryToken + ':' + name)
    .digest('base64url');
function fieldsFor(label, reference) {
  const f = manifest.fixtures[label];
  const values = {
    complete: ['DEMO-BK-001', 'Harbour Lodge', '2030-12-10', '2030-12-12'],
    missing: ['DEMO-BK-001', 'Harbour Lodge', '2030-12-10', null],
    ambiguous: ['DEMO-BK-001', 'Harbour Lodge', null, '2030-12-12'],
    adversarial: ['DEMO-BK-001', 'Harbour Lodge', '2030-12-10', '2030-12-12'],
    'other-source': ['DEMO-BK-002', 'Mountain Guesthouse', '2031-06-01', '2031-06-03'],
  }[label];
  return Object.fromEntries(
    DOCUMENT_FIELDS.map((name, i) => [
      name,
      {
        state: values[i] !== null ? 'known' : label === 'ambiguous' ? 'ambiguous' : 'missing',
        value: values[i],
        evidence_refs: f.regions[name].map((region) => ({
          source_id: reference.source_id,
          version: reference.version,
          sha256: reference.sha256,
          region,
        })),
      },
    ]),
  );
}
function crc(body) {
  let c = 0xffffffff;
  for (const b of body) {
    c ^= b;
    for (let i = 0; i < 8; i++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1;
  }
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, body) {
  const b = Buffer.alloc(body.length + 12);
  b.writeUInt32BE(body.length, 0);
  b.write(type, 4, 'ascii');
  b.set(body, 8);
  b.writeUInt32BE(crc(b.subarray(4, -4)), b.length - 4);
  return b;
}
function tiny(raw, options = {}) {
  const h = Buffer.alloc(13);
  h.writeUInt32BE(options.width ?? 1, 0);
  h.writeUInt32BE(options.height ?? 1, 4);
  h[8] = 8;
  h[9] = options.color ?? 2;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', h),
    ...(options.extra ? [options.extra] : []),
    chunk('IDAT', options.compressed ?? deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}
async function producer() {
  stage = 'producer';
  const request = parseDocumentRequest(Buffer.from(positive.canonical.request_utf8)),
    result = parseDocumentResult(Buffer.from(positive.canonical.result_utf8));
  const baseRequest = Buffer.from(encodeDocumentRequest(request)).toString(),
    baseResult = Buffer.from(encodeDocumentResult(result)).toString();
  const rows = CASES.map((name) => ({
    label: name,
    request_utf8: baseRequest,
    result_utf8: baseResult,
  }));
  rows[1].request_utf8 = Buffer.from(
    encodeRequest(parseRequest(Buffer.from(legacy.request_canonical))),
  ).toString();
  rows[1].result_utf8 = Buffer.from(
    encodeResult(parseResult(Buffer.from(legacy.result_canonical))),
  ).toString();
  const bad = structuredClone(result);
  bad.fields.booking_reference.value = 7;
  rows[2].result_utf8 = Buffer.from(canonical(bad)).toString();
  const wrong = structuredClone(result);
  wrong.fields.booking_reference.value = 'DEMO-BK-999';
  rows[3].result_utf8 = Buffer.from(
    encodeDocumentResult(parseDocumentResult(canonical(wrong))),
  ).toString();
  const swapped = structuredClone(result);
  swapped.fields.booking_reference.evidence_refs[0].region = structuredClone(
    result.fields.property_name.evidence_refs[0].region,
  );
  rows[4].result_utf8 = Buffer.from(
    encodeDocumentResult(parseDocumentResult(canonical(swapped))),
  ).toString();
  const callerOwned = JSON.parse(baseRequest);
  const fromConfiguredExample = await extractDocument(
    {
      invoke: async (snapshot) => {
        callerOwned.scope.account_id = 'changed_after_snapshot';
        if (snapshot.scope.account_id !== scope.account_id) throw Error('snapshot_changed');
        return result;
      },
    },
    callerOwned,
  );
  rows[7].result_utf8 = Buffer.from(encodeDocumentResult(fromConfiguredExample)).toString();
  save('document-producer.json', { schema_version: 1, kind: 'document.producer', rows });
  cleanup = true;
  return {
    schema_version: 1,
    status: 'passed',
    mode,
    node_version: process.versions.node,
    producer_rows: 8,
    proof: 'document-producer.json',
    cleanup_complete: true,
  };
}
async function serve() {
  if (
    !/^[A-Za-z0-9_-]{43}$/.test(primaryToken ?? '') ||
    !/^[A-Za-z0-9_-]{43}$/.test(otherToken ?? '') ||
    primaryToken === otherToken
  )
    throw Error('invalid_config');
  stage = 'registry';
  const records = [],
    bytes = {};
  for (const label of ['complete', 'missing', 'ambiguous', 'adversarial', 'other-source']) {
    const f = manifest.fixtures[label];
    if (f.file !== label + '.png') throw Error('invalid_manifest');
    const body = input('documents/' + f.file, 2097152);
    if (body.length !== f.source.byte_length || sha(body) !== f.source.sha256)
      throw Error('invalid_manifest');
    bytes[label] = body;
    records.push({ scope, reference: f.source, body });
  }
  const aliases = {
    document_post_decode: 'post_decode',
    document_timeout_held: 'timeout_held',
    document_cancel_held: 'cancel_held',
    document_close_held: 'close_held',
  };
  for (const source_id of Object.keys(aliases))
    records.push({
      scope,
      reference: { ...manifest.fixtures.complete.source, source_id },
      body: bytes.complete,
    });
  const mutations = {
    document_bad_crc: () => {
      const b = Buffer.from(bytes.complete);
      b[b.length - 1] ^= 1;
      return b;
    },
    document_truncated: () => bytes.complete.subarray(0, -1),
    document_trailing: () => Buffer.concat([bytes.complete, Buffer.from([0])]),
    document_apng: () => tiny(Buffer.from([0, 1, 2, 3]), { extra: chunk('acTL', Buffer.alloc(8)) }),
    document_unsupported: () => tiny(Buffer.from([0, 1]), { color: 0 }),
    document_bomb: () => tiny(Buffer.alloc(0), { compressed: deflateSync(Buffer.alloc(1048576)) }),
    document_bad_filter: () => tiny(Buffer.from([5, 1, 2, 3])),
    document_zlib_trailing: () =>
      tiny(Buffer.alloc(0), {
        compressed: Buffer.concat([deflateSync(Buffer.from([0, 1, 2, 3])), Buffer.from([1, 2, 3])]),
      }),
    document_huge_header: () => tiny(Buffer.from([0, 1, 2, 3]), { width: 2049 }),
  };
  const enrolled = [];
  for (const [source_id, make] of Object.entries(mutations)) {
    const body = make();
    const small = !['document_bad_crc', 'document_truncated', 'document_trailing'].includes(
      source_id,
    );
    const reference = {
      ...manifest.fixtures.complete.source,
      source_id,
      sha256: sha(body),
      byte_length: body.length,
      width: small ? 1 : 640,
      height: small ? 1 : 360,
    };
    records.push({ scope, reference, body });
    enrolled.push({ name: source_id.slice(9), reference });
  }
  save(
    'document-image-references.json',
    { schema_version: 1, kind: 'document.image-references', records: enrolled },
    8192,
  );
  records.push({
    scope: other,
    reference: manifest.fixtures.complete.source,
    body: bytes.complete,
  });
  const sources = records
    .filter((r) => r.scope.account_id === scope.account_id)
    .map((r) => r.reference.source_id);
  sources.push('document_missing_record');
  const grant = (principal, token, namespace = scope, blocked) => ({
    principal_id: principal,
    token_sha256: tokenDigest(token),
    scopes: [
      {
        scope: namespace,
        invoke_capabilities: blocked === 'invoke' ? [] : [DOCUMENT_CAPABILITY],
        result_capabilities: blocked === 'result' ? [] : [DOCUMENT_CAPABILITY],
        cancel_capabilities: blocked === 'cancel' ? [] : [DOCUMENT_CAPABILITY],
        evidence_sources:
          blocked === 'evidence'
            ? []
            : namespace === other
              ? [manifest.fixtures.complete.source.source_id]
              : sources,
      },
    ],
  });
  const trust = new LocalTrust([
    grant('primary', primaryToken),
    grant('other', otherToken, other),
    ...['invoke', 'result', 'cancel', 'evidence'].map((name) =>
      grant('no_' + name, roleToken(name), scope, name),
    ),
  ]);
  const workerRecords = [],
    providerRecords = [],
    seen = new Set();
  let closeIncomplete = false,
    postDecodeSeen = false,
    closeHeld = false;
  const configured = Object.entries(manifest.fixtures).map(([label, f]) => ({
    sha256: f.source.sha256,
    pixel_sha256: f.pixel_sha256,
    outcome: ['missing', 'ambiguous'].includes(label) ? 'clarification_required' : 'extracted',
    fields: fieldsFor(label, f.source),
  }));
  const base = createScriptedDocumentProvider(configured);
  const provider = {
    producer: base.producer,
    extract: async (request, image, signal) => {
      if (seen.has(request.attempt.attempt_id)) throw Error('duplicate_provider');
      seen.add(request.attempt.attempt_id);
      let kind = request.context_snapshot.document_source_id.replace('document_', '');
      if (kind === 'complete' && request.scope.account_id === other.account_id)
        kind = 'secondary_progress';
      const row = {
        kind,
        attempt_id: request.attempt.attempt_id,
        input_fingerprint: request.input_fingerprint,
        source_sha256: image.reference.sha256,
        result_sha256: null,
        settled: false,
      };
      providerRecords.push(row);
      try {
        const label = ['missing', 'ambiguous', 'adversarial', 'other_source'].includes(kind)
          ? kind.replace('_', '-')
          : 'complete';
        const literal = base.extract(request, image, signal);
        if (literal instanceof Promise) throw Error('invalid_fixture');
        const answer = { outcome: literal.outcome, fields: fieldsFor(label, image.reference) };
        if (['timeout_held', 'cancel_held', 'close_held'].includes(kind)) {
          if (kind === 'close_held') closeHeld = true;
          const name = 'document_' + kind;
          arrived(name);
          await released(name);
        }
        return answer;
      } finally {
        row.settled = true;
      }
    },
  };
  // Validate all scripted normal config independently of the explicit fault-provider holds.
  void base;
  const handler = new DocumentHandler(provider, {
    workerObserver: (v) => {
      if (workerRecords.length >= 64) throw Error('worker_proof_limit');
      workerRecords.push(v);
    },
  });
  const server = new SpecialistServer({
    trust,
    evidence: new EvidenceRegistry(records),
    document: handler,
    observer: () => undefined,
    limits: { maxActive: 2, maxPerPrincipal: 1 },
    hooks: {
      afterDocumentDecode: async ({ request }) => {
        if (request.context_snapshot.document_source_id !== 'document_post_decode') return;
        if (postDecodeSeen) throw Error('duplicate_phase');
        postDecodeSeen = true;
        const last = workerRecords.at(-1);
        if (!last || last.exit_code !== 0 || !last.normal_result) throw Error('worker_not_settled');
        save('document-phase.json', {
          schema_version: 1,
          kind: 'document.post-decode-held',
          node_pid: process.pid,
          attempt_id: request.attempt.attempt_id,
          input_fingerprint: request.input_fingerprint,
          deadline_at_ms: request.deadline_at_ms,
          worker_exit_code: 0,
        });
        arrived('document_post_decode_held');
        await released('document_post_decode_held');
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
    save('document-endpoint.json', {
      schema_version: 1,
      ...endpoint,
      node_version: process.versions.node,
    });
    arrived('document_server_ready');
    const until = performance.now() + 120000;
    stage = 'serve';
    while (!stopped && !existsSync(join(DIRECTORY, 'document-server.stop'))) {
      if (performance.now() >= until) throw Error('server_budget');
      await delay(5);
    }
    if (
      existsSync(join(DIRECTORY, 'document-server.stop')) &&
      read(join(DIRECTORY, 'document-server.stop'), 32).toString() !== process.pid + '\n'
    )
      throw Error('wrong_stop');
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
      arrived('document_close_incomplete');
      await released('document_close_held');
      await server.close();
    }
    const untilObservers = performance.now() + 3000;
    while (
      server.metrics().observerPending !== 0 ||
      handler.metrics().workerObserverPending !== 0
    ) {
      if (performance.now() >= untilObservers) throw Error('observer_pending');
      await delay(1);
    }
    const metrics = server.metrics(),
      owned = handler.metrics();
    if (
      providerRecords.length !== 8 ||
      owned.providerStarted !== 8 ||
      owned.providerSettled !== 8 ||
      owned.providerActive !== 0 ||
      owned.active !== 0 ||
      owned.workersActive !== 0 ||
      owned.observerFailures !== 0 ||
      owned.workerObserverPending !== 0 ||
      owned.workerObserverDropped !== 0 ||
      !closeIncomplete ||
      ['active', 'requests', 'sockets', 'observerPending'].some((k) => metrics[k] !== 0)
    )
      throw Error('owner_proof_mismatch');
    const wiresPath = join(DIRECTORY, 'document-http-wires.json'),
      proofPath = join(DIRECTORY, 'document-http-proof.json'),
      wireUntil = performance.now() + 5000;
    while (
      !existsSync(proofPath) ||
      !existsSync(wiresPath) ||
      publicationPending(proofPath, proofPath + '.publishing') ||
      publicationPending(wiresPath, wiresPath + '.publishing')
    ) {
      if (performance.now() >= wireUntil) throw Error('missing_wires');
      await delay(5);
    }
    const wireBytes = read(wiresPath),
      httpProof = JSON.parse(read(proofPath));
    if (
      httpProof.wires.path !== 'document-http-wires.json' ||
      httpProof.wires.bytes !== wireBytes.length ||
      httpProof.wires.sha256 !== sha(wireBytes)
    )
      throw Error('invalid_wires');
    const wires = JSON.parse(wireBytes);
    if (wires.kind !== 'document.http-canonical-wires' || wires.records.length !== 5)
      throw Error('invalid_wires');
    for (const wire of wires.records) {
      const request = parseDocumentRequest(Buffer.from(wire.request_utf8)),
        result = parseDocumentResult(Buffer.from(wire.result_utf8));
      if (
        matchDocumentResult(request, result, result.completed_at_ms) !== 'candidate' ||
        Buffer.from(encodeDocumentRequest(request)).toString() !== wire.request_utf8 ||
        Buffer.from(encodeDocumentResult(result)).toString() !== wire.result_utf8
      )
        throw Error('invalid_wires');
      const row = providerRecords.find((r) => r.attempt_id === result.attempt_id);
      if (
        !row ||
        row.input_fingerprint !== result.input_fingerprint ||
        row.source_sha256 !== request.evidence[0].sha256 ||
        row.result_sha256 !== null
      )
        throw Error('invalid_wires');
      row.result_sha256 = sha(Buffer.from(wire.result_utf8));
    }
    save('document-server-proof.json', {
      schema_version: 1,
      status: 'passed',
      kind: 'document.server-proof',
      node_version: process.versions.node,
      provider_calls: 8,
      provider_records: providerRecords,
      provider_active: 0,
      worker_records: workerRecords,
      workers_active: 0,
      requests: 0,
      sockets: 0,
      active: 0,
      observerPending: 0,
      close_incomplete_observed: true,
      closed: true,
    });
    cleanup = true;
    return {
      schema_version: 1,
      status: 'passed',
      mode,
      node_version: process.versions.node,
      proof: 'document-server-proof.json',
      cleanup_complete: true,
    };
  } finally {
    process.off('SIGTERM', stop);
    process.off('SIGINT', stop);
    if (!cleanup)
      try {
        await server.close();
      } catch {
        /* Parent retains exact child ownership if cleanup remains incomplete. */
      }
  }
}
async function main() {
  if (!['node-producer', 'node-server'].includes(mode)) throw Error('invalid_mode');
  directory(DIRECTORY);
  directory(FIXTURES);
  const baseKeys = [
    'PATH',
    'HOME',
    'TMPDIR',
    'LANG',
    'LC_ALL',
    'LC_CTYPE',
    'SYSTEMROOT',
    '__CF_USER_TEXT_ENCODING',
    'CI',
    'NO_COLOR',
    'COREPACK_HOME',
    'COREPACK_ENABLE_NETWORK',
  ];
  const allowed = new Set([
    ...baseKeys,
    'P3_DOCUMENT_DIRECTORY',
    'P3_DOCUMENT_FIXTURES',
    ...(mode === 'node-server' ? ['P3_DOCUMENT_TOKEN', 'P3_DOCUMENT_OTHER_TOKEN'] : []),
  ]);
  if (Object.keys(process.env).some((k) => !allowed.has(k))) throw Error('invalid_environment');
  positive = JSON.parse(input('document-v1.json'));
  legacy = JSON.parse(input('v1.json'));
  manifest = JSON.parse(input('documents/manifest.json'));
  return await (mode === 'node-producer' ? producer() : serve());
}
const safeCodes = new Set([
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
try {
  console.log(JSON.stringify(await main()));
} catch (error) {
  const code =
    (error instanceof ContractError || error instanceof SpecialistHttpError) &&
    typeof error.code === 'string' &&
    safeCodes.has(error.code)
      ? error.code
      : 'fixture_failed';
  try {
    save('document-node-failure.json', {
      schema_version: 1,
      status: 'failed',
      mode,
      stage,
      code,
      cleanup_complete: cleanup,
    });
  } catch {
    /* Preserve first fixed failure. */
  }
  console.log(
    JSON.stringify({
      schema_version: 1,
      status: 'failed',
      mode,
      stage,
      code,
      cleanup_complete: cleanup,
    }),
  );
  process.exitCode = 1;
}
