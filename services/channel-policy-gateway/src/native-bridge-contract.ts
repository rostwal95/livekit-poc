/** Separate opt-in native bridge profile and trusted attachment; no I/O on import. */
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
import { parseEventJson, type ProviderScope } from '@livekit-ecosystem/channel-continuity';
import type { DispatchPorts } from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  NativeRoomError,
  roomFailure,
  roomFields,
  roomText,
  roomGeneration,
  roomJson,
  ROOM_UUID,
  ROOM_TOKEN,
  roomTimestamp,
  type NativeRoomRoute,
} from './native-room-contract.js';
export type NativeBridgeConfiguration = Readonly<{
  schemaVersion: 1;
  prepareEndpoint: Readonly<{ host: '127.0.0.1'; port: number }>;
  rehydrationPort: number;
}>;
function port(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1 || value > 65535)
    throw new NativeRoomError('invalid_input');
  return value;
}
function configurationUnchecked(value: unknown): NativeBridgeConfiguration {
  const v = roomFields(value, ['schemaVersion', 'prepareEndpoint', 'rehydrationPort']),
    p = roomFields(v.prepareEndpoint, ['host', 'port']);
  if (v.schemaVersion !== 1 || p.host !== '127.0.0.1') throw new NativeRoomError('invalid_input');
  const prepare = port(p.port),
    context = port(v.rehydrationPort);
  if (prepare === context) throw new NativeRoomError('invalid_input');
  return Object.freeze({
    schemaVersion: 1,
    prepareEndpoint: Object.freeze({ host: '127.0.0.1', port: prepare }),
    rehydrationPort: context,
  });
}
export type RoomAttach = Readonly<{
  schemaVersion: 1;
  nodeEpoch: string;
  generation: string;
  openId: string;
  bindingId: string;
  prepareBearer: string;
}>;
export type RoomAttachment = Readonly<{
  schemaVersion: 1;
  nodeEpoch: string;
  generation: string;
  openId: string;
  bindingId: string;
  state: 'attached';
}>;
function attachmentUnchecked(value: unknown): RoomAttach {
  const v = roomFields(value, [
    'schemaVersion',
    'nodeEpoch',
    'generation',
    'openId',
    'bindingId',
    'prepareBearer',
  ]);
  if (v.schemaVersion !== 1) throw new NativeRoomError('invalid_input');
  const generation = roomGeneration(v.generation);
  if (generation === '0') throw new NativeRoomError('invalid_input');
  return Object.freeze({
    schemaVersion: 1,
    nodeEpoch: roomText(v.nodeEpoch, ROOM_UUID),
    generation,
    openId: roomText(v.openId, ROOM_UUID),
    bindingId: roomText(v.bindingId, ROOM_UUID),
    prepareBearer: roomText(v.prepareBearer, ROOM_TOKEN),
  });
}
// Only plain own data enters JSON serialization; getters/toJSON cannot run.
function data(value: unknown, depth = 0, budget = { left: 256 }): unknown {
  if (--budget.left < 0 || depth > 8) throw new NativeRoomError('invalid_input');
  if (value === null || typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    if (Buffer.byteLength(value) > 32768) throw new NativeRoomError('invalid_input');
    return value;
  }
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw new NativeRoomError('invalid_input');
  const out: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const k of Reflect.ownKeys(value)) {
    if (typeof k !== 'string' || k === 'toJSON') throw new NativeRoomError('invalid_input');
    const d = Object.getOwnPropertyDescriptor(value, k);
    if (!d || !('value' in d) || !d.enumerable) throw new NativeRoomError('invalid_input');
    out[k] = data(d.value, depth + 1, budget);
  }
  return Object.freeze(out);
}
function inputUnchecked(
  input: unknown,
  route: NativeRoomRoute,
  provider: ProviderScope,
): Parameters<DispatchPorts['agent']['prepare']>[0] {
  const copied = data(input),
    v = roomFields(copied, ['message', 'currentCase']),
    m = roomFields(v.message, [
      'receipt',
      'event',
      'operationKey',
      'processingState',
      'associationVersion',
    ]),
    c = roomFields(v.currentCase, ['scope', 'caseId', 'revision', 'source']);
  const e = parseEventJson(JSON.stringify(m.event), {
      providerScope: provider,
      accountScope: route.scope,
    }).event,
    s = roomFields(c.scope, ['tenantId', 'accountId']);
  if (
    e.type !== 'text.received' ||
    e.providerScope.provider !== 'livekit' ||
    !['web_chat', 'voice_transcript'].includes(e.channel) ||
    e.caseId !== route.caseId ||
    e.conversationId !== route.conversationId ||
    c.caseId !== route.caseId ||
    s.tenantId !== route.scope.tenantId ||
    s.accountId !== route.scope.accountId ||
    c.source !== 'synthetic_read_only'
  )
    throw new NativeRoomError('unauthorized');
  roomText(c.revision, /^[1-9][0-9]{0,6}$/);
  if (BigInt(c.revision as string) > 1000000n) throw new NativeRoomError('invalid_input');
  const receipt = roomFields(m.receipt, [
    'receiptId',
    'eventId',
    'messageId',
    'acceptanceSequence',
    'acceptedAt',
  ]);
  roomText(receipt.receiptId, ROOM_UUID);
  roomText(m.operationKey, ROOM_UUID);
  roomTimestamp(receipt.acceptedAt);
  for (const n of [receipt.acceptanceSequence, m.associationVersion]) {
    roomText(n, /^[1-9][0-9]{0,18}$/);
    if (BigInt(n as string) > 9223372036854775807n) throw new NativeRoomError('invalid_input');
  }
  if (
    receipt.eventId !== e.eventId ||
    receipt.messageId !== e.messageId ||
    typeof m.processingState !== 'string' ||
    m.processingState.length > 32
  )
    throw new NativeRoomError('invalid_input');
  if (Buffer.byteLength(JSON.stringify(copied)) > 32768) throw new NativeRoomError('invalid_input');
  return Object.freeze({ ...v, message: Object.freeze({ ...m, event: e }) }) as Parameters<
    DispatchPorts['agent']['prepare']
  >[0];
}

export function readNativeBridgeConfiguration(path: string): NativeBridgeConfiguration {
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
    return parseNativeBridgeConfiguration(roomJson(raw.subarray(0, n), 1024, true));
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

export function parseNativeBridgeConfiguration(value: unknown): NativeBridgeConfiguration {
  try {
    return configurationUnchecked(value);
  } catch (error) {
    throw roomFailure(error, 'invalid_input');
  }
}
export function parseRoomAttach(value: unknown): RoomAttach {
  try {
    return attachmentUnchecked(value);
  } catch (error) {
    throw roomFailure(error, 'invalid_input');
  }
}
export function nativeBridgeInput(
  input: unknown,
  route: NativeRoomRoute,
  provider: ProviderScope,
): Parameters<DispatchPorts['agent']['prepare']>[0] {
  try {
    return inputUnchecked(input, route, provider);
  } catch (error) {
    throw roomFailure(error, 'invalid_input');
  }
}
