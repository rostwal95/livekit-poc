/** Application-owned socket/process fixture, consuming only public P2 APIs. */
import assert from 'node:assert/strict';
import { randomUUID, createHash, createHmac } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import {
  createServer,
  request as httpRequest,
  type Server,
  type IncomingMessage,
  type ServerResponse,
} from 'node:http';
import type { Socket } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import { fixtureResult, observeFixtureWork, type FixtureOutcome } from './fixture-work.js';
import {
  ChannelInbox,
  SeededAccounts,
  type DatabaseSettings,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  createFakeSmsIntegration,
  signFakeSms,
} from '@livekit-ecosystem/channel-continuity/security';
import {
  ChannelOutbox,
  type SendRequest,
  type CarrierResult,
} from '@livekit-ecosystem/channel-continuity/outbox';
import { FakeSmsSendClient } from '@livekit-ecosystem/channel-continuity/fake-sms-send';
import {
  installChannelSchema,
  upgradeChannelSchemaV2,
  upgradeChannelSchemaV3,
  upgradeChannelSchemaV4,
} from '@livekit-ecosystem/channel-continuity/migrations';
import {
  CallbackInbox,
  CallbackError,
  createFakeSmsCallbackIntegration,
  signFakeSmsCallback,
  type CallbackObservation,
  type CallbackReceipt,
  type CallbackAttempt,
} from '@livekit-ecosystem/channel-continuity/callbacks';
const SCOPE = { tenantId: 'tenant-a', accountId: 'account-a' },
  PROVIDER = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
  KEY = Buffer.alloc(32, 0x61),
  CALLBACK_KEY = Buffer.alloc(32, 0x71),
  TOKEN = 'synthetic_account_'.repeat(4),
  OTHER = 'synthetic_other_'.repeat(4),
  ALT = 'synthetic_alt_'.repeat(4),
  PUBLISH = 'synthetic_publisher_'.repeat(4),
  BEARER = 'Bearer ' + 'c'.repeat(43),
  DIR = env('P2_CALLBACK_DIRECTORY');
function env(k: string) {
  const v = process.env[k];
  assert.ok(v);
  return v;
}
function db(owner = false): DatabaseSettings {
  const schema = env('P2_CALLBACK_SCHEMA');
  assert.match(schema, /^p2_callback_[a-f0-9]{32}$/);
  return {
    host: '127.0.0.1',
    port: Number(env('P2_CALLBACK_PG_PORT')),
    database: 'livekit_lab',
    user: owner ? 'continuity_migrator' : 'livekit_lab',
    password: env(owner ? 'P2_CALLBACK_OWNER_PASSWORD' : 'P2_CALLBACK_RUNTIME_PASSWORD'),
    schema,
  };
}
const accounts = () =>
  new SeededAccounts([
    { token: TOKEN, ...SCOPE, caseId: 'case-a', conversationId: 'conversation-a' },
    {
      token: OTHER,
      tenantId: 'tenant-a',
      accountId: 'account-b',
      caseId: 'case-a',
      conversationId: 'conversation-a',
    },
    { token: ALT, ...SCOPE, caseId: 'case-b', conversationId: 'conversation-b' },
  ]);
const integration = () => createFakeSmsIntegration(PROVIDER, KEY);
const callbacks = () =>
  new CallbackInbox(db(), createFakeSmsCallbackIntegration(PROVIDER, CALLBACK_KEY), accounts(), {
    observer: () => {},
  });
const ids = JSON.parse(readFileSync(DIR + '/fixture.json', 'utf8')).ids as string[];
const sha = (v: string) => createHash('sha256').update(v).digest('hex');
function save(name: string, value: unknown) {
  writeFileSync(DIR + '/' + name, JSON.stringify(value) + '\n', { mode: 0o600 });
}
function load<T>(name: string): T {
  return JSON.parse(readFileSync(DIR + '/' + name, 'utf8')) as T;
}
async function barrier(name: string) {
  writeFileSync(DIR + '/' + name + '.reached', String(process.pid) + '\n', {
    flag: 'wx',
    mode: 0o600,
  });
  const end = performance.now() + 10000;
  while (!existsSync(DIR + '/' + name + '.go')) {
    if (performance.now() > end) throw Error('barrier_timeout');
    await delay(5);
  }
}
function signed(body: string, senderId = 'sender-old') {
  const id = 'event-' + randomUUID();
  return signFakeSms(
    {
      schemaVersion: 1,
      eventId: id,
      messageId: id,
      senderId,
      body,
      occurredAt: '2030-01-01T00:00:00.000Z',
    },
    KEY,
    Math.floor(Date.now() / 1000),
    PROVIDER,
  );
}
async function associate(inbox: ChannelInbox, sender = 'sender-old', token = TOKEN) {
  const c = await inbox.createChallenge(token, sender),
    s = signed('LINK ' + c.challengeId + ' ' + c.secret, sender);
  return (await inbox.completeAssociation(s.raw, s.headers)).associationVersion;
}
function report(
  attempt: SendRequest,
  eventId: string,
  state: CallbackObservation['state'] = 'delivered',
  providerMessageId = 'provider-' + attempt.attemptId,
): CallbackObservation {
  return {
    schemaVersion: 1,
    eventId,
    attemptId: attempt.attemptId,
    providerOperationKey: attempt.providerOperationKey,
    requestDigest: sha(JSON.stringify(attempt)),
    providerMessageId,
    state,
    occurredAt: '2030-01-01T00:00:00.000Z',
  };
}
async function reject(work: () => unknown, code: string) {
  await assert.rejects(
    async () => work(),
    (e: unknown) => e instanceof CallbackError && e.code === code,
  );
}
type Ledger = { request: SendRequest; result: CarrierResult };
/** These explicit listeners belong to this application fixture, not CallbackInbox. */
class Peers {
  readonly sockets = new Set<Socket>();
  readonly tasks = new Set<Promise<void>>();
  readonly servers: Server[] = [];
  callbackPort = 0;
  carrierPort = 0;
  callback: CallbackInbox;
  beforeAck: ((request: SendRequest) => Promise<void>) | undefined;
  afterCallback: ((receipt: CallbackReceipt) => Promise<void>) | undefined;
  failures = 0;
  constructor(callback: CallbackInbox) {
    this.callback = callback;
  }
  async start() {
    for (const kind of ['callback', 'carrier'] as const) {
      const s = createServer({ maxHeaderSize: 4096 }, (req, res) => {
        if (this.tasks.size >= 4) {
          req.destroy();
          return;
        }
        const work = this.handle(kind, req, res);
        this.tasks.add(work);
        void work.then(
          () => this.tasks.delete(work),
          () => {
            this.failures++;
            this.tasks.delete(work);
            req.destroy();
          },
        );
      });
      s.maxHeadersCount = 16;
      s.requestTimeout = 1500;
      s.headersTimeout = 1000;
      s.keepAliveTimeout = 1;
      s.on('connection', (socket) => {
        if (this.sockets.size >= 16) {
          socket.destroy();
          return;
        }
        this.sockets.add(socket);
        socket.once('close', () => this.sockets.delete(socket));
      });
      s.on('clientError', (_e, socket) => socket.destroy());
      await new Promise<void>((resolve, reject) => {
        s.once('error', reject);
        s.listen(0, '127.0.0.1', resolve);
      });
      this.servers.push(s);
      const a = s.address();
      assert.ok(a && typeof a !== 'string');
      if (kind === 'callback') this.callbackPort = a.port;
      else this.carrierPort = a.port;
    }
  }
  async handle(kind: 'callback' | 'carrier', req: IncomingMessage, res: ServerResponse) {
    let sent = false;
    try {
      assert.equal(req.method, 'POST');
      assert.equal(req.url, kind === 'callback' ? '/v1/sms/callback' : '/v1/sms/send');
      assert.equal(req.headers.connection, 'close');
      assert.equal(req.headers['content-type'], 'application/json');
      assert.equal(req.headers['transfer-encoding'], undefined);
      const size = Number(req.headers['content-length']);
      assert.ok(
        Number.isSafeInteger(size) && size >= 1 && size <= (kind === 'callback' ? 4096 : 32768),
      );
      const chunks: Buffer[] = [];
      let count = 0;
      for await (const chunk of req) {
        count += chunk.length;
        assert.ok(count <= size);
        chunks.push(Buffer.from(chunk));
      }
      assert.equal(count, size);
      const raw = Buffer.concat(chunks);
      let value: unknown;
      if (kind === 'callback') {
        assert.equal(typeof req.headers['x-callback-timestamp'], 'string');
        assert.equal(typeof req.headers['x-callback-signature'], 'string');
        try {
          const receipt = await this.callback.accept(raw, {
            timestamp: req.headers['x-callback-timestamp'] as string,
            signature: req.headers['x-callback-signature'] as string,
          });
          if (this.afterCallback) await this.afterCallback(receipt);
          value = { status: 'accepted', receipt };
        } catch (e) {
          assert.ok(e instanceof CallbackError);
          value = { status: 'rejected', code: e.code };
        }
      } else {
        assert.equal(req.headers.authorization, BEARER);
        const request = JSON.parse(raw.toString()) as SendRequest;
        assert.deepEqual(request.providerScope, PROVIDER);
        assert.deepEqual(request.scope, SCOPE);
        assert.equal(request.caseId, 'case-a');
        const result: CarrierResult =
          request.body === 'fail'
            ? {
                schemaVersion: 1,
                attemptId: request.attemptId,
                requestDigest: sha(raw.toString()),
                status: 'definitive_not_accepted',
              }
            : {
                schemaVersion: 1,
                attemptId: request.attemptId,
                requestDigest: sha(raw.toString()),
                status: 'accepted_by_provider',
                providerMessageId: 'provider-' + request.attemptId,
              };
        const ledger = existsSync(DIR + '/provider.json') ? load<Ledger[]>('provider.json') : [];
        assert.ok(!ledger.some((x) => x.request.attemptId === request.attemptId));
        ledger.push({ request, result });
        save('provider.json', ledger);
        if (this.beforeAck) await this.beforeAck(request);
        value = { schemaVersion: 1, status: 'known', result };
      }
      const bytes = Buffer.from(JSON.stringify(value));
      assert.ok(bytes.length <= 2048);
      res.writeHead(200, {
        'Content-Type': 'application/json',
        'Content-Length': bytes.length,
        Connection: 'close',
      });
      res.end(bytes);
      sent = true;
    } finally {
      if (!sent) req.destroy();
    }
  }
  async submit(observation: CallbackObservation, reordered = false) {
    const s = signFakeSmsCallback(
      observation,
      CALLBACK_KEY,
      Math.floor(Date.now() / 1000),
      PROVIDER,
    );
    let raw = Buffer.from(s.raw),
      headers = s.headers;
    if (reordered) {
      raw = Buffer.from(
        '{ ' +
          Object.entries(observation)
            .reverse()
            .map(([k, v]) => JSON.stringify(k) + ' : ' + JSON.stringify(v))
            .join(', ') +
          ' }',
      );
      headers = {
        timestamp: s.headers.timestamp,
        signature: createHmac('sha256', CALLBACK_KEY)
          .update(
            'p2.fake_sms_callback.v1\n' +
              PROVIDER.tenantId +
              '\n' +
              PROVIDER.provider +
              '\n' +
              PROVIDER.providerAccountId +
              '\n' +
              s.headers.timestamp +
              '\n',
          )
          .update(raw)
          .digest('hex'),
      };
    }
    return await new Promise<{ status: string; receipt?: CallbackReceipt; code?: string }>(
      (resolve, reject) => {
        const req = httpRequest(
          {
            host: '127.0.0.1',
            port: this.callbackPort,
            path: '/v1/sms/callback',
            method: 'POST',
            agent: false,
            headers: {
              'content-type': 'application/json',
              'content-length': raw.length,
              connection: 'close',
              'x-callback-timestamp': headers.timestamp,
              'x-callback-signature': headers.signature,
            },
          },
          (res) => {
            const chunks: Buffer[] = [];
            let total = 0;
            res.on('data', (b: Buffer) => {
              total += b.length;
              if (total > 2048) res.destroy();
              else chunks.push(b);
            });
            res.on('end', () => {
              try {
                resolve(JSON.parse(Buffer.concat(chunks).toString()));
              } catch (e) {
                reject(e);
              }
            });
            res.on('error', reject);
          },
        );
        req.setTimeout(10000, () => req.destroy());
        req.on('error', reject);
        req.end(raw);
      },
    );
  }
  async close() {
    await Promise.all(
      this.servers.map(
        (s) => new Promise<void>((resolve, reject) => s.close((e) => (e ? reject(e) : resolve()))),
      ),
    );
    await Promise.all([...this.tasks]);
    for (const s of this.sockets) s.destroy();
    const end = performance.now() + 1500;
    while (this.sockets.size) {
      assert.ok(performance.now() < end);
      await delay(2);
    }
    assert.equal(this.failures, 0);
  }
}
function outbox(
  carrier:
    | FakeSmsSendClient
    | {
        capabilities: 'ordinary_fake_sms_v1';
        send: (r: SendRequest, s: AbortSignal) => Promise<CarrierResult>;
      },
) {
  return new ChannelOutbox(
    db(),
    integration(),
    accounts(),
    [{ token: PUBLISH, scope: SCOPE, caseId: 'case-a', conversationId: 'conversation-a' }],
    carrier,
    { observer: () => {} },
  );
}
const draft = (n: number) => ({
  schemaVersion: 1 as const,
  outboundId: ids[n]!,
  responseId: 'response-' + n,
  body: n === 1 || n === 3 ? 'fail' : n === 0 ? 'Notice é🙂\n"quoted"\t' : 'normal',
});
async function resources() {
  const cb = callbacks(),
    peers = new Peers(cb);
  let carrier: FakeSmsSendClient | undefined,
    box: ChannelOutbox | undefined,
    inbox: ChannelInbox | undefined;
  try {
    await peers.start();
    carrier = new FakeSmsSendClient(
      { host: '127.0.0.1', port: peers.carrierPort },
      BEARER,
      PROVIDER,
    );
    box = outbox(carrier);
    inbox = new ChannelInbox(db(), integration(), accounts(), {}, () => {});
    const ownedCarrier = carrier,
      ownedBox = box,
      ownedInbox = inbox;
    return {
      cb,
      peers,
      carrier: ownedCarrier,
      box: ownedBox,
      inbox: ownedInbox,
      async close() {
        await ownedBox.close();
        await ownedCarrier.close();
        await peers.close();
        await cb.close();
        await ownedInbox.close();
      },
    };
  } catch (error) {
    await Promise.allSettled([
      box?.close(),
      carrier?.close(),
      peers.close(),
      cb.close(),
      inbox?.close(),
    ]);
    throw error;
  }
}

async function main() {
  const mode = process.argv[2];
  if (mode === 'install') {
    await installChannelSchema(db(true));
    await upgradeChannelSchemaV2(db(true));
    await upgradeChannelSchemaV3(db(true), { maxReplies: 8, maxRoutes: 4, maxAttempts: 5 });
  } else if (mode === 'upgrade') {
    await upgradeChannelSchemaV4(db(true), { maxGlobal: 12, maxPerAttempt: 8 });
  } else if (mode === 'repeat') {
    await installChannelSchema(db(true));
    await upgradeChannelSchemaV2(db(true));
    await upgradeChannelSchemaV3(db(true), { maxReplies: 8, maxRoutes: 4, maxAttempts: 5 });
    await upgradeChannelSchemaV4(db(true), { maxGlobal: 12, maxPerAttempt: 8 });
    await assert.rejects(() =>
      upgradeChannelSchemaV4(db(true), { maxGlobal: 13, maxPerAttempt: 8 }),
    );
  } else if (mode === 'seed') {
    const r = await resources();
    try {
      const epoch = await associate(r.inbox);
      await r.box.selectRoute(TOKEN, {
        senderId: 'sender-old',
        associationVersion: epoch,
        expectedRouteVersion: '0',
      });
      const message = signed('investigate');
      const accepted = await r.inbox.acceptSms(message.raw, message.headers);
      save('original-inbox.json', accepted);
      for (const n of [0, 1, 3]) {
        await r.box.enqueue(PUBLISH, draft(n));
        await r.box.send(TOKEN, ids[n]!);
      }
      save(
        'original-replies.json',
        await Promise.all([0, 1, 3].map((n) => r.box.inspect(TOKEN, ids[n]!))),
      );
    } finally {
      await r.close();
    }
  } else if (mode === 'expiry') {
    const r = await resources();
    try {
      const normal =
        load<{ attempts: { request: SendRequest }[] }[]>('original-replies.json')[0]!.attempts[0]!
          .request;
      await barrier('expiry_ready');
      const timestamp = load<{ timestamp: number }>('expiry-timestamp.json').timestamp,
        expired = { ...report(normal, 'expired-held'), occurredAt: '2030-01-01T00:00:00.000Z' },
        signed = signFakeSmsCallback(expired, CALLBACK_KEY, timestamp, PROVIDER),
        pending = r.cb.accept(signed.raw, signed.headers).then(
          () => 'unexpected_acceptance',
          (error) => (error instanceof CallbackError ? error.code : 'unsafe_failure'),
        );
      await barrier('expiry_waiting');
      assert.equal(await pending, 'WebhookRejected');
      await barrier('expiry_rejected');
      const fresh = report(normal, 'normal-7', 'accepted_by_provider');
      const result = await r.peers.submit(fresh);
      assert.equal(result.status, 'accepted');
      save('expiry-proof.json', {
        expiredEventId: expired.eventId,
        transportTimestamp: timestamp,
        freshReceipt: result.receipt,
      });
    } finally {
      await r.close();
    }
  } else if (mode === 'exercise') {
    const r = await resources();
    try {
      const original = load<unknown[]>('original-replies.json');
      assert.deepEqual(
        await Promise.all([0, 1, 3].map((n) => r.box.inspect(TOKEN, ids[n]!))),
        original,
      );
      const m = signed('new-v4-input');
      await r.inbox.acceptSms(m.raw, m.headers);
      const normal = (await r.box.inspect(TOKEN, ids[0]!)).attempts[0]!.request,
        events: CallbackObservation[] = [];
      const normalFirst = report(normal, 'normal-0', 'delivered'),
        duplicates = await Promise.all(
          Array.from({ length: 3 }, () => r.peers.submit(normalFirst)),
        );
      assert.ok(duplicates.every((x) => x.status === 'accepted'));
      assert.deepEqual(duplicates[0]!.receipt, duplicates[1]!.receipt);
      assert.deepEqual((await r.peers.submit(normalFirst, true)).receipt, duplicates[0]!.receipt);
      events.push(normalFirst);
      for (const [i, state] of (
        [
          'accepted_by_provider',
          'unknown',
          'read_reported',
          'failed',
          'unknown',
          'failed',
          'accepted_by_provider',
        ] as const
      ).entries()) {
        const o = {
          ...report(
            normal,
            'normal-' + (i + 1),
            state,
            i === 4 ? 'different-message' : 'provider-' + normal.attemptId,
          ),
          occurredAt: '2030-01-0' + ((i % 2) + 1) + 'T00:00:00.000Z',
        };
        assert.equal((await r.peers.submit(o)).status, 'accepted');
        events.push(o);
      }
      assert.equal((await r.peers.submit(report(normal, 'normal-over-cap'))).code, 'Overloaded');
      assert.deepEqual((await r.peers.submit(normalFirst)).receipt, duplicates[0]!.receipt);
      for (const changed of [
        { state: 'failed' },
        { providerMessageId: 'changed' },
        { occurredAt: '2030-01-02T00:00:00.000Z' },
      ])
        assert.equal(
          (await r.peers.submit({ ...normalFirst, ...changed } as CallbackObservation)).code,
          'IdentityConflict',
        );
      const view = await r.cb.inspectAttempt(TOKEN, {
        outboundId: ids[0]!,
        attemptId: normal.attemptId,
      });
      assert.deepEqual(view.evidence.conflicts, ['terminal_reports', 'provider_identity']);
      assert.equal(view.evidence.strongestReported, 'read_reported');
      assert.equal(view.observations.length, 8);
      assert.equal(view.evidence.sendResult?.status, 'accepted_by_provider');
      // Every rejected original tuple fails without gaining any recipient authority.
      for (const changed of [
        { attemptId: randomUUID() },
        { providerOperationKey: randomUUID() },
        { requestDigest: '0'.repeat(64) },
      ])
        assert.equal(
          (await r.peers.submit({ ...normalFirst, ...changed, eventId: 'bad-' + randomUUID() }))
            .code,
          'AccessDenied',
        );
      const s = signFakeSmsCallback(
        normalFirst,
        CALLBACK_KEY,
        Math.floor(Date.now() / 1000) - 61,
        PROVIDER,
      );
      await reject(() => r.cb.accept(s.raw, s.headers), 'WebhookRejected');
      const wrongKey = signFakeSmsCallback(
        normalFirst,
        KEY,
        Math.floor(Date.now() / 1000),
        PROVIDER,
      );
      await reject(() => r.cb.accept(wrongKey.raw, wrongKey.headers), 'WebhookRejected');
      const wrongDomain = signed('not-a-callback');
      await reject(() => r.cb.accept(wrongDomain.raw, wrongDomain.headers), 'WebhookRejected');
      const other = new CallbackInbox(
        db(),
        createFakeSmsCallbackIntegration(
          { ...PROVIDER, providerAccountId: 'carrier-b' },
          CALLBACK_KEY,
        ),
        accounts(),
        { observer: () => {} },
      );
      try {
        const wrong = signFakeSmsCallback(
          { ...normalFirst, eventId: 'wrong-provider' },
          CALLBACK_KEY,
          Math.floor(Date.now() / 1000),
          { ...PROVIDER, providerAccountId: 'carrier-b' },
        );
        await reject(() => other.accept(wrong.raw, wrong.headers), 'AccessDenied');
      } finally {
        await other.close();
      }
      await r.inbox.revokeAssociation(TOKEN, 'sender-old');
      await associate(r.inbox, 'sender-old', OTHER);
      const newer = await associate(r.inbox, 'sender-new');
      await r.box.selectRoute(TOKEN, {
        senderId: 'sender-new',
        associationVersion: newer,
        expectedRouteVersion: '1',
      });
      await reject(
        () => r.cb.inspectAttempt(OTHER, { outboundId: ids[0]!, attemptId: normal.attemptId }),
        'AccessDenied',
      );
      await reject(
        () => r.cb.inspectAttempt(ALT, { outboundId: ids[0]!, attemptId: normal.attemptId }),
        'AccessDenied',
      );
      assert.deepEqual(
        (await r.cb.inspectAttempt(TOKEN, { outboundId: ids[0]!, attemptId: normal.attemptId }))
          .observations,
        view.observations,
      );
      // Two known definitive failures; a callback on the older one blocks another NEW call.
      await r.box.send(TOKEN, ids[1]!);
      const retry = (await r.box.inspect(TOKEN, ids[1]!)).attempts;
      assert.equal(retry.length, 2);
      save('race-observation.json', report(retry[0]!.request, 'older-attempt', 'unknown'));
      await barrier('race_ready');
      const raceWork: Promise<FixtureOutcome<unknown>>[] = [];
      try {
        const signing = signFakeSmsCallback(
            load<CallbackObservation>('race-observation.json'),
            CALLBACK_KEY,
            Math.floor(Date.now() / 1000),
            PROVIDER,
          ),
          before = load<Ledger[]>('provider.json').length,
          pending = observeFixtureWork(r.cb.accept(signing.raw, signing.headers));
        raceWork.push(pending);
        await barrier('race_callback');
        // Parent has observed the callback actually queued first on admission.
        const contender = observeFixtureWork(r.box.send(TOKEN, ids[1]!));
        raceWork.push(contender);
        await barrier('race_reserve');
        await fixtureResult(pending);
        assert.equal((await fixtureResult(contender)).status, 'unknown');
        assert.equal(load<Ledger[]>('provider.json').length, before);
      } finally {
        await Promise.all(raceWork);
      }

      assert.ok(!(await r.box.pending(TOKEN)).includes(ids[1]!));
      assert.equal(
        (
          await r.cb.inspectAttempt(TOKEN, {
            outboundId: ids[1]!,
            attemptId: retry[0]!.request.attemptId,
          })
        ).evidence.assessment,
        'reported',
      );
      // App provider publishes a correlated callback BEFORE releasing its ordinary successful ACK.
      await r.box.enqueue(PUBLISH, draft(2));
      r.peers.beforeAck = async (request) => {
        assert.equal(
          (await r.peers.submit(report(request, 'before-send-result'))).status,
          'accepted',
        );
        const early = await r.cb.inspectAttempt(TOKEN, {
          outboundId: request.outboundId,
          attemptId: request.attemptId,
        });
        assert.equal(early.evidence.sendResult, null);
        assert.equal(early.evidence.strongestReported, 'delivered');
        save('before-result.json', early);
      };
      assert.equal((await r.box.send(TOKEN, ids[2]!)).status, 'accepted_by_provider');
      r.peers.beforeAck = undefined;
      // Actual reservation is already committed. Independent process will append a callback on attempt1.
      const base = (await r.box.inspect(TOKEN, ids[3]!)).attempts[0]!.request;
      save('late-observation.json', report(base, 'reservation-first', 'failed'));
      let heldRequest: SendRequest | undefined;
      const paused = outbox({
        capabilities: 'ordinary_fake_sms_v1',
        async send(request, signal) {
          heldRequest = request;
          save('admitted-request.json', request);
          await barrier('reservation');
          return r.carrier.send(request, signal);
        },
      });
      try {
        const result = await paused.send(TOKEN, ids[3]!);
        assert.equal(result.status, 'definitive_not_accepted');
        assert.ok(heldRequest);
        assert.equal(heldRequest.senderId, 'sender-new');
        assert.equal((await r.box.send(TOKEN, ids[3]!)).status, 'unknown');
      } finally {
        await paused.close();
      }
      // A local possible marker without a known result stays unknown, even after later reports.
      await r.box.enqueue(PUBLISH, draft(4));
      const possible = outbox({
        capabilities: 'ordinary_fake_sms_v1',
        async send() {
          throw Error('owned possible before wire');
        },
      });
      try {
        assert.equal((await possible.send(TOKEN, ids[4]!)).status, 'unknown');
      } finally {
        await possible.close();
      }
      const unknown = (await r.box.inspect(TOKEN, ids[4]!)).attempts[0]!.request;
      save('crash-observation.json', report(unknown, 'committed-crash', 'delivered'));
      save('proof.json', {
        normal: await r.cb.inspectAttempt(TOKEN, {
          outboundId: ids[0]!,
          attemptId: normal.attemptId,
        }),
        normalEvents: events,
        older: retry[0]!.request.attemptId,
        unknown: unknown.attemptId,
        providerCalls: load<Ledger[]>('provider.json').length,
        sourceInputCount: 2,
        originalInput: load('original-inbox.json'),
      });
      assert.equal(r.cb.metrics().accepted, 9);
      assert.equal(r.cb.metrics().replayed, 5);
    } finally {
      await r.close();
    }
  } else if (mode === 'late-callback') {
    const r = await resources();
    try {
      assert.equal((await r.peers.submit(load('late-observation.json'))).status, 'accepted');
    } finally {
      await r.close();
    }
  } else if (mode === 'crash') {
    const r = await resources();
    r.peers.afterCallback = async (receipt) => {
      save('crash-receipt.json', receipt);
      await barrier('committed');
    };
    void r.peers.submit(load('crash-observation.json')).catch(() => {});
    await new Promise<void>(() => {});
  } else if (mode === 'replay') {
    const r = await resources();
    try {
      const o = load<CallbackObservation>('crash-observation.json'),
        expected = load<CallbackReceipt>('crash-receipt.json'),
        before = load<Ledger[]>('provider.json').length;
      assert.deepEqual((await r.peers.submit(o, true)).receipt, expected);
      const view = await r.cb.inspectAttempt(TOKEN, {
        outboundId: ids[4]!,
        attemptId: o.attemptId,
      });
      assert.equal(view.evidence.strongestReported, 'delivered');
      assert.equal(view.evidence.sendResult, null);
      assert.equal((await r.box.send(TOKEN, ids[4]!)).status, 'unknown');
      assert.equal((await r.peers.submit({ ...o, eventId: 'global-cap' })).code, 'Overloaded');
      assert.equal(
        (await r.peers.submit({ ...o, eventId: 'committed-crash', state: 'failed' })).code,
        'IdentityConflict',
      );
      assert.deepEqual((await r.peers.submit(o)).receipt, expected);
      const first = load<{ normal: CallbackAttempt }>('proof.json').normal;
      assert.deepEqual(
        await r.cb.inspectAttempt(TOKEN, { outboundId: ids[0]!, attemptId: first.attemptId }),
        first,
      );
      assert.equal(load<Ledger[]>('provider.json').length, before);
      save('reopen-proof.json', {
        receipt: expected,
        view,
        providerBefore: before,
        providerAfter: before,
      });
    } finally {
      await r.close();
    }
  } else if (mode === 'counter' || mode === 'drift') {
    const r = await resources();
    try {
      if (mode === 'counter') {
        const o = load<CallbackObservation>('crash-observation.json');
        const signed = signFakeSmsCallback(
          { ...o, eventId: 'counter-test' },
          CALLBACK_KEY,
          Math.floor(Date.now() / 1000),
          PROVIDER,
        );
        await reject(() => r.cb.accept(signed.raw, signed.headers), 'Unavailable');
      } else {
        const o = load<CallbackObservation>('crash-observation.json');
        await reject(
          () => r.cb.inspectAttempt(TOKEN, { outboundId: ids[4]!, attemptId: o.attemptId }),
          'Unavailable',
        );
      }
    } finally {
      await r.close();
    }
  } else throw Error('invalid_mode');
  console.log(
    JSON.stringify({
      status: 'passed',
      mode,
      node_version: process.versions.node,
      cleanup_complete: true,
    }),
  );
}
void main().catch(() => {
  console.log(JSON.stringify({ status: 'failed', mode: process.argv[2], code: 'fixture_failed' }));
  process.exitCode = 1;
});
