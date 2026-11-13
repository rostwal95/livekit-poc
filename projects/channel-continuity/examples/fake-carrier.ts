/** Standalone local fixture. Imports only declared public package entry points. */
import {
  ChannelInbox,
  SeededAccounts,
  ChannelError,
  type DatabaseSettings,
  type DurableReceipt,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  createFakeSmsIntegration,
  signFakeSms,
  WebhookError,
} from '@livekit-ecosystem/channel-continuity/security';
import {
  createStandaloneExample,
  StandaloneError,
  type StandaloneBinding,
  type StandalonePorts,
  type StandalonePreview,
} from '@livekit-ecosystem/channel-continuity/standalone';

const SCOPE = Object.freeze({
  tenantId: 'tenant-a',
  provider: 'fake_sms',
  providerAccountId: 'carrier-a',
});
const ACCOUNT_TOKEN = 'synthetic-account-a-' + 'a'.repeat(40);
const KEY = Buffer.alloc(32, 0x61); // Public synthetic fixture, never a real provider key.
const BINDING: StandaloneBinding = Object.freeze({
  providerScope: SCOPE,
  accountScope: Object.freeze({ tenantId: 'tenant-a', accountId: 'account-a' }),
  conversationId: 'conversation-a',
  caseId: 'case-a',
});
type ExampleReport = Readonly<{
  schema_version: 1;
  mode: 'standalone_input_preview';
  status: 'passed' | 'failed';
  code: string;
  acceptance: 'observed' | 'unknown' | 'not_observed';
  receipt?: DurableReceipt;
  replayed?: boolean;
  operationKey?: string;
  processingState?: 'pending';
  execution?: 'not_executed';
  cleanup_complete: boolean;
}>;
function connection(): DatabaseSettings {
  if (process.argv.length !== 2 || Object.hasOwn(process.env, 'P2_MIGRATION_PASSWORD'))
    throw new Error('MissingExampleSetup');
  const password = process.env.P2_RUNTIME_PASSWORD,
    schema = process.env.P2_DEMO_SCHEMA;
  const port = Number(process.env.P2_POSTGRES_PORT);
  if (
    typeof password !== 'string' ||
    password.length < 32 ||
    password.length > 128 ||
    typeof schema !== 'string' ||
    !/^p2_inbox_[a-f0-9]{32}(?![\s\S])/.test(schema) ||
    !Number.isSafeInteger(port) ||
    port < 1 ||
    port > 65535
  )
    throw new Error('MissingExampleSetup');
  return {
    host: '127.0.0.1',
    port,
    database: 'livekit_lab',
    user: 'livekit_lab',
    password,
    schema,
  };
}
function adapters(inbox: ChannelInbox): StandalonePorts {
  return {
    inbox,
    cases: {
      async inspect(reference, signal) {
        if (signal.aborted) throw new StandaloneError('PreviewUnavailable');
        return { ...reference, revision: '1', source: 'synthetic_read_only' };
      },
    },
    agent: {
      async preview(input, signal) {
        if (signal.aborted) throw new StandaloneError('PreviewUnavailable');
        return {
          kind: 'investigation',
          source: 'scripted',
          caseRevision: input.currentCase.revision,
        };
      },
    },
    operations: {
      async inspectPending(input, signal) {
        if (signal.aborted) throw new StandaloneError('PreviewUnavailable');
        return { operationKey: input.operationKey, state: 'not_executed', durable: false };
      },
    },
  };
}
async function main(): Promise<void> {
  let inbox: ChannelInbox | undefined;
  let example: ReturnType<typeof createStandaloneExample> | undefined;
  let acceptance: Readonly<{ receipt: DurableReceipt; replayed: boolean }> | undefined;
  let preview: StandalonePreview | undefined;
  let failure: string | undefined;
  let cleanup = true;
  try {
    inbox = new ChannelInbox(
      connection(),
      createFakeSmsIntegration(SCOPE, KEY),
      new SeededAccounts([
        {
          token: ACCOUNT_TOKEN,
          tenantId: 'tenant-a',
          accountId: 'account-a',
          conversationId: 'conversation-a',
          caseId: 'case-a',
        },
      ]),
      {},
      () => undefined,
    );
    example = createStandaloneExample(adapters(inbox), BINDING);
    const frame = signFakeSms(
      {
        schemaVersion: 1,
        eventId: 'example-owned-event',
        messageId: 'example-owned-message',
        senderId: 'example-owned-sender',
        body: 'Inspect the synthetic request',
        occurredAt: '2030-01-01T00:00:00.000Z',
      },
      KEY,
      Math.floor(Date.now() / 1000),
      SCOPE,
    );
    // Return/retain acceptance before any separate preview adapter runs.
    acceptance = await example.accept(frame.raw, frame.headers);
    preview = await example.preview(ACCOUNT_TOKEN, acceptance.receipt.receiptId);
  } catch (error) {
    failure =
      error instanceof ChannelError ||
      error instanceof StandaloneError ||
      error instanceof WebhookError
        ? error.code
        : 'MissingExampleSetup';
  } finally {
    try {
      await example?.close();
    } catch {
      cleanup = false;
    }
    try {
      await inbox?.close();
    } catch {
      cleanup = false;
    }
  }
  const report: ExampleReport = {
    schema_version: 1,
    mode: 'standalone_input_preview',
    status: !failure && cleanup ? 'passed' : 'failed',
    code: cleanup ? (failure ?? 'ok') : 'CleanupIncomplete',
    acceptance: acceptance
      ? 'observed'
      : failure === 'AcknowledgementUnknown'
        ? 'unknown'
        : 'not_observed',
    ...(acceptance ? { receipt: acceptance.receipt, replayed: acceptance.replayed } : {}),
    ...(preview
      ? {
          operationKey: preview.operationKey,
          processingState: preview.processingState,
          execution: preview.execution,
        }
      : {}),
    cleanup_complete: cleanup,
  };
  process.stdout.write(JSON.stringify(report) + '\n');
  process.exitCode = report.status === 'passed' ? 0 : 1;
}
void main().catch(() => {
  process.stdout.write(
    '{"status":"failed","code":"ExampleFailed","mode":"standalone_input_preview"}\n',
  );
  process.exitCode = 1;
});
