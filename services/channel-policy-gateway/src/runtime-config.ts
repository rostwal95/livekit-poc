/** Closed non-secret owner configuration; runtime credentials remain separate. Imports are inert. */
import {
  constants,
  openSync,
  closeSync,
  fstatSync,
  lstatSync,
  readSync,
  realpathSync,
} from 'node:fs';
import { dirname, isAbsolute, resolve } from 'node:path';
import type { ProviderScope } from '@livekit-ecosystem/channel-continuity';
import type { GatewayApplicationRoute } from './application.js';
export class GatewayRuntimeError extends Error {
  readonly code: 'invalid_configuration' | 'unavailable' | 'closed' | 'cleanup_incomplete';
  constructor(code: GatewayRuntimeError['code'] = 'unavailable') {
    const safe =
      typeof code === 'string' &&
      ['invalid_configuration', 'unavailable', 'closed', 'cleanup_incomplete'].includes(code)
        ? code
        : 'unavailable';
    super(safe);
    this.name = 'GatewayRuntimeError';
    this.code = safe;
  }
}
export type LoopbackEndpoint = Readonly<{ host: '127.0.0.1'; port: number }>;
export type RuntimeConfiguration = Readonly<{
  schemaVersion: 1;
  profileInboxLimit: 16;
  route: GatewayApplicationRoute;
  postgres: Readonly<{
    host: '127.0.0.1';
    port: number;
    database: 'livekit_lab';
    user: 'livekit_lab';
    schema: string;
  }>;
  providers: Readonly<{ native: ProviderScope; sms: ProviderScope }>;
  simulationHmac: 'public_synthetic_v1';
  caseEndpoint: LoopbackEndpoint;
  originEndpoints: Readonly<{ native: LoopbackEndpoint; sms: LoopbackEndpoint }>;
  listen: Readonly<{ nativePort: number; smsPort: number; readPort: number; receiverPort: number }>;
}>;
export type RuntimeCredentials = Readonly<{
  postgresPassword: string;
  accountToken: string;
  nativePublisherToken: string;
  resultPublisherToken: string;
  workerBearer: string;
  nativeOriginBearer: string;
  smsOriginBearer: string;
  caseAuthorization: string;
}>;
export const RUNTIME_ENVIRONMENT_KEYS = Object.freeze([
  'P2_DEMO_POSTGRES_PASSWORD',
  'P2_DEMO_ACCOUNT_TOKEN',
  'P2_DEMO_NATIVE_PUBLISHER_TOKEN',
  'P2_DEMO_RESULT_PUBLISHER_TOKEN',
  'P2_DEMO_WORKER_BEARER',
  'P2_DEMO_NATIVE_ORIGIN_BEARER',
  'P2_DEMO_SMS_ORIGIN_BEARER',
  'P2_DEMO_CASE_AUTHORIZATION',
] as const);
const BASE = new Set(['PATH', 'LANG', 'CI', 'NO_COLOR', '__CF_USER_TEXT_ENCODING']);
const ID = /^[a-z][a-z0-9_-]{0,63}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export function runtimeFields(value: unknown, names: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw new GatewayRuntimeError('invalid_configuration');
  const keys = Reflect.ownKeys(value);
  if (keys.length !== names.length || keys.some((k) => typeof k !== 'string' || !names.includes(k)))
    throw new GatewayRuntimeError('invalid_configuration');
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const key of names) {
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !('value' in d) || !d.enumerable)
      throw new GatewayRuntimeError('invalid_configuration');
    result[key] = d.value;
  }
  return result;
}
export function runtimeString(value: unknown, pattern: RegExp): string {
  if (typeof value !== 'string' || pattern.exec(value)?.[0] !== value)
    throw new GatewayRuntimeError('invalid_configuration');
  return value;
}
export function runtimePort(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1 || value > 65535)
    throw new GatewayRuntimeError('invalid_configuration');
  return value;
}
export function runtimeEndpoint(value: unknown): LoopbackEndpoint {
  const e = runtimeFields(value, ['host', 'port']);
  if (e.host !== '127.0.0.1') throw new GatewayRuntimeError('invalid_configuration');
  return Object.freeze({ host: '127.0.0.1', port: runtimePort(e.port) });
}
function provider(value: unknown, kind: 'livekit' | 'fake_sms', tenant: string): ProviderScope {
  const p = runtimeFields(value, ['tenantId', 'provider', 'providerAccountId']);
  if (p.tenantId !== tenant || p.provider !== kind)
    throw new GatewayRuntimeError('invalid_configuration');
  return Object.freeze({
    tenantId: tenant,
    provider: kind,
    providerAccountId: runtimeString(p.providerAccountId, /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/),
  });
}
export function parseRuntimeConfiguration(value: unknown): RuntimeConfiguration {
  try {
    const p = runtimeFields(value, [
      'schemaVersion',
      'profileInboxLimit',
      'route',
      'postgres',
      'providers',
      'simulationHmac',
      'caseEndpoint',
      'originEndpoints',
      'listen',
    ]);
    if (
      p.schemaVersion !== 1 ||
      p.profileInboxLimit !== 16 ||
      p.simulationHmac !== 'public_synthetic_v1'
    )
      throw new GatewayRuntimeError('invalid_configuration');
    const r = runtimeFields(p.route, [
        'profileId',
        'receiverId',
        'scope',
        'caseId',
        'conversationId',
        'recipientId',
      ]),
      s = runtimeFields(r.scope, ['tenantId', 'accountId']);
    const scope = Object.freeze({
      tenantId: runtimeString(s.tenantId, ID),
      accountId: runtimeString(s.accountId, ID),
    });
    const route = Object.freeze({
      profileId: runtimeString(r.profileId, UUID),
      receiverId: runtimeString(r.receiverId, UUID),
      scope,
      caseId: runtimeString(r.caseId, ID),
      conversationId: runtimeString(r.conversationId, ID),
      recipientId: runtimeString(r.recipientId, ID),
    });
    const db = runtimeFields(p.postgres, ['host', 'port', 'database', 'user', 'schema']);
    if (db.host !== '127.0.0.1' || db.database !== 'livekit_lab' || db.user !== 'livekit_lab')
      throw new GatewayRuntimeError('invalid_configuration');
    const postgres = Object.freeze({
      host: '127.0.0.1' as const,
      port: runtimePort(db.port),
      database: 'livekit_lab' as const,
      user: 'livekit_lab' as const,
      schema: runtimeString(db.schema, /^[a-z][a-z0-9_]{0,62}$/),
    });
    const providers = runtimeFields(p.providers, ['native', 'sms']),
      origins = runtimeFields(p.originEndpoints, ['native', 'sms']),
      l = runtimeFields(p.listen, ['nativePort', 'smsPort', 'readPort', 'receiverPort']);
    const caseEndpoint = runtimeEndpoint(p.caseEndpoint),
      originEndpoints = Object.freeze({
        native: runtimeEndpoint(origins.native),
        sms: runtimeEndpoint(origins.sms),
      });
    const listen = Object.freeze({
      nativePort: runtimePort(l.nativePort),
      smsPort: runtimePort(l.smsPort),
      readPort: runtimePort(l.readPort),
      receiverPort: runtimePort(l.receiverPort),
    });
    const ports = [
      caseEndpoint.port,
      originEndpoints.native.port,
      originEndpoints.sms.port,
      ...Object.values(listen),
    ];
    if (new Set(ports).size !== 7) throw new GatewayRuntimeError('invalid_configuration');
    return Object.freeze({
      schemaVersion: 1,
      profileInboxLimit: 16,
      route,
      postgres,
      providers: Object.freeze({
        native: provider(providers.native, 'livekit', scope.tenantId),
        sms: provider(providers.sms, 'fake_sms', scope.tenantId),
      }),
      simulationHmac: 'public_synthetic_v1',
      caseEndpoint,
      originEndpoints,
      listen,
    });
  } catch {
    throw new GatewayRuntimeError('invalid_configuration');
  }
}
export function parseRuntimeEnvironment(input: unknown): RuntimeCredentials {
  try {
    if (!input || typeof input !== 'object' || Array.isArray(input))
      throw new GatewayRuntimeError('invalid_configuration');
    const keys = Reflect.ownKeys(input),
      allowed = new Set<string>([...BASE, ...RUNTIME_ENVIRONMENT_KEYS]);
    if (
      keys.some((k) => typeof k !== 'string' || !allowed.has(k)) ||
      RUNTIME_ENVIRONMENT_KEYS.some((k) => !keys.includes(k))
    )
      throw new GatewayRuntimeError('invalid_configuration');
    // process.env has an exotic prototype. Own data only, after rejecting unknown keys.
    const copy: Record<string, string> = Object.create(null) as Record<string, string>;
    for (const key of keys) {
      const d = Object.getOwnPropertyDescriptor(input, key);
      if (!d || !('value' in d) || !d.enumerable || typeof d.value !== 'string')
        throw new GatewayRuntimeError('invalid_configuration');
      copy[key as string] = d.value;
    }
    const token = (k: string) => runtimeString(copy[k], /^[A-Za-z0-9_-]{43}$/);
    const postgresPassword = runtimeString(
      copy.P2_DEMO_POSTGRES_PASSWORD,
      /^[^\x00-\x20\x7f]{32,128}$/,
    );
    if (Buffer.from(postgresPassword, 'utf8').toString('utf8') !== postgresPassword)
      throw new GatewayRuntimeError('invalid_configuration');
    const accountToken = token('P2_DEMO_ACCOUNT_TOKEN'),
      nativePublisherToken = token('P2_DEMO_NATIVE_PUBLISHER_TOKEN'),
      resultPublisherToken = token('P2_DEMO_RESULT_PUBLISHER_TOKEN'),
      workerBearer = token('P2_DEMO_WORKER_BEARER'),
      nativeOriginBearer = token('P2_DEMO_NATIVE_ORIGIN_BEARER'),
      smsOriginBearer = token('P2_DEMO_SMS_ORIGIN_BEARER');
    const caseAuthorization = runtimeString(
      copy.P2_DEMO_CASE_AUTHORIZATION,
      /^Bearer [A-Za-z0-9_-]{43}$/,
    );
    if (
      new Set([
        accountToken,
        nativePublisherToken,
        resultPublisherToken,
        workerBearer,
        nativeOriginBearer,
        smsOriginBearer,
        caseAuthorization.slice(7),
      ]).size !== 7
    )
      throw new GatewayRuntimeError('invalid_configuration');
    return Object.freeze({
      postgresPassword,
      accountToken,
      nativePublisherToken,
      resultPublisherToken,
      workerBearer,
      nativeOriginBearer,
      smsOriginBearer,
      caseAuthorization,
    });
  } catch {
    throw new GatewayRuntimeError('invalid_configuration');
  }
}
export function parseRuntimeConfigurationBytes(raw: Buffer): RuntimeConfiguration {
  try {
    if (!Buffer.isBuffer(raw) || !raw.length || raw.length > 8192)
      throw new GatewayRuntimeError('invalid_configuration');
    const text = new TextDecoder('utf8', { fatal: true, ignoreBOM: true }).decode(raw),
      value: unknown = JSON.parse(text);
    if (text !== JSON.stringify(value) + '\n')
      throw new GatewayRuntimeError('invalid_configuration');
    return parseRuntimeConfiguration(value);
  } catch {
    throw new GatewayRuntimeError('invalid_configuration');
  }
}
export function readRuntimeConfiguration(path: string): RuntimeConfiguration {
  let fd: number | undefined;
  try {
    if (typeof path !== 'string' || !isAbsolute(path) || resolve(path) !== path)
      throw new GatewayRuntimeError('invalid_configuration');
    const parent = dirname(path),
      folder = lstatSync(parent);
    if (
      !folder.isDirectory() ||
      folder.isSymbolicLink() ||
      folder.uid !== process.getuid?.() ||
      (folder.mode & 0o777) !== 0o700 ||
      realpathSync(parent) !== parent
    )
      throw new GatewayRuntimeError('invalid_configuration');
    fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    const before = fstatSync(fd);
    if (
      !before.isFile() ||
      before.uid !== process.getuid?.() ||
      before.nlink !== 1 ||
      (before.mode & 0o777) !== 0o600 ||
      before.size < 1 ||
      before.size > 8192
    )
      throw new GatewayRuntimeError('invalid_configuration');
    const raw = Buffer.alloc(before.size + 1);
    let n = 0;
    while (n < raw.length) {
      const got = readSync(fd, raw, n, raw.length - n, null);
      if (!got) break;
      n += got;
    }
    const after = fstatSync(fd);
    if (
      n !== before.size ||
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.size !== after.size ||
      before.mtimeMs !== after.mtimeMs ||
      after.nlink !== 1 ||
      after.uid !== process.getuid?.() ||
      (after.mode & 0o777) !== 0o600
    )
      throw new GatewayRuntimeError('invalid_configuration');
    return parseRuntimeConfigurationBytes(raw.subarray(0, n));
  } catch {
    throw new GatewayRuntimeError('invalid_configuration');
  } finally {
    if (fd !== undefined) {
      try {
        closeSync(fd);
      } catch {
        throw new GatewayRuntimeError('invalid_configuration');
      }
    }
  }
}
/** Deliberately public synthetic simulation material, never a real provider credential. */
export function publicSimulationHmacKey(): Buffer {
  return Buffer.alloc(32, 0x4f);
}

/** Validate an already parsed programmatic credential DTO without invoking accessors. */
export function parseRuntimeCredentials(value: unknown): RuntimeCredentials {
  try {
    const c = runtimeFields(value, [
      'postgresPassword',
      'accountToken',
      'nativePublisherToken',
      'resultPublisherToken',
      'workerBearer',
      'nativeOriginBearer',
      'smsOriginBearer',
      'caseAuthorization',
    ]);
    return parseRuntimeEnvironment({
      P2_DEMO_POSTGRES_PASSWORD: c.postgresPassword,
      P2_DEMO_ACCOUNT_TOKEN: c.accountToken,
      P2_DEMO_NATIVE_PUBLISHER_TOKEN: c.nativePublisherToken,
      P2_DEMO_RESULT_PUBLISHER_TOKEN: c.resultPublisherToken,
      P2_DEMO_WORKER_BEARER: c.workerBearer,
      P2_DEMO_NATIVE_ORIGIN_BEARER: c.nativeOriginBearer,
      P2_DEMO_SMS_ORIGIN_BEARER: c.smsOriginBearer,
      P2_DEMO_CASE_AUTHORIZATION: c.caseAuthorization,
    });
  } catch {
    throw new GatewayRuntimeError('invalid_configuration');
  }
}
