/** Closed internal room control; none of these credentials or selectors is a browser DTO. */
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
import { currentCase } from '@livekit-ecosystem/channel-continuity/rehydration';
import {
  encodeResultIntent,
  parseResultIntent,
  resultReceipt,
  matchResultReceipt,
  type P1ResultIntent,
  type ResultNativeView,
} from '@livekit-ecosystem/channel-continuity/result-receiver';
import type {
  NativeBindingReceipt,
  NativePublication,
} from '@livekit-ecosystem/channel-continuity/native';
export type NativeRoomCode =
  | 'invalid_input'
  | 'unauthorized'
  | 'conflict'
  | 'capacity'
  | 'unavailable'
  | 'outcome_unknown'
  | 'closed'
  | 'cleanup_incomplete'
  | 'recovery_required';
const CODES: readonly string[] = [
  'invalid_input',
  'unauthorized',
  'conflict',
  'capacity',
  'unavailable',
  'outcome_unknown',
  'closed',
  'cleanup_incomplete',
  'recovery_required',
];
export class NativeRoomError extends Error {
  readonly code: NativeRoomCode;
  constructor(code: NativeRoomCode = 'unavailable') {
    const safe = typeof code === 'string' && CODES.includes(code) ? code : 'unavailable';
    super(safe);
    this.name = 'NativeRoomError';
    this.code = safe;
  }
}
export function roomFailure(
  error: unknown,
  fallback: NativeRoomCode = 'unavailable',
): NativeRoomError {
  try {
    if (error instanceof NativeRoomError) {
      const d = Object.getOwnPropertyDescriptor(error, 'code');
      if (d && 'value' in d && typeof d.value === 'string' && CODES.includes(d.value))
        return new NativeRoomError(d.value as NativeRoomCode);
    }
  } catch {
    /* finite boundary */
  }
  return new NativeRoomError(fallback);
}
export function roomFields(value: unknown, names: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw new NativeRoomError('invalid_input');
  const keys = Reflect.ownKeys(value);
  if (keys.length !== names.length || keys.some((k) => typeof k !== 'string' || !names.includes(k)))
    throw new NativeRoomError('invalid_input');
  const out: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const key of names) {
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !('value' in d) || !d.enumerable) throw new NativeRoomError('invalid_input');
    out[key] = d.value;
  }
  return out;
}
export function roomText(value: unknown, pattern: RegExp): string {
  if (typeof value !== 'string' || pattern.exec(value)?.[0] !== value)
    throw new NativeRoomError('invalid_input');
  return value;
}
export const ROOM_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export const ROOM_TOKEN = /^[A-Za-z0-9_-]{43}$/;
export function roomTimestamp(value: unknown): string {
  const v = roomText(value, /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$/);
  if (!Number.isFinite(Date.parse(v)) || new Date(v).toISOString() !== v)
    throw new NativeRoomError('invalid_input');
  return v;
}
export function roomGeneration(value: unknown): string {
  const v = roomText(value, /^(0|[1-9][0-9]{0,6})$/);
  if (BigInt(v) > 1000000n) throw new NativeRoomError('invalid_input');
  return v;
}
export function roomJson(raw: Buffer, maximum = 1024, newline = false): unknown {
  try {
    if (!Buffer.isBuffer(raw) || raw.length < 1 || raw.length > maximum)
      throw new NativeRoomError('invalid_input');
    const text = new TextDecoder('utf8', { fatal: true, ignoreBOM: true }).decode(raw),
      v: unknown = JSON.parse(text);
    if (text !== JSON.stringify(v) + (newline ? '\n' : ''))
      throw new NativeRoomError('invalid_input');
    return v;
  } catch {
    throw new NativeRoomError('invalid_input');
  }
}
export type RoomControlConfiguration = Readonly<{
  schemaVersion: 1;
  port: number;
  recoverBindingId: string | null;
}>;
export function parseRoomControlConfiguration(value: unknown): RoomControlConfiguration {
  try {
    const v = roomFields(value, ['schemaVersion', 'port', 'recoverBindingId']);
    if (
      v.schemaVersion !== 1 ||
      typeof v.port !== 'number' ||
      !Number.isSafeInteger(v.port) ||
      v.port < 1 ||
      v.port > 65535
    )
      throw new NativeRoomError('invalid_input');
    return Object.freeze({
      schemaVersion: 1,
      port: v.port,
      recoverBindingId:
        v.recoverBindingId === null ? null : roomText(v.recoverBindingId, ROOM_UUID),
    });
  } catch {
    throw new NativeRoomError('invalid_input');
  }
}
export function readRoomControlConfiguration(path: string): RoomControlConfiguration {
  let fd: number | undefined;
  try {
    if (typeof path !== 'string' || !isAbsolute(path) || resolve(path) !== path)
      throw new NativeRoomError('invalid_input');
    const parent = dirname(path),
      folder = lstatSync(parent);
    if (
      !folder.isDirectory() ||
      folder.isSymbolicLink() ||
      folder.uid !== process.getuid?.() ||
      (folder.mode & 0o777) !== 0o700 ||
      realpathSync(parent) !== parent
    )
      throw new NativeRoomError('invalid_input');
    fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    const first = fstatSync(fd);
    if (
      !first.isFile() ||
      first.uid !== process.getuid?.() ||
      first.nlink !== 1 ||
      (first.mode & 0o777) !== 0o600 ||
      first.size < 1 ||
      first.size > 1024
    )
      throw new NativeRoomError('invalid_input');
    const raw = Buffer.alloc(first.size + 1);
    let n = 0;
    while (n < raw.length) {
      const got = readSync(fd, raw, n, raw.length - n, null);
      if (!got) break;
      n += got;
    }
    const last = fstatSync(fd);
    if (
      n !== first.size ||
      first.dev !== last.dev ||
      first.ino !== last.ino ||
      first.size !== last.size ||
      first.mtimeMs !== last.mtimeMs ||
      first.ctimeMs !== last.ctimeMs ||
      last.nlink !== 1 ||
      last.uid !== process.getuid?.() ||
      (last.mode & 0o777) !== 0o600
    )
      throw new NativeRoomError('invalid_input');
    return parseRoomControlConfiguration(roomJson(raw.subarray(0, n), 1024, true));
  } catch {
    throw new NativeRoomError('invalid_input');
  } finally {
    if (fd !== undefined) {
      try {
        closeSync(fd);
      } catch {
        throw new NativeRoomError('invalid_input');
      }
    }
  }
}
export type NativeRoomRoute = Readonly<{
  profileId: string;
  receiverId: string;
  scope: Readonly<{ tenantId: string; accountId: string }>;
  caseId: string;
  conversationId: string;
  recipientId: string;
}>;
export function parseNativeRoomRoute(value: unknown): NativeRoomRoute {
  const v = roomFields(value, [
      'profileId',
      'receiverId',
      'scope',
      'caseId',
      'conversationId',
      'recipientId',
    ]),
    s = roomFields(v.scope, ['tenantId', 'accountId']),
    id = /^[a-z][a-z0-9_-]{0,63}$/;
  return Object.freeze({
    profileId: roomText(v.profileId, ROOM_UUID),
    receiverId: roomText(v.receiverId, ROOM_UUID),
    scope: Object.freeze({
      tenantId: roomText(s.tenantId, id),
      accountId: roomText(s.accountId, id),
    }),
    caseId: roomText(v.caseId, id),
    conversationId: roomText(v.conversationId, id),
    recipientId: roomText(v.recipientId, id),
  });
}
export type RoomBinding = Readonly<{
  bindingId: string;
  nativeBearer: string;
  roomId: string;
  participantId: string;
  agentId: string;
  expiresAt: string;
}>;
export type RoomOpen = Readonly<{
  schemaVersion: 1;
  nodeEpoch: string;
  expectedGeneration: string;
  openId: string;
  binding: RoomBinding;
  roomViewBearer: string;
}>;
export type RoomCommand = Readonly<{
  schemaVersion: 1;
  nodeEpoch: string;
  generation: string;
  openId: string;
}>;
export type RoomRecover = Readonly<{
  schemaVersion: 1;
  nodeEpoch: string;
  expectedGeneration: string;
  bindingId: string;
}>;
export type RoomRead = Readonly<{
  schemaVersion: 1;
  nodeEpoch: string;
  generation: string;
  deliveryId: string;
}>;
function version(v: Record<string, unknown>): void {
  if (v.schemaVersion !== 1) throw new NativeRoomError('invalid_input');
}
export function parseRoomOpen(value: unknown): RoomOpen {
  const v = roomFields(value, [
    'schemaVersion',
    'nodeEpoch',
    'expectedGeneration',
    'openId',
    'binding',
    'roomViewBearer',
  ]);
  version(v);
  const b = roomFields(v.binding, [
      'bindingId',
      'nativeBearer',
      'roomId',
      'participantId',
      'agentId',
      'expiresAt',
    ]),
    id = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  return Object.freeze({
    schemaVersion: 1,
    nodeEpoch: roomText(v.nodeEpoch, ROOM_UUID),
    expectedGeneration: roomGeneration(v.expectedGeneration),
    openId: roomText(v.openId, ROOM_UUID),
    binding: Object.freeze({
      bindingId: roomText(b.bindingId, ROOM_UUID),
      nativeBearer: roomText(b.nativeBearer, ROOM_TOKEN),
      roomId: roomText(b.roomId, id),
      participantId: roomText(b.participantId, id),
      agentId: roomText(b.agentId, id),
      expiresAt: roomTimestamp(b.expiresAt),
    }),
    roomViewBearer: roomText(v.roomViewBearer, ROOM_TOKEN),
  });
}
export function parseRoomCommand(value: unknown): RoomCommand {
  const v = roomFields(value, ['schemaVersion', 'nodeEpoch', 'generation', 'openId']);
  version(v);
  return Object.freeze({
    schemaVersion: 1,
    nodeEpoch: roomText(v.nodeEpoch, ROOM_UUID),
    generation: roomGeneration(v.generation),
    openId: roomText(v.openId, ROOM_UUID),
  });
}
export function parseRoomRecover(value: unknown): RoomRecover {
  const v = roomFields(value, ['schemaVersion', 'nodeEpoch', 'expectedGeneration', 'bindingId']);
  version(v);
  return Object.freeze({
    schemaVersion: 1,
    nodeEpoch: roomText(v.nodeEpoch, ROOM_UUID),
    expectedGeneration: roomGeneration(v.expectedGeneration),
    bindingId: roomText(v.bindingId, ROOM_UUID),
  });
}
export function parseRoomRead(value: unknown): RoomRead {
  const v = roomFields(value, ['schemaVersion', 'nodeEpoch', 'generation', 'deliveryId']);
  version(v);
  return Object.freeze({
    schemaVersion: 1,
    nodeEpoch: roomText(v.nodeEpoch, ROOM_UUID),
    generation: roomGeneration(v.generation),
    deliveryId: roomText(v.deliveryId, ROOM_UUID),
  });
}
export function publicationReceipt(
  value: unknown,
  publication: NativePublication,
): NativeBindingReceipt {
  const v = roomFields(value, ['bindingId', 'bindingDigest', 'publishedAt', 'expiresAt']);
  const result = Object.freeze({
    bindingId: roomText(v.bindingId, ROOM_UUID),
    bindingDigest: roomText(v.bindingDigest, /^[0-9a-f]{64}$/),
    publishedAt: roomTimestamp(v.publishedAt),
    expiresAt: roomTimestamp(v.expiresAt),
  });
  if (
    result.bindingId !== publication.bindingId ||
    result.expiresAt !== publication.expiresAt ||
    Date.parse(result.publishedAt) > Date.parse(result.expiresAt)
  )
    throw new NativeRoomError('unavailable');
  return result;
}
export type RoomRevocation = Readonly<{
  bindingId: string;
  state: 'revoked' | 'absent' | 'unpublished';
  revokedAt: string | null;
}>;
export function revocationReceipt(value: unknown, id: string): RoomRevocation {
  const v = roomFields(value, ['bindingId', 'revokedAt']);
  if (roomText(v.bindingId, ROOM_UUID) !== id) throw new NativeRoomError('unavailable');
  return Object.freeze({ bindingId: id, state: 'revoked', revokedAt: roomTimestamp(v.revokedAt) });
}
export function snapshotNativeResult(
  value: unknown,
  route: NativeRoomRoute,
  deliveryId: string,
): ResultNativeView | null {
  if (value === null) return null;
  try {
    const v = roomFields(value, ['schemaVersion', 'intent', 'receipt', 'case', 'observed']);
    if (v.schemaVersion !== 1) throw new NativeRoomError('unavailable');
    const intent = parseResultIntent(encodeResultIntent(v.intent as P1ResultIntent)),
      receipt = resultReceipt(v.receipt);
    matchResultReceipt(intent, receipt);
    if (
      intent.delivery_id !== deliveryId ||
      intent.receiver_id !== route.receiverId ||
      intent.recipient_id !== route.recipientId ||
      intent.scope.tenant_id !== route.scope.tenantId ||
      intent.scope.account_id !== route.scope.accountId
    )
      throw new NativeRoomError('unavailable');
    const observed = roomFields(v.observed, [
      'p2ObservedAt',
      'caseObservedAt',
      'disclosureAdmittedAt',
      'atomic',
    ]);
    if (observed.atomic !== false) throw new NativeRoomError('unavailable');
    const current = currentCase(v.case, {
      scope: route.scope,
      caseId: route.caseId,
      conversationId: route.conversationId,
    });
    if (current.source !== 'p1_public_v4') throw new NativeRoomError('unavailable');
    const result: ResultNativeView = Object.freeze({
      schemaVersion: 1,
      intent,
      receipt,
      case: current,
      observed: Object.freeze({
        p2ObservedAt: roomTimestamp(observed.p2ObservedAt),
        caseObservedAt: roomTimestamp(observed.caseObservedAt),
        disclosureAdmittedAt: roomTimestamp(observed.disclosureAdmittedAt),
        atomic: false,
      }),
    });
    if (Buffer.byteLength(JSON.stringify(result)) > 32768) throw new NativeRoomError('unavailable');
    return result;
  } catch {
    throw new NativeRoomError('unavailable');
  }
}
export type RoomEndpoint = Readonly<{ host: '127.0.0.1'; port: number }>;
export type RoomControlReady = Readonly<{
  nodeEpoch: string;
  endpoint: RoomEndpoint;
  generation: string;
  recoveryRequired: boolean;
}>;
export type RoomObservation = Readonly<{
  schemaVersion: 1;
  nodeEpoch: string;
  generation: string;
  openId: string;
  state: 'opening' | 'ready' | 'publication_unknown' | 'closing' | 'closed';
  publication: NativeBindingReceipt | null;
  revocation: RoomRevocation | null;
  globalReaderDrained: false;
}>;
export type RoomRecoveryObservation = Readonly<{
  schemaVersion: 1;
  nodeEpoch: string;
  generation: string;
  bindingId: string;
  state: 'recovered';
  revocation: RoomRevocation;
}>;

export type NativeRoomOptions = Readonly<{
  configuration: RoomControlConfiguration;
  publisherToken: string;
  forbiddenBearers: readonly string[];
}>;
export function parseNativeRoomOptions(value: unknown): NativeRoomOptions {
  const v = roomFields(value, ['configuration', 'publisherToken', 'forbiddenBearers']),
    tokens = v.forbiddenBearers;
  if (
    !Array.isArray(tokens) ||
    Object.getPrototypeOf(tokens) !== Array.prototype ||
    tokens.length > 16 ||
    Reflect.ownKeys(tokens).length !== tokens.length + 1
  )
    throw new NativeRoomError('invalid_input');
  const copy: string[] = [];
  for (let i = 0; i < tokens.length; i++) {
    const d = Object.getOwnPropertyDescriptor(tokens, String(i));
    if (!d || !('value' in d) || !d.enumerable) throw new NativeRoomError('invalid_input');
    copy.push(roomText(d.value, ROOM_TOKEN));
  }
  return Object.freeze({
    configuration: parseRoomControlConfiguration(v.configuration),
    publisherToken: roomText(v.publisherToken, ROOM_TOKEN),
    forbiddenBearers: Object.freeze(copy),
  });
}
