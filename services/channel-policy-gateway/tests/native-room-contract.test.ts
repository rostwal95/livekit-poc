import { chmodSync, mkdtempSync, writeFileSync, rmSync, symlinkSync, linkSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  parseRoomControlConfiguration,
  readRoomControlConfiguration,
  parseRoomOpen,
  parseRoomCommand,
  parseRoomRead,
  roomJson,
  snapshotNativeResult,
  roomFailure,
  NativeRoomError,
} from '../src/native-room-contract.js';
import { route, opening, view } from './native-room-fixtures.js';
const dirs: string[] = [];
afterEach(() => {
  vi.restoreAllMocks();
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
});
describe('internal room data contracts', () => {
  it('keeps separate config versioned and closed with no scope or credential selectors', () => {
    expect(
      parseRoomControlConfiguration({ schemaVersion: 1, port: 11029, recoverBindingId: null }),
    ).toEqual({ schemaVersion: 1, port: 11029, recoverBindingId: null });
    for (const value of [
      { schemaVersion: 1, port: 0, recoverBindingId: null },
      { schemaVersion: 1, port: 11029, recoverBindingId: null, scope: {} },
      { schemaVersion: 2, port: 11029, recoverBindingId: null },
    ])
      expect(() => parseRoomControlConfiguration(value)).toThrow('invalid_input');
  });
  it('denies accessors/unknown fields before calling getters', () => {
    const get = vi.fn(() => {
        throw new Error('PRIVATE');
      }),
      value = { schemaVersion: 1, port: 11029, recoverBindingId: null };
    Object.defineProperty(value, 'port', { get, enumerable: true });
    expect(() => parseRoomControlConfiguration(value)).toThrow('invalid_input');
    expect(get).not.toHaveBeenCalled();
    const open = opening(route.profileId);
    expect(() => parseRoomOpen({ ...open, scope: route.scope })).toThrow('invalid_input');
  });
  it('rejects duplicate/alternate JSON before any control call', () => {
    for (const raw of [
      '{"schemaVersion":1,"schemaVersion":1}',
      '{"schemaVersion":1e0}',
      ' {"schemaVersion":1}',
      '{"schemaVersion":1}\n',
    ])
      expect(() => roomJson(Buffer.from(raw))).toThrow('invalid_input');
  });
  it('validates finite generations and canonical times without expiry rewriting', () => {
    const a = opening(route.profileId);
    expect(parseRoomOpen(a).binding.expiresAt).toBe(a.binding.expiresAt);
    for (const generation of ['01', '-1', '1000001', '1e3'])
      expect(() =>
        parseRoomCommand({
          schemaVersion: 1,
          nodeEpoch: a.nodeEpoch,
          generation,
          openId: a.openId,
        }),
      ).toThrow('invalid_input');
    expect(() =>
      parseRoomRead({
        schemaVersion: 1,
        nodeEpoch: a.nodeEpoch,
        generation: '1',
        deliveryId: a.openId,
        nativeBearer: a.binding.nativeBearer,
      }),
    ).toThrow('invalid_input');
    expect(() =>
      parseRoomOpen({ ...a, binding: { ...a.binding, expiresAt: '2026-11-13T24:00:00.000Z' } }),
    ).toThrow('invalid_input');
  });
  it('copies full native view, original opaque base64 and exact current route joins', () => {
    const id = route.profileId,
      original = view(id),
      copied = snapshotNativeResult(original, route, id)!;
    expect(copied.intent.body).toBe(original.intent.body);
    expect(Buffer.from(copied.intent.body, 'base64')).toEqual(Buffer.from([0, 255, 128, 65]));
    (original.case.scope as { tenantId: string }).tenantId = 'changed';
    expect(copied.case.scope.tenantId).toBe('tenant_demo');
    expect(Object.isFrozen(copied.observed)).toBe(true);
  });
  it('never turns malformed/foreign native views into absence or evaluates getters', () => {
    const id = route.profileId;
    for (const value of [
      { ...view(id), receipt: { ...view(id).receipt, receiver_id: route.profileId } },
      { ...view(id), case: { ...view(id).case, source: 'standalone_reference_v1' } },
      { ...view(id), intent: { ...view(id).intent, body: 'PRIVATE' } },
      { ...view(id), observed: { ...view(id).observed, atomic: true } },
    ])
      expect(() => snapshotNativeResult(value, route, id)).toThrow('unavailable');
    const value = view(id),
      get = vi.fn(() => {
        throw new Error('PRIVATE');
      });
    Object.defineProperty(value, 'intent', { get, enumerable: true });
    expect(() => snapshotNativeResult(value, route, id)).toThrow('unavailable');
    expect(get).not.toHaveBeenCalled();
    expect(snapshotNativeResult(null, route, id)).toBeNull();
  });
  it('requires private NL1 canonical config files and rejects symbolic/hard aliases', () => {
    const d = mkdtempSync('/private/tmp/native-room-config-');
    dirs.push(d);
    chmodSync(d, 0o700);
    const p = join(d, 'room.json');
    writeFileSync(p, '{"schemaVersion":1,"port":11029,"recoverBindingId":null}\n', { mode: 0o600 });
    expect(readRoomControlConfiguration(p).port).toBe(11029);
    symlinkSync(p, join(d, 'alias'));
    expect(() => readRoomControlConfiguration(join(d, 'alias'))).toThrow('invalid_input');
    linkSync(p, join(d, 'hard'));
    expect(() => readRoomControlConfiguration(p)).toThrow('invalid_input');
  });
  it('copies finite errors and never reads dependency code getters', () => {
    const e = new NativeRoomError('conflict');
    e.message = 'PRIVATE';
    expect(roomFailure(e)).toMatchObject({ code: 'conflict', message: 'conflict' });
    const get = vi.fn(() => {
      throw new Error('PRIVATE');
    });
    Object.defineProperty(e, 'code', { get });
    expect(roomFailure(e)).toMatchObject({ code: 'unavailable', message: 'unavailable' });
    expect(get).not.toHaveBeenCalled();
  });
});
