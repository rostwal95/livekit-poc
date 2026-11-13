/** Test-only one-invocation public peer. Import starts no listener or file I/O. */
import {
  constants,
  openSync,
  closeSync,
  readSync,
  fstatSync,
  lstatSync,
  realpathSync,
  existsSync,
  writeSync,
  fsyncSync,
  linkSync,
  unlinkSync,
} from 'node:fs';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import {
  CAPABILITY,
  EvidenceRegistry,
  LocalTrust,
  tokenDigest,
  SpecialistServer,
} from '@livekit-ecosystem/delegation-specialist';
import {
  FixedPolicyHandler,
  parseFixedPolicyRequest,
  encodeFixedPolicyRequest,
  encodeFixedPolicyResult,
} from '@livekit-ecosystem/delegation-specialist/fixed-policy';
import { readPrivate, publishPrivate, publicationPending } from './durable-fixed-policy-server.mjs';

const INPUT_MAX = 131072,
  PROOF_MAX = 65536;
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
function fields(value, names) {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.keys(value).length !== names.length ||
    names.some((name) => !Object.hasOwn(value, name))
  )
    throw Error('invalid_input');
  return value;
}
function metadata(value, maximum = PROOF_MAX) {
  let nodes = 2048;
  function copy(item, depth) {
    if (--nodes < 0 || depth > 12) throw Error('invalid_input');
    if (item === null || typeof item === 'boolean') return item;
    if (typeof item === 'string') {
      if (/[\ud800-\udfff]/u.test(item)) throw Error('invalid_input');
      return item;
    }
    if (typeof item === 'number' && Number.isSafeInteger(item) && !Object.is(item, -0)) return item;
    if (Array.isArray(item)) return item.map((child) => copy(child, depth + 1));
    if (
      !item ||
      typeof item !== 'object' ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(item))
    )
      throw Error('invalid_input');
    return Object.fromEntries(
      Object.keys(item)
        .sort()
        .map((key) => [key, copy(item[key], depth + 1)]),
    );
  }
  const result = Buffer.from(JSON.stringify(copy(value, 0)));
  if (!result.length || result.length > maximum) throw Error('invalid_input');
  return result;
}
function privateDirectory(directory) {
  const info = lstatSync(directory);
  if (
    resolve(directory) !== directory ||
    realpathSync(directory) !== directory ||
    !info.isDirectory() ||
    info.uid !== process.getuid() ||
    (info.mode & 0o777) !== 0o700
  )
    throw Error('invalid_input');
}
function readInput(path) {
  privateDirectory(dirname(path));
  const safe = (s) =>
    s.isFile() &&
    !s.isSymbolicLink() &&
    s.uid === process.getuid() &&
    s.nlink === 1 &&
    (s.mode & 0o777) === 0o600 &&
    s.size > 0 &&
    s.size <= INPUT_MAX;
  const identity = (a, b) =>
    a.ino === b.ino &&
    a.dev === b.dev &&
    a.size === b.size &&
    a.mtimeMs === b.mtimeMs &&
    a.ctimeMs === b.ctimeMs;
  const before = lstatSync(path);
  if (!safe(before)) throw Error('invalid_input');
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const opened = fstatSync(fd),
      buffer = Buffer.alloc(INPUT_MAX + 1);
    if (!safe(opened) || !identity(before, opened)) throw Error('invalid_input');
    let length = 0;
    while (length < buffer.length) {
      const count = readSync(fd, buffer, length, buffer.length - length, null);
      if (!count) break;
      length += count;
    }
    const after = fstatSync(fd),
      current = lstatSync(path);
    if (
      !safe(after) ||
      !safe(current) ||
      !identity(opened, after) ||
      !identity(after, current) ||
      length !== opened.size ||
      length > INPUT_MAX
    )
      throw Error('invalid_input');
    return buffer.subarray(0, length);
  } finally {
    closeSync(fd);
  }
}
function saveProof(path, value) {
  privateDirectory(dirname(path));
  const bytes = Buffer.concat([metadata(value), Buffer.from('\n')]);
  if (bytes.length > PROOF_MAX) throw Error('fixture_failed');
  const pending = path + '.' + process.pid + '.pending';
  let created = false;
  try {
    const fd = openSync(
      pending,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
      0o600,
    );
    created = true;
    try {
      let written = 0;
      while (written < bytes.length) {
        const count = writeSync(fd, bytes, written, bytes.length - written);
        if (!count) throw Error('fixture_failed');
        written += count;
      }
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
    linkSync(pending, path);
  } finally {
    if (created) unlinkSync(pending);
  }
  return bytes;
}
function marker(path) {
  if (!existsSync(path) || publicationPending(path)) return false;
  if (readPrivate(path, 32).toString() !== process.pid + '\n') throw Error('invalid_input');
  return true;
}
function arrived(directory, name) {
  publishPrivate(join(directory, name + '.reached'), Buffer.from(process.pid + '\n'));
}
export function parseNativeInput(raw) {
  if (!Buffer.isBuffer(raw) || !raw.length || raw.length > INPUT_MAX) throw Error('invalid_input');
  const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
  const input = fields(JSON.parse(text), [
    'schema_version',
    'owner_id',
    'request_utf8',
    'evidence',
  ]);
  if (
    input.schema_version !== 1 ||
    typeof input.owner_id !== 'string' ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(input.owner_id) ||
    typeof input.request_utf8 !== 'string' ||
    !Array.isArray(input.evidence) ||
    input.evidence.length !== 2
  )
    throw Error('invalid_input');
  const canonical = metadata(input, INPUT_MAX).toString();
  if (text !== canonical && text !== canonical + '\n') throw Error('invalid_input');
  const template = parseFixedPolicyRequest(Buffer.from(input.request_utf8));
  if (Buffer.from(encodeFixedPolicyRequest(template)).toString() !== input.request_utf8)
    throw Error('invalid_input');
  const records = input.evidence.map((item) => {
    fields(item, ['scope', 'reference', 'body_utf8']);
    if (typeof item.body_utf8 !== 'string') throw Error('invalid_input');
    const body = Buffer.from(item.body_utf8);
    if (
      !body.length ||
      body.length > 4096 ||
      !metadata(item.scope).equals(metadata(template.scope))
    )
      throw Error('invalid_input');
    const ref = template.evidence.find(
      (candidate) => candidate.source_id === item.reference?.source_id,
    );
    if (
      !ref ||
      !metadata(ref).equals(metadata(item.reference)) ||
      ref.media_type !== 'application/json' ||
      ref.byte_length !== body.length ||
      ref.sha256 !== sha(body)
    )
      throw Error('invalid_input');
    return { scope: item.scope, reference: item.reference, body };
  });
  if (new Set(records.map((item) => item.reference.source_id)).size !== 2)
    throw Error('invalid_input');
  new EvidenceRegistry(records); // Real byte/length/digest admission, no evaluation/provider call.
  return { input, template, records, input_sha256: sha(raw) };
}
export function validateNativeEnvironment(env) {
  const required = ['P3_NATIVE_DIRECTORY', 'P3_NATIVE_TOKEN'];
  const optional = ['PATH', 'LANG', 'CI', 'NO_COLOR', '__CF_USER_TEXT_ENCODING'];
  if (
    Object.keys(env).some((name) => !required.includes(name) && !optional.includes(name)) ||
    required.some((name) => typeof env[name] !== 'string' || !env[name]) ||
    !/^[A-Za-z0-9_-]{43}$/.test(env.P3_NATIVE_TOKEN)
  )
    throw Error('invalid_input');
  privateDirectory(env.P3_NATIVE_DIRECTORY);
  return { directory: env.P3_NATIVE_DIRECTORY, token: env.P3_NATIVE_TOKEN };
}
export function createNativePeer(configuration, decoded) {
  const { directory, token } = configuration,
    { input, template, records } = decoded;
  let stage = 'listen',
    lastResolved,
    current,
    invoked = 0,
    returned = 0,
    duplicates = 0;
  let held = false,
    released = false,
    invalid = false;
  const events = [];
  const compare = (request) => {
    const actual = parseFixedPolicyRequest(encodeFixedPolicyRequest(request));
    if (
      !metadata({ ...actual, attempt: template.attempt }).equals(metadata(template)) ||
      !/^attempt_[0-9a-f]{32}$/.test(actual.attempt.attempt_id) ||
      actual.attempt.number < 1 ||
      actual.attempt.number > 3
    )
      throw Error('fixture_failed');
    return actual;
  };
  class RecordingRegistry extends EvidenceRegistry {
    resolve(authorization, request, trust) {
      const evidence = super.resolve(authorization, request, trust);
      lastResolved = compare(request);
      return evidence;
    }
  }
  class RecordingPolicy extends FixedPolicyHandler {
    evaluate(request, evidence, observedAtMs) {
      if (!current || current.result !== null || duplicates) throw Error('fixture_failed');
      const actual = compare(request);
      if (sha(encodeFixedPolicyRequest(actual)) !== current.request_sha256)
        throw Error('fixture_failed');
      const result = super.evaluate(actual, evidence, observedAtMs);
      current.result = JSON.parse(Buffer.from(encodeFixedPolicyResult(result)).toString());
      current.result_sha256 = sha(encodeFixedPolicyResult(result));
      return result;
    }
  }
  const policy = new RecordingPolicy();
  const trust = new LocalTrust([
    {
      principal_id: 'native_policy_peer',
      token_sha256: tokenDigest(token),
      scopes: [
        {
          scope: template.scope,
          invoke_capabilities: [CAPABILITY],
          result_capabilities: [CAPABILITY],
          cancel_capabilities: [],
          evidence_sources: template.evidence.map((ref) => ref.source_id),
        },
      ],
    },
  ]);
  const server = new SpecialistServer({
    trust,
    evidence: new RecordingRegistry(records),
    fixedPolicy: policy,
    limits: { maxActive: 1, maxPerPrincipal: 1 },
    observer: (event) => {
      if (events.length >= 32) {
        invalid = true;
        return;
      }
      events.push({ ...event });
      if (event.event === 'attempt_started') {
        invoked++;
        if (invoked !== 1 || !lastResolved) {
          duplicates++;
          invalid = true;
          return;
        }
        current = {
          request: JSON.parse(Buffer.from(encodeFixedPolicyRequest(lastResolved)).toString()),
          request_sha256: sha(encodeFixedPolicyRequest(lastResolved)),
          result: null,
          result_sha256: null,
          started_at_ms: Date.now(),
          returned_at_ms: null,
          code: null,
        };
        lastResolved = undefined;
      } else if (event.event === 'attempt_finished') {
        returned++;
        if (!current || current.returned_at_ms !== null) {
          invalid = true;
          return;
        }
        current.returned_at_ms = Date.now();
        current.code = event.code;
      }
    },
    hooks: {
      beforeEvaluate: async ({ signal }) => {
        if (!current || duplicates || held) throw Error('fixture_failed');
        held = true;
        stage = 'held';
        arrived(directory, 'native_policy_held');
        const end = performance.now() + 5000;
        while (!marker(join(directory, 'native_policy_held.released'))) {
          signal.throwIfAborted();
          if (performance.now() >= end) throw Error('fixture_failed');
          await delay(5, undefined, { signal });
        }
        released = true;
        stage = 'serve';
        signal.throwIfAborted();
      },
    },
  });
  return {
    async start() {
      stage = 'listen';
      return await server.listen();
    },
    async close() {
      stage = 'close';
      await server.close();
    },
    stage: () => stage,
    async finish() {
      stage = 'close';
      await server.close();
      const metrics = server.metrics(),
        policyMetrics = policy.metrics();
      const cleanup =
        metrics.active === 0 &&
        metrics.requests === 0 &&
        metrics.sockets === 0 &&
        metrics.observerPending === 0;
      const passed =
        !invalid &&
        invoked === 1 &&
        returned === 1 &&
        duplicates === 0 &&
        held &&
        released &&
        current?.code === 'ok' &&
        current?.result !== null &&
        policyMetrics.evaluated === 1 &&
        metrics.invoked === 1 &&
        metrics.completed === 1 &&
        metrics.rejected === 0 &&
        metrics.cancellations === 0 &&
        metrics.expirations === 0 &&
        metrics.disconnects === 0 &&
        metrics.observerFailures === 0 &&
        metrics.observerDropped === 0 &&
        metadata(events).equals(
          metadata([
            { event: 'attempt_started', operation: 'invoke', code: 'ok' },
            { event: 'attempt_finished', operation: 'invoke', code: 'ok' },
            { event: 'closed', operation: 'http', code: 'ok' },
          ]),
        ) &&
        cleanup;
      stage = 'proof';
      const proof = {
        schema_version: 1,
        kind: 'native-policy.peer',
        status: passed ? 'passed' : 'failed',
        owner_id: input.owner_id,
        scope: template.scope,
        input_sha256: decoded.input_sha256,
        template_sha256: sha(Buffer.from(input.request_utf8)),
        invoked,
        returned,
        duplicate_entries: duplicates,
        hold_reached: held,
        hold_released: released,
        record: current ?? null,
        server_metrics: metrics,
        policy_metrics: policyMetrics,
        events,
        cleanup_complete: cleanup,
      };
      const bytes = saveProof(join(directory, 'native-policy-peer.json'), proof);
      if (!passed) throw Error('fixture_failed');
      return bytes;
    },
  };
}
export async function main() {
  let owner,
    configuration,
    cleanup = true,
    stage = 'setup';
  try {
    if (
      process.argv.length !== 3 ||
      process.argv[2] !== 'serve' ||
      process.versions.node !== '24.22.2'
    )
      throw Error('invalid_input');
    configuration = validateNativeEnvironment(process.env);
    const { directory } = configuration;
    const input = join(directory, 'native-policy-input.json'),
      endpoint = join(directory, 'native-policy-endpoint.json'),
      stop = join(directory, 'native-policy-server.stop');
    for (const path of [
      endpoint,
      stop,
      join(directory, 'native_policy_server_ready.reached'),
      join(directory, 'native_policy_held.reached'),
      join(directory, 'native_policy_held.released'),
      join(directory, 'native-policy-peer.json'),
    ]) {
      try {
        lstatSync(path);
        throw Error('invalid_input');
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
    }
    const decoded = parseNativeInput(readInput(input));
    owner = createNativePeer(configuration, decoded);
    cleanup = false;
    stage = 'listen';
    const address = await owner.start();
    publishPrivate(
      endpoint,
      Buffer.concat([
        metadata({
          schema_version: 1,
          kind: 'native-policy.endpoint',
          endpoint: address,
          owner_id: decoded.input.owner_id,
          input_sha256: decoded.input_sha256,
          template_sha256: sha(Buffer.from(decoded.input.request_utf8)),
        }),
        Buffer.from('\n'),
      ]),
    );
    arrived(directory, 'native_policy_server_ready');
    stage = 'serve';
    const end = performance.now() + 150000;
    while (!marker(stop)) {
      if (performance.now() >= end) throw Error('fixture_failed');
      await delay(5);
    }
    const proof = await owner.finish();
    cleanup = true;
    process.stdout.write(
      metadata({
        schema_version: 1,
        status: 'passed',
        mode: 'serve',
        node_version: process.versions.node,
        peer_sha256: sha(proof),
        cleanup_complete: true,
      }).toString() + '\n',
    );
  } catch {
    if (owner) {
      stage = owner.stage();
      try {
        await owner.close();
        cleanup = true;
      } catch {
        cleanup = false;
      }
    }
    const failure = {
      schema_version: 1,
      status: 'failed',
      mode: 'serve',
      stage,
      code: cleanup ? 'fixture_failed' : 'cleanup_incomplete',
      cleanup_complete: cleanup,
    };
    if (configuration) {
      try {
        saveProof(join(configuration.directory, 'native-policy-node-failure.json'), failure);
      } catch {
        /* preserve primary */
      }
    }
    process.stdout.write(metadata(failure).toString() + '\n');
    process.exitCode = 1;
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
