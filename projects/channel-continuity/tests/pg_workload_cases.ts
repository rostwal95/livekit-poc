/** Local fixed workload application; public P2 APIs, owner reconciliation kept separate. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {
  existsSync,
  readFileSync,
  writeFileSync,
  renameSync,
  openSync,
  closeSync,
  writeSync,
  readSync,
  fsyncSync,
  fstatSync,
  linkSync,
  unlinkSync,
  constants,
} from 'node:fs';
import { request, type ClientRequest } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import pg from 'pg';
import { monitorEventLoopDelay } from 'node:perf_hooks';
import {
  ChannelInbox,
  SeededAccounts,
  ChannelError,
  type DatabaseSettings,
  type StoredMessage,
  type DurableReceipt,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  createFakeSmsIntegration,
  signFakeSms,
  type FakeSmsMessage,
} from '@livekit-ecosystem/channel-continuity/security';
import { ChannelGateway, GatewayError } from '@livekit-ecosystem/channel-continuity/gateway';
import {
  ChannelDispatcher,
  type DispatchPorts,
  type OperationReceipt,
  type PreparedDispatch,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  installChannelSchema,
  upgradeChannelSchemaV2,
  upgradeChannelSchemaV3,
  upgradeChannelSchemaV4,
  upgradeChannelSchemaV5,
  upgradeChannelSchemaV6,
  upgradeChannelSchemaV7,
} from '@livekit-ecosystem/channel-continuity/migrations';
import {
  CASE_NAMES,
  SCHEMA_TABLES,
  WORKLOAD_SEED,
  PERFORMANCE_BUDGETS,
  POPULATIONS,
  OWNER_LIMITS,
  experiment,
  schema,
  secret,
  uuid,
  provider,
  tenant,
  caseData,
  capacityTenant,
  message as modelMessage,
  windows,
  latencies,
  fingerprint,
  type Profile,
  type Tenant,
  type CaseData,
} from './workload-model.js';
function message(...args: Parameters<typeof modelMessage>) {
  return modelMessage(...args).value;
}
const eventLoop = monitorEventLoopDelay({ resolution: 20 });
eventLoop.enable();
const MODES = [
  'install',
  'seed',
  'serve',
  'reopen',
  'dormant-wake',
  'verify',
  'drop',
  'restored-replay',
  'restored-verify',
  'cleanup',
] as const;
const mode = process.argv[2];
assert.ok(process.argv.length === 3 && MODES.includes(mode as (typeof MODES)[number]));
const owner = ['install', 'verify', 'drop', 'restored-verify', 'cleanup'].includes(mode!);
function env(name: string) {
  const value = process.env[name];
  assert.ok(value && value.length <= 4096);
  return value;
}
const DIR = env('P2_WORKLOAD_DIRECTORY'),
  runId = env('P2_WORKLOAD_RUN_ID');
function load<T>(name: string): T {
  return JSON.parse(readFileSync(DIR + '/' + name, 'utf8')) as T;
}
function save(name: string, value: unknown) {
  const raw = JSON.stringify(value) + '\n';
  assert.ok(Buffer.byteLength(raw) <= 2 * 1024 * 1024);
  const file = DIR + '/' + name,
    pending = file + '.pending';
  assert.ok(!existsSync(pending));
  writeFileSync(pending, raw, { flag: 'wx', mode: 0o600 });
  renameSync(pending, file);
}
const f = experiment(load('fixture.json'));
assert.equal(f.runId, runId);
assert.equal(
  process.env[owner ? 'P2_WORKLOAD_RUNTIME_PASSWORD' : 'P2_WORKLOAD_OWNER_PASSWORD'],
  undefined,
);
const stages = new Set<string>();
let phase = 'configuration';
function db(profile: Profile): DatabaseSettings {
  return {
    host: '127.0.0.1',
    port: Number(env('P2_WORKLOAD_PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'P2_WORKLOAD_OWNER_PASSWORD' : 'P2_WORKLOAD_RUNTIME_PASSWORD'),
    schema: schema(f, profile),
  };
}
function integration(t: Tenant) {
  return createFakeSmsIntegration(provider(t), secret(f, 'hmac:' + t));
}
function inbox(
  profile: Profile,
  selected: Tenant,
  cases: readonly CaseData[],
  observer?: ConstructorParameters<typeof ChannelInbox>[4],
) {
  return new ChannelInbox(
    db(profile),
    integration(selected),
    new SeededAccounts(cases.map((c) => c.seed)),
    {},
    observer ?? (() => undefined),
  );
}
function raw(m: FakeSmsMessage) {
  return Buffer.from(JSON.stringify(m));
}
function signed(t: Tenant, m: FakeSmsMessage) {
  const s = signFakeSms(m, secret(f, 'hmac:' + t), Math.floor(Date.now() / 1000), provider(t));
  return { bytes: s.raw, headers: s.headers };
}
async function accept(box: ChannelInbox, t: Tenant, m: FakeSmsMessage) {
  const s = signed(t, m);
  return box.acceptSms(s.bytes, s.headers);
}
async function associate(box: ChannelInbox, c: CaseData) {
  const challenge = await box.createChallenge(c.seed.token, c.senderId),
    m = {
      ...message(f, 'rejected', 0),
      eventId: uuid(f, 'link:' + c.seed.accountId),
      messageId: uuid(f, 'link:' + c.seed.accountId),
      senderId: c.senderId,
      body: 'LINK ' + challenge.challengeId + ' ' + challenge.secret,
    };
  const s = signed(c.tenant, m);
  assert.equal((await box.completeAssociation(s.bytes, s.headers)).associationVersion, '1');
}
async function until(check: () => boolean | Promise<boolean>, ms = 10000) {
  const end = performance.now() + ms;
  while (!(await check())) {
    assert.ok(performance.now() < end, 'fixed_wait_exceeded');
    await delay(10);
  }
}
function publishMarker(stem: string) {
  assert.ok(
    [
      'workload_dormant_ready',
      'workload_burst_ready',
      'workload_burst_waiting',
      'workload_slow_held',
    ].includes(stem),
  );
  const target = DIR + '/' + stem + '.reached',
    pending = target + '.' + process.pid + '.pending';
  let fd: number | undefined,
    created = false;
  try {
    fd = openSync(
      pending,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
      0o600,
    );
    created = true;
    const bytes = Buffer.from(process.pid + '\n');
    assert.equal(writeSync(fd, bytes), bytes.length);
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    linkSync(pending, target);
  } finally {
    if (fd !== undefined) closeSync(fd);
    if (created) unlinkSync(pending);
  }
}
function released(stem: string): boolean {
  const path = DIR + '/' + stem + '.released';
  let fd: number;
  try {
    fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  } catch (error) {
    if (
      error instanceof Error &&
      Object.getOwnPropertyDescriptor(error, 'code')?.value === 'ENOENT'
    )
      return false;
    throw error;
  }
  try {
    const expected = Buffer.from(process.pid + '\n'),
      info = fstatSync(fd),
      bytes = Buffer.alloc(33);
    assert.ok(
      info.isFile() &&
        info.nlink === 1 &&
        (info.mode & 0o777) === 0o600 &&
        info.uid === process.getuid!() &&
        info.size === expected.length,
    );
    const count = readSync(fd, bytes, 0, 33, null);
    assert.equal(count, expected.length);
    assert.equal(bytes.subarray(0, count).equals(expected), true);
    return true;
  } finally {
    closeSync(fd);
  }
}
async function barrier(stem: string) {
  publishMarker(stem);
  await until(() => released(stem), 15000);
}
function reached(stem: string) {
  publishMarker(stem);
}
function sample(population: number) {
  const memory = process.memoryUsage(),
    cpu = process.cpuUsage();
  return {
    population,
    eventLoopMaxMs: eventLoop.max / 1000000,
    monotonicMs: performance.now(),
    rssBytes: memory.rss,
    heapUsedBytes: memory.heapUsed,
    externalBytes: memory.external,
    cpuUserMicroseconds: cpu.user,
    cpuSystemMicroseconds: cpu.system,
  };
}
function validateSamples(samples: readonly ReturnType<typeof sample>[]) {
  for (const row of samples) {
    assert.ok(row.rssBytes <= PERFORMANCE_BUDGETS.nodeRssBytes);
    assert.ok(row.eventLoopMaxMs <= PERFORMANCE_BUDGETS.eventLoopMaxMs);
  }
}

type Original = {
  kind: 'capacity' | 'dormant' | 'wake';
  index: number;
  receipt: DurableReceipt;
  operationKey: string;
  eventDigest: string;
  bodyDigest: string;
};
function original(kind: Original['kind'], index: number, m: StoredMessage): Original {
  return {
    kind,
    index,
    receipt: m.receipt,
    operationKey: m.operationKey,
    eventDigest: fingerprint(m.event),
    bodyDigest: createHash('sha256')
      .update((m.event as { body: string }).body)
      .digest('hex'),
  };
}
function checkOriginal(old: Original, m: StoredMessage) {
  assert.deepEqual(m.receipt, old.receipt);
  assert.equal(m.operationKey, old.operationKey);
  assert.equal(fingerprint(m.event), old.eventDigest);
  assert.equal(
    createHash('sha256')
      .update((m.event as { body: string }).body)
      .digest('hex'),
    old.bodyDigest,
  );
}
async function install() {
  for (const profile of ['capacity', 'dormant'] as const) {
    phase = 'install_' + profile;
    const settings = db(profile);
    await installChannelSchema(settings, OWNER_LIMITS[profile]);
    await upgradeChannelSchemaV2(settings);
    await upgradeChannelSchemaV3(settings);
    await upgradeChannelSchemaV4(settings);
    await upgradeChannelSchemaV5(settings);
    await upgradeChannelSchemaV6(settings);
    await upgradeChannelSchemaV7(settings);
  }
  stages.add(CASE_NAMES[0]);
  return { schemas: 2, storageVersion: 7 };
}
async function seed() {
  const processSamples: ReturnType<typeof sample>[] = [],
    processSampler = setInterval(() => {
      assert.ok(processSamples.length < 4096);
      processSamples.push(sample(-1));
    }, 100);
  try {
    const originals: Original[] = [],
      times: number[] = [],
      samples = [sample(0)];
    for (const t of [0, 1] as const) {
      const c = caseData(f, 'capacity', t),
        box = inbox('capacity', t, [c]);
      try {
        await associate(box, c);
      } finally {
        await box.close();
      }
    }
    let count = 0;
    for (const t of [0, 1] as const)
      for (const group of windows(f, t)) {
        const box = inbox('dormant', t, group);
        try {
          for (const c of group) {
            const start = performance.now();
            await associate(box, c);
            const result = await accept(box, t, message(f, 'dormant', c.index));
            assert.equal(result.replayed, false);
            const stored = await box.inspect(c.seed.token, result.receipt.receiptId);
            originals.push(original('dormant', c.index, stored));
            times.push(performance.now() - start);
            count++;
            if (POPULATIONS.includes(count as (typeof POPULATIONS)[number]))
              samples.push(sample(count));
          }
        } finally {
          await box.close();
        }
      }
    assert.equal(count, 1000);
    for (const t of [0, 1] as const)
      for (const group of windows(f, t)) {
        const box = inbox('dormant', t, group);
        try {
          for (const c of group)
            checkOriginal(
              originals[c.index]!,
              await box.inspect(c.seed.token, originals[c.index]!.receipt.receiptId),
            );
        } finally {
          await box.close();
        }
      }
    save('workload-dormant-originals.json', originals);
    validateSamples([...samples, ...processSamples]);
    save('workload-dormant-resources.json', {
      workloadSeed: WORKLOAD_SEED,
      performanceBudgets: PERFORMANCE_BUDGETS,
      processSamples,
      schemaVersion: 1,
      scope: 'one_node_process_sequential_reader_windows',
      samples,
      cohort: 'public_associate_accept_inspect_1000',
      latencyMs: latencies(times),
      readersConcurrent: 1,
      maximumCredentialWindow: 64,
      roomsAllocated: 0,
      agentsAllocated: 0,
    });
    save('workload-dormant-ready.json', {
      schemaVersion: 1,
      population: 1000,
      processId: process.pid,
      schemas: 2,
    });
    await barrier('workload_dormant_ready');
    stages.add(CASE_NAMES[18]);
    stages.add(CASE_NAMES[19]);
    return { dormantInputs: 1000, capacityInputs: 0, credentialWindows: 16 };
  } finally {
    clearInterval(processSampler);
  }
}

type LedgerRow = { prepared: PreparedDispatch; receipt: OperationReceipt };
function ledger(): LedgerRow[] {
  return existsSync(DIR + '/workload-operations.json') ? load('workload-operations.json') : [];
}
function ports(profile: Profile, options: { slow?: boolean; lost?: boolean } = {}) {
  const calls: { eventId: string; signalAborted: boolean; at: number }[] = [],
    holds = new Map<number, { release: () => void; signal: AbortSignal }>();
  let active = 0,
    maximum = 0;
  const completionTimes = new Map<string, number>();
  const p: DispatchPorts = {
    cases: {
      async inspect(ref) {
        assert.ok(
          [0, 1].some((t) => {
            const c = caseData(f, profile, profile === 'capacity' ? t : t * 500);
            return (
              ref.scope.tenantId === c.seed.tenantId &&
              ref.scope.accountId === c.seed.accountId &&
              ref.caseId === c.seed.caseId
            );
          }),
        );
        return { ...ref, revision: '1', source: 'synthetic_read_only' };
      },
    },
    agent: {
      async prepare(input, signal) {
        active++;
        maximum = Math.max(maximum, active);
        try {
          const e = input.message.event.eventId;
          calls.push({ eventId: e, signalAborted: signal.aborted, at: performance.now() });
          const n = [20, 21].find((i) => message(f, 'capacity', i).eventId === e);
          if (options.slow && n !== undefined && !holds.has(n)) {
            let release!: () => void;
            const wait = new Promise<void>((r) => {
              release = r;
            });
            holds.set(n, { release, signal });
            await wait;
          }
          return {
            kind: 'investigation',
            source: 'scripted',
            caseRevision: input.currentCase.revision,
          };
        } finally {
          active--;
        }
      },
    },
    operations: {
      capabilities: 'stable_idempotency_and_lookup',
      async lookup(input) {
        const rows = ledger(),
          found = rows.find((r) => r.receipt.operationKey === input.operationKey);
        if (found) {
          assert.deepEqual(found.receipt.scope, input.scope);
          assert.equal(found.receipt.payloadDigest, input.payloadDigest);
          if (
            options.lost &&
            found.prepared.submission.message.eventId === message(f, 'capacity', 62).eventId
          )
            throw new ChannelError('DispatchUnavailable');
          return { status: 'accepted', receipt: found.receipt };
        }
        return { status: 'absent' };
      },
      async accept(prepared) {
        const rows = ledger(),
          prior = rows.find((r) => r.receipt.operationKey === prepared.submission.operationKey);
        if (prior) {
          assert.deepEqual(prior.prepared, prepared);
          return prior.receipt;
        }
        const receipt = {
          operationKey: prepared.submission.operationKey,
          scope: prepared.submission.scope,
          payloadDigest: prepared.payloadDigest,
          receiptId: uuid(f, 'operation:' + prepared.submission.operationKey),
        };
        rows.push({ prepared, receipt });
        completionTimes.set(prepared.submission.message.eventId, performance.now());
        save('workload-operations.json', rows);
        if (
          options.lost &&
          prepared.submission.message.eventId === message(f, 'capacity', 62).eventId
        )
          throw new ChannelError('DispatchUnavailable');
        return receipt;
      },
    },
  };
  return {
    ports: p,
    completionTimes,
    calls,
    holds,
    get active() {
      return active;
    },
    get maximum() {
      return maximum;
    },
  };
}
type HttpResult = { status: number; body: Record<string, unknown>; elapsedMs: number };
let httpActive = 0,
  httpMaximum = 0;
function http(
  port: number,
  m: FakeSmsMessage,
  selected: Tenant,
  overrides: { body?: Buffer; badSignature?: boolean } = {},
) {
  const bytes = overrides.body ?? raw(m),
    sig = signFakeSms(
      m,
      secret(f, 'hmac:' + selected),
      Math.floor(Date.now() / 1000),
      provider(selected),
    ).headers;
  let req!: ClientRequest;
  const started = performance.now();
  httpActive++;
  httpMaximum = Math.max(httpMaximum, httpActive);
  let settled!: Promise<HttpResult>;
  settled = new Promise<HttpResult>((resolve, reject) => {
    let result: HttpResult | undefined, error: unknown;
    req = request(
      {
        host: '127.0.0.1',
        port,
        path: '/webhooks/fake-sms',
        method: 'POST',
        agent: false,
        headers: {
          'content-type': 'application/json',
          'content-length': String(bytes.length),
          'x-p2-timestamp': sig.timestamp,
          'x-p2-signature': sig.signature,
          ...(overrides.badSignature ? { 'x-p2-signature': '0'.repeat(64) } : {}),
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        let size = 0;
        res.on('data', (chunk: Buffer) => {
          size += chunk.length;
          if (size > 16384) res.destroy();
          else chunks.push(chunk);
        });
        res.on('end', () => {
          try {
            result = {
              status: res.statusCode!,
              body: JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>,
              elapsedMs: performance.now() - started,
            };
          } catch (e) {
            error = e;
          }
        });
      },
    );
    const timer = setTimeout(() => req.destroy(new Error('http_deadline')), 5000);
    req.on('error', (e) => {
      error = e;
    });
    req.once('close', () => {
      clearTimeout(timer);
      httpActive--;
      if (result) resolve(result);
      else reject(error ?? new Error('http_closed'));
    });
    req.end(bytes);
  });
  return { settled, abort: () => req.destroy() };
}
function known(result: HttpResult) {
  assert.equal(result.status, 200);
  assert.equal(result.body.kind, 'channel.receipt');
  return result.body.receipt as DurableReceipt;
}
async function closeGateways(gws: readonly ChannelGateway[]) {
  const results = await Promise.allSettled(gws.map((g) => g.close()));
  if (results.some((r) => r.status === 'rejected')) throw new Error('gateway_cleanup_incomplete');
  for (const g of gws) {
    const m = g.metrics();
    for (const k of ['active', 'intakes', 'sockets', 'handlers', 'driver', 'observerPending'])
      assert.equal(m[k], 0);
  }
}
async function serve() {
  const adapter = ports('capacity', { slow: true, lost: true }),
    pools: pg.Pool[] = [],
    poolMax = new Map<pg.Pool, { total: number; waiting: number; occupied: number }>(),
    originalConnect = pg.Pool.prototype.connect;
  let capture = false,
    published = false;
  const pids = new Set<number>();
  const wrapped = async function (this: pg.Pool) {
    if (!pools.includes(this)) pools.push(this);
    const client = await (originalConnect as (this: pg.Pool) => Promise<pg.PoolClient>).call(this);
    try {
      if (capture && this === pools[2]) {
        const row = await client.query('SELECT pg_backend_pid() AS pid');
        assert.ok(Number.isSafeInteger(row.rows[0].pid));
        pids.add(row.rows[0].pid as number);
        assert.ok(pids.size <= 2);
        if (pids.size === 2 && !published) {
          save('workload-burst-backends.json', {
            schemaVersion: 1,
            phase: 'burst',
            processId: process.pid,
            schema: schema(f, 'capacity'),
            backendIds: [...pids].sort((a, b) => a - b),
          });
          published = true;
        }
      }
      return client;
    } catch (e) {
      client.release(true);
      throw e;
    }
  };
  pg.Pool.prototype.connect = wrapped as typeof originalConnect;
  const resources: ReturnType<typeof sample>[] = [],
    snapshots: unknown[] = [];
  const sampler = setInterval(() => {
    assert.ok(resources.length < 2000);
    resources.push(sample(-1));
    for (const pool of pools) {
      const prior = poolMax.get(pool) ?? { total: 0, waiting: 0, occupied: 0 };
      prior.total = Math.max(prior.total, pool.totalCount);
      prior.waiting = Math.max(prior.waiting, pool.waitingCount);
      prior.occupied = Math.max(
        prior.occupied,
        pool.totalCount - pool.idleCount + pool.waitingCount,
      );
      poolMax.set(pool, prior);
    }
  }, 50);
  const preacceptance: {
    eventId: string;
    status: number;
    code: unknown;
    receiptPresent: boolean;
  }[] = [];
  let holdAck = false,
    releaseAck!: () => void;
  const heldAck = new Promise<void>((r) => {
    releaseAck = r;
  });
  const gws = [0, 1].map((v) => {
    const t = tenant(v);
    return new ChannelGateway({
      database: db('capacity'),
      integration: integration(t),
      accounts: [caseData(f, 'capacity', t).seed],
      ports: adapter.ports,
      options: {
        observer: () => undefined,
        pollMs: 20,
        batchSize: 4,
        cleanupMs: 200,
        startupMs: 5000,
        harnessAfterAcknowledgement: () => (holdAck ? heldAck : undefined),
      },
    });
  });
  const offers = new Map<number, number>();
  const accepted: { index: number; receipt: DurableReceipt }[] = [],
    cohorts: Record<string, number[]> = { steady: [], burst: [], slow: [], capfill: [] };
  let endpoints: Awaited<ReturnType<ChannelGateway['listen']>>[] = [];
  async function send(index: number, cohort: string) {
    offers.set(index, performance.now());
    const result = await http(
      endpoints[capacityTenant(index)]!.port,
      message(f, 'capacity', index),
      capacityTenant(index),
    ).settled;
    accepted.push({ index, receipt: known(result) });
    cohorts[cohort]!.push(result.elapsedMs);
    return result;
  }
  async function progress(indices: readonly number[]) {
    await until(() => {
      const ids = new Set(ledger().map((r) => r.prepared.submission.message.eventId));
      return indices.every((i) => ids.has(message(f, 'capacity', i).eventId));
    }, 15000);
  }
  let primary: unknown;
  try {
    endpoints = [await gws[0]!.listen(), await gws[1]!.listen()];
    assert.equal(pools.length, 2);
    for (let i = 0; i < 16; i++) await send(i, 'steady');
    await progress(Array.from({ length: 16 }, (_, i) => i));
    assert.equal(pools.length, 4);
    save('workload-burst-ready.json', {
      schemaVersion: 1,
      processId: process.pid,
      schema: schema(f, 'capacity'),
    });
    await barrier('workload_burst_ready');
    capture = true;
    for (const i of [16, 17, 18, 19]) offers.set(i, performance.now());
    const admitted = [16, 17, 18, 19].map((i) => ({
      i,
      request: http(endpoints[0]!.port, message(f, 'capacity', i), 0),
    }));
    // Observe failures immediately, retaining actual sockets until request.close.
    const settled = admitted.map((a) =>
      a.request.settled.then(
        (value) => ({ value }),
        () => ({ value: null }),
      ),
    );
    await until(() => published && gws[0]!.metrics().active === 4, 900);
    assert.equal(pools[2]!.waitingCount, 2);
    const rejected = await Promise.all(
      [0, 1, 2, 3].map((i) => http(endpoints[0]!.port, message(f, 'rejected', i), 0).settled),
    );
    assert.ok(rejected.every((r) => r.status === 429));
    rejected.forEach((r, i) =>
      preacceptance.push({
        eventId: message(f, 'rejected', i).eventId,
        status: r.status,
        code: r.body.code,
        receiptPresent: Object.hasOwn(r.body, 'receipt'),
      }),
    );
    assert.ok(preacceptance.every((r) => r.code === 'capacity' && !r.receiptPresent));
    admitted[0]!.request.abort();
    assert.equal((await settled[0]!).value, null);
    snapshots.push({
      phase: 'burst_held',
      gateway: gws.map((g) => g.metrics()),
      pools: pools.map((p) => ({
        total: p.totalCount,
        idle: p.idleCount,
        waiting: p.waitingCount,
      })),
    });
    reached('workload_burst_waiting');
    const outcomes = await Promise.all(settled);
    capture = false;
    for (let j = 1; j < 4; j++) {
      const result = outcomes[j]!.value!;
      accepted.push({ index: admitted[j]!.i, receipt: known(result) });
      cohorts.burst!.push(result.elapsedMs);
    }
    const replay = await http(endpoints[0]!.port, message(f, 'capacity', 16), 0).settled;
    assert.equal(replay.body.replayed, true);
    accepted.push({ index: 16, receipt: known(replay) });
    await progress([16, 17, 18, 19]);
    const changed = await http(
      endpoints[0]!.port,
      { ...message(f, 'capacity', 0), body: 'changed' },
      0,
    ).settled;
    assert.equal(changed.status, 409);
    const malformed = await http(endpoints[0]!.port, message(f, 'capacity', 0), 0, {
        body: Buffer.from('{'),
      }).settled,
      oversized = await http(endpoints[0]!.port, message(f, 'capacity', 0), 0, {
        body: Buffer.alloc(32769, 65),
      }).settled,
      unauthorized = await http(endpoints[0]!.port, message(f, 'capacity', 0), 0, {
        badSignature: true,
      }).settled;
    assert.ok([400, 401].includes(malformed.status));
    assert.equal(oversized.status, 413);
    assert.equal(unauthorized.status, 401);
    await send(20, 'slow');
    await send(21, 'slow');
    await until(() => adapter.holds.size === 2);
    await send(22, 'slow');
    await send(23, 'slow');
    await until(() => [...adapter.holds.values()].every((h) => h.signal.aborted), 3000);
    assert.equal(adapter.active, 2);
    assert.equal(adapter.maximum, 2);
    const callsHeld = adapter.calls.length;
    await delay(50);
    assert.equal(adapter.calls.length, callsHeld);
    await barrier('workload_slow_held');
    adapter.holds.get(21)!.release();
    await progress([22]);
    assert.equal(adapter.active, 1);
    adapter.holds.get(20)!.release();
    await progress([20, 21, 22, 23]);
    for (let i = 24; i < 63; i++) await send(i, 'capfill');
    await progress(Array.from({ length: 62 }, (_, i) => i));
    holdAck = true;
    await send(63, 'capfill');
    await until(() => gws[1]!.metrics().intakes === 1);
    let incomplete = false;
    try {
      await gws[1]!.close();
    } catch (e) {
      assert.ok(e instanceof GatewayError && e.code === 'cleanup_incomplete');
      incomplete = true;
    }
    assert.equal(incomplete, true);
    assert.equal(gws[1]!.metrics().intakes, 1);
    releaseAck();
    await closeGateways(gws);
    assert.equal(adapter.active, 0);
    assert.equal(ledger().length, 63);
  } catch (e) {
    primary = e;
  } finally {
    capture = false;
    releaseAck();
    for (const h of adapter.holds.values()) h.release();
    try {
      await closeGateways(gws);
    } catch (e) {
      primary ??= e;
    }
    clearInterval(sampler);
    pg.Pool.prototype.connect = originalConnect;
  }
  if (primary) throw primary;
  const originals: Original[] = [];
  for (const t of [0, 1] as const) {
    const c = caseData(f, 'capacity', t),
      box = inbox('capacity', t, [c]);
    try {
      for (const row of accepted.filter((r) => capacityTenant(r.index) === t)) {
        const stored = await box.inspect(c.seed.token, row.receipt.receiptId);
        assert.deepEqual(stored.receipt, row.receipt);
        originals.push(original('capacity', row.index, stored));
      }
      const old = originals.find((r) => r.index === (t === 0 ? 0 : 1))!;
      const equal = await accept(box, t, message(f, 'capacity', old.index));
      assert.equal(equal.replayed, true);
      assert.deepEqual(equal.receipt, old.receipt);
      await assert.rejects(
        accept(box, t, { ...message(f, 'capacity', old.index), body: 'changed' }),
        (e) => e instanceof ChannelError && e.code === 'IdentityConflict',
      );
      await assert.rejects(
        accept(box, t, { ...message(f, 'rejected', 8 + t), senderId: c.senderId }),
        (e) => e instanceof ChannelError && e.code === 'Overloaded',
      );
      const display: StoredMessage[] = [];
      let cursor: string | undefined;
      do {
        const page = await box.history(c.seed.token, {
          limit: 4,
          ...(cursor ? { after: cursor } : {}),
        });
        display.push(...page.messages);
        while (display.length > 4) display.shift();
        cursor = page.nextCursor ?? undefined;
      } while (cursor);
      assert.equal(display.length, 4);
      assert.equal(
        display.some((r) => r.receipt.receiptId === old.receipt.receiptId),
        false,
      );
      checkOriginal(old, await box.inspect(c.seed.token, old.receipt.receiptId));
    } finally {
      await box.close();
    }
  }
  originals.sort((a, b) => a.index - b.index);
  assert.equal(originals.length, 64);
  assert.notEqual(originals[0]!.receipt.receiptId, originals[2]!.receipt.receiptId);
  assert.equal(originals[0]!.bodyDigest, originals[2]!.bodyDigest);
  const releases: (() => void)[] = [],
    c = caseData(f, 'capacity', 0),
    observerInbox = inbox(
      'capacity',
      0,
      [c],
      () =>
        new Promise<void>((r) => {
          releases.push(r);
        }),
    );
  let telemetryBefore: unknown, telemetryAfterClose: unknown;
  try {
    for (let i = 0; i < 20; i++) await observerInbox.history(c.seed.token, { limit: 1 });
    telemetryBefore = observerInbox.telemetryMetrics();
    assert.deepEqual(telemetryBefore, {
      observerPending: 8,
      observerDropped: 12,
      observerFailures: 0,
    });
    await observerInbox.close();
    telemetryAfterClose = observerInbox.telemetryMetrics();
    assert.equal(observerInbox.telemetryMetrics().observerPending, 8);
  } finally {
    for (const release of releases) release();
    await until(() => observerInbox.telemetryMetrics().observerPending === 0);
    await observerInbox.close();
  }
  save('workload-capacity-originals.json', originals);
  const completionMs = [...adapter.completionTimes].map(([eventId, at]) => {
    const index = Array.from({ length: 64 }, (_, i) => i).find(
      (i) => message(f, 'capacity', i).eventId === eventId,
    );
    assert.notEqual(index, undefined);
    const offered = offers.get(index!);
    assert.notEqual(offered, undefined);
    return at - offered!;
  });
  assert.equal(completionMs.length, 63);
  assert.ok(completionMs.every((ms) => ms >= 0 && ms <= PERFORMANCE_BUDGETS.usefulCompletionMaxMs));
  assert.ok(
    Object.values(cohorts)
      .flat()
      .every((ms) => ms <= PERFORMANCE_BUDGETS.acceptedAdmissionMaxMs),
  );
  validateSamples(resources);
  save('workload-capacity-resources.json', {
    workloadSeed: WORKLOAD_SEED,
    performanceBudgets: PERFORMANCE_BUDGETS,
    usefulCompletionMs: latencies(completionMs),
    schemaVersion: 1,
    scope: 'one_node_process_two_gateways',
    configured: {
      gateways: 2,
      pools: 4,
      connections: 8,
      retainedSqlOperations: 16,
      dispatcherTasksPerInstance: 2,
      persistedClaimsPerSchema: 2,
    },
    observed: {
      httpMaximum,
      preacceptance,
      prepareMaximum: adapter.maximum,
      pools: [...poolMax.values()],
      snapshots,
    },
    samples: resources,
    cohorts: Object.fromEntries(Object.entries(cohorts).map(([k, v]) => [k, latencies(v)])),
    observer: {
      beforeSqlClose: telemetryBefore,
      afterSqlClose: telemetryAfterClose,
      afterActualCallbackSettlement: observerInbox.telemetryMetrics(),
    },
    terminalGateways: gws.map((g) => g.metrics()),
    cleanupComplete: true,
  });
  for (let i = 1; i < 16; i++) stages.add(CASE_NAMES[i]!);
  return {
    capacityInputs: 64,
    operationAcceptances: 63,
    abandonedCallers: 1,
    preacceptanceRejected: 4,
  };
}
async function reopen(restored = false) {
  const originals = load<Original[]>('workload-capacity-originals.json'),
    adapter = ports('capacity');
  const c = caseData(f, 'capacity', 0),
    dispatcher = new ChannelDispatcher(
      db('capacity'),
      integration(0),
      new SeededAccounts([c.seed]),
      adapter.ports,
    );
  try {
    const row = originals[62]!;
    const before = await dispatcher.inspect(c.seed.token, row.receipt.receiptId);
    if (!restored) {
      assert.equal(before.possibleExternal, true);
      assert.notEqual(before.state, 'dispatched');
      const result = await dispatcher.reconcile(c.seed.token, row.receipt.receiptId);
      assert.equal(result.status, 'dispatched');
      assert.equal('reconciled' in result && result.reconciled, true);
    } else assert.equal(before.state, 'dispatched');
  } finally {
    await dispatcher.close();
  }
  if (!restored) {
    const gateways = [0, 1].map((v) => {
      const t = tenant(v);
      return new ChannelGateway({
        database: db('capacity'),
        integration: integration(t),
        accounts: [caseData(f, 'capacity', t).seed],
        ports: adapter.ports,
        options: { observer: () => undefined, pollMs: 20 },
      });
    });
    try {
      await Promise.all(gateways.map((g) => g.listen()));
      await until(() => ledger().length === 64, 10000);
    } finally {
      await closeGateways(gateways);
    }
  }
  for (const t of [0, 1] as const) {
    const c = caseData(f, 'capacity', t),
      box = inbox('capacity', t, [c]);
    try {
      for (const row of originals.filter((r) => capacityTenant(r.index) === t)) {
        const stored = await box.inspect(c.seed.token, row.receipt.receiptId);
        checkOriginal(row, stored);
        assert.equal(stored.processingState, 'dispatched');
      }
      const equal = await accept(box, t, message(f, 'capacity', t));
      assert.equal(equal.replayed, true);
      assert.deepEqual(equal.receipt, originals[t]!.receipt);
    } finally {
      await box.close();
    }
  }
  assert.equal(adapter.calls.length, restored ? 0 : 1);
  assert.equal(
    ledger().filter(
      (r) => r.prepared.submission.message.eventId === message(f, 'capacity', 62).eventId,
    ).length,
    1,
  );
  if (!restored) {
    stages.add(CASE_NAMES[16]);
    stages.add(CASE_NAMES[17]);
  }
  return { capacityInputs: 64, operationAcceptances: 64, originalPreparedReconciled: true };
}
async function wake() {
  const adapter = ports('dormant'),
    old = load<Original[]>('workload-dormant-originals.json'),
    fresh: Original[] = [];
  const gateways = [0, 1].map((v) => {
    const t = tenant(v),
      c = caseData(f, 'dormant', t * 500);
    return new ChannelGateway({
      database: db('dormant'),
      integration: integration(t),
      accounts: [c.seed],
      ports: adapter.ports,
      options: { observer: () => undefined, pollMs: 20 },
    });
  });
  try {
    const ends = await Promise.all(gateways.map((g) => g.listen()));
    for (const t of [0, 1] as const) {
      const result = await http(ends[t]!.port, message(f, 'wake', t), t).settled;
      known(result);
    }
    await until(() => ledger().length === 68, 10000);
  } finally {
    await closeGateways(gateways);
  }
  for (const t of [0, 1] as const) {
    const c = caseData(f, 'dormant', t * 500),
      box = inbox('dormant', t, [c]);
    try {
      checkOriginal(
        old[c.index]!,
        await box.inspect(c.seed.token, old[c.index]!.receipt.receiptId),
      );
      const result = await accept(box, t, message(f, 'wake', t));
      assert.equal(result.replayed, true);
      fresh.push(original('wake', t, await box.inspect(c.seed.token, result.receipt.receiptId)));
    } finally {
      await box.close();
    }
  }
  save('workload-wake-originals.json', fresh);
  stages.add(CASE_NAMES[21]);
  return { dormantInputs: 1002, wokenOriginalCases: 2, operationAcceptances: 4 };
}
async function restoredReplay() {
  const before = fingerprint(ledger());
  await reopen(true);
  const old = load<Original[]>('workload-dormant-originals.json'),
    fresh = load<Original[]>('workload-wake-originals.json');
  for (const t of [0, 1] as const)
    for (const group of windows(f, t)) {
      const box = inbox('dormant', t, group);
      try {
        for (const c of group) {
          const stored = await box.inspect(c.seed.token, old[c.index]!.receipt.receiptId);
          checkOriginal(old[c.index]!, stored);
          assert.equal(stored.processingState, c.index % 500 === 0 ? 'dispatched' : 'pending');
        }
        if (group[0]!.index % 500 === 0) {
          const replay = await accept(box, t, message(f, 'dormant', group[0]!.index));
          assert.equal(replay.replayed, true);
          assert.deepEqual(replay.receipt, old[group[0]!.index]!.receipt);
          const replayWake = await accept(box, t, message(f, 'wake', t));
          assert.deepEqual(replayWake.receipt, fresh[t]!.receipt);
        }
      } finally {
        await box.close();
      }
    }
  assert.equal(fingerprint(ledger()), before);
  stages.add(CASE_NAMES[22]);
  return { originalReceipts: 1066, operationAcceptances: 68, newOperationAcceptances: 0 };
}
async function ownerClient<T>(work: (client: pg.Client) => Promise<T>) {
  const client = new pg.Client({
    ...db('capacity'),
    connectionTimeoutMillis: 1500,
    query_timeout: 5000,
  });
  try {
    await client.connect();
    return await work(client);
  } finally {
    await client.end();
  }
}
async function verify(restored = false) {
  return ownerClient(async (client) => {
    const snapshots: Record<string, string> = {};
    for (const p of ['capacity', 'dormant'] as const) {
      const name = schema(f, p),
        q = '"' + name + '".';
      const meta = (
        await client.query(
          `SELECT m.*,obj_description(n.oid,'pg_namespace') AS marker FROM ${q}schema_metadata m JOIN pg_namespace n ON n.nspname=$1`,
          [name],
        )
      ).rows;
      assert.equal(meta.length, 1);
      assert.equal(meta[0].version, 7);
      assert.equal(meta[0].runtime_role, 'livekit_lab');
      assert.equal(meta[0].marker, 'p2-channel-schema-v7');
      for (const [key, v] of Object.entries(OWNER_LIMITS[p]))
        assert.equal(meta[0][key.replace(/[A-Z]/g, (s) => '_' + s.toLowerCase())], v);
      const count = (
        await client.query(
          `SELECT p.state,count(*)::int AS count FROM ${q}processing_intents p GROUP BY p.state ORDER BY p.state`,
        )
      ).rows;
      assert.deepEqual(
        count,
        p === 'capacity'
          ? [{ state: 'dispatched', count: 64 }]
          : [
              { state: 'dispatched', count: 4 },
              { state: 'pending', count: 998 },
            ],
      );
      const tables = (
        await client.query(
          'SELECT tablename FROM pg_tables WHERE schemaname=$1 ORDER BY tablename',
          [name],
        )
      ).rows.map((r) => String(r.tablename));
      assert.deepEqual(tables, SCHEMA_TABLES);
      for (const table of tables) {
        assert.match(table, /^[a-z_]+$/);
        const rows = (
          await client.query(
            `SELECT to_jsonb(t) AS row FROM ${q}"${table}" t ORDER BY to_jsonb(t)::text`,
          )
        ).rows.map((r) => r.row as unknown);
        const file = 'workload-' + p + '-' + table + (restored ? '-restored' : '-before') + '.json';
        save(file, { schemaVersion: 1, schema: name, table, rows });
        snapshots[p + ':' + table] = fingerprint(rows);
      }
      const originals = [
        ...(p === 'capacity'
          ? load<Original[]>('workload-capacity-originals.json')
          : load<Original[]>('workload-dormant-originals.json')),
        ...(p === 'dormant' ? load<Original[]>('workload-wake-originals.json') : []),
      ];
      const rows = (
        await client.query(
          `SELECT i.*,p.operation_key,p.state FROM ${q}inbox i JOIN ${q}processing_intents p USING(receipt_id) ORDER BY i.receipt_id`,
        )
      ).rows;
      assert.equal(rows.length, p === 'capacity' ? 64 : 1002);
      for (const old of originals) {
        const row = rows.find((r) => r.receipt_id === old.receipt.receiptId);
        assert.ok(row);
        assert.equal(row.event_id, old.receipt.eventId);
        assert.equal(String(row.acceptance_sequence), old.receipt.acceptanceSequence);
        assert.equal(row.accepted_at.toISOString(), old.receipt.acceptedAt);
        assert.equal(row.operation_key, old.operationKey);
        const canonical = JSON.parse(row.canonical_payload as string) as { body: string };
        assert.equal(createHash('sha256').update(canonical.body).digest('hex'), old.bodyDigest);
      }
      const operations = ledger().filter((r) =>
        r.prepared.submission.caseId.startsWith('case-' + p),
      );
      assert.equal(operations.length, p === 'capacity' ? 64 : 4);
      for (const op of operations) {
        const row = rows.find((r) => r.receipt_id === op.prepared.submission.message.receiptId);
        assert.ok(row);
        assert.equal(row.operation_key, op.receipt.operationKey);
        assert.equal(row.state, 'dispatched');
        const plan = (
          await client.query(`SELECT * FROM ${q}dispatch_plans WHERE receipt_id=$1`, [
            row.receipt_id,
          ])
        ).rows[0];
        assert.ok(plan);
        assert.equal(plan.payload_json, op.prepared.canonicalPayload);
        assert.equal(plan.payload_digest, op.prepared.payloadDigest);
        assert.equal(
          createHash('sha256').update(op.prepared.canonicalPayload).digest('hex'),
          op.receipt.payloadDigest,
        );
      }
      const role = (
        await client.query(
          "SELECT has_schema_privilege('livekit_lab',$1,'CREATE') AS can_create,pg_has_role('livekit_lab','continuity_migrator','MEMBER') AS owner_member",
          [name],
        )
      ).rows[0];
      assert.deepEqual(role, { can_create: false, owner_member: false });
    }
    if (restored) {
      assert.deepEqual(snapshots, load('workload-before-digests.json'));
      stages.add(CASE_NAMES[22]);
    } else save('workload-before-digests.json', snapshots);
    save(restored ? 'workload-restored-owner-proof.json' : 'workload-owner-proof.json', {
      schemaVersion: 1,
      schemas: 2,
      capacityInputs: 64,
      dormantInputs: 1002,
      capacityDispatched: 64,
      dormantDispatched: 4,
      dormantPending: 998,
      operationAcceptances: 68,
      snapshots,
      rolesSeparated: true,
    });
    stages.add(CASE_NAMES[23]);
    return {
      schemas: 2,
      capacityInputs: 64,
      dormantInputs: 1002,
      operationAcceptances: 68,
      rolesSeparated: true,
    };
  });
}
async function drop(cleanup = false) {
  return ownerClient(async (client) => {
    for (const p of ['capacity', 'dormant'] as const) {
      const name = schema(f, p),
        found = (
          await client.query(
            "SELECT nspname,obj_description(oid,'pg_namespace') AS marker,pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=$1",
            [name],
          )
        ).rows[0];
      if (!found) {
        assert.ok(cleanup);
        continue;
      }
      assert.equal(found.owner, 'continuity_migrator');
      assert.match(String(found.marker), /^p2-channel-schema-v[1-7]$/);
      await client.query('DROP SCHEMA "' + name + '" CASCADE');
    }
    return { ownedSchemasAbsent: true, cleanupComplete: true };
  });
}
try {
  phase = mode!;
  let result: Record<string, unknown>;
  switch (mode) {
    case 'install':
      result = await install();
      break;
    case 'seed':
      result = await seed();
      break;
    case 'serve':
      result = await serve();
      break;
    case 'reopen':
      result = await reopen();
      break;
    case 'dormant-wake':
      result = await wake();
      break;
    case 'verify':
      result = await verify();
      break;
    case 'drop':
      result = await drop();
      break;
    case 'restored-replay':
      result = await restoredReplay();
      break;
    case 'restored-verify':
      result = await verify(true);
      break;
    case 'cleanup':
      result = await drop(true);
      break;
    default:
      throw new Error('invalid_mode');
  }
  process.stdout.write(
    JSON.stringify({
      schemaVersion: 1,
      status: 'passed',
      mode,
      nodeVersion: process.versions.node,
      completedGroups: [...stages],
      ...result,
    }) + '\n',
  );
} catch (error) {
  const code =
    error instanceof ChannelError &&
    [
      'InvalidConfiguration',
      'InvalidEvent',
      'AccessDenied',
      'AssociationRequired',
      'AssociationRejected',
      'IdentityConflict',
      'Overloaded',
      'NotFound',
      'StorageUnavailable',
      'AcknowledgementUnknown',
      'SchemaMismatch',
      'CleanupIncomplete',
      'UpgradeRequired',
      'DispatchClaimLost',
      'DispatchUnavailable',
      'OperationConflict',
    ].includes(error.code)
      ? error.code
      : null;
  const frames =
    error instanceof Error
      ? (error.stack ?? '')
          .split('\n')
          .slice(1)
          .flatMap((line) => {
            const match = /pg_workload_cases\.js:(\d+):\d+/.exec(line);
            return match ? [{ file: 'pg_workload_cases.js', line: Number(match[1]) }] : [];
          })
          .slice(0, 4)
      : [];
  save('workload-failure-' + mode + '.json', {
    schemaVersion: 1,
    status: 'failed',
    mode,
    phase,
    errorType:
      error instanceof ChannelError
        ? 'ChannelError'
        : error instanceof assert.AssertionError
          ? 'AssertionError'
          : 'DependencyError',
    code,
    frames,
  });
  process.stdout.write(
    JSON.stringify({ schemaVersion: 1, status: 'failed', mode, code: 'workload_fixture_failed' }) +
      '\n',
  );
  process.exitCode = 1;
} finally {
  eventLoop.disable();
}
