/** Separate installed-public-P1 controls. No service, file or client is opened on import. */
import { createHash } from 'node:crypto';
import {
  constants,
  closeSync,
  fstatSync,
  fsyncSync,
  linkSync,
  lstatSync,
  openSync,
  readSync,
  unlinkSync,
  writeSync,
} from 'node:fs';
import { dirname, join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import {
  CaseAuthorityHttpClient,
  RoutingError,
  type CaseReference,
  type InvestigationRequest,
} from '@livekit-ecosystem/channel-continuity/routing';
import {
  ConfirmationHttpClient,
  ConfirmationError,
  type ExactConfirmation,
} from '@livekit-ecosystem/channel-continuity/confirmation';
import {
  CurrentCaseHttpClient,
  RehydrationError,
  type CurrentCaseReference,
  type CurrentCase,
} from '@livekit-ecosystem/channel-continuity/rehydration';
import {
  readPrivateJson,
  StarterError,
  type StarterCode,
} from '@livekit-ecosystem/channel-continuity/starter';

export const P1_CONTRACT_STAGES = [
  'zero-read',
  'zero-release',
  'known-revise',
  'known-response',
  'unknown-entry',
  'unknown-outcome',
  'unknown-readback',
  'stale-reject',
] as const;
export type P1ContractStage = (typeof P1_CONTRACT_STAGES)[number];
type Phase = 'revision' | 'stale-confirmation' | 'exact-confirmation' | 'current-facts';
type Endpoint = Readonly<{ host: '127.0.0.1'; port: number }>;
type Metrics = Readonly<Record<string, number>>;
export type P1ContractProof = Readonly<{
  schemaVersion: 1;
  mode: 'p1-contract';
  phase: Phase;
  owner: string;
  groups: readonly string[];
  facts: Readonly<Record<string, unknown>>;
  metrics: Readonly<{ case: Metrics; confirmation: Metrics; currentCase: Metrics }>;
  cleanupComplete: true;
}>;
const phases = ['revision', 'stale-confirmation', 'exact-confirmation', 'current-facts'] as const;
const groups = [
  'installed_public_case_identity_scope_read',
  'public_revision_CAS_conflict_unknown_ACK',
  'exact_quote_confirmation_stale_rejection',
  'currentCase_allowlist_excludes_quote_control',
  'revision_zero_read_only_no_dispatch_claim',
  'public_supplier_effect_sources_no_extra_acceptance',
] as const;
function requireFact(value: unknown): asserts value {
  if (!value) throw new StarterError('Unavailable');
}
function object(value: unknown, keys: readonly string[]): Record<string, unknown> {
  requireFact(value !== null && typeof value === 'object' && !Array.isArray(value));
  const names = Reflect.ownKeys(value as object);
  requireFact(
    names.length === keys.length && names.every((k) => typeof k === 'string' && keys.includes(k)),
  );
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const key of keys) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    requireFact(descriptor && 'value' in descriptor && descriptor.enumerable);
    result[key] = descriptor.value;
  }
  return result;
}
function same(a: unknown, b: unknown): void {
  requireFact(isDeepStrictEqual(a, b, { skipPrototype: true }));
}
function uuid(value: unknown): string {
  requireFact(
    typeof value === 'string' &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value),
  );
  return value;
}
function endpoint(value: unknown): Endpoint {
  const e = object(value, ['host', 'port']);
  requireFact(
    e.host === '127.0.0.1' &&
      typeof e.port === 'number' &&
      Number.isInteger(e.port) &&
      e.port > 0 &&
      e.port <= 65535,
  );
  return { host: '127.0.0.1', port: e.port };
}
function token(value: unknown): string {
  requireFact(typeof value === 'string' && /^[A-Za-z0-9_-]{43}$/.test(value));
  return value;
}
function request(value: unknown, day: string): InvestigationRequest {
  const expected = {
    schemaVersion: 1,
    kind: 'booking_investigation',
    bookingReference: 'DEMO-BK-001',
    newCheckIn: '2030-12-' + day,
    investigationConsent: true,
  } as const;
  same(value, expected);
  return expected;
}
function safeCode(error: unknown): StarterCode {
  try {
    if (
      error instanceof RoutingError ||
      error instanceof ConfirmationError ||
      error instanceof RehydrationError ||
      error instanceof StarterError
    ) {
      const d = Object.getOwnPropertyDescriptor(error, 'code');
      if (d && 'value' in d && typeof d.value === 'string') {
        if (d.value === 'access_denied') return 'AccessDenied';
        if (d.value === 'overloaded') return 'Overloaded';
        if (
          [
            'AccessDenied',
            'InvalidCommand',
            'OutcomeUnknown',
            'RevisionConflict',
            'CleanupIncomplete',
            'Closed',
            'Overloaded',
          ].includes(d.value)
        )
          return d.value as StarterCode;
      }
    }
  } catch {
    /* Never observe a getter/message/stack to choose a diagnostic. */
  }
  return 'Unavailable';
}
function observe<T>(promise: Promise<T>) {
  return promise.then(
    (value) => ({ status: 'fulfilled' as const, value }),
    (error) => ({ status: 'rejected' as const, code: safeCode(error) }),
  );
}
function privateDirectory(path: string): void {
  const info = lstatSync(path);
  requireFact(
    info.isDirectory() &&
      info.uid === process.getuid?.() &&
      (info.mode & 0o777) === 0o700 &&
      !info.isSymbolicLink(),
  );
}
function publishMarker(directory: string, name: string): void {
  privateDirectory(directory);
  requireFact(/^[a-z][a-z0-9_]{0,63}$/.test(name));
  const path = join(directory, name + '.reached'),
    pending = path + '.' + process.pid + '.pending';
  let owned = false,
    fd: number | undefined;
  try {
    fd = openSync(
      pending,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
      0o600,
    );
    owned = true;
    const bytes = Buffer.from(process.pid + '\n');
    let written = 0;
    while (written < bytes.length) written += writeSync(fd, bytes, written, bytes.length - written);
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    linkSync(pending, path);
  } finally {
    if (fd !== undefined) closeSync(fd);
    if (owned) unlinkSync(pending);
  }
}
function marker(directory: string, name: string, pid: number): boolean {
  const path = join(directory, name);
  let info;
  try {
    info = lstatSync(path);
  } catch (error) {
    if (
      error &&
      typeof error === 'object' &&
      Object.getOwnPropertyDescriptor(error, 'code')?.value === 'ENOENT'
    )
      return false;
    throw new StarterError('Unavailable');
  }
  requireFact(
    info.isFile() &&
      !info.isSymbolicLink() &&
      info.uid === process.getuid?.() &&
      (info.mode & 0o777) === 0o600 &&
      [1, 2].includes(info.nlink),
  );
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const opened = fstatSync(fd);
    requireFact(opened.dev === info.dev && opened.ino === info.ino && opened.size <= 33);
    const bytes = Buffer.alloc(34),
      length = readSync(fd, bytes, 0, bytes.length, null);
    const after = fstatSync(fd);
    requireFact(after.dev === opened.dev && after.ino === opened.ino && after.size === opened.size);
    same(bytes.subarray(0, length).toString('ascii'), pid + '\n');
    return true;
  } finally {
    closeSync(fd);
  }
}
function delay(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    let timer: ReturnType<typeof setTimeout>;
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    timer = setTimeout(finish, 10);
    signal.addEventListener('abort', finish, { once: true });
    if (signal.aborted) finish();
  });
}
async function waitUntil(
  predicate: () => boolean,
  signal: AbortSignal,
  maximumMs = 10000,
): Promise<void> {
  const deadline = performance.now() + maximumMs;
  while (!predicate()) {
    requireFact(!signal.aborted && performance.now() < deadline);
    await delay(signal);
  }
}
async function waitIdle(client: { metrics(): Metrics }, signal: AbortSignal): Promise<void> {
  await waitUntil(() => client.metrics().active === 0, signal, 2000);
}

async function expectCode<T>(work: Promise<T>, code: StarterCode): Promise<void> {
  const result = await observe(work);
  requireFact(result.status === 'rejected' && result.code === code);
}
function current(
  value: CurrentCase,
  ref: CurrentCaseReference,
  taskId: string,
  original: InvestigationRequest,
): void {
  same(
    Object.keys(value).sort(),
    [
      'schemaVersion',
      'source',
      'scope',
      'caseId',
      'conversationId',
      'revision',
      'request',
      'workflow',
      'intent',
      'mutation',
      'supplierResult',
      'sourceRevision',
    ].sort(),
  );
  same(value.scope, ref.scope);
  same(value.caseId, ref.caseId);
  same(value.conversationId, ref.conversationId);
  requireFact(value.source === 'p1_public_v4' && value.workflow?.taskId === taskId);
  same(value.request, original);
  requireFact(/^[a-f0-9]{64}$/.test(value.sourceRevision));
}
function metrics(value: Metrics): Metrics {
  same(
    Object.keys(value).sort(),
    ['started', 'known', 'rejected', 'unknown', 'failed', 'active'].sort(),
  );
  requireFact(
    Object.values(value).every((v) => Number.isSafeInteger(v) && v >= 0) && value.active === 0,
  );
  return { ...value };
}

export async function runP1Contract(
  configPath: string,
  credentialsPath: string,
  onStage?: (stage: P1ContractStage) => void,
): Promise<P1ContractProof> {
  const config = object(readPrivateJson(configPath), [
    'schemaVersion',
    'mode',
    'phase',
    'owner',
    'scope',
    'caseId',
    'conversationId',
    'endpoints',
    'fixtures',
  ]);
  requireFact(
    config.schemaVersion === 1 &&
      config.mode === 'p1-contract' &&
      typeof config.phase === 'string' &&
      phases.includes(config.phase as Phase),
  );
  const phase = config.phase as Phase,
    slot = phase === 'revision' ? 'revision' : phase === 'stale-confirmation' ? 'stale' : 'exact';
  requireFact(typeof config.owner === 'string' && /^[a-f0-9]{32}$/.test(config.owner));
  const owner = config.owner;
  const scope = { tenantId: 'tenant_starter_p1', accountId: 'account_starter_' + slot };
  same(config.scope, scope);
  same(config.caseId, 'case_starter_' + owner + '_' + slot);
  same(config.conversationId, 'conversation_starter_' + owner + '_' + slot);
  const ref: CaseReference = { scope, caseId: config.caseId as string },
    fullRef: CurrentCaseReference = { ...ref, conversationId: config.conversationId as string };
  const foreign: CaseReference = {
    ...ref,
    scope: { ...scope, accountId: scope.accountId + '_foreign' },
  };
  const endpoints = object(config.endpoints, ['case', 'confirmation', 'currentCase']);
  const e = {
    case: endpoint(endpoints.case),
    confirmation: endpoint(endpoints.confirmation),
    currentCase: endpoint(endpoints.currentCase),
  };
  const credentials = object(readPrivateJson(credentialsPath), [
    'schemaVersion',
    'role',
    'caseToken',
    'confirmationToken',
    'currentCaseToken',
  ]);
  requireFact(credentials.schemaVersion === 1 && credentials.role === 'p1-contract');
  const tokens = [
    token(credentials.caseToken),
    token(credentials.confirmationToken),
    token(credentials.currentCaseToken),
  ];
  requireFact(new Set(tokens).size === 3);
  const keys =
    phase === 'revision'
      ? [
          'originalRequest',
          'knownRequest',
          'unknownReplyRequest',
          'expectedTaskId',
          'authorityCaseId',
        ]
      : phase === 'stale-confirmation'
        ? ['originalRequest', 'revisedRequest', 'expectedTaskId', 'authorityCaseId', 'confirmation']
        : phase === 'exact-confirmation'
          ? ['originalRequest', 'expectedTaskId', 'authorityCaseId', 'confirmation']
          : ['originalRequest', 'expectedTaskId', 'authorityCaseId', 'expectedSupplier'];
  const fixture = object(config.fixtures, keys),
    taskId = uuid(fixture.expectedTaskId),
    authorityCaseId = uuid(fixture.authorityCaseId);
  requireFact(taskId !== authorityCaseId);
  const original = request(
    fixture.originalRequest,
    slot === 'revision' ? '02' : slot === 'stale' ? '03' : '04',
  );
  const directory = dirname(configPath);
  privateDirectory(directory);
  const ready = object(readPrivateJson(join(directory, 'p1-endpoints.json')), [
    'schemaVersion',
    'owner',
    'pid',
    'endpoints',
  ]);
  requireFact(
    ready.schemaVersion === 1 &&
      ready.owner === owner &&
      typeof ready.pid === 'number' &&
      Number.isSafeInteger(ready.pid) &&
      ready.pid > 1,
  );
  same(ready.endpoints, e);
  const options = { timeoutMs: 5000, cleanupMs: 2000, maxActive: 1 };
  const resources: { close(): Promise<void> }[] = [];
  let cases: CaseAuthorityHttpClient | undefined,
    confirmations: ConfirmationHttpClient | undefined,
    reads: CurrentCaseHttpClient | undefined;
  let primary: StarterCode | undefined,
    closed = false;
  let facts: Record<string, unknown> = {},
    passed: readonly string[] = [];
  try {
    cases = new CaseAuthorityHttpClient(e.case, 'Bearer ' + tokens[0]!, [ref, foreign], options);
    resources.push(cases);
    confirmations = new ConfirmationHttpClient(
      e.confirmation,
      'Bearer ' + tokens[1]!,
      [ref],
      options,
    );
    resources.push(confirmations);
    reads = new CurrentCaseHttpClient(
      e.currentCase,
      'Bearer ' + tokens[2]!,
      [fullRef, { ...fullRef, scope: foreign.scope }],
      options,
    );
    resources.push(reads);
    const signal = () => new AbortController().signal;
    if (phase === 'revision') {
      onStage?.('zero-read');
      const initial = await cases.inspect(ref, signal());
      same(initial.revision, '0');
      same(initial.request, original);
      const zero = await reads.inspect(fullRef, signal());
      current(zero, fullRef, taskId, original);
      same(zero.revision, '0');
      same(zero.intent, { state: 'not_committed', intentId: null });
      requireFact(zero.mutation.state === 'not_observed' && zero.supplierResult === null);
      await waitIdle(cases, signal());
      await expectCode(cases.inspect(foreign, signal()), 'AccessDenied');
      publishMarker(directory, 'p1_zero_read_done');
      onStage?.('zero-release');
      await waitUntil(() => marker(directory, 'p1_zero_read_done.released', process.pid), signal());
      onStage?.('known-revise');
      const firstRequest = request(fixture.knownRequest, '03'),
        nextRequest = request(fixture.unknownReplyRequest, '04');
      await waitIdle(cases, signal());
      const first = await cases.revise(
        { ...ref, expectedRevision: '0', request: firstRequest },
        signal(),
      );
      onStage?.('known-response');
      same(first.revision, '1');
      same(first.request, firstRequest);
      onStage?.('unknown-entry');
      await waitIdle(cases, signal());
      const controller = new AbortController(),
        entryControl = new AbortController();
      const caller = observe(
        cases.revise({ ...ref, expectedRevision: '1', request: nextRequest }, controller.signal),
      );
      const entry = observe(
        waitUntil(
          () => marker(directory, 'p1_revision_committed.reached', ready.pid as number),
          entryControl.signal,
          4000,
        ),
      );
      try {
        const won = await Promise.race([
          entry.then((result) => ({ kind: 'entry' as const, result })),
          caller.then((result) => ({ kind: 'caller' as const, result })),
        ]);
        requireFact(won.kind === 'entry' && won.result.status === 'fulfilled');
        onStage?.('unknown-outcome');
        controller.abort();
        const outcome = await caller;
        requireFact(outcome.status === 'rejected' && outcome.code === 'OutcomeUnknown');
        publishMarker(directory, 'p1_revision_unknown');
        await waitUntil(() => cases!.metrics().active === 0, signal(), 2000);
      } finally {
        entryControl.abort();
        controller.abort();
        await entry;
        await caller;
      }
      onStage?.('unknown-readback');
      await waitIdle(cases, signal());
      const after = await cases.inspect(ref, signal());
      same(after.revision, '2');
      same(after.request, nextRequest);
      onStage?.('stale-reject');
      await waitIdle(cases, signal());
      await expectCode(
        cases.revise({ ...ref, expectedRevision: '1', request: original }, signal()),
        'RevisionConflict',
      );
      facts = {
        initialCase: initial,
        zeroCurrentCase: zero,
        knownRevision: first,
        unknownOutcome: 'OutcomeUnknown',
        afterUnknownCase: after,
        staleOutcome: 'RevisionConflict',
        foreignOutcome: 'AccessDenied',
      };
      passed = [groups[0]!, groups[1]!, groups[4]!];
    } else if (phase === 'stale-confirmation' || phase === 'exact-confirmation') {
      const before = await cases.inspect(ref, signal());
      same(before.revision, '0');
      same(before.request, original);
      const command = object(fixture.confirmation, [
        'scope',
        'caseId',
        'commandId',
        'expectedRevision',
        'quoteId',
        'quoteDigest',
        'quoteJson',
        'explicit',
      ]);
      same(command.scope, scope);
      same(command.caseId, ref.caseId);
      same(command.expectedRevision, '0');
      requireFact(command.explicit === true);
      uuid(command.commandId);
      requireFact(
        typeof command.quoteJson === 'string' &&
          Buffer.byteLength(command.quoteJson) <= 4096 &&
          createHash('sha256').update(command.quoteJson).digest('hex') === command.quoteDigest,
      );
      const quote = JSON.parse(command.quoteJson) as Record<string, unknown>;
      requireFact(
        quote.schema_version === 2 &&
          quote.task_id === taskId &&
          quote.case_id === authorityCaseId &&
          quote.revision === 0 &&
          quote.quote_id === command.quoteId &&
          quote.new_check_in === original.newCheckIn &&
          quote.booking_reference === original.bookingReference,
      );
      const exact = command as unknown as ExactConfirmation;
      if (phase === 'stale-confirmation') {
        const changed = request(fixture.revisedRequest, '04');
        await waitIdle(cases, signal());
        const revised = await cases.revise(
          { ...ref, expectedRevision: '0', request: changed },
          signal(),
        );
        same(revised.revision, '1');
        await expectCode(confirmations.confirm(exact, signal()), 'RevisionConflict');
        facts = { beforeCase: before, afterRevision: revised, staleOutcome: 'RevisionConflict' };
      } else {
        const receipt = await confirmations.confirm(exact, signal());
        await waitIdle(confirmations, signal());
        const replay = await confirmations.confirm(exact, signal());
        same(receipt, replay);
        requireFact(
          receipt.commandId === exact.commandId &&
            receipt.quoteDigest === exact.quoteDigest &&
            receipt.quoteId === exact.quoteId,
        );
        facts = {
          beforeCase: before,
          confirmationReceipt: receipt,
          replayedConfirmationReceipt: replay,
        };
        passed = [groups[2]!];
      }
    } else {
      const expected = object(fixture.expectedSupplier, [
        'bookingReference',
        'newCheckIn',
        'revision',
      ]);
      same(expected, { bookingReference: 'DEMO-BK-001', newCheckIn: '2030-12-04', revision: '1' });
      const value = await reads.inspect(fullRef, signal());
      await waitIdle(reads, signal());
      const replay = await reads.inspect(fullRef, signal());
      current(value, fullRef, taskId, original);
      same(value, replay);
      same(value.revision, '0');
      requireFact(
        value.intent.state === 'committed' &&
          value.intent.intentId !== null &&
          value.mutation.state === 'succeeded' &&
          value.mutation.outcome === 'succeeded' &&
          value.mutation.effectId !== null &&
          value.mutation.outcomeEventId !== null &&
          value.supplierResult !== null,
      );
      same(value.supplierResult.bookingReference, expected.bookingReference);
      same(value.supplierResult.newCheckIn, expected.newCheckIn);
      same(value.supplierResult.revision, expected.revision);
      await waitIdle(reads, signal());
      await expectCode(
        reads.inspect({ ...fullRef, scope: foreign.scope }, signal()),
        'AccessDenied',
      );
      facts = { currentCase: value, replayedCurrentCase: replay, foreignOutcome: 'AccessDenied' };
      passed = [groups[3]!, groups[5]!];
    }
  } catch (error) {
    primary = safeCode(error);
  } finally {
    const outcomes = await Promise.allSettled(
      resources.map((resource) => Promise.resolve().then(() => resource.close())),
    );
    closed = outcomes.every((result) => result.status === 'fulfilled');
  }
  if (primary || !closed || !cases || !confirmations || !reads) {
    const failure = new StarterError(primary ?? 'CleanupIncomplete');
    Object.defineProperty(failure, 'cleanupComplete', {
      value: closed,
      writable: false,
      configurable: false,
      enumerable: true,
    });
    throw failure;
  }
  return {
    schemaVersion: 1,
    mode: 'p1-contract',
    phase,
    owner,
    groups: passed,
    facts,
    metrics: {
      case: metrics(cases.metrics()),
      confirmation: metrics(confirmations.metrics()),
      currentCase: metrics(reads.metrics()),
    },
    cleanupComplete: true,
  };
}
