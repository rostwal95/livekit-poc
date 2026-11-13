/** Trusted recovery fault fixture. Observation only; no durable execution authority. */
import { createHash } from 'node:crypto';
import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { basename, dirname, isAbsolute, join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import {
  CAPABILITY,
  ContractError,
  EvidenceRegistry,
  LocalTrust,
  SpecialistServer,
  canonical,
  encodeRequest,
  parseRequest,
  tokenDigest,
} from '@livekit-ecosystem/delegation-specialist';

const BASE = [
  'PATH',
  'HOME',
  'TMPDIR',
  'TEMP',
  'TMP',
  'LANG',
  'LC_ALL',
  'LC_CTYPE',
  'SYSTEMROOT',
  '__CF_USER_TEXT_ENCODING',
  'NO_COLOR',
  'CI',
];
const TASK = [
  'P3_RECOVERY_NODE_TOKEN',
  'P3_RECOVERY_DIRECTORY',
  'P3_RECOVERY_GENERATION',
  'P3_RECOVERY_ENDPOINT_FILE',
  'P3_RECOVERY_READY',
  'P3_RECOVERY_STOP',
];
const LABELS = Object.freeze({
  a: Object.freeze(['issued_recovery', 'specialist_loss']),
  b: Object.freeze([
    'specialist_recovery',
    'coordinator_loss',
    'coordinator_recovery',
    'result_precommit',
    'result_precommit_recovery',
    'result_postcommit',
    'unknown_delivery',
    'useful_current',
  ]),
});
const MAX_JOURNAL = 32768;
const MAX_WRITES = 128;
const MAX_RECORDS = 10;
const PID = `${process.pid}\n`;
const uid = process.getuid?.();
const sameFile = (a, b) => a.dev === b.dev && a.ino === b.ino;
function regular(stat, size) {
  return (
    stat.isFile() &&
    stat.uid === uid &&
    (stat.mode & 0o777) === 0o600 &&
    stat.nlink === 1 &&
    stat.size <= size
  );
}
function checkedFile(path, maximum) {
  const before = lstatSync(path);
  if (!regular(before, maximum)) throw new Error('fixture_file');
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const actual = fstatSync(fd);
    if (!regular(actual, maximum) || !sameFile(before, actual)) throw new Error('fixture_file');
    const bytes = Buffer.alloc(maximum + 1);
    const n = readSync(fd, bytes, 0, bytes.length, 0);
    if (n > maximum || n !== actual.size) throw new Error('fixture_file');
    return bytes.subarray(0, n);
  } finally {
    closeSync(fd);
  }
}
function absent(path) {
  try {
    lstatSync(path);
    return false;
  } catch (error) {
    if (error.code === 'ENOENT') return true;
    throw error;
  }
}
function writeExclusive(path, value, maximum) {
  const bytes = Buffer.isBuffer(value) ? value : Buffer.from(value);
  if (bytes.length > maximum) throw new Error('fixture_size');
  writeFileSync(path, bytes, { flag: 'wx', mode: 0o600 });
  if (!regular(lstatSync(path), maximum)) throw new Error('fixture_file');
}
function configuration() {
  const allowed = new Set([...BASE, ...TASK]);
  if (
    Object.keys(process.env).some((key) => !allowed.has(key)) ||
    TASK.some((key) => typeof process.env[key] !== 'string')
  )
    throw new Error('fixture_environment');
  const token = process.env.P3_RECOVERY_NODE_TOKEN;
  const generation = process.env.P3_RECOVERY_GENERATION;
  const directory = process.env.P3_RECOVERY_DIRECTORY;
  if (
    !/^[A-Za-z0-9_-]{43}(?![\s\S])/.test(token) ||
    !Object.hasOwn(LABELS, generation) ||
    !isAbsolute(directory) ||
    directory.length > 4096 ||
    resolve(directory) !== directory
  )
    throw new Error('fixture_configuration');
  const stat = lstatSync(directory);
  if (
    !stat.isDirectory() ||
    stat.isSymbolicLink() ||
    stat.uid !== uid ||
    (stat.mode & 0o777) !== 0o700
  )
    throw new Error('fixture_directory');
  const selected = ['P3_RECOVERY_ENDPOINT_FILE', 'P3_RECOVERY_READY', 'P3_RECOVERY_STOP'].map(
    (key) => {
      const value = process.env[key];
      if (
        !isAbsolute(value) ||
        value.length > 4096 ||
        resolve(value) !== value ||
        dirname(value) !== directory ||
        !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}(?![\s\S])/.test(basename(value))
      )
        throw new Error('fixture_path');
      return value;
    },
  );
  const journal = join(directory, `recovery-peer-${generation}.json`);
  const marker = join(
    directory,
    generation === 'a' ? 'specialist_http_started.reached' : 'coordinator_remote_started.reached',
  );
  if (
    new Set([...selected, journal, marker]).size !== 5 ||
    [...selected, journal, marker].some((path) => !absent(path))
  )
    throw new Error('fixture_existing_file');
  return {
    token,
    generation,
    directory,
    endpoint: selected[0],
    ready: selected[1],
    stop: selected[2],
    journal,
    marker,
  };
}
async function waitForAbort(signal) {
  if (signal.aborted) return;
  let timer;
  let abort;
  try {
    await new Promise((yes, no) => {
      abort = () => yes();
      signal.addEventListener('abort', abort, { once: true });
      timer = setTimeout(() => no(new Error('fixture_abort_timeout')), 4500);
      if (signal.aborted) yes();
    });
  } finally {
    if (timer) clearTimeout(timer);
    if (abort) signal.removeEventListener('abort', abort);
  }
}
async function main() {
  const config = configuration();
  const scopes = ['execution', 'completion'].map((account_id) =>
    Object.freeze({ tenant_id: 'tenant_recovery', account_id }),
  );
  const body = canonical({ minimum_notice_days: 7, policy_version: 'policy_v1' });
  const reference = Object.freeze({
    source_id: 'policy_demo',
    version: 'source_v1',
    sha256: createHash('sha256').update(body).digest('hex'),
    media_type: 'application/json',
    byte_length: body.byteLength,
    width: null,
    height: null,
  });
  const trust = new LocalTrust([
    {
      principal_id: 'recovery_fixture_service',
      token_sha256: tokenDigest(config.token),
      scopes: scopes.map((scope) => ({
        scope,
        invoke_capabilities: [CAPABILITY],
        result_capabilities: [CAPABILITY],
        cancel_capabilities: [CAPABILITY],
        evidence_sources: ['policy_demo'],
      })),
    },
  ]);
  const records = [];
  let candidate = null;
  let current = null;
  let server;
  let failure;
  let writes = 0;
  let lastCounters = '';
  const initialMetrics = {
    invoked: 0,
    completed: 0,
    cancellations: 0,
    disconnects: 0,
    active: 0,
    requests: 0,
    sockets: 0,
  };
  function currentCounters() {
    const metrics = server?.metrics() ?? initialMetrics;
    return {
      invoked: metrics.invoked,
      strict_completed: metrics.completed,
      cancel_requests: metrics.cancellations,
      disconnects: metrics.disconnects,
      active: metrics.active,
      requests: metrics.requests,
      sockets: metrics.sockets,
    };
  }
  function snapshot(status = 'running') {
    if (++writes > MAX_WRITES) throw new Error('fixture_write_limit');
    const counters = currentCounters();
    if (Object.values(counters).some((value) => !Number.isSafeInteger(value) || value < 0))
      throw new Error('fixture_metrics');
    const bytes = Buffer.from(
      JSON.stringify({
        schema_version: 1,
        generation: config.generation,
        node_version: process.versions.node,
        status,
        counters,
        records,
      }),
    );
    if (bytes.length > MAX_JOURNAL) throw new Error('fixture_journal_size');
    if (!absent(config.journal)) checkedFile(config.journal, MAX_JOURNAL);
    const temporary = join(
      config.directory,
      `recovery-peer-${config.generation}.${process.pid}.${writes}.tmp`,
    );
    let ownedTemporary = false;
    try {
      writeExclusive(temporary, bytes, MAX_JOURNAL);
      ownedTemporary = true;
      renameSync(temporary, config.journal);
      lastCounters = JSON.stringify(counters);
    } finally {
      if (ownedTemporary && !absent(temporary)) unlinkSync(temporary);
    }
  }
  class ObservedEvidence extends EvidenceRegistry {
    resolve(authorization, request, localTrust) {
      const validated = super.resolve(authorization, request, localTrust);
      const copied = parseRequest(encodeRequest(request));
      const digest = createHash('sha256').update(encodeRequest(copied)).digest('hex');
      if (current?.attempt_id === copied.attempt.attempt_id) {
        if (current.request_sha256 !== digest) throw new ContractError('identity_conflict');
      } else {
        candidate = { request: copied, digest };
      }
      return validated;
    }
  }
  function observe(event) {
    try {
      if (event.event === 'attempt_started') {
        const label = LABELS[config.generation][records.length];
        if (!candidate || current || !label || records.length >= MAX_RECORDS)
          throw new Error('fixture_invocation');
        const { request, digest } = candidate;
        const account = ['unknown_delivery', 'useful_current'].includes(label)
          ? 'completion'
          : 'execution';
        if (
          request.scope.tenant_id !== 'tenant_recovery' ||
          request.scope.account_id !== account ||
          !/^attempt_[0-9a-f]{32}(?![\s\S])/.test(request.attempt.attempt_id)
        )
          throw new Error('fixture_identity');
        current = {
          label,
          scope: { ...request.scope },
          delegation_id: request.delegation_id,
          case_id: request.case_id,
          request_revision: request.request_revision,
          attempt_id: request.attempt.attempt_id,
          input_fingerprint: request.input_fingerprint,
          request_sha256: digest,
          started_at_ms: Date.now(),
          finished_at_ms: null,
          outcome: 'running',
        };
        candidate = null;
        records.push(current);
        snapshot();
      } else if (event.event === 'attempt_finished') {
        if (!current) throw new Error('fixture_finish');
        if (event.code === 'ok') current.outcome = 'completed';
        else if (['request_aborted', 'closing'].includes(event.code)) current.outcome = 'aborted';
        else throw new Error('fixture_evaluation');
        const finishedAt = Date.now();
        if (!Number.isSafeInteger(finishedAt) || finishedAt < current.started_at_ms)
          throw new Error('fixture_clock');
        current.finished_at_ms = finishedAt;
        current = null;
        snapshot();
      }
    } catch (error) {
      failure ??= error;
    }
  }
  let primary;
  let closed = false;
  try {
    server = new SpecialistServer({
      trust,
      evidence: new ObservedEvidence(scopes.map((scope) => ({ scope, reference, body }))),
      limits: { maxActive: 1, maxPerPrincipal: 1, invokeMs: 5000, closeMs: 2000 },
      observer: observe,
      hooks: {
        beforeEvaluate: async ({ signal }) => {
          if (failure || !current) throw new Error('fixture_observation');
          if (records.length === 2) {
            snapshot();
            writeExclusive(config.marker, PID, 32);
            await waitForAbort(signal);
          }
        },
      },
    });
    snapshot();
    const endpoint = await server.listen();
    if (
      endpoint.host !== '127.0.0.1' ||
      !Number.isInteger(endpoint.port) ||
      endpoint.port < 1024 ||
      endpoint.port > 65535
    )
      throw new Error('fixture_endpoint');
    writeExclusive(
      config.endpoint,
      JSON.stringify({
        schema_version: 1,
        generation: config.generation,
        host: endpoint.host,
        port: endpoint.port,
        node_version: process.versions.node,
      }),
      256,
    );
    writeExclusive(config.ready, PID, 32);
    const deadline = performance.now() + 165000;
    while (absent(config.stop)) {
      if (failure) throw failure;
      // attempt_finished precedes actual permit/socket release. Observe that
      // later public metric transition without inventing a settled zero.
      if (JSON.stringify(currentCounters()) !== lastCounters) snapshot();
      if (performance.now() >= deadline) throw new Error('fixture_stop_timeout');
      await delay(10);
    }
    if (checkedFile(config.stop, 32).toString() !== PID) throw new Error('fixture_stop_identity');
  } catch (error) {
    primary = error;
  } finally {
    if (server) {
      try {
        await server.close();
        closed = true;
      } catch (error) {
        primary ??= error;
      }
    }
  }
  if (primary) throw primary;
  if (failure) throw failure;
  const metrics = server.metrics();
  if (
    !closed ||
    config.generation !== 'b' ||
    records.length !== 8 ||
    metrics.invoked !== 8 ||
    metrics.completed !== 7 ||
    metrics.cancellations !== 0 ||
    metrics.disconnects !== 1 ||
    records.filter((record) => record.outcome === 'completed').length !== 7 ||
    records.filter((record) => record.outcome === 'aborted').length !== 1 ||
    records[1].outcome !== 'aborted' ||
    metrics.active !== 0 ||
    metrics.requests !== 0 ||
    metrics.sockets !== 0
  )
    throw new Error('fixture_truth');
  snapshot('closed');
  console.info(
    JSON.stringify({
      schema_version: 1,
      status: 'passed',
      generation: 'b',
      cleanup_complete: true,
      node_version: process.versions.node,
      invocations: 8,
      strict_completed: 7,
      active: 0,
      requests: 0,
      sockets: 0,
    }),
  );
}
main().catch(() => {
  console.error(JSON.stringify({ status: 'failed', code: 'fixture_failed' }));
  process.exitCode = 1;
});
