/** Test-fixture correctness only; no database or durable execution qualification. */
import { afterEach, describe, expect, it } from 'vitest';
import {
  readFileSync,
  mkdtempSync,
  chmodSync,
  lstatSync,
  symlinkSync,
  linkSync,
  rmSync,
  unlinkSync,
  renameSync,
  existsSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import type { Stats } from 'node:fs';
import { realpathSync } from 'node:fs';
import { join } from 'node:path';
import { request } from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { canonical as productCanonical } from '../src/index.js';
import { setTimeout as delay } from 'node:timers/promises';
import { produceFixedPolicyRequest, encodeFixedPolicyRequest } from '../src/fixed-policy.js';

type Config = Readonly<{
  directory: string;
  input: string;
  endpoint: string;
  stop: string;
  token: string;
}>;
type Endpoint = Readonly<{
  public: { host: string; port: number };
  fault: { host: string; port: number };
}>;
type Owner = {
  start(): Promise<Endpoint>;
  close(): Promise<void>;
  finish(): Promise<Buffer>;
  stage(): string;
};
type Fixture = {
  publicationPending(path: string, inspect?: (path: string) => Stats): boolean;
  fixtureBytes(value: unknown): Buffer;
  parsePeerInput(raw: Buffer): unknown;
  validateEnvironment(env: Record<string, string>): Config;
  publishPrivate(path: string, data: Buffer): void;
  readPrivate(path: string, maximum?: number): Buffer;
  createPeer(config: Config, input: unknown): Owner;
};
const peer = (await import(
  new URL('./fixtures/durable-fixed-policy-server.mjs', import.meta.url).href
)) as Fixture;
const corpus = JSON.parse(
  readFileSync(
    new URL('../../../../tests/fixtures/p3-fixed-work-proof-positive.json', import.meta.url),
    'utf8',
  ),
) as {
  expected_scope: { tenant_id: string; account_id: string };
  sources: unknown[];
  wires: { label: string; accepted_request_utf8: string }[];
};
const directories = new Set<string>();
function directory(): string {
  const path = mkdtempSync(join(realpathSync(tmpdir()), 'p3-fixed-work-fixture-'));
  chmodSync(path, 0o700);
  directories.add(path);
  return path;
}
function env(path: string): Record<string, string> {
  return {
    P3_FIXED_WORK_DIRECTORY: path,
    P3_FIXED_WORK_INPUT_FILE: join(path, 'fixed-work-input.json'),
    P3_FIXED_WORK_ENDPOINT_FILE: join(path, 'fixed-work-endpoint.json'),
    P3_FIXED_WORK_STOP_FILE: join(path, 'fixed-work.stop'),
    P3_FIXED_WORK_TOKEN: 'A'.repeat(43),
  };
}
function input() {
  return {
    schema_version: 1,
    kind: 'fixed-work.peer-input',
    scope: structuredClone(corpus.expected_scope),
    records: structuredClone(corpus.sources),
    cases: corpus.wires.map((row) => {
      const accepted = JSON.parse(row.accepted_request_utf8);
      return {
        label: row.label,
        delegation_id: accepted.delegation_id,
        case_id: accepted.case_id,
        request_revision: accepted.request_revision,
        conversation_id: accepted.result_route.conversation_id,
        context_snapshot: accepted.context_snapshot,
        evidence: accepted.evidence,
        peer: [
          'known',
          'missing',
          'conflicting',
          'cancelled',
          'abandoned',
          'postcommit',
          'useful',
        ].includes(row.label)
          ? 'public'
          : 'fault',
      };
    }),
  };
}
function body(label: string): Buffer {
  const row = corpus.wires.find((value) => value.label === label)!;
  const value = JSON.parse(row.accepted_request_utf8);
  delete value.input_fingerprint;
  value.deadline_at_ms = Date.now() + 30000;
  value.attempt = { attempt_id: 'attempt_00000000000040008000000000000001', number: 1 };
  return Buffer.from(encodeFixedPolicyRequest(produceFixedPolicyRequest(value)));
}
function invoke(port: number, raw: Buffer): Promise<{ status: number; body: Buffer }> {
  return new Promise((yes, no) => {
    const call = request(
      {
        host: '127.0.0.1',
        port,
        path: '/v1/invoke',
        method: 'POST',
        signal: AbortSignal.timeout(3000),
        headers: {
          Authorization: 'Bearer ' + 'A'.repeat(43),
          'Content-Type': 'application/json',
          'Content-Length': raw.length,
          Connection: 'close',
        },
      },
      (response) => {
        const chunks: Buffer[] = [];
        let size = 0;
        response.on('data', (chunk: Buffer) => {
          size += chunk.length;
          if (size > 8192) {
            response.destroy();
            no(Error('response_limit'));
          } else chunks.push(chunk);
        });
        response.once('end', () =>
          yes({ status: response.statusCode ?? 0, body: Buffer.concat(chunks) }),
        );
        response.once('error', no);
      },
    );
    call.once('error', no);
    call.end(raw);
  });
}
afterEach(() => {
  for (const path of directories) {
    rmSync(path, { recursive: true });
    directories.delete(path);
  }
});

describe('durable fixed-policy peer fixture', () => {
  it('validates canonical complete trusted inputs before startup', () => {
    const value = input();
    expect(peer.parsePeerInput(peer.fixtureBytes(value))).toBeDefined();
    expect(
      peer.parsePeerInput(Buffer.concat([peer.fixtureBytes(value), Buffer.from('\n')])),
    ).toBeDefined();
    expect(() => peer.parsePeerInput(Buffer.from(JSON.stringify(value, null, 2)))).toThrow();
    expect(() =>
      peer.parsePeerInput(Buffer.from('{"schema_version":1,"schema_version":1}')),
    ).toThrow();
    for (const mutate of [
      (v: ReturnType<typeof input>) => {
        v.cases.pop();
      },
      (v: ReturnType<typeof input>) => {
        v.cases[0]!.peer = 'fault';
      },
      (v: ReturnType<typeof input>) => {
        v.records.push(v.records[0]);
      },
      (v: ReturnType<typeof input>) => {
        v.cases[0]!.evidence[0].sha256 = '0'.repeat(64);
      },
    ]) {
      const changed = input();
      mutate(changed);
      expect(() => peer.parsePeerInput(peer.fixtureBytes(changed))).toThrow();
    }
  });

  it('bounds setup metadata separately from unchanged product wire limits', () => {
    expect(peer.fixtureBytes(input()).length).toBeLessThan(32768);
    expect(() => productCanonical(input())).toThrow();
    expect(peer.fixtureBytes({ z: 1, a: [{ b: 2, a: 3 }] }).toString()).toBe(
      '{"a":[{"a":3,"b":2}],"z":1}',
    );
    expect(() => peer.fixtureBytes(Array(129).fill(0))).toThrow();
    expect(() => peer.fixtureBytes({ body: 'x'.repeat(32769) })).toThrow();
    expect(() => peer.fixtureBytes(Array.from({ length: 64 }, () => Array(64).fill(0)))).toThrow();
    expect(() => peer.fixtureBytes({ invalid: '\ud800' })).toThrow();
    let invoked = false;
    expect(() =>
      peer.fixtureBytes({
        get unsafe() {
          invoked = true;
          return 1;
        },
      }),
    ).toThrow();
    expect(invoked).toBe(false);
  });

  it('rejects ambient role selectors and foreign private paths', () => {
    const path = directory(),
      allowed = env(path);
    expect(peer.validateEnvironment(allowed).directory).toBe(path);
    for (const key of ['PGPASSWORD', 'NODE_OPTIONS', 'HTTP_PROXY'])
      expect(() => peer.validateEnvironment({ ...allowed, [key]: 'PRIVATE_SENTINEL' })).toThrow();
    expect(() =>
      peer.validateEnvironment({ ...allowed, P3_FIXED_WORK_STOP_FILE: join(path, 'foreign.stop') }),
    ).toThrow();
    expect(() => peer.validateEnvironment({ ...allowed, P3_FIXED_WORK_TOKEN: 'bad' })).toThrow();
  });

  it('publishes complete exclusive private files and rejects links', () => {
    const path = directory(),
      target = join(path, 'proof.json');
    peer.publishPrivate(target, Buffer.from('{"known":true}\n'));
    expect(peer.readPrivate(target).toString()).toBe('{"known":true}\n');
    expect(lstatSync(target).mode & 0o777).toBe(0o600);
    expect(lstatSync(target).nlink).toBe(1);
    expect(() => peer.publishPrivate(target, Buffer.from('changed'))).toThrow();
    expect(peer.readPrivate(target).toString()).toBe('{"known":true}\n');
    const alias = join(path, 'alias.json');
    symlinkSync(target, alias);
    expect(() => peer.readPrivate(alias)).toThrow();
    linkSync(target, join(path, 'hard.json'));
    expect(() => peer.readPrivate(target)).toThrow();
  });

  it('observes only the same private inode when publication finishes between lstats', () => {
    const path = directory(),
      target = join(path, 'publication.released');
    peer.publishPrivate(target, Buffer.from(process.pid + '\n'));
    const pending = target + '.' + process.pid + '.pending';
    linkSync(target, pending);
    let unlinked = false;
    expect(
      peer.publicationPending(target, (name) => {
        if (name === pending && !unlinked) {
          unlinkSync(pending);
          unlinked = true;
        }
        return lstatSync(name);
      }),
    ).toBe(false);
    expect(lstatSync(target).nlink).toBe(1);
    const replacement = join(path, 'replacement.json');
    peer.publishPrivate(replacement, Buffer.from(process.pid + '\n'));
    linkSync(target, pending);
    unlinked = false;
    expect(() =>
      peer.publicationPending(target, (name) => {
        if (name === pending && !unlinked) {
          unlinkSync(pending);
          unlinkSync(target);
          renameSync(replacement, target);
          unlinked = true;
        }
        return lstatSync(name);
      }),
    ).toThrow();
  });

  it('keeps construction inert and closes both explicit listeners', async () => {
    const path = directory(),
      owner = peer.createPeer(
        peer.validateEnvironment(env(path)),
        peer.parsePeerInput(peer.fixtureBytes(input())),
      );
    try {
      expect(existsSync(join(path, 'fixed-work-endpoint.json'))).toBe(false);
      const endpoints = await owner.start();
      expect(endpoints.public.host).toBe('127.0.0.1');
      expect(endpoints.fault.host).toBe('127.0.0.1');
      expect(endpoints.public.port).not.toBe(endpoints.fault.port);
      await owner.close();
      expect(owner.stage()).toBe('close');
      await owner.close();
    } catch (error) {
      try {
        await owner.close();
      } catch {
        directories.delete(path);
      }
      throw error;
    }
  });

  it('runs real public and explicit-fault HTTP without claiming durable results', async () => {
    const path = directory(),
      owner = peer.createPeer(
        peer.validateEnvironment(env(path)),
        peer.parsePeerInput(peer.fixtureBytes(input())),
      );
    try {
      const endpoints = await owner.start();
      const known = await invoke(endpoints.public.port, body('known'));
      expect(known.status).toBe(200);
      expect(JSON.parse(known.body.toString()).eligible).toBe(true);
      const wrong = await invoke(endpoints.fault.port, body('wrong_decision'));
      expect(wrong.status).toBe(200);
      expect(JSON.parse(wrong.body.toString()).eligible).toBe(false);
      const saved = JSON.parse(
        peer.readPrivate(join(path, 'peer-wires', 'wrong_decision.json')).toString(),
      );
      expect(saved.result_utf8).toBe(wrong.body.toString());
      await owner.close();
      expect(existsSync(join(path, 'fixed-work-peer.json'))).toBe(false);
    } catch (error) {
      try {
        await owner.close();
      } catch {
        directories.delete(path);
      }
      throw error;
    }
  });

  it('publishes actual child readiness and settles the closed stop/terminal protocol', async () => {
    const path = directory(),
      environment = env(path);
    peer.publishPrivate(environment.P3_FIXED_WORK_INPUT_FILE!, peer.fixtureBytes(input()));
    const child = spawn(
      process.execPath,
      [
        fileURLToPath(new URL('./fixtures/durable-fixed-policy-server.mjs', import.meta.url)),
        'serve',
      ],
      {
        env: { ...environment, PATH: process.env.PATH ?? '', LANG: 'C', CI: '1', NO_COLOR: '1' },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );
    let stdout = '',
      stderr = '',
      settled = false;
    const exited = new Promise<{ code: number | null; signal: NodeJS.Signals | null }>(
      (yes, no) => {
        child.once('error', no);
        child.once('close', (code, signal) => {
          settled = true;
          yes({ code, signal });
        });
      },
    );
    child.stdout.on('data', (data: Buffer) => {
      stdout += data.toString();
      if (Buffer.byteLength(stdout) > 4096) child.kill('SIGTERM');
    });
    child.stderr.on('data', (data: Buffer) => {
      stderr += data.toString();
      if (Buffer.byteLength(stderr) > 4096) child.kill('SIGTERM');
    });
    try {
      const marker = join(path, 'fixed_work_server_ready.reached'),
        end = performance.now() + 3000;
      // Publishing links the marker before unlinking its private staging name.
      while (lstatSync(marker, { throwIfNoEntry: false })?.nlink !== 1) {
        if (settled || performance.now() >= end) throw Error('missing_owned_readiness');
        await delay(5);
      }
      expect(peer.readPrivate(marker, 32).toString()).toBe(child.pid + '\n');
      const endpoint = JSON.parse(
        peer.readPrivate(environment.P3_FIXED_WORK_ENDPOINT_FILE!).toString(),
      );
      expect(endpoint.pid).toBe(child.pid);
      const pending = environment.P3_FIXED_WORK_STOP_FILE! + '.publishing';
      peer.publishPrivate(pending, Buffer.from(child.pid + '\n'));
      linkSync(pending, environment.P3_FIXED_WORK_STOP_FILE!);
      unlinkSync(pending);
      const result = await Promise.race([
        exited,
        delay(3000).then(() => {
          throw Error('child_stop_timeout');
        }),
      ]);
      expect(result).toEqual({ code: 1, signal: null });
      expect(stderr).toBe('');
      expect(JSON.parse(stdout)).toEqual({
        schema_version: 1,
        status: 'failed',
        mode: 'serve',
        code: 'fixture_failed',
        stage: 'proof',
        cleanup_complete: true,
      });
      expect(stdout).not.toContain(environment.P3_FIXED_WORK_TOKEN);
      expect(existsSync(join(path, 'fixed-work-peer.json'))).toBe(false);
    } finally {
      if (!settled) {
        child.kill('SIGTERM');
        try {
          await Promise.race([
            exited,
            delay(1000).then(() => {
              throw Error('owned_child_pending');
            }),
          ]);
        } catch {
          child.kill('SIGKILL');
          await exited;
        }
      }
      if (!settled) directories.delete(path);
    }
  });

  it('settles a held fault handler and its actual socket on close', async () => {
    const path = directory(),
      owner = peer.createPeer(
        peer.validateEnvironment(env(path)),
        peer.parsePeerInput(peer.fixtureBytes(input())),
      );
    try {
      const endpoints = await owner.start();
      const pending = invoke(endpoints.fault.port, body('expired_valid'));
      const observed = pending.then(
        (value) => ({ known: true, value }),
        () => ({ known: false }),
      );
      const marker = join(path, 'fixed_work_expired_valid_held.reached'),
        until = performance.now() + 2000;
      while (!existsSync(marker)) {
        if (performance.now() >= until) throw Error('missing_hold');
        await delay(5);
      }
      expect(peer.readPrivate(marker, 32).toString()).toBe(process.pid + '\n');
      await owner.close();
      await observed;
      await owner.close();
      expect(existsSync(join(path, 'fixed-work-peer.json'))).toBe(false);
    } catch (error) {
      try {
        await owner.close();
      } catch {
        directories.delete(path);
      }
      throw error;
    }
  });
});
