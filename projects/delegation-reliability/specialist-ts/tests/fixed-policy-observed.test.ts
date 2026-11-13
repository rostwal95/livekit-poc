/** Verified observed API parity; loopback peer is explicitly a scripted fault fixture. */
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import type { Socket } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import { expect, test } from 'vitest';
import { canonical } from '../src/contracts.js';
import {
  FixedPolicySpecialistClient,
  produceFixedPolicyRequest,
  parseFixedPolicyRequest,
} from '../src/fixed-policy.js';
import type { FixedPolicyRequest } from '../src/fixed-policy.js';
import type { EvidenceRecord } from '../src/security.js';
const fixture = JSON.parse(
  readFileSync(
    new URL('../../../../contracts/delegation/fixed-policy-v2.json', import.meta.url),
    'utf8',
  ),
);
function fresh(horizon = 60000): FixedPolicyRequest {
  return produceFixedPolicyRequest({
    ...fixture.producer_input,
    deadline_at_ms: Date.now() + horizon,
  });
}
function sources(input: FixedPolicyRequest): EvidenceRecord[] {
  return input.evidence.map((reference, index) => ({
    scope: input.scope,
    reference,
    body: Buffer.from(index === 0 ? fixture.policy_body_utf8 : fixture.facts_body_utf8),
  }));
}
async function enteredOrSettled(entry: Promise<void>, pending: Promise<unknown>): Promise<void> {
  let arrived = false,
    timer: ReturnType<typeof setTimeout> | undefined;
  const guard = new Promise<void>((resolve) => {
    timer = setTimeout(resolve, 1000);
  });
  try {
    await Promise.race([
      entry.then(() => {
        arrived = true;
      }),
      pending.then(
        () => {},
        () => {},
      ),
      guard,
    ]);
    expect(arrived).toBe(true);
  } finally {
    clearTimeout(timer);
  }
}
async function peer(
  wrong: boolean,
  hold: Promise<void> | undefined,
  entered: () => void,
  run: (client: FixedPolicySpecialistClient) => Promise<void>,
) {
  const sockets = new Set<Socket>(),
    owners = new Set<Promise<void>>(),
    errors: unknown[] = [];
  const server = createServer((request, response) => {
    const work = (async () => {
      const chunks: Buffer[] = [];
      let size = 0;
      for await (const raw of request) {
        const chunk = Buffer.from(raw);
        size += chunk.length;
        if (size > 16384) throw Error('bounded_request');
        chunks.push(chunk);
      }
      const input = parseFixedPolicyRequest(Buffer.concat(chunks));
      const result = {
        ...fixture.result,
        scope: input.scope,
        delegation_id: input.delegation_id,
        case_id: input.case_id,
        request_revision: input.request_revision,
        attempt_id: input.attempt.attempt_id,
        input_fingerprint: input.input_fingerprint,
        eligible: !wrong,
        completed_at_ms: Date.now(),
      };
      entered();
      if (hold) await hold;
      const body = canonical(result);
      response.writeHead(200, {
        'Content-Type': 'application/json',
        'Content-Length': body.byteLength,
        Connection: 'close',
      });
      response.end(body);
    })();
    owners.add(work);
    void work.catch((error) => errors.push(error)).finally(() => owners.delete(work));
  });
  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.once('close', () => sockets.delete(socket));
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw Error('address');
  const client = new FixedPolicySpecialistClient(
    { host: '127.0.0.1', port: address.port },
    'Bearer ' + 'A'.repeat(43),
  );
  try {
    await run(client);
  } finally {
    await client.close();
    const closed = new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
    const socketClosures = [...sockets].map(
      (socket) =>
        new Promise<void>((resolve) => {
          socket.once('close', () => resolve());
          socket.destroy();
        }),
    );
    await Promise.allSettled([...owners]);
    await Promise.all(socketClosures);
    await closed;
    expect(client.active).toBe(0);
    expect(sockets.size).toBe(0);
    expect(errors).toEqual([]);
  }
}
test('invalid explicit inventories fail before any HTTP registration', async () => {
  const client = new FixedPolicySpecialistClient(
    { host: '127.0.0.1', port: 1 },
    'Bearer ' + 'A'.repeat(43),
  );
  const input = fresh(),
    records = sources(input);
  try {
    for (const invalid of [
      null,
      undefined,
      [],
      [records[0]],
      [...records, records[0]],
      [{ ...records[0]!, body: Buffer.alloc(4097) }, records[1]],
      records.map((r) => ({ ...r, scope: { ...r.scope, account_id: 'foreign_account' } })),
    ]) {
      await expect(
        client.invokeObserved(input, invalid as unknown as EvidenceRecord[]),
      ).rejects.toBeDefined();
    }
    expect(client.metrics().started).toBe(0);
  } finally {
    await client.close();
  }
});
test('actual valid JSON with unsupported facts fails the verified API', async () => {
  await peer(
    true,
    undefined,
    () => {},
    async (client) => {
      const input = fresh();
      await expect(client.invokeObserved(input, sources(input))).rejects.toMatchObject({
        code: 'invalid_response',
      });
      expect(client.metrics().validationFailed).toBe(1);
    },
  );
});
test('legacy invoke remains correlation-only', async () => {
  await peer(
    true,
    undefined,
    () => {},
    async (client) => {
      expect((await client.invoke(fresh())).eligible).toBe(false);
    },
  );
});
test.each([false, true])(
  'late observation verifies facts before expiry disposition (wrong=%s)',
  async (wrong) => {
    let release = () => {},
      arrived = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const entry = new Promise<void>((resolve) => {
      arrived = resolve;
    });
    await peer(wrong, held, arrived, async (client) => {
      const input = fresh(100),
        pending = client.invokeObserved(input, sources(input));
      void pending.catch(() => {});
      try {
        await enteredOrSettled(entry, pending);
        await delay(Math.max(0, input.deadline_at_ms - Date.now()) + 5);
        release();
        if (wrong) await expect(pending).rejects.toMatchObject({ code: 'invalid_response' });
        else expect((await pending).applicability).toBe('expired');
      } finally {
        release();
        await Promise.allSettled([pending]);
      }
    });
  },
);
test('request and source bytes are copied before the actual HTTP await', async () => {
  let release = () => {},
    arrived = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const entry = new Promise<void>((resolve) => {
    arrived = resolve;
  });
  await peer(false, held, arrived, async (client) => {
    const input: FixedPolicyRequest = structuredClone(fresh()),
      records = sources(input);
    const pending = client.invokeObserved(input, records);
    void pending.catch(() => {});
    try {
      await enteredOrSettled(entry, pending);
      Object.assign(input, { request_revision: 9 });
      records[0]!.body.fill(0);
      release();
      const observed = await pending;
      expect(observed.result.request_revision).toBe(1);
      expect(observed.applicability).toBe('candidate');
    } finally {
      release();
      await Promise.allSettled([pending]);
    }
  });
});
