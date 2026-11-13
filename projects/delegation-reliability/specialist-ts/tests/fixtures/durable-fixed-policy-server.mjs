/** Test-only public/fault HTTP peers. Importing this file starts no work. */
import {
  constants,
  openSync,
  closeSync,
  fstatSync,
  readSync,
  writeSync,
  fsyncSync,
  linkSync,
  unlinkSync,
  lstatSync,
  realpathSync,
  existsSync,
  mkdirSync,
} from 'node:fs';
import { resolve, join, isAbsolute, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import {
  CAPABILITY,
  EvidenceRegistry,
  LocalTrust,
  tokenDigest,
  AttemptBoundary,
  SpecialistServer,
} from '@livekit-ecosystem/delegation-specialist';
import {
  FixedPolicyHandler,
  produceFixedPolicyRequest,
  parseFixedPolicyRequest,
  encodeFixedPolicyRequest,
  encodeFixedPolicyResult,
} from '@livekit-ecosystem/delegation-specialist/fixed-policy';

export const LABELS = Object.freeze([
  'known',
  'missing',
  'conflicting',
  'wrong_rule',
  'wrong_decision',
  'wrong_witness',
  'foreign_scope',
  'expired_wrong_facts',
  'expired_valid',
  'cancelled',
  'abandoned',
  'postcommit',
  'useful',
]);
const PUBLIC = new Set([
  'known',
  'missing',
  'conflicting',
  'cancelled',
  'abandoned',
  'postcommit',
  'useful',
]);
const HOLDS = new Map(
  ['expired_wrong_facts', 'expired_valid', 'cancelled', 'abandoned'].map((name) => [
    name,
    'fixed_work_' + name + '_held',
  ]),
);
const REQUIRED = [
  'P3_FIXED_WORK_DIRECTORY',
  'P3_FIXED_WORK_INPUT_FILE',
  'P3_FIXED_WORK_ENDPOINT_FILE',
  'P3_FIXED_WORK_STOP_FILE',
  'P3_FIXED_WORK_TOKEN',
];
const OPTIONAL = ['PATH', 'LANG', 'CI', 'NO_COLOR', '__CF_USER_TEXT_ENCODING'];
const sha = (value) => createHash('sha256').update(value).digest('hex');
/** Metadata has its own bounded profile; SDK request/result wire limits stay fixed. */
export function fixtureBytes(value) {
  const seen = new Set();
  let remaining = 4096;
  function visit(current, depth) {
    if (--remaining < 0 || depth > 12) throw Error('invalid_input');
    if (current === null || typeof current === 'boolean') return current;
    if (typeof current === 'number') {
      if (!Number.isSafeInteger(current) || Object.is(current, -0)) throw Error('invalid_input');
      return current;
    }
    if (typeof current === 'string') {
      if (/[\ud800-\udfff]/u.test(current)) throw Error('invalid_input');
      return current;
    }
    if (!current || typeof current !== 'object' || seen.has(current)) throw Error('invalid_input');
    seen.add(current);
    try {
      if (Array.isArray(current)) {
        if (current.length > 128 || Reflect.ownKeys(current).length !== current.length + 1)
          throw Error('invalid_input');
        return Array.from({ length: current.length }, (_, i) => {
          const descriptor = Object.getOwnPropertyDescriptor(current, String(i));
          if (!descriptor || !('value' in descriptor) || !descriptor.enumerable)
            throw Error('invalid_input');
          return visit(descriptor.value, depth + 1);
        });
      }
      if (![Object.prototype, null].includes(Object.getPrototypeOf(current)))
        throw Error('invalid_input');
      const names = Reflect.ownKeys(current);
      if (names.some((name) => typeof name !== 'string')) throw Error('invalid_input');
      const result = Object.create(null);
      for (const name of names.sort()) {
        const descriptor = Object.getOwnPropertyDescriptor(current, name);
        if (
          !descriptor ||
          !('value' in descriptor) ||
          !descriptor.enumerable ||
          /[\ud800-\udfff]/u.test(name)
        )
          throw Error('invalid_input');
        result[name] = visit(descriptor.value, depth + 1);
      }
      return result;
    } finally {
      seen.delete(current);
    }
  }
  const result = Buffer.from(JSON.stringify(visit(value, 0)));
  if (!result.length || result.length > 32768) throw Error('invalid_input');
  return result;
}
const bytes = fixtureBytes;
const same = (a, b) => bytes(a).equals(bytes(b));
function fields(value, names) {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw Error('invalid_input');
  if (
    Reflect.ownKeys(value).length !== names.length ||
    Reflect.ownKeys(value).some((n) => typeof n !== 'string' || !names.includes(n))
  )
    throw Error('invalid_input');
  for (const name of names) {
    const d = Object.getOwnPropertyDescriptor(value, name);
    if (!d || !('value' in d) || !d.enumerable) throw Error('invalid_input');
  }
  return value;
}
function privateDirectory(path) {
  if (
    typeof path !== 'string' ||
    !isAbsolute(path) ||
    resolve(path) !== path ||
    realpathSync(path) !== path
  )
    throw Error('invalid_input');
  const info = lstatSync(path);
  if (!info.isDirectory() || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o700)
    throw Error('invalid_input');
  return path;
}
export function readPrivate(path, maximum = 32768) {
  if (!Number.isSafeInteger(maximum) || maximum < 1 || maximum > 32768)
    throw Error('invalid_input');
  privateDirectory(dirname(path));
  const before = lstatSync(path);
  if (
    !before.isFile() ||
    before.isSymbolicLink() ||
    before.uid !== process.getuid() ||
    before.nlink !== 1 ||
    (before.mode & 0o777) !== 0o600 ||
    before.size < 1 ||
    before.size > maximum
  )
    throw Error('invalid_input');
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const opened = fstatSync(fd),
      buffer = Buffer.alloc(maximum + 1);
    let length = 0;
    while (length < buffer.length) {
      const count = readSync(fd, buffer, length, buffer.length - length, null);
      if (!count) break;
      length += count;
    }
    const after = fstatSync(fd);
    const safe = (info) =>
      info.isFile() &&
      info.uid === process.getuid() &&
      info.nlink === 1 &&
      (info.mode & 0o777) === 0o600;
    if (
      !safe(opened) ||
      !safe(after) ||
      before.ino !== opened.ino ||
      before.dev !== opened.dev ||
      opened.size !== before.size ||
      length !== before.size ||
      length > maximum ||
      after.size !== opened.size ||
      after.mtimeMs !== opened.mtimeMs
    )
      throw Error('invalid_input');
    return buffer.subarray(0, length);
  } finally {
    closeSync(fd);
  }
}
export function publishPrivate(path, data) {
  privateDirectory(dirname(path));
  if (!Buffer.isBuffer(data) || !data.length || data.length > 32768) throw Error('invalid_input');
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
      while (written < data.length) {
        const count = writeSync(fd, data, written, data.length - written);
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
}
function save(path, value) {
  const raw = Buffer.concat([bytes(value), Buffer.from('\n')]);
  publishPrivate(path, raw);
  return raw;
}
function arrived(directory, name) {
  publishPrivate(join(directory, name + '.reached'), Buffer.from(process.pid + '\n'));
}
export function publicationPending(path, inspect = lstatSync) {
  const info = inspect(path);
  if (info.nlink === 1) return false;
  if (
    !info.isFile() ||
    info.uid !== process.getuid() ||
    (info.mode & 0o777) !== 0o600 ||
    info.nlink !== 2
  )
    throw Error('invalid_input');
  for (const pending of [path + '.' + process.pid + '.pending', path + '.publishing']) {
    let other;
    try {
      other = inspect(pending);
    } catch (error) {
      if (error.code === 'ENOENT') continue;
      throw error;
    }
    if (
      info.isFile() &&
      other.isFile() &&
      info.nlink === 2 &&
      other.nlink === 2 &&
      info.uid === process.getuid() &&
      other.uid === info.uid &&
      (info.mode & 0o777) === 0o600 &&
      (other.mode & 0o777) === 0o600 &&
      info.ino === other.ino &&
      info.dev === other.dev
    )
      return true;
  }
  // The known publisher may have unlinked its pending name between the lstats.
  const settled = inspect(path);
  if (
    settled.isFile() &&
    settled.uid === info.uid &&
    (settled.mode & 0o777) === 0o600 &&
    settled.nlink === 1 &&
    settled.dev === info.dev &&
    settled.ino === info.ino
  )
    return false;
  throw Error('invalid_input');
}
function marker(path) {
  if (!existsSync(path) || publicationPending(path)) return false;
  if (readPrivate(path, 32).toString() !== process.pid + '\n') throw Error('invalid_input');
  return true;
}
async function released(directory, name, signal) {
  const path = join(directory, name + '.released'),
    end = performance.now() + 20000;
  for (;;) {
    signal?.throwIfAborted();
    if (marker(path)) return;
    if (performance.now() >= end) throw Error('fixture_failed');
    await delay(5, undefined, signal ? { signal } : undefined);
  }
}
export function validateEnvironment(env) {
  if (
    !env ||
    typeof env !== 'object' ||
    Object.keys(env).some((k) => !REQUIRED.includes(k) && !OPTIONAL.includes(k)) ||
    REQUIRED.some((k) => typeof env[k] !== 'string' || !env[k].length)
  )
    throw Error('invalid_input');
  const directory = privateDirectory(env.P3_FIXED_WORK_DIRECTORY);
  if (
    env.P3_FIXED_WORK_INPUT_FILE !== join(directory, 'fixed-work-input.json') ||
    env.P3_FIXED_WORK_ENDPOINT_FILE !== join(directory, 'fixed-work-endpoint.json') ||
    env.P3_FIXED_WORK_STOP_FILE !== join(directory, 'fixed-work.stop') ||
    !/^[A-Za-z0-9_-]{43}$/.test(env.P3_FIXED_WORK_TOKEN)
  )
    throw Error('invalid_input');
  return Object.freeze({
    directory,
    input: env.P3_FIXED_WORK_INPUT_FILE,
    endpoint: env.P3_FIXED_WORK_ENDPOINT_FILE,
    stop: env.P3_FIXED_WORK_STOP_FILE,
    token: env.P3_FIXED_WORK_TOKEN,
  });
}
export function parsePeerInput(raw) {
  if (!Buffer.isBuffer(raw) || !raw.length || raw.length > 32768) throw Error('invalid_input');
  let input;
  try {
    input = JSON.parse(raw.toString('utf8'));
  } catch {
    throw Error('invalid_input');
  }
  if (!raw.equals(bytes(input)) && !raw.equals(Buffer.concat([bytes(input), Buffer.from('\n')])))
    throw Error('invalid_input');
  fields(input, ['schema_version', 'kind', 'scope', 'cases', 'records']);
  fields(input.scope, ['tenant_id', 'account_id']);
  if (
    input.schema_version !== 1 ||
    input.kind !== 'fixed-work.peer-input' ||
    !Array.isArray(input.cases) ||
    input.cases.length !== 13 ||
    !Array.isArray(input.records) ||
    input.records.length !== 4
  )
    throw Error('invalid_input');
  const records = input.records.map((row) => {
    fields(row, ['scope', 'reference', 'body_utf8']);
    fields(row.reference, [
      'source_id',
      'version',
      'sha256',
      'media_type',
      'byte_length',
      'width',
      'height',
    ]);
    if (
      !same(row.scope, input.scope) ||
      typeof row.body_utf8 !== 'string' ||
      !Buffer.byteLength(row.body_utf8) ||
      Buffer.byteLength(row.body_utf8) > 4096 ||
      row.reference.media_type !== 'application/json' ||
      row.reference.width !== null ||
      row.reference.height !== null ||
      row.reference.byte_length !== Buffer.byteLength(row.body_utf8) ||
      row.reference.sha256 !== sha(Buffer.from(row.body_utf8))
    )
      throw Error('invalid_input');
    return { scope: row.scope, reference: row.reference, body: Buffer.from(row.body_utf8) };
  });
  new EvidenceRegistry(records);
  const ids = new Set(),
    referenced = new Set();
  for (const [index, row] of input.cases.entries()) {
    fields(row, [
      'label',
      'delegation_id',
      'case_id',
      'request_revision',
      'conversation_id',
      'context_snapshot',
      'evidence',
      'peer',
    ]);
    if (
      row.label !== LABELS[index] ||
      row.peer !== (PUBLIC.has(row.label) ? 'public' : 'fault') ||
      ids.has(row.delegation_id)
    )
      throw Error('invalid_input');
    ids.add(row.delegation_id);
    if (!Array.isArray(row.evidence) || row.evidence.length !== 2) throw Error('invalid_input');
    for (const reference of row.evidence) {
      if (records.filter((record) => same(record.reference, reference)).length !== 1)
        throw Error('invalid_input');
      referenced.add(bytes(reference).toString());
    }
    produceFixedPolicyRequest({
      schema_version: 1,
      kind: 'delegation.request',
      capability: CAPABILITY,
      input_schema_version: 2,
      scope: input.scope,
      delegation_id: row.delegation_id,
      case_id: row.case_id,
      request_revision: row.request_revision,
      context_snapshot: row.context_snapshot,
      evidence: row.evidence,
      deadline_at_ms: Date.now() + 30000,
      result_route: { conversation_id: row.conversation_id },
      attempt: { attempt_id: 'attempt_00000000000040008000000000000001', number: 1 },
    });
  }
  if (referenced.size !== records.length) throw Error('invalid_input');
  return { input, records };
}

/** Explicit fixture owner; parent tooling owns its actual process/group. */
export function createPeer(configuration, decoded) {
  const { directory, token } = configuration,
    { input, records } = decoded;
  const wireDirectory = join(directory, 'peer-wires');
  if (!existsSync(wireDirectory)) mkdirSync(wireDirectory, { mode: 0o700 });
  privateDirectory(wireDirectory);
  const trust = new LocalTrust([
    {
      principal_id: 'fixed_work_peer',
      token_sha256: tokenDigest(token),
      scopes: [
        {
          scope: input.scope,
          invoke_capabilities: [CAPABILITY],
          result_capabilities: [CAPABILITY],
          cancel_capabilities: [],
          evidence_sources: records.map((r) => r.reference.source_id),
        },
      ],
    },
  ]);
  const registry = new EvidenceRegistry(records),
    boundary = new AttemptBoundary(trust, registry, 1, 1);
  const entries = new Map(),
    queue = [],
    events = [],
    faultSockets = new Map(),
    handlers = new Set();
  const closing = new AbortController();
  let primary,
    stage = 'listen',
    lastResolved,
    currentPublic,
    duplicates = 0,
    faultPort;
  let faultActive = 0,
    faultRequests = 0,
    publicInvoked = 0,
    faultInvoked = 0,
    returned = 0,
    faultStopped;
  const fail = () => {
    primary ??= Error('fixture_failed');
  };
  function bind(request, peer) {
    const snapshot = parseFixedPolicyRequest(encodeFixedPolicyRequest(request));
    const row = input.cases.find((c) => c.delegation_id === snapshot.delegation_id);
    if (
      !row ||
      row.peer !== peer ||
      !same(snapshot.scope, input.scope) ||
      snapshot.case_id !== row.case_id ||
      snapshot.request_revision !== row.request_revision ||
      snapshot.result_route.conversation_id !== row.conversation_id ||
      !same(snapshot.context_snapshot, row.context_snapshot) ||
      !same(snapshot.evidence, row.evidence) ||
      snapshot.attempt.number !== 1 ||
      !/^attempt_[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/.test(snapshot.attempt.attempt_id) ||
      snapshot.deadline_at_ms <= Date.now() ||
      snapshot.deadline_at_ms - Date.now() > 60000
    )
      throw Error('fixture_failed');
    return {
      template: row,
      request: snapshot,
      request_utf8: Buffer.from(encodeFixedPolicyRequest(snapshot)).toString(),
    };
  }
  function enter(bound) {
    const { request, template, request_utf8 } = bound;
    if (template.peer === 'public') publicInvoked++;
    else faultInvoked++;
    if (entries.has(template.label)) {
      duplicates++;
      if (duplicates === 1)
        save(join(directory, 'fixed-work-duplicate.json'), {
          schema_version: 1,
          label: template.label,
          physical_admissions: publicInvoked + faultInvoked,
        });
      fail();
      throw Error('fixture_failed');
    }
    const row = {
      label: template.label,
      peer: template.peer,
      scope: request.scope,
      delegation_id: request.delegation_id,
      wire_attempt_id: request.attempt.attempt_id,
      input_fingerprint: request.input_fingerprint,
      request_sha256: sha(Buffer.from(request_utf8)),
      result_sha256: null,
      started_at_ms: Date.now(),
      returned_at_ms: null,
    };
    const entry = { row, request, request_utf8 };
    entries.set(template.label, entry);
    return entry;
  }
  function recordResult(entry, result) {
    const result_utf8 = Buffer.from(encodeFixedPolicyResult(result)).toString();
    entry.row.result_sha256 = sha(Buffer.from(result_utf8));
    save(join(wireDirectory, entry.row.label + '.json'), {
      request_utf8: entry.request_utf8,
      result_utf8,
    });
    return Buffer.from(result_utf8);
  }
  class RecordingRegistry extends EvidenceRegistry {
    resolve(authorization, request, configuredTrust) {
      const result = super.resolve(authorization, request, configuredTrust);
      lastResolved = bind(request, 'public');
      return result;
    }
  }
  class RecordingPolicy extends FixedPolicyHandler {
    evaluate(request, evidence, now) {
      const result = super.evaluate(request, evidence, now);
      const entry = entries.get(
        input.cases.find((c) => c.delegation_id === request.delegation_id)?.label,
      );
      if (!entry || entry.row.wire_attempt_id !== request.attempt.attempt_id)
        throw Error('fixture_failed');
      recordResult(entry, result);
      return result;
    }
  }
  function observe(event) {
    try {
      fields(event, ['event', 'operation', 'code']);
      if (events.length >= 64) throw Error('fixture_failed');
      events.push({ ...event });
      if (event.event === 'attempt_started') {
        if (!lastResolved) throw Error('fixture_failed');
        currentPublic = enter(lastResolved);
        lastResolved = undefined;
        queue.push(currentPublic);
      } else if (event.event === 'attempt_finished') {
        if (
          !currentPublic ||
          event.code !== 'ok' ||
          !currentPublic.row.result_sha256 ||
          currentPublic.row.returned_at_ms !== null
        )
          throw Error('fixture_failed');
        currentPublic.row.returned_at_ms = Date.now();
        returned++;
        currentPublic = undefined;
      } else if (event.event !== 'closed') throw Error('fixture_failed');
    } catch {
      fail();
    }
  }
  const publicServer = new SpecialistServer({
    trust,
    evidence: new RecordingRegistry(records),
    fixedPolicy: new RecordingPolicy(),
    observer: observe,
    limits: { maxActive: 1, maxPerPrincipal: 1 },
    hooks: {
      beforeEvaluate: async ({ signal }) => {
        const entry = queue.shift();
        if (!entry) throw Error('fixture_failed');
        const name = HOLDS.get(entry.row.label);
        if (name) {
          arrived(directory, name);
          await released(directory, name, AbortSignal.any([signal, closing.signal]));
          signal.throwIfAborted();
        }
      },
    },
  });
  async function fault(request, response) {
    faultRequests++;
    let permit,
      timer,
      admitted = false;
    try {
      if (
        closing.signal.aborted ||
        faultActive >= 1 ||
        faultRequests > 1 ||
        request.method !== 'POST' ||
        request.url !== '/v1/invoke'
      )
        throw Error('fixture_failed');
      const names = request.rawHeaders.filter((_, i) => i % 2 === 0).map((n) => n.toLowerCase());
      if (
        new Set(names).size !== names.length ||
        names.some(
          (n) =>
            !['host', 'authorization', 'content-type', 'content-length', 'connection'].includes(n),
        ) ||
        request.headers.host !== '127.0.0.1:' + faultPort ||
        request.headers['content-type'] !== 'application/json' ||
        request.headers.connection !== 'close' ||
        !/^[1-9][0-9]{0,4}$/.test(request.headers['content-length'] ?? '')
      )
        throw Error('fixture_failed');
      const length = Number(request.headers['content-length']);
      if (length > 16384) throw Error('fixture_failed');
      faultActive++;
      admitted = true;
      const payload = await new Promise((yes, no) => {
        const chunks = [];
        let total = 0;
        timer = setTimeout(() => {
          request.destroy();
          no(Error('fixture_failed'));
        }, 1500);
        request.on('data', (chunk) => {
          total += chunk.length;
          if (total > length || total > 16384) {
            request.destroy();
            no(Error('fixture_failed'));
          } else chunks.push(chunk);
        });
        request.once('end', () => {
          clearTimeout(timer);
          if (total !== length) no(Error('fixture_failed'));
          else yes(Buffer.concat(chunks));
        });
        request.once('error', () => no(Error('fixture_failed')));
        request.once('aborted', () => no(Error('fixture_failed')));
      });
      const parsed = parseFixedPolicyRequest(payload),
        authorization = request.headers.authorization;
      trust.authorize(authorization, 'result', parsed);
      permit = boundary.acquire(authorization, parsed, Date.now());
      const entry = enter(bind(parsed, 'fault'));
      const base = new FixedPolicyHandler().evaluate(
        parsed,
        registry.resolve(authorization, parsed, trust),
        Date.now(),
      );
      const hold = HOLDS.get(entry.row.label);
      if (hold) {
        save(join(directory, 'fixed-work-' + entry.row.label + '-phase.json'), {
          schema_version: 1,
          label: entry.row.label,
          deadline_at_ms: parsed.deadline_at_ms,
          request_sha256: entry.row.request_sha256,
        });
        arrived(directory, hold);
        await released(directory, hold, closing.signal);
      }
      const result = structuredClone(base);
      if (entry.row.label === 'wrong_rule') result.rule_refs[0].rule_id = 'notice_invented';
      else if (entry.row.label === 'wrong_witness') result.fact_refs[0].fact_id = 'notice_forged';
      else if (entry.row.label === 'foreign_scope') result.scope.account_id = 'account_foreign';
      else if (entry.row.label !== 'expired_valid') result.eligible = false;
      const body = recordResult(entry, result);
      await new Promise((yes, no) => {
        let settled = false;
        const finish = () => {
          if (!settled) {
            settled = true;
            entry.row.returned_at_ms = Date.now();
            returned++;
            yes();
          }
        };
        response.once('finish', finish);
        response.once('close', () => {
          if (!settled) {
            settled = true;
            no(Error('fixture_failed'));
          }
        });
        response.writeHead(200, {
          'Content-Type': 'application/json',
          'Content-Length': body.length,
          Connection: 'close',
        });
        response.end(body);
      });
    } catch {
      fail();
      if (!response.headersSent && !response.destroyed)
        response.writeHead(400, { 'Content-Length': '0', Connection: 'close' });
      response.end();
    } finally {
      if (timer) clearTimeout(timer);
      if (permit) boundary.release(permit);
      if (admitted) faultActive--;
      faultRequests--;
    }
  }
  const faultServer = createServer({ maxHeaderSize: 4096 }, (request, response) => {
    const work = fault(request, response);
    handlers.add(work);
    void work.then(
      () => handlers.delete(work),
      () => {
        handlers.delete(work);
        fail();
      },
    );
  });
  faultServer.maxHeadersCount = 8;
  faultServer.maxConnections = 4;
  faultServer.maxRequestsPerSocket = 1;
  faultServer.on('dropRequest', (_request, socket) => {
    fail();
    socket.destroy();
  });
  faultServer.headersTimeout = 1000;
  faultServer.requestTimeout = 2000;
  faultServer.on('connection', (socket) => {
    if (faultSockets.size >= 4 || closing.signal.aborted) {
      socket.destroy();
      fail();
      return;
    }
    let done;
    const closed = new Promise((resolve) => {
      done = resolve;
    });
    const timer = setTimeout(() => {
      socket.destroy();
      fail();
    }, 1500);
    faultSockets.set(socket, { closed, timer });
    socket.once('close', () => {
      clearTimeout(timer);
      faultSockets.delete(socket);
      done();
    });
    socket.once('error', () => undefined);
  });
  faultServer.on('request', (request) => {
    const owned = faultSockets.get(request.socket);
    if (owned) clearTimeout(owned.timer);
  });
  faultServer.on('clientError', (_error, socket) => {
    fail();
    socket.destroy();
  });
  faultServer.on('checkContinue', (_request, response) => {
    fail();
    response.writeHead(417, { 'Content-Length': 0, Connection: 'close' });
    response.end();
  });
  faultServer.on('upgrade', (_request, socket) => {
    fail();
    socket.destroy();
  });
  faultServer.on('connect', (_request, socket) => {
    fail();
    socket.destroy();
  });
  faultServer.on('error', () => fail());
  async function close() {
    stage = 'close';
    closing.abort(Error('fixture_failed'));
    const closeDeadline = performance.now() + 10000;
    const sockets = [...faultSockets.values()].map((owner) => owner.closed);
    for (const socket of faultSockets.keys()) socket.destroy();
    faultStopped ??= new Promise((yes) => {
      if (faultServer.listening) faultServer.close(yes);
      else yes();
    });
    let timeout;
    try {
      await Promise.race([
        Promise.allSettled([publicServer.close(), faultStopped, ...handlers, ...sockets]).then(
          (outcomes) => {
            if (outcomes.some((o) => o.status === 'rejected')) throw Error('cleanup_incomplete');
          },
        ),
        new Promise((_, no) => {
          timeout = setTimeout(() => no(Error('cleanup_incomplete')), 10000);
        }),
      ]);
      while (publicServer.metrics().observerPending) {
        if (performance.now() >= closeDeadline) throw Error('cleanup_incomplete');
        await delay(0);
      }
      const metrics = publicServer.metrics();
      if (
        metrics.active ||
        metrics.requests ||
        metrics.sockets ||
        faultActive ||
        faultRequests ||
        faultSockets.size ||
        handlers.size ||
        boundary.active
      )
        throw Error('cleanup_incomplete');
    } finally {
      if (timeout) clearTimeout(timeout);
    }
  }
  return {
    async start() {
      const normal = await publicServer.listen();
      const raw = await new Promise((yes, no) => {
        faultServer.once('error', no);
        faultServer.listen(0, '127.0.0.1', () => {
          faultServer.off('error', no);
          yes(faultServer.address());
        });
      });
      faultPort = raw.port;
      stage = 'serve';
      return {
        schema_version: 1,
        node_version: process.versions.node,
        pid: process.pid,
        public: normal,
        fault: { host: '127.0.0.1', port: faultPort },
      };
    },
    close,
    async finish() {
      await close();
      stage = 'proof';
      const metrics = publicServer.metrics();
      if (
        primary ||
        duplicates ||
        publicInvoked !== 7 ||
        faultInvoked !== 6 ||
        returned !== 13 ||
        entries.size !== 13 ||
        metrics.invoked !== 7 ||
        metrics.completed !== 7 ||
        metrics.rejected ||
        metrics.observerFailures ||
        metrics.observerDropped
      )
        throw Error('fixture_failed');
      const rows = LABELS.map((name) => entries.get(name)?.row);
      if (rows.some((row) => !row || !row.result_sha256 || row.returned_at_ms === null))
        throw Error('fixture_failed');
      const proof = {
        schema_version: 1,
        kind: 'fixed-policy.execution-peer',
        cleanup_complete: true,
        counts: {
          invoked: publicInvoked + faultInvoked,
          returned,
          public_server_invoked: publicInvoked,
          fault_invoked: faultInvoked,
          active: 0,
          requests: 0,
          sockets: 0,
        },
        records: rows,
      };
      save(join(directory, 'fixed-work-node-observations.json'), {
        schema_version: 1,
        public_metrics: metrics,
        events,
        duplicates,
        fault_active: faultActive,
        fault_requests: faultRequests,
        fault_sockets: faultSockets.size,
        pending_handlers: handlers.size,
      });
      return save(join(directory, 'fixed-work-peer.json'), proof);
    },
    stage: () => stage,
  };
}

export async function main() {
  let owner,
    cleanup = true,
    stage = 'setup';
  try {
    if (
      process.argv.length !== 3 ||
      process.argv[2] !== 'serve' ||
      process.versions.node !== '24.22.2'
    )
      throw Error('invalid_input');
    const config = validateEnvironment(process.env),
      decoded = parsePeerInput(readPrivate(config.input));
    if (
      existsSync(config.endpoint) ||
      existsSync(config.stop) ||
      existsSync(join(config.directory, 'fixed_work_server_ready.reached'))
    )
      throw Error('invalid_input');
    owner = createPeer(config, decoded);
    cleanup = false;
    stage = 'listen';
    const endpoint = await owner.start();
    save(config.endpoint, endpoint);
    arrived(config.directory, 'fixed_work_server_ready');
    stage = 'serve';
    const until = performance.now() + 150000;
    while (!marker(config.stop)) {
      if (performance.now() >= until) throw Error('fixture_failed');
      await delay(5);
    }
    const proof = await owner.finish();
    cleanup = true;
    process.stdout.write(
      JSON.stringify({
        schema_version: 1,
        status: 'passed',
        mode: 'serve',
        node_version: process.versions.node,
        peer_sha256: sha(proof),
        cleanup_complete: true,
      }) + '\n',
    );
  } catch (error) {
    if (owner) {
      stage = owner.stage();
      try {
        await owner.close();
        cleanup = true;
      } catch {
        cleanup = false;
      }
    }
    const code =
      !cleanup && owner
        ? 'cleanup_incomplete'
        : error.message === 'invalid_input'
          ? 'invalid_input'
          : 'fixture_failed';
    process.stdout.write(
      JSON.stringify({
        schema_version: 1,
        status: 'failed',
        mode: 'serve',
        code,
        stage,
        cleanup_complete: cleanup,
      }) + '\n',
    );
    process.exitCode = 1;
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
