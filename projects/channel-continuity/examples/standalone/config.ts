/** Closed trusted starter configuration. Importing this module performs no I/O. */
import {
  constants,
  closeSync,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
  realpathSync,
  writeSync,
  fsyncSync,
  linkSync,
  unlinkSync,
} from 'node:fs';
import { dirname, isAbsolute, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import type { AccountScope, ProviderScope } from '@livekit-ecosystem/channel-continuity';
import type { DatabaseSettings } from '@livekit-ecosystem/channel-continuity/postgres';
import type { CaseSnapshot } from '@livekit-ecosystem/channel-continuity/routing';

export const STARTER_CODES = Object.freeze([
  'InvalidConfiguration',
  'InvalidCommand',
  'UnsafeFile',
  'AccessDenied',
  'ApplicationBusy',
  'AssociationRequired',
  'AssociationRejected',
  'IdentityConflict',
  'Overloaded',
  'NotFound',
  'SchemaMismatch',
  'UpgradeRequired',
  'InvalidEvent',
  'DispatchClaimLost',
  'DispatchUnavailable',
  'OperationConflict',
  'RevisionConflict',
  'ClarificationRequired',
  'AcknowledgementUnknown',
  'OutcomeUnknown',
  'Unavailable',
  'CleanupIncomplete',
  'Closed',
] as const);
export type StarterCode = (typeof STARTER_CODES)[number];
const starterErrors = new WeakSet<object>();
export class StarterError extends Error {
  readonly code: StarterCode;
  constructor(code: StarterCode) {
    const safe = STARTER_CODES.includes(code) ? code : 'Unavailable';
    super(safe);
    this.name = 'StarterError';
    this.code = safe;
    Object.defineProperty(this, 'code', {
      value: safe,
      enumerable: true,
      writable: false,
      configurable: false,
    });
    starterErrors.add(this);
  }
}
export function safeStarterCode(error: unknown): StarterCode | undefined {
  if (!error || typeof error !== 'object' || !starterErrors.has(error)) return undefined;
  const d = Object.getOwnPropertyDescriptor(error, 'code');
  return d && 'value' in d && STARTER_CODES.includes(d.value as StarterCode)
    ? (d.value as StarterCode)
    : undefined;
}
export const STARTER_LIMITS = Object.freeze({
  maxBindings: 64,
  maxInbox: 64,
  externalReceipts: 16,
  privateBytes: 16384,
  commandBytes: 32768,
  outputBytes: 65536,
  summaryBytes: 2048,
  externalHeaderBytes: 4096,
  externalRequestBytes: 32768,
  externalResponseBytes: 4096,
  externalErrorBytes: 1024,
  externalHandlers: 4,
  externalSockets: 8,
  externalActive: 2,
  externalCallMs: 2000,
  externalFlushMs: 1000,
} as const);
export type StarterBinding = Readonly<{
  alias: string;
  providerScope: ProviderScope;
  accountScope: AccountScope;
  caseId: string;
  conversationId: string;
  senderId: string;
  initialCase: Readonly<Pick<CaseSnapshot, 'revision' | 'request'>>;
}>;
export type StarterConfig = Readonly<{
  schemaVersion: 1;
  profileId: string;
  postgres: Readonly<{ host: '127.0.0.1'; port: number; database: 'livekit_lab' }>;
  schemas: Readonly<{ inbox: string; case: string; external: string }>;
  bindings: readonly StarterBinding[];
  endpoints: Readonly<{ gateway: number; external: number }>;
  limits: Readonly<{ maxInbox: 64; externalReceipts: 16 }>;
}>;
export type StarterBearer = Readonly<{
  alias: string;
  operation: string;
  ordinary: string;
  idempotent: string;
}>;
export type OwnerCredentials = Readonly<{
  schemaVersion: 1;
  role: 'owner';
  profileId: string;
  postgresPassword: string;
}>;
export type RuntimeCredentials = Readonly<{
  schemaVersion: 1;
  role: 'runtime';
  profileId: string;
  postgresPassword: string;
  bindings: readonly Readonly<{
    alias: string;
    accountToken: string;
    publisherToken: string;
    recoveryToken: string;
  }>[];
  providerHmac: string;
  callbackHmac: string;
  externalBearers: readonly StarterBearer[];
}>;
export type ExternalCredentials = Readonly<{
  schemaVersion: 1;
  role: 'external';
  profileId: string;
  postgresPassword: string;
  bearers: readonly StarterBearer[];
}>;
export type StarterCredentials = OwnerCredentials | RuntimeCredentials | ExternalCredentials;
export function fields(value: unknown, keys: readonly string[]): Record<string, unknown> {
  try {
    if (
      !value ||
      typeof value !== 'object' ||
      Array.isArray(value) ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(value))
    )
      throw Error();
    const own = Reflect.ownKeys(value);
    if (own.length !== keys.length || own.some((k) => typeof k !== 'string' || !keys.includes(k)))
      throw Error();
    const out: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
    for (const k of keys) {
      const d = Object.getOwnPropertyDescriptor(value, k);
      if (!d || !('value' in d) || !d.enumerable) throw Error();
      out[k] = d.value;
    }
    return out;
  } catch {
    throw new StarterError('InvalidConfiguration');
  }
}
export function text(value: unknown, max = 128): string {
  if (
    typeof value !== 'string' ||
    !value.length ||
    Buffer.byteLength(value, 'utf8') > max ||
    value.trim() !== value ||
    /[\u0000-\u001f\u007f\ud800-\udfff]/u.test(value)
  )
    throw new StarterError('InvalidConfiguration');
  return value;
}
export function id(value: unknown): string {
  const v = text(value);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(v))
    throw new StarterError('InvalidConfiguration');
  return v;
}
export function uuid(value: unknown): string {
  const v = text(value, 36);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(v))
    throw new StarterError('InvalidConfiguration');
  return v;
}
export function digest(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}
export function token(value: unknown): string {
  const v = text(value);
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(v)) throw new StarterError('InvalidConfiguration');
  return v;
}
function hmac(value: unknown): string {
  const v = text(value, 43);
  if (
    !/^[A-Za-z0-9_-]{43}$/.test(v) ||
    Buffer.from(v, 'base64url').length !== 32 ||
    Buffer.from(v, 'base64url').toString('base64url') !== v
  )
    throw new StarterError('InvalidConfiguration');
  return v;
}
function port(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 1 || (value as number) > 65535)
    throw new StarterError('InvalidConfiguration');
  return value as number;
}
function list(value: unknown): readonly unknown[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > STARTER_LIMITS.maxBindings)
    throw new StarterError('InvalidConfiguration');
  const ds = Object.getOwnPropertyDescriptors(value);
  if (Reflect.ownKeys(value).length !== value.length + 1)
    throw new StarterError('InvalidConfiguration');
  const copy: unknown[] = [];
  for (let i = 0; i < value.length; i++) {
    const d = ds[String(i)];
    if (!d || !('value' in d) || !d.enumerable) throw new StarterError('InvalidConfiguration');
    copy.push(d.value);
  }
  return Object.freeze(copy);
}
function date(value: unknown): string {
  const v = text(value, 10);
  if (
    !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(v) ||
    !Number.isFinite(Date.parse(v + 'T00:00:00.000Z')) ||
    new Date(v + 'T00:00:00.000Z').toISOString().slice(0, 10) !== v
  )
    throw new StarterError('InvalidConfiguration');
  return v;
}
export function parseConfig(input: unknown): StarterConfig {
  const p = fields(input, [
    'schemaVersion',
    'profileId',
    'postgres',
    'schemas',
    'bindings',
    'endpoints',
    'limits',
  ]);
  const db = fields(p.postgres, ['host', 'port', 'database']);
  const schemas = fields(p.schemas, ['inbox', 'case', 'external']);
  const endpoints = fields(p.endpoints, ['gateway', 'external']);
  const limits = fields(p.limits, ['maxInbox', 'externalReceipts']);
  if (
    p.schemaVersion !== 1 ||
    db.host !== '127.0.0.1' ||
    db.database !== 'livekit_lab' ||
    limits.maxInbox !== 64 ||
    limits.externalReceipts !== 16
  )
    throw new StarterError('InvalidConfiguration');
  for (const k of ['inbox', 'case', 'external'] as const) {
    const prefix = k === 'external' ? 'demo' : k;
    if (
      typeof schemas[k] !== 'string' ||
      !new RegExp('^p2_' + prefix + '_[0-9a-f]{32}$').test(schemas[k] as string)
    )
      throw new StarterError('InvalidConfiguration');
  }
  const aliases = new Set<string>(),
    cases = new Set<string>(),
    senders = new Set<string>();
  let provider: string | undefined;
  const bindings = list(p.bindings).map((raw) => {
    const b = fields(raw, [
      'alias',
      'providerScope',
      'accountScope',
      'caseId',
      'conversationId',
      'senderId',
      'initialCase',
    ]);
    const ps = fields(b.providerScope, ['tenantId', 'provider', 'providerAccountId']);
    const as = fields(b.accountScope, ['tenantId', 'accountId']);
    const providerScope = Object.freeze({
      tenantId: id(ps.tenantId),
      provider: 'fake_sms',
      providerAccountId: id(ps.providerAccountId),
    });
    const accountScope = Object.freeze({ tenantId: id(as.tenantId), accountId: id(as.accountId) });
    if (ps.provider !== 'fake_sms' || providerScope.tenantId !== accountScope.tenantId)
      throw new StarterError('InvalidConfiguration');
    const a = id(b.alias),
      caseId = id(b.caseId),
      senderId = id(b.senderId);
    const scopeKey = JSON.stringify(accountScope); // This starter binds one case/conversation per account.
    const providerKey = JSON.stringify(providerScope);
    if (
      aliases.has(a) ||
      cases.has(scopeKey) ||
      senders.has(senderId) ||
      (provider && provider !== providerKey)
    )
      throw new StarterError('InvalidConfiguration');
    provider = providerKey;
    aliases.add(a);
    cases.add(scopeKey);
    senders.add(senderId);
    const initial = fields(b.initialCase, ['revision', 'request']);
    const request = fields(initial.request, [
      'schemaVersion',
      'kind',
      'bookingReference',
      'newCheckIn',
      'investigationConsent',
    ]);
    const bookingReference = text(request.bookingReference, 64);
    if (
      initial.revision !== '0' ||
      request.schemaVersion !== 1 ||
      request.kind !== 'booking_investigation' ||
      request.investigationConsent !== true ||
      !/^[A-Z0-9][A-Z0-9._:-]{0,63}$/.test(bookingReference)
    )
      throw new StarterError('InvalidConfiguration');
    const initialCase = Object.freeze({
      revision: '0' as const,
      request: Object.freeze({
        schemaVersion: 1,
        kind: 'booking_investigation',
        bookingReference,
        newCheckIn: date(request.newCheckIn),
        investigationConsent: true as const,
      }),
    });
    return Object.freeze({
      alias: a,
      providerScope,
      accountScope,
      caseId,
      conversationId: id(b.conversationId),
      senderId,
      initialCase,
    });
  });
  const gateway = port(endpoints.gateway),
    external = port(endpoints.external);
  if (gateway === external) throw new StarterError('InvalidConfiguration');
  return Object.freeze({
    schemaVersion: 1,
    profileId: uuid(p.profileId),
    postgres: Object.freeze({ host: '127.0.0.1', port: port(db.port), database: 'livekit_lab' }),
    schemas: Object.freeze({
      inbox: schemas.inbox as string,
      case: schemas.case as string,
      external: schemas.external as string,
    }),
    endpoints: Object.freeze({ gateway, external }),
    bindings: Object.freeze(bindings),
    limits: Object.freeze({ maxInbox: 64, externalReceipts: 16 }),
  });
}
function externalToken(value: unknown): string {
  const v = token(value);
  if (v.length !== 43) throw new StarterError('InvalidConfiguration');
  return v;
}
function bearerList(value: unknown, config: StarterConfig): readonly StarterBearer[] {
  const result = list(value).map((v) => {
    const p = fields(v, ['alias', 'operation', 'ordinary', 'idempotent']);
    return Object.freeze({
      alias: id(p.alias),
      operation: externalToken(p.operation),
      ordinary: externalToken(p.ordinary),
      idempotent: externalToken(p.idempotent),
    });
  });
  if (
    result.length !== config.bindings.length ||
    new Set(result.map((v) => v.alias)).size !== result.length ||
    result.some((v) => !config.bindings.some((b) => b.alias === v.alias))
  )
    throw new StarterError('InvalidConfiguration');
  return Object.freeze(result);
}
export function parseCredentials(input: unknown, configInput: StarterConfig): StarterCredentials {
  const config = parseConfig(configInput);
  if (!input || typeof input !== 'object' || Array.isArray(input))
    throw new StarterError('InvalidConfiguration');
  const descriptor = Object.getOwnPropertyDescriptor(input, 'role');
  if (!descriptor || !('value' in descriptor)) throw new StarterError('InvalidConfiguration');
  const role: unknown = descriptor.value;
  const keys =
    role === 'owner'
      ? ['schemaVersion', 'role', 'profileId', 'postgresPassword']
      : role === 'external'
        ? ['schemaVersion', 'role', 'profileId', 'postgresPassword', 'bearers']
        : [
            'schemaVersion',
            'role',
            'profileId',
            'postgresPassword',
            'bindings',
            'providerHmac',
            'callbackHmac',
            'externalBearers',
          ];
  const p = fields(input, keys);
  if (
    p.schemaVersion !== 1 ||
    p.profileId !== config.profileId ||
    (role !== 'owner' && role !== 'runtime' && role !== 'external')
  )
    throw new StarterError('InvalidConfiguration');
  const common = {
    schemaVersion: 1 as const,
    profileId: config.profileId,
    postgresPassword: token(p.postgresPassword),
  };
  if (role === 'owner') return Object.freeze({ ...common, role: 'owner' });
  if (role === 'external') {
    const bearers = bearerList(p.bearers, config);
    const all = bearers.flatMap((b) => [b.operation, b.ordinary, b.idempotent]);
    if (new Set(all).size !== all.length) throw new StarterError('InvalidConfiguration');
    return Object.freeze({ ...common, role: 'external', bearers });
  }
  const bindings = list(p.bindings).map((v) => {
    const b = fields(v, ['alias', 'accountToken', 'publisherToken', 'recoveryToken']);
    return Object.freeze({
      alias: id(b.alias),
      accountToken: token(b.accountToken),
      publisherToken: token(b.publisherToken),
      recoveryToken: token(b.recoveryToken),
    });
  });
  if (
    bindings.length !== config.bindings.length ||
    new Set(bindings.map((b) => b.alias)).size !== bindings.length ||
    bindings.some((b) => !config.bindings.some((c) => c.alias === b.alias))
  )
    throw new StarterError('InvalidConfiguration');
  const externalBearers = bearerList(p.externalBearers, config),
    providerHmac = hmac(p.providerHmac),
    callbackHmac = hmac(p.callbackHmac);
  const all = [
    ...bindings.flatMap((b) => [b.accountToken, b.publisherToken, b.recoveryToken]),
    ...externalBearers.flatMap((b) => [b.operation, b.ordinary, b.idempotent]),
    providerHmac,
    callbackHmac,
  ];
  if (new Set(all).size !== all.length) throw new StarterError('InvalidConfiguration');
  return Object.freeze({
    ...common,
    role: 'runtime',
    bindings: Object.freeze(bindings),
    providerHmac,
    callbackHmac,
    externalBearers,
  });
}
export function database(
  config: StarterConfig,
  credentials: StarterCredentials,
  area: keyof StarterConfig['schemas'],
): DatabaseSettings {
  return Object.freeze({
    ...config.postgres,
    user: credentials.role === 'owner' ? 'continuity_migrator' : 'livekit_lab',
    password: credentials.postgresPassword,
    schema: config.schemas[area],
  });
}
/** Strict bounded JSON: duplicate keys, invalid UTF8, deep nesting and nonfinite numbers fail closed. */
export function parseJson(raw: Uint8Array, maximum: number = STARTER_LIMITS.privateBytes): unknown {
  if (!raw.length || raw.length > maximum) throw new StarterError('InvalidConfiguration');
  let source: string;
  try {
    source = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw);
  } catch {
    throw new StarterError('InvalidConfiguration');
  }
  let at = 0,
    entries = 0;
  const ws = () => {
    while (/[\x20\t\r\n]/.test(source[at] ?? 'x')) at++;
  };
  const string = (): string => {
    const begin = at++;
    while (at < source.length) {
      const ch = source[at++];
      if (ch === '\\') {
        at++;
        continue;
      }
      if (ch === '"') {
        try {
          const v = JSON.parse(source.slice(begin, at)) as unknown;
          if (typeof v !== 'string' || /[\ud800-\udfff]/u.test(v)) throw Error();
          return v;
        } catch {
          throw new StarterError('InvalidConfiguration');
        }
      }
    }
    throw new StarterError('InvalidConfiguration');
  };
  const value = (depth: number): unknown => {
    ws();
    if (depth > 12 || ++entries > 2048) throw new StarterError('InvalidConfiguration');
    const ch = source[at];
    if (ch === '"') return string();
    if (ch === '{') {
      at++;
      ws();
      const out: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
      if (source[at] === '}') {
        at++;
        return out;
      }
      for (;;) {
        ws();
        if (source[at] !== '"') throw new StarterError('InvalidConfiguration');
        const key = string();
        ws();
        if (Object.hasOwn(out, key) || source[at++] !== ':')
          throw new StarterError('InvalidConfiguration');
        out[key] = value(depth + 1);
        ws();
        const next = source[at++];
        if (next === '}') return out;
        if (next !== ',') throw new StarterError('InvalidConfiguration');
      }
    }
    if (ch === '[') {
      at++;
      ws();
      const out: unknown[] = [];
      if (source[at] === ']') {
        at++;
        return out;
      }
      for (;;) {
        out.push(value(depth + 1));
        ws();
        const next = source[at++];
        if (next === ']') return out;
        if (next !== ',') throw new StarterError('InvalidConfiguration');
      }
    }
    for (const [literal, result] of [
      ['true', true],
      ['false', false],
      ['null', null],
    ] as const)
      if (source.slice(at, at + literal.length) === literal) {
        at += literal.length;
        return result;
      }
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(source.slice(at));
    if (!match) throw new StarterError('InvalidConfiguration');
    at += match[0].length;
    const n = Number(match[0]);
    if (!Number.isFinite(n) || (Number.isInteger(n) && !Number.isSafeInteger(n)))
      throw new StarterError('InvalidConfiguration');
    return n;
  };
  const result = value(0);
  ws();
  if (at !== source.length) throw new StarterError('InvalidConfiguration');
  return result;
}
function privatePath(path: string): string {
  if (!isAbsolute(path) || resolve(path) !== path) throw new StarterError('UnsafeFile');
  const parent = dirname(path),
    st = lstatSync(parent);
  if (
    !st.isDirectory() ||
    st.isSymbolicLink() ||
    st.uid !== process.getuid?.() ||
    (st.mode & 0o777) !== 0o700 ||
    realpathSync(parent) !== parent
  )
    throw new StarterError('UnsafeFile');
  return path;
}
export function readPrivateJson(
  path: string,
  maximum: number = STARTER_LIMITS.privateBytes,
): unknown {
  let fd: number | undefined;
  try {
    fd = openSync(privatePath(path), constants.O_RDONLY | constants.O_NOFOLLOW);
    const before = fstatSync(fd);
    if (
      !before.isFile() ||
      before.uid !== process.getuid?.() ||
      before.nlink !== 1 ||
      (before.mode & 0o777) !== 0o600 ||
      before.size < 1 ||
      before.size > maximum
    )
      throw new StarterError('UnsafeFile');
    const buf = Buffer.alloc(maximum + 1);
    let n = 0;
    while (n < buf.length) {
      const got = readSync(fd, buf, n, buf.length - n, null);
      if (!got) break;
      n += got;
    }
    const after = fstatSync(fd);
    if (
      n !== before.size ||
      after.size !== before.size ||
      after.mtimeMs !== before.mtimeMs ||
      n > maximum
    )
      throw new StarterError('UnsafeFile');
    return parseJson(buf.subarray(0, n), maximum);
  } catch (e) {
    if (e instanceof StarterError) throw e;
    throw new StarterError('UnsafeFile');
  } finally {
    if (fd !== undefined) closeSync(fd);
  }
}
export function writePrivateJson(
  path: string,
  value: unknown,
  maximum: number = STARTER_LIMITS.outputBytes,
): void {
  const data = Buffer.from(JSON.stringify(value) + '\n', 'utf8');
  if (data.length > maximum) throw new StarterError('InvalidCommand');
  const target = privatePath(path),
    pending = target + '.publishing';
  let fd: number | undefined, owned: Readonly<{ dev: number; ino: number }> | undefined;
  try {
    fd = openSync(
      pending,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
      0o600,
    );
    const st = fstatSync(fd);
    owned = { dev: st.dev, ino: st.ino };
    let n = 0;
    while (n < data.length) n += writeSync(fd, data, n, data.length - n);
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    // The target is published complete and exclusively. A reader may briefly observe
    // the exact same inode under two links; it must wait for this known transition.
    linkSync(pending, target);
    unlinkSync(pending);
    owned = undefined;
  } catch (e) {
    if (e instanceof StarterError) throw e;
    throw new StarterError('UnsafeFile');
  } finally {
    if (fd !== undefined) closeSync(fd);
    if (owned)
      try {
        const st = lstatSync(pending);
        if (st.dev === owned.dev && st.ino === owned.ino) unlinkSync(pending);
      } catch {
        /* retain unknown state */
      }
  }
}
/** Canonical data comparison retains array order and rejects executable properties. */
export function canonicalJson(value: unknown): string {
  const visit = (v: unknown, depth: number): unknown => {
    if (depth > 16) throw new StarterError('SchemaMismatch');
    if (v === null || typeof v === 'string' || typeof v === 'boolean') return v;
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (Array.isArray(v)) {
      const ds = Object.getOwnPropertyDescriptors(v),
        out: unknown[] = [];
      if (Reflect.ownKeys(v).length !== v.length + 1) throw new StarterError('SchemaMismatch');
      for (let i = 0; i < v.length; i++) {
        const d = ds[String(i)];
        if (!d || !('value' in d)) throw new StarterError('SchemaMismatch');
        out.push(visit(d.value, depth + 1));
      }
      return out;
    }
    if (!v || typeof v !== 'object' || ![Object.prototype, null].includes(Object.getPrototypeOf(v)))
      throw new StarterError('SchemaMismatch');
    const out: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
    const names = Reflect.ownKeys(v);
    if (names.some((k) => typeof k !== 'string')) throw new StarterError('SchemaMismatch');
    for (const k of (names as string[]).sort()) {
      const d = Object.getOwnPropertyDescriptor(v, k);
      if (!d || !('value' in d) || !d.enumerable) throw new StarterError('SchemaMismatch');
      out[k] = visit(d.value, depth + 1);
    }
    return out;
  };
  return JSON.stringify(visit(value, 0));
}

export function profileDigest(config: StarterConfig): string {
  return digest(
    JSON.stringify({
      profileId: config.profileId,
      postgres: config.postgres,
      schemas: config.schemas,
      bindings: config.bindings,
      limits: config.limits,
    }),
  );
}

/** One actual close pass and one bounded observation, shared across repeated callers. */
export class CloseObservation {
  #view: Promise<void> | undefined;
  #complete = false;
  get pending(): boolean {
    return this.#view !== undefined && !this.#complete;
  }
  observe(action: () => Promise<void>, timeoutMs = 2000): Promise<void> {
    if (this.#complete) return Promise.resolve();
    if (this.#view) return this.#view;
    let resolve!: () => void, reject!: (e: StarterError) => void;
    const view = new Promise<void>((ok, bad) => {
      resolve = ok;
      reject = bad;
    });
    this.#view = view;
    const timer = setTimeout(() => reject(new StarterError('CleanupIncomplete')), timeoutMs);
    // Reservation precedes action and thenable assimilation, including reentrant close.
    const actual = Promise.resolve().then(action);
    void actual.then(
      () => {
        clearTimeout(timer);
        this.#complete = true;
        resolve();
      },
      () => {
        clearTimeout(timer);
        if (this.#view === view) this.#view = undefined;
        reject(new StarterError('CleanupIncomplete'));
      },
    );
    void view.catch(() => undefined);
    return view;
  }
}
