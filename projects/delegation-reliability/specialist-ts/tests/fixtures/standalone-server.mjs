/** One public scripted policy invocation for isolated standalone qualification. */
import { createHash } from 'node:crypto';
import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
  writeFileSync,
} from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';
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

const BASE = Object.freeze([
  'PATH',
  'LANG',
  'LC_ALL',
  'TMPDIR',
  'COREPACK_HOME',
  'COREPACK_ENABLE_NETWORK',
  'UV_PYTHON_DOWNLOADS',
  'UV_NO_PROGRESS',
  'PYTHONDONTWRITEBYTECODE',
  '__CF_USER_TEXT_ENCODING',
]);
const TASK = Object.freeze([
  'P3_STANDALONE_DIRECTORY',
  'P3_STANDALONE_SPECIALIST_TOKEN',
  'P3_STANDALONE_READY_FILE',
  'P3_STANDALONE_ENDPOINT_FILE',
  'P3_STANDALONE_STOP_FILE',
]);
const SCOPE = Object.freeze({ tenant_id: 'tenant_standalone', account_id: 'account_standalone' });
const MAX_PROOF = 32768;
const MAX_CONTROL = 32;
const MAX_LIFETIME_MS = 120000;
const sameFile = (a, b) => a.dev === b.dev && a.ino === b.ino;

function regular(stat, maximum) {
  return (
    stat.isFile() &&
    stat.uid === process.getuid?.() &&
    (stat.mode & 0o777) === 0o600 &&
    stat.nlink === 1 &&
    stat.size <= maximum
  );
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
function checkedFile(path, maximum) {
  const before = lstatSync(path);
  if (!regular(before, maximum)) throw new Error('fixture_file');
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const actual = fstatSync(fd);
    if (!regular(actual, maximum) || !sameFile(before, actual)) throw new Error('fixture_file');
    const bytes = Buffer.alloc(maximum + 1);
    const n = readSync(fd, bytes, 0, bytes.length, 0);
    const after = fstatSync(fd);
    if (
      n !== actual.size ||
      n > maximum ||
      !regular(after, maximum) ||
      after.size !== actual.size ||
      !sameFile(actual, after)
    )
      throw new Error('fixture_file');
    return bytes.subarray(0, n);
  } finally {
    closeSync(fd);
  }
}
function writeExclusive(path, value, maximum) {
  const bytes = Buffer.from(value);
  if (bytes.length > maximum) throw new Error('fixture_size');
  const fd = openSync(
    path,
    constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
    0o600,
  );
  try {
    writeFileSync(fd, bytes);
    if (!regular(fstatSync(fd), maximum)) throw new Error('fixture_file');
  } finally {
    closeSync(fd);
  }
}
function configuration() {
  const allowed = new Set([...BASE, ...TASK]);
  if (
    Object.keys(process.env).some((key) => !allowed.has(key)) ||
    TASK.some((key) => typeof process.env[key] !== 'string')
  )
    throw new Error('fixture_environment');
  const token = process.env.P3_STANDALONE_SPECIALIST_TOKEN;
  const directory = process.env.P3_STANDALONE_DIRECTORY;
  if (
    !/^[A-Za-z0-9_-]{43}(?![\s\S])/.test(token) ||
    !isAbsolute(directory) ||
    directory.length > 4096 ||
    resolve(directory) !== directory
  )
    throw new Error('fixture_configuration');
  const stat = lstatSync(directory);
  if (
    !stat.isDirectory() ||
    stat.isSymbolicLink() ||
    stat.uid !== process.getuid?.() ||
    (stat.mode & 0o777) !== 0o700
  )
    throw new Error('fixture_directory');
  const selected = [
    ['P3_STANDALONE_READY_FILE', 'specialist.ready'],
    ['P3_STANDALONE_ENDPOINT_FILE', 'specialist-endpoint.json'],
    ['P3_STANDALONE_STOP_FILE', 'specialist.stop'],
  ].map(([key, name]) => {
    const path = process.env[key];
    if (
      !isAbsolute(path) ||
      path.length > 4096 ||
      resolve(path) !== path ||
      dirname(path) !== directory ||
      path !== join(directory, name)
    )
      throw new Error('fixture_path');
    return path;
  });
  const proof = join(directory, 'standalone-service.json');
  const duplicate = join(directory, 'specialist-duplicate-invoke.json');
  if ([...selected, proof, duplicate].some((path) => !absent(path)))
    throw new Error('fixture_existing_file');
  if (process.versions.node !== '24.22.2') throw new Error('fixture_node_version');
  return {
    token,
    directory,
    ready: selected[0],
    endpoint: selected[1],
    stop: selected[2],
    proof,
    duplicate,
  };
}

export async function main() {
  let server;
  let failure;
  let cleanupComplete = true;
  let proof;
  try {
    const config = configuration();
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
        principal_id: 'standalone_fixture_service',
        token_sha256: tokenDigest(config.token),
        scopes: [
          {
            scope: SCOPE,
            invoke_capabilities: [CAPABILITY],
            result_capabilities: [CAPABILITY],
            cancel_capabilities: [CAPABILITY],
            evidence_sources: [reference.source_id],
          },
        ],
      },
    ]);
    let candidate;
    let original;
    let started = 0;
    let completed = 0;
    class ObservedEvidence extends EvidenceRegistry {
      resolve(authorization, request, localTrust) {
        const validated = super.resolve(authorization, request, localTrust);
        const snapshot = parseRequest(encodeRequest(request));
        const observed = Object.freeze({
          request_sha256: createHash('sha256').update(encodeRequest(snapshot)).digest('hex'),
          wire_attempt_id: snapshot.attempt.attempt_id,
          scope: Object.freeze({ ...snapshot.scope }),
        });
        if (
          original &&
          started === 1 &&
          completed === 0 &&
          (original.request_sha256 !== observed.request_sha256 ||
            original.wire_attempt_id !== observed.wire_attempt_id)
        )
          throw new ContractError('identity_conflict');
        candidate = observed;
        return validated;
      }
    }
    function observe(event) {
      try {
        if (event.event === 'attempt_started') {
          started++;
          if (started === 1) {
            if (!candidate) throw new Error('fixture_missing_identity');
            original = candidate;
          } else {
            if (absent(config.duplicate))
              writeExclusive(
                config.duplicate,
                JSON.stringify({
                  schema_version: 1,
                  status: 'failed',
                  code: 'duplicate_invocation',
                }),
                MAX_PROOF,
              );
            throw new Error('fixture_duplicate_invocation');
          }
        } else if (event.event === 'attempt_finished') {
          if (event.code !== 'ok') throw new Error('fixture_evaluation');
          completed++;
        }
      } catch (error) {
        failure ??= error;
      }
    }
    server = new SpecialistServer({
      trust,
      evidence: new ObservedEvidence([{ scope: SCOPE, reference, body }]),
      limits: { maxActive: 1, maxPerPrincipal: 1 },
      observer: observe,
      hooks: {
        beforeEvaluate: () => {
          if (failure || started !== 1) throw new ContractError('identity_conflict');
        },
      },
    });
    const endpoint = await server.listen();
    if (
      endpoint.host !== '127.0.0.1' ||
      !Number.isInteger(endpoint.port) ||
      endpoint.port < 1 ||
      endpoint.port > 65535
    )
      throw new Error('fixture_endpoint');
    writeExclusive(
      config.endpoint,
      JSON.stringify({
        schema_version: 1,
        host: endpoint.host,
        port: endpoint.port,
        node_version: process.versions.node,
      }),
      256,
    );
    const pid = `${process.pid}\n`;
    writeExclusive(config.ready, pid, MAX_CONTROL);
    const deadline = performance.now() + MAX_LIFETIME_MS;
    while (absent(config.stop)) {
      if (failure) throw failure;
      if (performance.now() >= deadline) throw new Error('fixture_stop_timeout');
      await delay(10);
    }
    if (checkedFile(config.stop, MAX_CONTROL).toString('utf8') !== pid)
      throw new Error('fixture_stop_identity');
    await server.close();
    const observerDeadline = performance.now() + 1000;
    while (server.metrics().observerPending !== 0) {
      if (performance.now() >= observerDeadline) throw new Error('fixture_observer_pending');
      await delay(1);
    }
    const metrics = server.metrics();
    if (
      failure ||
      started !== 1 ||
      completed !== 1 ||
      metrics.invoked !== started ||
      metrics.completed !== completed ||
      metrics.active !== 0 ||
      metrics.requests !== 0 ||
      metrics.sockets !== 0 ||
      metrics.observerFailures !== 0 ||
      metrics.observerDropped !== 0 ||
      !original ||
      !absent(config.duplicate)
    )
      throw new Error('fixture_truth');
    proof = {
      schema_version: 1,
      status: 'closed',
      node_version: process.versions.node,
      invoked: metrics.invoked,
      strict_completed: metrics.completed,
      active: metrics.active,
      requests: metrics.requests,
      sockets: metrics.sockets,
      request_sha256: original.request_sha256,
      wire_attempt_id: original.wire_attempt_id,
      scope: original.scope,
    };
    writeExclusive(config.proof, canonical(proof), MAX_PROOF);
  } catch (error) {
    failure ??= error;
  } finally {
    if (server) {
      try {
        await server.close();
      } catch (error) {
        cleanupComplete = false;
        failure ??= error;
      }
    }
  }
  if (failure) {
    console.info(
      JSON.stringify({
        schema_version: 1,
        status: 'failed',
        code: 'standalone_fixture_failed',
        cleanup_complete: cleanupComplete,
      }),
    );
    process.exitCode = 1;
    return;
  }
  console.info(Buffer.from(canonical(proof)).toString('utf8'));
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url)
  await main();
