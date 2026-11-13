/** New communication query parsing fails safely before any PostgreSQL connection. */
import { afterEach, expect, test } from 'vitest';
import {
  CommunicationInbox,
  CommunicationGateway,
  createCommunicationIntegration,
} from '../src/communication.js';
import { createNativeIntegration } from '../src/native.js';
import { SeededAccounts, ChannelError } from '../src/postgres.js';
const scope = { tenantId: 'communication-query', accountId: 'account' },
  reference = { scope, caseId: 'case', conversationId: 'conversation' };
const native = createNativeIntegration(
  { tenantId: scope.tenantId, provider: 'livekit', providerAccountId: 'local' },
  [{ ...reference, token: 'N'.repeat(43) }],
);
const integration = createCommunicationIntegration(native, [
  {
    ...reference,
    publisherToken: 'P'.repeat(43),
    sdkToken: 'S'.repeat(43),
    browserToken: 'B'.repeat(43),
  },
]);
const accounts = new SeededAccounts([
  { ...scope, caseId: 'case', conversationId: 'conversation', token: 'A'.repeat(43) },
]);
const owned: CommunicationInbox[] = [];
afterEach(async () => {
  await Promise.all(owned.splice(0).map((i) => i.close()));
});
const invalid = [
  null,
  undefined,
  7,
  [],
  { limit: 1, unknown: true },
  Object.create({ limit: 1 }),
  Object.defineProperty({}, 'limit', {
    get() {
      throw new Error('must not read getter');
    },
    enumerable: true,
  }),
  new Proxy(
    {},
    {
      ownKeys() {
        throw new Error('sentinel');
      },
    },
  ),
];
for (const [n, value] of invalid.entries())
  test(`fixed query rejection ${n}`, () => {
    const inbox = new CommunicationInbox(
      {
        host: '127.0.0.1',
        port: 1,
        database: 'livekit_lab',
        user: 'livekit_lab',
        password: 'x'.repeat(43),
        schema: 'p2_inbox_' + 'a'.repeat(32),
      },
      integration,
      accounts,
    );
    owned.push(inbox);
    for (const call of [
      () => inbox.responses('A'.repeat(43), value as { limit: number }),
      () =>
        inbox.observations(
          'A'.repeat(43),
          '11111111-1111-4111-8111-111111111111',
          value as { limit: number },
        ),
    ]) {
      try {
        call();
        throw new Error('unexpected success');
      } catch (error) {
        expect(error).toBeInstanceOf(ChannelError);
        expect((error as ChannelError).code).toBe('InvalidEvent');
      }
    }
  });
for (const [n, value] of [
  null,
  undefined,
  new Proxy(
    {},
    {
      ownKeys() {
        throw new Error('sentinel');
      },
    },
  ),
].entries())
  test(`fixed gateway options rejection ${n}`, () => {
    expect(() => new CommunicationGateway(value as never)).toThrow(ChannelError);
    try {
      new CommunicationGateway(value as never);
    } catch (error) {
      expect((error as ChannelError).code).toBe('InvalidEvent');
    }
  });
