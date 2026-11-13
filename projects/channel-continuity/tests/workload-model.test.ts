/** Pure frozen workload protocol; neither measurements nor PostgreSQL evidence. */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { SeededAccounts } from '../src/postgres.js';
import {
  CASE_NAMES,
  SCHEMA_TABLES,
  POPULATIONS,
  OWNER_LIMITS,
  experiment,
  schema,
  caseData,
  capacityTenant,
  message,
  windows,
  secret,
  uuid,
  latencies,
} from './workload-model.js';
const config = experiment({ schemaVersion: 1, runId: 'a'.repeat(32), seedHex: 'b'.repeat(64) });
describe('fixed workload model', () => {
  it('binds the exact v7 table inventory to frozen owner CREATE TABLE DDL, not observed state', () => {
    const ddl = readFileSync(new URL('../src/migrations.ts', import.meta.url), 'utf8');
    const [v7, v8] = ddl.split('const RESULT_RECEIVER_SPEC =');
    expect(v8).toBeDefined();
    const names = [...v7!.matchAll(/^CREATE TABLE ([a-z_]+)\(/gm)].map((m) => m[1]!).sort();
    expect([...v8!.matchAll(/^CREATE TABLE ([a-z_]+)\(/gm)].map((m) => m[1]!)).toEqual([
      'result_receipts',
    ]);
    expect(names).toHaveLength(29);
    expect(new Set(names).size).toBe(29);
    expect(SCHEMA_TABLES).toEqual(names);
    expect(ddl).not.toMatch(/^DROP TABLE /m);
  });
  it('retains the exact24 unique assertions and predeclared populations/caps', () => {
    expect(CASE_NAMES).toHaveLength(24);
    expect(new Set(CASE_NAMES).size).toBe(24);
    expect(POPULATIONS).toEqual([0, 64, 256, 1000]);
    expect(OWNER_LIMITS.capacity.maxInbox).toBe(64);
    expect(OWNER_LIMITS.dormant.maxInbox).toBe(1024);
  });
  it('snapshots strict owner data without invoking getters or accepting extra fields', () => {
    let called = false;
    expect(() =>
      experiment({
        schemaVersion: 1,
        runId: config.runId,
        get seedHex() {
          called = true;
          return config.seedHex;
        },
      }),
    ).toThrow('invalid_workload_model');
    expect(called).toBe(false);
    expect(() => experiment({ ...config, room: 'arbitrary' })).toThrow();
    expect(() => experiment({ ...config, runId: config.runId + '\n' })).toThrow();
    expect(Object.isFrozen(config)).toBe(true);
  });
  it('uses canonical bounded owned schema names and disjoint stable UUID4 identities', () => {
    expect(schema(config, 'capacity')).toMatch(/^p2_workload_[a-f0-9]{32}_capacity$/);
    expect(schema(config, 'dormant').length).toBeLessThanOrEqual(63);
    expect(uuid(config, 'capacity:event:1')).toMatch(
      /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/,
    );
    expect(uuid(config, 'capacity:event:1')).toBe(uuid(config, 'capacity:event:1'));
    expect(uuid(config, 'wake:event:1')).not.toBe(uuid(config, 'capacity:event:1'));
  });
  it('seeds1000 only through bounded valid public account windows', () => {
    const all = [];
    for (const selected of [0, 1] as const)
      for (const window of windows(config, selected)) {
        expect(window.length).toBeLessThanOrEqual(64);
        expect(Object.isFrozen(window)).toBe(true);
        const verifier = new SeededAccounts(window.map((x) => x.seed));
        for (const c of window) {
          expect(verifier.authenticate(c.seed.token, c.seed.tenantId)).toMatchObject({
            accountId: c.seed.accountId,
            conversationId: c.seed.conversationId,
            caseId: c.seed.caseId,
          });
          all.push(c);
        }
      }
    expect(all).toHaveLength(1000);
    expect(new Set(all.map((x) => x.seed.token)).size).toBe(1000);
    expect(new Set(all.map((x) => x.seed.conversationId)).size).toBe(1000);
  });
  it('keeps credential material separate from case identifiers and copies each key', () => {
    const c = caseData(config, 'dormant', 0),
      key = secret(config, 'provider:0');
    key.fill(0);
    expect(secret(config, 'provider:0').equals(key)).toBe(false);
    expect(secret(config, 'provider:0').equals(secret(config, 'provider:1'))).toBe(false);
    expect(c.seed.token.length).toBe(43);
    expect(JSON.stringify({ sender: c.senderId, case: c.seed.caseId })).not.toContain(c.seed.token);
  });
  it('preserves two equal text bodies as distinct messages in one case', () => {
    const a = message(config, 'capacity', 0),
      b = message(config, 'capacity', 2);
    expect(a.case.seed).toEqual(b.case.seed);
    expect(a.value.body).toBe('yes');
    expect(b.value.body).toBe('yes');
    expect(a.value.eventId).not.toBe(b.value.eventId);
    expect(capacityTenant(16)).toBe(0);
    expect(capacityTenant(23)).toBe(1);
  });
  it('binds wake inputs to original dormant cases with fresh event identities', () => {
    for (const i of [0, 1]) {
      const wake = message(config, 'wake', i),
        old = message(config, 'dormant', i * 500);
      expect(wake.case.seed).toEqual(old.case.seed);
      expect(wake.value.eventId).not.toBe(old.value.eventId);
      expect(wake.value.senderId).toBe(old.value.senderId);
    }
    expect(() => message(config, 'wake', 2)).toThrow();
  });
  it('reports no percentile for empty cohorts and no p95 below20 samples', () => {
    expect(latencies([])).toEqual({ count: 0, p50Ms: null, maximumMs: null });
    expect(latencies([9, 1, 5])).toEqual({ count: 3, p50Ms: 5, maximumMs: 9 });
    expect(latencies(Array.from({ length: 19 }, (_, i) => i))).not.toHaveProperty('p95Ms');
  });
  it('reports nearest-rank p95 only for a sufficiently labelled-size cohort', () => {
    expect(latencies(Array.from({ length: 20 }, (_, i) => 20 - i))).toEqual({
      count: 20,
      p50Ms: 10,
      maximumMs: 20,
      p95Ms: 19,
    });
  });
  it('rejects malformed/nonfinite latency data without invoking overridden iteration', () => {
    for (const value of [[NaN], [Infinity], [-1], [true], new Array(1)])
      expect(() => latencies(value as number[])).toThrow();
    const a = [1];
    Object.defineProperty(a, '0', {
      get() {
        throw Error('SENTINEL');
      },
    });
    expect(() => latencies(a)).toThrow('invalid_workload_model');
  });
});
