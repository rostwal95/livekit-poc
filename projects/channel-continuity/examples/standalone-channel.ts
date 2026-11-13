#!/usr/bin/env node
/** Inert executable shim: all authority comes from explicit private configuration. */
import { randomUUID } from 'node:crypto';
import {
  createStandaloneOwner,
  createStandaloneApplication,
  ExternalHttpServer,
  STARTER_GROUPS,
  STARTER_MANIFEST_SHA256,
} from './standalone/application.js';
import {
  StarterError,
  safeStarterCode,
  STARTER_LIMITS,
  fields,
  parseConfig,
  parseCredentials,
  readPrivateJson,
  writePrivateJson,
  id,
  uuid,
  type StarterCode,
  type RuntimeCredentials,
  type ExternalCredentials,
} from './standalone/config.js';
import type { ReplyDraft } from '@livekit-ecosystem/channel-continuity/outbox';
import type { WebhookHeaders } from '@livekit-ecosystem/channel-continuity/security';
import type { StarterCarrier } from './standalone/application.js';
const COMMANDS = Object.freeze([
  'plan',
  'bootstrap',
  'challenge',
  'associate',
  'accept',
  'route',
  'serve',
  'external',
  'inspect',
  'history',
  'case',
  'processing',
  'dispatch',
  'reconcile-dispatch',
  'reply',
  'select-route',
  'send',
  'inspect-reply',
  'callback',
  'inspect-callbacks',
  'reconcile',
  'retry',
] as const);
type Command = (typeof COMMANDS)[number];
type Args = Readonly<{
  command: Command;
  config?: string;
  credentials?: string;
  input?: string;
  output?: string;
  ready?: string;
  failure?: string;
}>;
export function starterPlan() {
  return Object.freeze({
    schemaVersion: 1,
    command: 'plan',
    status: 'not_started',
    manifestSha256: STARTER_MANIFEST_SHA256,
    groups: STARTER_GROUPS,
    limits: STARTER_LIMITS,
    setupStarted: false,
    providersInvoked: false,
  });
}
export function parseArguments(argv: readonly string[]): Args {
  const command = argv[0];
  if (!COMMANDS.includes(command as Command)) throw new StarterError('InvalidCommand');
  if (command === 'plan') {
    if (argv.length !== 1) throw new StarterError('InvalidCommand');
    return Object.freeze({ command });
  }
  const p: Record<string, string> = {};
  for (let i = 1; i < argv.length; i += 2) {
    const key = argv[i],
      value = argv[i + 1];
    if (
      !key ||
      !['--config', '--credentials', '--input', '--output', '--ready', '--failure'].includes(key) ||
      typeof value !== 'string' ||
      !value.length ||
      Object.hasOwn(p, key)
    )
      throw new StarterError('InvalidCommand');
    p[key] = value;
  }
  if (
    !p['--config'] ||
    !p['--credentials'] ||
    ((command === 'serve' || command === 'external' || command === 'bootstrap') && p['--input']) ||
    (!(command === 'serve' || command === 'external' || command === 'bootstrap') &&
      !p['--input']) ||
    (command === 'challenge' && !p['--output']) ||
    (p['--ready'] && command !== 'serve' && command !== 'external')
  )
    throw new StarterError('InvalidCommand');
  return Object.freeze({
    command: command as Command,
    config: p['--config'],
    credentials: p['--credentials'],
    ...(p['--input'] ? { input: p['--input'] } : {}),
    ...(p['--output'] ? { output: p['--output'] } : {}),
    ...(p['--ready'] ? { ready: p['--ready'] } : {}),
    ...(p['--failure'] ? { failure: p['--failure'] } : {}),
  });
}
function wire(value: unknown): Readonly<{ raw: Buffer; headers: WebhookHeaders }> {
  const p = fields(value, ['raw', 'headers']),
    h = fields(p.headers, ['timestamp', 'signature']);
  if (
    typeof p.raw !== 'string' ||
    Buffer.byteLength(p.raw, 'utf8') > STARTER_LIMITS.commandBytes ||
    typeof h.timestamp !== 'string' ||
    typeof h.signature !== 'string'
  )
    throw new StarterError('InvalidCommand');
  return Object.freeze({
    raw: Buffer.from(p.raw, 'utf8'),
    headers: Object.freeze({ timestamp: h.timestamp, signature: h.signature }),
  });
}
function capability(value: unknown): StarterCarrier {
  if (value !== 'ordinary_fake_sms_v1' && value !== 'idempotent_fake_sms_v1')
    throw new StarterError('InvalidCommand');
  return value;
}
function summary(command: Command, value: unknown): Record<string, unknown> {
  const v = value as Record<string, unknown>;
  if (command === 'challenge') return { challengeId: v.challengeId, expiresAt: v.expiresAt };
  if (command === 'associate') return { associationVersion: v.associationVersion };
  if (command === 'accept') {
    const r = v.receipt as Record<string, unknown>;
    return {
      receiptId: r.receiptId,
      acceptanceSequence: r.acceptanceSequence,
      replayed: v.replayed,
    };
  }
  if (command === 'history')
    return {
      messageCount: (v.messages as unknown[]).length,
      ...(v.nextCursor ? { nextCursor: v.nextCursor } : {}),
    };
  if (command === 'inspect') {
    const r = v.receipt as Record<string, unknown>;
    return {
      receiptId: r.receiptId,
      operationKey: v.operationKey,
      processingState: v.processingState,
    };
  }
  if (command === 'processing')
    return {
      receiptId: v.receiptId,
      operationKey: v.operationKey,
      state: v.state,
      attempts: v.attempts,
      possibleExternal: v.possibleExternal,
      externalReceiptId: v.externalReceiptId,
    };
  if (command === 'case')
    return { revision: v.revision, cancelled: v.cancelled, committed: v.committed };
  if (command === 'route')
    return {
      status: v.status,
      receiptId: v.receiptId,
      operationKey: v.operationKey,
      ...(v.case ? { revision: (v.case as Record<string, unknown>).revision } : {}),
    };
  if (command === 'reply') return { outboundId: v.outboundId, receiptId: v.receiptId };
  if (command === 'callback')
    return { eventId: v.eventId, attemptId: v.attemptId, receiptId: v.receiptId };
  if (command === 'reconcile' || command === 'retry') {
    const r = v.receipt as Record<string, unknown>;
    return {
      commandId: r.commandId,
      receiptId: r.receiptId,
      decision: r.decision,
      code: r.code,
      observationKnown: v.observation !== null,
    };
  }
  if (command === 'inspect-reply')
    return { state: v.state, attemptCount: (v.attempts as unknown[]).length };
  if (command === 'inspect-callbacks') return { observed: true };
  return { ...v }; // Remaining commands are fixed bounded status/version/route DTOs, without bodies.
}
/** Exported only for controlled CLI tests; the public package factory is ./starter. */
export async function main(argv: readonly string[]): Promise<number> {
  let requestId: string | undefined;
  let args: Args | undefined;
  let resource: Readonly<{ close(): Promise<void> }> | undefined;
  let terminalMetrics: (() => unknown) | undefined;
  let result: unknown,
    failed = false,
    code: StarterCode | 'ok' = 'ok',
    cleanupComplete = true;
  let errorType: 'StarterError' | 'UnexpectedError' = 'UnexpectedError';
  type Stage =
    'arguments' | 'configuration' | 'bootstrap' | 'command' | 'startup' | 'running' | 'cleanup';
  let stage: Stage = 'arguments';
  let observedStage: Stage = stage;
  let stopping = false,
    resolveStop!: () => void;
  let stopClose: Promise<void> | undefined;
  const stopped = new Promise<void>((resolve) => {
    resolveStop = resolve;
  });
  const stop = () => {
    stopping = true;
    const owner = resource;
    if (owner && !stopClose) {
      stopClose = Promise.resolve().then(() => owner.close());
      void stopClose.catch(() => undefined);
    }
    resolveStop();
  };
  try {
    args = parseArguments(argv);
    if (args.command === 'plan') {
      process.stdout.write(JSON.stringify(starterPlan()) + '\n');
      return 0;
    }
    requestId = randomUUID();
    stage = 'configuration';
    const config = parseConfig(readPrivateJson(args.config!));
    const credentials = parseCredentials(readPrivateJson(args.credentials!), config);
    if (args.command === 'bootstrap') {
      stage = 'bootstrap';
      const owner = createStandaloneOwner(config, credentials);
      resource = owner;
      result = await owner.bootstrap();
    } else if (args.command === 'serve' || args.command === 'external') {
      process.once('SIGINT', stop);
      process.once('SIGTERM', stop);
      stage = 'startup';
      let endpoint: Readonly<{ host: '127.0.0.1'; port: number }>;
      if (args.command === 'serve') {
        const app = createStandaloneApplication(config, credentials);
        resource = app;
        terminalMetrics = () => ({ application: app.metrics(), gateway: app.gatewayMetrics() });
        endpoint = await app.startGateway();
      } else {
        if (credentials.role !== 'external') throw new StarterError('AccessDenied');
        const server = new ExternalHttpServer(config, credentials as ExternalCredentials);
        resource = server;
        terminalMetrics = () => ({ external: server.metrics() });
        endpoint = await server.start();
      }
      if (args.ready && !stopping)
        writePrivateJson(args.ready, {
          schemaVersion: 1,
          owner: config.profileId.replaceAll('-', ''),
          pid: process.pid,
          kind: args.command === 'serve' ? 'gateway' : 'external',
          profileId: config.profileId,
          ...endpoint,
        });
      stage = 'running';
      await stopped;
      result = { stopped: true, port: endpoint.port };
    } else {
      if (credentials.role !== 'runtime') throw new StarterError('AccessDenied');
      const app = createStandaloneApplication(config, credentials as RuntimeCredentials);
      resource = app;
      const input = readPrivateJson(args.input!, STARTER_LIMITS.commandBytes);
      stage = 'command';
      switch (args.command) {
        case 'challenge': {
          const p = fields(input, ['bindingAlias']);
          result = await app.challenge(id(p.bindingAlias));
          break;
        }
        case 'associate': {
          const w = wire(input);
          result = await app.associate(w.raw, w.headers);
          break;
        }
        case 'accept': {
          const w = wire(input);
          result = await app.accept(w.raw, w.headers);
          break;
        }
        case 'callback': {
          const w = wire(input);
          result = await app.callback(w.raw, w.headers);
          break;
        }
        case 'route': {
          const p = fields(input, ['bindingAlias', 'receiptId']);
          result = await app.route(id(p.bindingAlias), uuid(p.receiptId));
          break;
        }
        case 'case': {
          const p = fields(input, ['bindingAlias']);
          result = await app.currentCase(id(p.bindingAlias));
          break;
        }
        case 'processing': {
          const p = fields(input, ['bindingAlias', 'receiptId']);
          result = await app.processing(id(p.bindingAlias), uuid(p.receiptId));
          break;
        }
        case 'inspect': {
          const p = fields(input, ['bindingAlias', 'receiptId']);
          result = await app.inspect(id(p.bindingAlias), uuid(p.receiptId));
          break;
        }
        case 'history': {
          const p = fields(input, ['bindingAlias', 'after', 'limit']);
          result = await app.history(id(p.bindingAlias), {
            after: p.after as string,
            limit: p.limit as number,
          });
          break;
        }
        case 'dispatch':
        case 'reconcile-dispatch': {
          const p = fields(input, ['bindingAlias', 'receiptId']);
          result = await app.dispatch(
            id(p.bindingAlias),
            uuid(p.receiptId),
            args.command === 'reconcile-dispatch',
          );
          break;
        }
        case 'reply': {
          const p = fields(input, ['bindingAlias', 'draft']);
          result = await app.reply(id(p.bindingAlias), p.draft as ReplyDraft);
          break;
        }
        case 'select-route': {
          const p = fields(input, [
            'bindingAlias',
            'senderId',
            'associationVersion',
            'expectedRouteVersion',
          ]);
          result = await app.selectRoute(id(p.bindingAlias), {
            senderId: p.senderId as string,
            associationVersion: p.associationVersion as string,
            expectedRouteVersion: p.expectedRouteVersion as string,
          });
          break;
        }
        case 'send':
        case 'inspect-reply': {
          const p = fields(input, ['bindingAlias', 'outboundId', 'capability']);
          result =
            args.command === 'send'
              ? await app.send(id(p.bindingAlias), uuid(p.outboundId), capability(p.capability))
              : await app.inspectReply(
                  id(p.bindingAlias),
                  uuid(p.outboundId),
                  capability(p.capability),
                );
          break;
        }
        case 'inspect-callbacks': {
          const p = fields(input, ['bindingAlias', 'outboundId', 'attemptId']);
          result = await app.inspectCallbacks(
            id(p.bindingAlias),
            uuid(p.outboundId),
            uuid(p.attemptId),
          );
          break;
        }
        case 'reconcile': {
          const p = fields(input, [
            'bindingAlias',
            'capability',
            'commandId',
            'outboundId',
            'attemptId',
          ]);
          result = await app.reconcile(id(p.bindingAlias), capability(p.capability), {
            commandId: uuid(p.commandId),
            outboundId: uuid(p.outboundId),
            attemptId: uuid(p.attemptId),
          });
          break;
        }
        case 'retry': {
          const p = fields(input, [
            'bindingAlias',
            'capability',
            'commandId',
            'outboundId',
            'expectedAttemptId',
          ]);
          result = await app.retry(id(p.bindingAlias), capability(p.capability), {
            commandId: uuid(p.commandId),
            outboundId: uuid(p.outboundId),
            expectedAttemptId: uuid(p.expectedAttemptId),
          });
          break;
        }
      }
    }
  } catch (e) {
    failed = true;
    observedStage = stage;
    const own = safeStarterCode(e);
    errorType = own ? 'StarterError' : 'UnexpectedError';
    code = own ?? 'Unavailable';
  } finally {
    process.off('SIGINT', stop);
    process.off('SIGTERM', stop);
    if (resource)
      try {
        stage = 'cleanup';
        if (stopClose) await stopClose.catch(() => undefined);
        await resource.close();
      } catch {
        cleanupComplete = false;
        if (!failed) {
          failed = true;
          code = 'CleanupIncomplete';
          observedStage = stage;
        }
      }
  }
  if (terminalMetrics && result !== undefined)
    result = { ...(result as Record<string, unknown>), metrics: terminalMetrics() };
  if (args?.output && result !== undefined)
    try {
      writePrivateJson(args.output, result);
    } catch (e) {
      if (!failed) {
        failed = true;
        observedStage = 'cleanup';
        code = safeStarterCode(e) ?? 'Unavailable';
        errorType = safeStarterCode(e) ? 'StarterError' : 'UnexpectedError';
      }
    }
  requestId ??= randomUUID();
  if (failed && args?.failure)
    try {
      writePrivateJson(
        args.failure,
        {
          schemaVersion: 1,
          status: 'failed',
          mode: args.command,
          stage: observedStage,
          errorType,
          code,
          cleanupComplete,
        },
        2048,
      );
    } catch {
      /* preserve primary, never print body */
    }
  let status: 'known' | 'unknown' | 'rejected' | 'unavailable' = failed
    ? code === 'OutcomeUnknown' || code === 'AcknowledgementUnknown'
      ? 'unknown'
      : 'unavailable'
    : 'known';
  const v = result as Record<string, unknown> | undefined;
  if (
    !failed &&
    (v?.status === 'outcome_unknown' ||
      (args?.command === 'send' && v?.status === 'unknown') ||
      ((args?.command === 'dispatch' || args?.command === 'reconcile-dispatch') &&
        v?.status === 'uncertain'))
  ) {
    status = 'unknown';
    code = 'OutcomeUnknown';
  }
  if (!failed && v?.status === 'revision_conflict') {
    status = 'rejected';
    code = 'RevisionConflict';
  }
  const report = {
    schemaVersion: 1,
    command: args?.command ?? 'invalid',
    requestId,
    status,
    code,
    result: failed || !args ? null : summary(args.command, result),
    cleanupComplete,
  };
  const output = JSON.stringify(report);
  if (Buffer.byteLength(output) > STARTER_LIMITS.summaryBytes) {
    process.stdout.write(
      JSON.stringify({ ...report, status: 'unavailable', code: 'InvalidCommand', result: null }) +
        '\n',
    );
    return 1;
  }
  process.stdout.write(output + '\n');
  return status === 'known' && cleanupComplete ? 0 : 1;
}
if (import.meta.main) {
  void main(process.argv.slice(2)).then(
    (code) => {
      process.exitCode = code;
    },
    () => {
      process.stdout.write(
        '{"schemaVersion":1,"command":"invalid","status":"unavailable","code":"Unavailable","result":null,"cleanupComplete":false}\n',
      );
      process.exitCode = 1;
    },
  );
}
