/** Test-only noncooperating peer. No execution ledger, supplier, scheduler or provider. */
import { createHash, randomUUID } from 'node:crypto';
import {
  existsSync,
  constants,
  openSync,
  fstatSync,
  closeSync,
  lstatSync,
  linkSync,
  readFileSync,
  readSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { createServer } from 'node:http';
import { basename, dirname, isAbsolute, join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import {
  AttemptBoundary,
  CAPABILITY,
  ContractError,
  EvidenceRegistry,
  LocalTrust,
  canonical,
  encodeError,
  encodeRequest,
  encodeResult,
  matchResult,
  parseRequest,
  parseResult,
  tokenDigest,
  verifyPolicyFacts,
} from '@livekit-ecosystem/delegation-specialist';

const LABELS = Object.freeze({
  expiry: 'remote_expiry',
  lease: 'remote_lease',
  cancel: 'remote_cancel',
  cancel_lost: 'remote_cancel_lost',
  caller_timeout: 'remote_timeout',
  caller_cancel: 'remote_waiter_cancel',
  crash: 'remote_crash',
  known: null,
  useful: null,
});
const EXPECTED = Object.freeze({
  invocations: 9,
  completed: 9,
  cancel_requests: 2,
  cancel_acknowledgements: 1,
  cancel_ack_lost: 1,
  status_observations: 1,
  rejected: 2,
  active: 0,
  requests: 0,
  sockets: 0,
});
const ENV = new Set([
  'PATH',
  'HOME',
  'TMPDIR',
  'TEMP',
  'TMP',
  'LANG',
  'LC_ALL',
  '__CF_USER_TEXT_ENCODING',
  'NO_COLOR',
  'CI',
  'P3_DEADLINE_TOKEN',
  'P3_DEADLINE_DIRECTORY',
  'P3_DEADLINE_READY',
  'P3_DEADLINE_ENDPOINT_FILE',
  'P3_DEADLINE_STOP',
]);
const MAX_RECORDS = 64;
const MAX_PROOF = 32768;
const MAX_BODY = 16384;
const MAX_ACTIVE = 4;
const MAX_HANDLERS = 16;
const MAX_SOCKETS = 16;
const HOLD_MS = 4500;
const IO_MS = 1000;
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
function fail() {
  throw new Error('fixture_failed');
}
function owned(path, directory = false) {
  const info = lstatSync(path);
  if (
    info.isSymbolicLink() ||
    (directory ? !info.isDirectory() : !info.isFile()) ||
    info.uid !== process.getuid() ||
    (info.mode & 0o777) !== (directory ? 0o700 : 0o600) ||
    (!directory && info.nlink !== 1)
  )
    fail();
  return info;
}
async function readReleasedPid(path, pid, deadline) {
  const pending = path + '.' + pid + '.pending';
  let original;
  const safe = (info, links) =>
    info.isFile() &&
    !info.isSymbolicLink() &&
    info.uid === process.getuid() &&
    (info.mode & 0o777) === 0o600 &&
    info.nlink === links &&
    info.size >= 1 &&
    info.size <= 32;
  const same = (a, b) => a.dev === b.dev && a.ino === b.ino;
  while (performance.now() < deadline) {
    const info = lstatSync(path);
    if (original && !same(info, original)) fail();
    original ??= info;
    if (safe(info, 1)) {
      const descriptor = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
      try {
        const opened = fstatSync(descriptor);
        if (!safe(opened, 1) || !same(opened, original)) fail();
        const bytes = Buffer.alloc(33);
        const count = readSync(descriptor, bytes, 0, bytes.length, 0);
        const observed = fstatSync(descriptor);
        const after = lstatSync(path);
        if (
          count > 32 ||
          count !== opened.size ||
          !safe(observed, 1) ||
          !same(observed, original) ||
          observed.size !== opened.size ||
          !safe(after, 1) ||
          !same(after, original) ||
          after.size !== opened.size ||
          bytes.subarray(0, count).toString('utf8') !== String(pid) + '\n'
        )
          fail();
        if (performance.now() >= deadline) fail();
        return pid;
      } finally {
        closeSync(descriptor);
      }
    }
    if (!safe(info, 2)) fail();
    let publishing;
    try {
      publishing = lstatSync(pending);
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      const settled = lstatSync(path);
      if (!safe(settled, 1) || !same(settled, original)) fail();
      continue;
    }
    if (!safe(publishing, 2) || !same(info, publishing)) fail();
    await delay(1);
  }
  fail();
}
function configuration() {
  if (Object.keys(process.env).some((key) => !ENV.has(key))) fail();
  const token = process.env.P3_DEADLINE_TOKEN;
  if (!/^[A-Za-z0-9_-]{43}(?![\s\S])/.test(token ?? '')) fail();
  const original = process.env.P3_DEADLINE_DIRECTORY;
  if (!original || !isAbsolute(original) || original.length > 4096) fail();
  const directory = resolve(original);
  owned(directory, true);
  const paths = {};
  for (const [name, key] of [
    ['ready', 'READY'],
    ['endpoint', 'ENDPOINT_FILE'],
    ['stop', 'STOP'],
  ]) {
    const value = process.env['P3_DEADLINE_' + key];
    if (
      !value ||
      !isAbsolute(value) ||
      value.length > 4096 ||
      dirname(resolve(value)) !== directory ||
      existsSync(value)
    )
      fail();
    paths[name] = resolve(value);
  }
  if (new Set(Object.values(paths)).size !== 3) fail();
  return { token, directory, ...paths };
}
function atomic(path, bytes, replace = false) {
  if (bytes.byteLength > MAX_PROOF) fail();
  if (replace && existsSync(path)) owned(path);
  const temporary = join(dirname(path), '.' + basename(path) + '-' + randomUUID());
  writeFileSync(temporary, bytes, { flag: 'wx', mode: 0o600 });
  try {
    if (replace) renameSync(temporary, path);
    else {
      linkSync(temporary, path);
      unlinkSync(temporary);
    }
  } finally {
    if (existsSync(temporary)) unlinkSync(temporary);
  }
}
function jsonFile(path, value, replace = false) {
  atomic(path, Buffer.from(JSON.stringify(value) + '\n'), replace);
}
function status(error) {
  return (
    {
      unauthorized: 401,
      unknown_attempt: 404,
      identity_conflict: 409,
      expired: 408,
      capacity: 429,
    }[error.code] ?? 400
  );
}
async function main() {
  const config = configuration();
  const scope = Object.freeze({ tenant_id: 'tenant_deadline', account_id: 'account_deadline' });
  const policyBody = canonical({ minimum_notice_days: 7, policy_version: 'policy_v1' });
  const reference = Object.freeze({
    source_id: 'policy_demo',
    version: 'source_v1',
    sha256: hash(policyBody),
    media_type: 'application/json',
    byte_length: policyBody.byteLength,
    width: null,
    height: null,
  });
  const trust = new LocalTrust([
    {
      principal_id: 'deadline_check_service',
      token_sha256: tokenDigest(config.token),
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
  const evidence = new EvidenceRegistry([{ scope, reference, body: policyBody }]);
  const boundary = new AttemptBoundary(trust, evidence, MAX_ACTIVE, MAX_ACTIVE);
  const counts = { ...EXPECTED };
  for (const key of Object.keys(counts)) counts[key] = 0;
  const records = [];
  const active = new Map();
  const labels = new Set();
  const sockets = new Set();
  const handlers = new Set();
  const headerTimers = new Map();
  const usedSockets = new WeakSet();
  const proofPath = join(config.directory, 'peer-observations.json');
  if (existsSync(proofPath)) fail();
  let closing = false;
  let interrupted = false;
  let fatal = false;
  function journal(final = false) {
    if (records.length > MAX_RECORDS) fail();
    jsonFile(
      proofPath,
      {
        schema_version: 1,
        status: final ? 'passed' : 'running',
        counters: {
          ...counts,
          active: active.size,
          requests: handlers.size,
          sockets: sockets.size,
        },
        records,
      },
      true,
    );
  }
  async function barrier(name) {
    const reached = join(config.directory, name + '.reached');
    const released = join(config.directory, name + '.released');
    atomic(reached, Buffer.from(String(process.pid) + '\n'));
    const deadline = performance.now() + HOLD_MS;
    while (!existsSync(released)) {
      if (closing || performance.now() >= deadline) fail();
      await delay(5);
    }
    await readReleasedPid(released, process.pid, deadline);
  }
  async function send(response, code, body) {
    if (body.byteLength > 8192) fail();
    if (response.destroyed || response.socket?.destroyed) return false;
    return await new Promise((settle) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        response.off('finish', finish);
        response.off('close', finish);
        response.off('error', finish);
        settle(response.writableFinished);
      };
      const timer = setTimeout(() => {
        response.destroy();
        finish();
      }, IO_MS);
      response.once('finish', finish);
      response.once('close', finish);
      response.once('error', finish);
      response.writeHead(code, {
        'content-type': 'application/json',
        'content-length': body.byteLength,
        connection: 'close',
        'cache-control': 'no-store',
      });
      response.end(body);
    });
  }
  function body(request, length) {
    return new Promise((settle, reject) => {
      const bytes = Buffer.alloc(length);
      let used = 0;
      let done = false;
      const finish = (error = null) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        request.off('data', data);
        request.off('end', end);
        request.off('aborted', abort);
        request.off('error', abort);
        if (error) {
          request.pause();
          reject(error);
        } else settle(bytes);
      };
      const data = (chunk) => {
        if (used + chunk.byteLength > length) {
          finish(new ContractError());
          return;
        }
        chunk.copy(bytes, used);
        used += chunk.byteLength;
      };
      const end = () => finish(used === length ? null : new ContractError());
      const abort = () => finish(new ContractError());
      const timer = setTimeout(() => finish(new ContractError()), IO_MS);
      request.on('data', data);
      request.once('end', end);
      request.once('aborted', abort);
      request.once('error', abort);
    });
  }
  function headers(request) {
    if (
      request.httpVersion !== '1.1' ||
      request.method !== 'POST' ||
      !['/v1/invoke', '/v1/cancel', '/v1/status'].includes(request.url) ||
      request.rawHeaders.length > 32
    )
      throw new ContractError();
    const seen = new Set();
    const allowed = new Set([
      'host',
      'content-type',
      'content-length',
      'connection',
      'authorization',
    ]);
    for (let n = 0; n < request.rawHeaders.length; n += 2) {
      const key = request.rawHeaders[n].toLowerCase();
      if (seen.has(key) || !allowed.has(key)) throw new ContractError();
      seen.add(key);
    }
    const length = request.headers['content-length'];
    const authorization = request.headers.authorization;
    if (
      request.headers['content-type'] !== 'application/json' ||
      request.headers.connection !== 'close' ||
      typeof length !== 'string' ||
      !/^(0|[1-9][0-9]{0,5})(?![\s\S])/.test(length) ||
      Number(length) > MAX_BODY
    )
      throw new ContractError();
    if (typeof authorization !== 'string') throw new ContractError('unauthorized');
    trust.authenticate(authorization);
    return { length: Number(length), authorization };
  }
  async function invoke(input, authorization, response) {
    const label = input.delegation_id.slice('delegation_'.length);
    if (
      input.delegation_id !== 'delegation_' + label ||
      !Object.hasOwn(LABELS, label) ||
      labels.has(label)
    )
      throw new ContractError('identity_conflict');
    if (records.length >= MAX_RECORDS) throw new ContractError('capacity');
    const permit = boundary.acquire(authorization, input, Date.now());
    labels.add(label);
    const record = {
      label,
      delegation_id: input.delegation_id,
      attempt_id: input.attempt.attempt_id,
      input_fingerprint: input.input_fingerprint,
      request_sha256: hash(encodeRequest(input)),
      result_sha256: null,
      started_at_ms: Date.now(),
      request_deadline_at_ms: input.deadline_at_ms,
      result_completed_at_ms: null,
      result_ready_at_ms: null,
      cancel_requested: false,
      cancel_acknowledged: false,
      cancel_ack_lost: false,
      response_finished: false,
      transport_disconnected: false,
      timeliness_observed: null,
    };
    records.push(record);
    counts.invocations++;
    active.set(input.attempt.attempt_id, { input, record });
    const disconnected = () => {
      if (!response.writableFinished) record.transport_disconnected = true;
    };
    response.once('close', disconnected);
    try {
      journal();
      if (LABELS[label] !== null) await barrier(LABELS[label]);
      // The peer intentionally does not honor business cancellation or expiry.
      // Production SpecialistServer remains cooperative and is not altered.
      const records = evidence.resolve(authorization, input, trust);
      const policy = records.find(
        (item) => item.reference.source_id === input.context_snapshot.policy_source_id,
      );
      if (!policy) throw new ContractError('evidence_mismatch');
      const completed =
        label === 'expiry' || label === 'crash' ? input.deadline_at_ms - 1 : Date.now();
      const result = parseResult(
        canonical({
          schema_version: 1,
          kind: 'delegation.result',
          capability: CAPABILITY,
          result_schema_version: 1,
          scope: input.scope,
          delegation_id: input.delegation_id,
          case_id: input.case_id,
          request_revision: input.request_revision,
          attempt_id: input.attempt.attempt_id,
          input_fingerprint: input.input_fingerprint,
          eligible: input.context_snapshot.days_before_arrival >= 7,
          uncertainty: 'none',
          evidence_refs: [
            {
              source_id: policy.reference.source_id,
              version: policy.reference.version,
              sha256: policy.reference.sha256,
              rule_id: 'notice_minimum_days',
            },
          ],
          producer: {
            producer_id: 'scripted_policy_http_v1',
            model_id: null,
            model_version: null,
            config_fingerprint: hash(Buffer.from('scripted_policy_http_v1')),
          },
          completed_at_ms: completed,
        }),
      );
      // Validate strict facts at a predeadline observation; actual lateness is
      // recorded separately and remains entirely governed by P1's DB authority.
      if (
        verifyPolicyFacts(
          input,
          result,
          records,
          Math.min(Date.now(), input.deadline_at_ms - 1),
        ) !== 'candidate'
      )
        throw new ContractError('unsupported_facts');
      const encoded = encodeResult(result);
      record.result_sha256 = hash(encoded);
      record.result_completed_at_ms = result.completed_at_ms;
      record.result_ready_at_ms = Date.now();
      record.timeliness_observed = matchResult(input, result, record.result_ready_at_ms);
      counts.completed++;
      journal();
      record.response_finished = await send(response, 200, encoded);
      if (!record.response_finished) record.transport_disconnected = true;
    } finally {
      response.off('close', disconnected);
      active.delete(input.attempt.attempt_id);
      boundary.release(permit);
      journal();
    }
  }
  async function handle(request, response) {
    try {
      if (closing) throw new ContractError('capacity');
      const { authorization, length } = headers(request);
      const input = parseRequest(await body(request, length));
      if (request.url === '/v1/invoke') {
        await invoke(input, authorization, response);
        return;
      }
      boundary.inspect(authorization, input, request.url === '/v1/cancel' ? 'cancel' : 'result');
      const state = active.get(input.attempt.attempt_id);
      if (!state) throw new ContractError('unknown_attempt');
      if (request.url === '/v1/cancel') {
        if (state.record.cancel_requested) throw new ContractError('identity_conflict');
        state.record.cancel_requested = true;
        counts.cancel_requests++;
        if (state.record.label === 'cancel_lost') {
          state.record.cancel_ack_lost = true;
          counts.cancel_ack_lost++;
          journal();
          // Graceful FIN without any response header: correctly uncertain ACK.
          response.socket?.end();
          return;
        }
        state.record.cancel_acknowledged = true;
        counts.cancel_acknowledgements++;
      } else counts.status_observations++;
      journal();
      await send(
        response,
        request.url === '/v1/cancel' ? 202 : 200,
        canonical({
          schema_version: 1,
          kind: 'specialist.attempt_observation',
          scope: state.input.scope,
          delegation_id: state.input.delegation_id,
          attempt_id: state.input.attempt.attempt_id,
          input_fingerprint: state.input.input_fingerprint,
          state: 'running',
          cancel_requested: state.record.cancel_requested,
          deadline_exceeded: Date.now() >= state.input.deadline_at_ms,
          transport_disconnected: state.record.transport_disconnected,
          closing,
          durable: false,
        }),
      );
    } catch (error) {
      counts.rejected++;
      const safe = error instanceof ContractError ? error : new ContractError();
      if (!(error instanceof ContractError)) fatal = true;
      journal();
      await send(response, status(safe), encodeError(safe.code, 'deadline_peer_request'));
    }
  }
  const server = createServer(
    { maxHeaderSize: 8192, headersTimeout: 0, requestTimeout: 0, keepAliveTimeout: 1 },
    (request, response) => {
      const timer = headerTimers.get(request.socket);
      if (timer) clearTimeout(timer);
      headerTimers.delete(request.socket);
      if (closing || usedSockets.has(request.socket) || handlers.size >= MAX_HANDLERS) {
        request.socket.destroy();
        return;
      }
      usedSockets.add(request.socket);
      const pending = handle(request, response);
      handlers.add(pending);
      void pending
        .catch(() => {
          fatal = true;
          response.destroy();
        })
        .finally(() => {
          handlers.delete(pending);
        });
    },
  );
  server.maxConnections = MAX_SOCKETS;
  server.on('connection', (socket) => {
    if (closing || sockets.size >= MAX_SOCKETS) {
      socket.destroy();
      return;
    }
    sockets.add(socket);
    const timer = setTimeout(() => socket.destroy(), IO_MS);
    headerTimers.set(socket, timer);
    socket.once('close', () => {
      sockets.delete(socket);
      const timer = headerTimers.get(socket);
      if (timer) clearTimeout(timer);
      headerTimers.delete(socket);
    });
    socket.on('error', () => {});
  });
  server.on('clientError', (_error, socket) => {
    counts.rejected++;
    socket.destroy();
  });
  server.on('error', () => {
    fatal = true;
  });
  const interruptedSignal = () => {
    interrupted = true;
  };
  process.once('SIGTERM', interruptedSignal);
  process.once('SIGINT', interruptedSignal);
  try {
    await new Promise((settle, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', () => {
        server.off('error', reject);
        settle();
      });
    });
    const address = server.address();
    if (!address || typeof address === 'string') fail();
    journal();
    jsonFile(config.endpoint, { port: address.port, node_version: process.versions.node });
    atomic(config.ready, Buffer.from(String(process.pid) + '\n'));
    const deadline = performance.now() + 120000;
    while (!existsSync(config.stop)) {
      if (fatal || interrupted || performance.now() >= deadline) fail();
      await delay(10);
    }
    owned(config.stop);
  } finally {
    closing = true;
    const closed = new Promise((settle) => {
      server.close(() => settle());
    });
    for (const timer of headerTimers.values()) clearTimeout(timer);
    headerTimers.clear();
    const deadline = performance.now() + 2000;
    while ((handlers.size || active.size || sockets.size) && performance.now() < deadline)
      await delay(5);
    for (const socket of sockets) socket.destroy();
    await closed;
    await Promise.allSettled([...handlers]);
    process.off('SIGTERM', interruptedSignal);
    process.off('SIGINT', interruptedSignal);
    if (handlers.size || active.size || sockets.size || boundary.active) fail();
  }
  if (fatal || interrupted || records.length !== 9 || labels.size !== 9) fail();
  for (const [key, value] of Object.entries(EXPECTED)) {
    const actual =
      key === 'active'
        ? active.size
        : key === 'requests'
          ? handlers.size
          : key === 'sockets'
            ? sockets.size
            : counts[key];
    if (actual !== value) fail();
  }
  journal(true);
  console.info(
    JSON.stringify({
      status: 'passed',
      cleanup_complete: true,
      node_version: process.versions.node,
      ...EXPECTED,
    }),
  );
}
main().catch(() => {
  console.error(JSON.stringify({ status: 'failed', code: 'fixture_failed' }));
  process.exitCode = 1;
});
