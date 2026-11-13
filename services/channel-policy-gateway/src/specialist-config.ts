/** Closed immutable evidence configuration. No files, environment or network are read on import. */
import { createHash } from 'node:crypto';
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
import { EvidenceRegistry, type EvidenceRecord } from '@livekit-ecosystem/delegation-specialist';
export type SpecialistRuntimeCode =
  'invalid_configuration' | 'unavailable' | 'closed' | 'cleanup_incomplete';
const CODES: readonly string[] = [
  'invalid_configuration',
  'unavailable',
  'closed',
  'cleanup_incomplete',
];
export class SpecialistRuntimeError extends Error {
  readonly code: SpecialistRuntimeCode;
  constructor(code: SpecialistRuntimeCode = 'unavailable') {
    const safe = typeof code === 'string' && CODES.includes(code) ? code : 'unavailable';
    super(safe);
    this.name = 'SpecialistRuntimeError';
    this.code = safe;
  }
}
export function specialistFailureCode(error: unknown): SpecialistRuntimeCode {
  try {
    if (error instanceof SpecialistRuntimeError) {
      const d = Object.getOwnPropertyDescriptor(error, 'code');
      if (d && 'value' in d && typeof d.value === 'string' && CODES.includes(d.value))
        return d.value as SpecialistRuntimeCode;
    }
  } catch {
    /* malformed errors never reveal dependency state */
  }
  return 'unavailable';
}
export type SpecialistEvidence = Readonly<{
  reference: Readonly<{
    source_id: string;
    version: string;
    sha256: string;
    media_type: 'application/json';
    byte_length: number;
    width: null;
    height: null;
  }>;
  bodyBase64: string;
}>;
export type SpecialistConfiguration = Readonly<{
  schemaVersion: 1;
  label: 'scripted';
  scope: Readonly<{ tenantId: string; accountId: string }>;
  port: number;
  evidence: readonly SpecialistEvidence[];
}>;
export type SpecialistCredentials = Readonly<{ bearer: string }>;
export const SPECIALIST_ENVIRONMENT_KEYS = Object.freeze(['P3_DEMO_SPECIALIST_BEARER'] as const);
export const SPECIALIST_CONFIGURATION_BYTES = 262144;
const BASE = new Set(['PATH', 'LANG', 'CI', 'NO_COLOR', '__CF_USER_TEXT_ENCODING']);
function fields(value: unknown, names: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw new SpecialistRuntimeError('invalid_configuration');
  const keys = Reflect.ownKeys(value);
  if (keys.length !== names.length || keys.some((k) => typeof k !== 'string' || !names.includes(k)))
    throw new SpecialistRuntimeError('invalid_configuration');
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const key of names) {
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !('value' in d) || !d.enumerable)
      throw new SpecialistRuntimeError('invalid_configuration');
    result[key] = d.value;
  }
  return result;
}
function text(value: unknown, pattern: RegExp): string {
  if (typeof value !== 'string' || pattern.exec(value)?.[0] !== value)
    throw new SpecialistRuntimeError('invalid_configuration');
  return value;
}
export function parseSpecialistConfiguration(value: unknown): SpecialistConfiguration {
  try {
    const c = fields(value, ['schemaVersion', 'label', 'scope', 'port', 'evidence']),
      s = fields(c.scope, ['tenantId', 'accountId']);
    if (
      c.schemaVersion !== 1 ||
      c.label !== 'scripted' ||
      typeof c.port !== 'number' ||
      !Number.isSafeInteger(c.port) ||
      c.port < 1 ||
      c.port > 65535
    )
      throw new SpecialistRuntimeError('invalid_configuration');
    const scope = Object.freeze({
      tenantId: text(s.tenantId, /^[a-z][a-z0-9_-]{0,63}$/),
      accountId: text(s.accountId, /^[a-z][a-z0-9_-]{0,63}$/),
    });
    if (
      !Array.isArray(c.evidence) ||
      Object.getPrototypeOf(c.evidence) !== Array.prototype ||
      c.evidence.length < 1 ||
      c.evidence.length > 32 ||
      Reflect.ownKeys(c.evidence).length !== c.evidence.length + 1
    )
      throw new SpecialistRuntimeError('invalid_configuration');
    const evidence: SpecialistEvidence[] = [],
      records: EvidenceRecord[] = [];
    let total = 0;
    for (let i = 0; i < c.evidence.length; i++) {
      const d = Object.getOwnPropertyDescriptor(c.evidence, String(i));
      if (!d || !('value' in d) || !d.enumerable)
        throw new SpecialistRuntimeError('invalid_configuration');
      const e = fields(d.value, ['reference', 'bodyBase64']),
        r = fields(e.reference, [
          'source_id',
          'version',
          'sha256',
          'media_type',
          'byte_length',
          'width',
          'height',
        ]);
      if (
        r.media_type !== 'application/json' ||
        r.width !== null ||
        r.height !== null ||
        typeof r.byte_length !== 'number' ||
        !Number.isSafeInteger(r.byte_length) ||
        r.byte_length < 1 ||
        r.byte_length > 4096 ||
        typeof e.bodyBase64 !== 'string' ||
        e.bodyBase64.length < 4 ||
        e.bodyBase64.length > 5464
      )
        throw new SpecialistRuntimeError('invalid_configuration');
      const body = Buffer.from(e.bodyBase64, 'base64');
      if (
        body.toString('base64') !== e.bodyBase64 ||
        body.byteLength !== r.byte_length ||
        createHash('sha256').update(body).digest('hex') !== r.sha256
      )
        throw new SpecialistRuntimeError('invalid_configuration');
      total += body.byteLength;
      if (total > 131072) throw new SpecialistRuntimeError('invalid_configuration');
      const reference = Object.freeze({
        source_id: text(r.source_id, /^[a-z][a-z0-9_-]{0,63}$/),
        version: text(r.version, /^[a-z][a-z0-9_-]{0,63}$/),
        sha256: text(r.sha256, /^[0-9a-f]{64}$/),
        media_type: 'application/json' as const,
        byte_length: r.byte_length,
        width: null,
        height: null,
      });
      evidence.push(Object.freeze({ reference, bodyBase64: e.bodyBase64 }));
      records.push({
        scope: { tenant_id: scope.tenantId, account_id: scope.accountId },
        reference,
        body,
      });
    }
    // The real public registry independently enforces exact scoped identities and evidence bytes.
    new EvidenceRegistry(records);
    return Object.freeze({
      schemaVersion: 1,
      label: 'scripted',
      scope,
      port: c.port,
      evidence: Object.freeze(evidence),
    });
  } catch {
    throw new SpecialistRuntimeError('invalid_configuration');
  }
}
export function parseSpecialistCredentials(value: unknown): SpecialistCredentials {
  try {
    const c = fields(value, ['bearer']);
    return Object.freeze({ bearer: text(c.bearer, /^[A-Za-z0-9_-]{43}$/) });
  } catch {
    throw new SpecialistRuntimeError('invalid_configuration');
  }
}
export function parseSpecialistEnvironment(input: unknown): SpecialistCredentials {
  try {
    if (!input || typeof input !== 'object' || Array.isArray(input))
      throw new SpecialistRuntimeError('invalid_configuration');
    const keys = Reflect.ownKeys(input),
      allowed = new Set<string>([...BASE, ...SPECIALIST_ENVIRONMENT_KEYS]);
    if (
      keys.some((key) => typeof key !== 'string' || !allowed.has(key)) ||
      !keys.includes('P3_DEMO_SPECIALIST_BEARER')
    )
      throw new SpecialistRuntimeError('invalid_configuration');
    const copy: Record<string, string> = Object.create(null) as Record<string, string>;
    for (const key of keys) {
      const d = Object.getOwnPropertyDescriptor(input, key);
      if (!d || !('value' in d) || !d.enumerable || typeof d.value !== 'string')
        throw new SpecialistRuntimeError('invalid_configuration');
      copy[key as string] = d.value;
    }
    return parseSpecialistCredentials({ bearer: copy.P3_DEMO_SPECIALIST_BEARER });
  } catch {
    throw new SpecialistRuntimeError('invalid_configuration');
  }
}
export function parseSpecialistConfigurationBytes(raw: Buffer): SpecialistConfiguration {
  try {
    if (!Buffer.isBuffer(raw) || raw.length < 1 || raw.length > SPECIALIST_CONFIGURATION_BYTES)
      throw new SpecialistRuntimeError('invalid_configuration');
    const valueText = new TextDecoder('utf8', { fatal: true, ignoreBOM: true }).decode(raw),
      value: unknown = JSON.parse(valueText);
    if (valueText !== JSON.stringify(value) + '\n')
      throw new SpecialistRuntimeError('invalid_configuration');
    return parseSpecialistConfiguration(value);
  } catch {
    throw new SpecialistRuntimeError('invalid_configuration');
  }
}
export function readSpecialistConfiguration(path: string): SpecialistConfiguration {
  let fd: number | undefined;
  try {
    if (typeof path !== 'string' || !isAbsolute(path) || resolve(path) !== path)
      throw new SpecialistRuntimeError('invalid_configuration');
    const parent = dirname(path),
      folder = lstatSync(parent);
    if (
      !folder.isDirectory() ||
      folder.isSymbolicLink() ||
      folder.uid !== process.getuid?.() ||
      (folder.mode & 0o777) !== 0o700 ||
      realpathSync(parent) !== parent
    )
      throw new SpecialistRuntimeError('invalid_configuration');
    fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    const before = fstatSync(fd);
    if (
      !before.isFile() ||
      before.uid !== process.getuid?.() ||
      before.nlink !== 1 ||
      (before.mode & 0o777) !== 0o600 ||
      before.size < 1 ||
      before.size > SPECIALIST_CONFIGURATION_BYTES
    )
      throw new SpecialistRuntimeError('invalid_configuration');
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
      before.ctimeMs !== after.ctimeMs ||
      after.nlink !== 1 ||
      after.uid !== process.getuid?.() ||
      (after.mode & 0o777) !== 0o600
    )
      throw new SpecialistRuntimeError('invalid_configuration');
    return parseSpecialistConfigurationBytes(raw.subarray(0, n));
  } catch {
    throw new SpecialistRuntimeError('invalid_configuration');
  } finally {
    if (fd !== undefined) {
      try {
        closeSync(fd);
      } catch {
        throw new SpecialistRuntimeError('invalid_configuration');
      }
    }
  }
}
