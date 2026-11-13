import { afterEach, describe, expect, it } from 'vitest';
import { spawn, type ChildProcess } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmod, lstat, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  CAPABILITY,
  SpecialistClient,
  canonical,
  encodeRequest,
  produceRequest,
  type Scope,
} from '@livekit-ecosystem/delegation-specialist';

const fixture = fileURLToPath(new URL('./fixtures/standalone-server.mjs', import.meta.url));
const directoryRoot = dirname(dirname(fixture));
const token = 's'.repeat(43);
const scope = Object.freeze({ tenant_id: 'tenant_standalone', account_id: 'account_standalone' });
const baseKeys = [
  'PATH',
  'LANG',
  'LC_ALL',
  'TMPDIR',
  'COREPACK_HOME',
  'COREPACK_ENABLE_NETWORK',
  'UV_PYTHON_DOWNLOADS',
  'UV_NO_PROGRESS',
  'PYTHONDONTWRITEBYTECODE',
  '__CF_USER_TEXT_ENCODING',
];
const roots: string[] = [];
const children: { child: ChildProcess; done: Promise<number | null> }[] = [];
function baseEnvironment(): NodeJS.ProcessEnv {
  return Object.fromEntries(
    baseKeys.flatMap((key) => (process.env[key] === undefined ? [] : [[key, process.env[key]]])),
  ) as NodeJS.ProcessEnv;
}
async function bounded<T>(promise: Promise<T>, milliseconds = 4000): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<never>((_yes, no) => {
        timer = setTimeout(() => no(new Error('test_timeout')), milliseconds);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
async function ownedDirectory() {
  const root = await mkdtemp('/private/tmp/p3-standalone-node-test-');
  roots.push(root);
  await chmod(root, 0o700);
  return root;
}
function launch(args: string[], env: NodeJS.ProcessEnv) {
  const child = spawn(process.execPath, args, {
    cwd: directoryRoot,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stdout = '',
    stderr = '';
  child.stdout!.on('data', (chunk: Buffer) => {
    stdout += chunk.toString();
    if (Buffer.byteLength(stdout) > 32768) child.kill('SIGKILL');
  });
  child.stderr!.on('data', (chunk: Buffer) => {
    stderr += chunk.toString();
    if (Buffer.byteLength(stderr) > 32768) child.kill('SIGKILL');
  });
  const done = new Promise<number | null>((yes, no) => {
    child.once('error', no);
    child.once('close', (code) => yes(code));
  });
  children.push({ child, done });
  return { child, done, output: () => ({ stdout, stderr }) };
}
async function configured(extra: NodeJS.ProcessEnv = {}) {
  const root = await ownedDirectory();
  const files = {
    ready: join(root, 'specialist.ready'),
    endpoint: join(root, 'specialist-endpoint.json'),
    stop: join(root, 'specialist.stop'),
    proof: join(root, 'standalone-service.json'),
    duplicate: join(root, 'specialist-duplicate-invoke.json'),
  };
  const env = {
    ...baseEnvironment(),
    P3_STANDALONE_DIRECTORY: root,
    P3_STANDALONE_SPECIALIST_TOKEN: token,
    P3_STANDALONE_READY_FILE: files.ready,
    P3_STANDALONE_ENDPOINT_FILE: files.endpoint,
    P3_STANDALONE_STOP_FILE: files.stop,
    ...extra,
  };
  return { root, files, env };
}
async function ready(run: ReturnType<typeof launch>, file: string) {
  await bounded(
    (async () => {
      while (true) {
        try {
          const value = await readFile(file, 'utf8');
          expect(value).toBe(`${run.child.pid}\n`);
          return;
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
          if (run.child.exitCode !== null || run.child.signalCode !== null)
            throw new Error('test_child_exited');
          await new Promise((yes) => setTimeout(yes, 5));
        }
      }
    })(),
  );
}
function request(selectedScope: Scope = scope) {
  const body = canonical({ minimum_notice_days: 7, policy_version: 'policy_v1' });
  return produceRequest({
    schema_version: 1,
    kind: 'delegation.request',
    capability: CAPABILITY,
    input_schema_version: 1,
    scope: selectedScope,
    delegation_id: 'delegation_standalone',
    case_id: 'case_standalone',
    request_revision: 2,
    context_snapshot: {
      policy_version: 'policy_v1',
      policy_source_id: 'policy_demo',
      days_before_arrival: 14,
      note: 'Synthetic standalone socket qualification.',
    },
    evidence: [
      {
        source_id: 'policy_demo',
        version: 'source_v1',
        sha256: createHash('sha256').update(body).digest('hex'),
        media_type: 'application/json',
        byte_length: body.byteLength,
        width: null,
        height: null,
      },
    ],
    deadline_at_ms: Date.now() + 10000,
    result_route: { conversation_id: 'conversation_standalone' },
    attempt: { attempt_id: 'attempt_standalone', number: 1 },
  });
}
async function clientFor(
  files: Awaited<ReturnType<typeof configured>>['files'],
  credential = token,
) {
  const value = JSON.parse(await readFile(files.endpoint, 'utf8'));
  expect(Object.keys(value).sort()).toEqual(['host', 'node_version', 'port', 'schema_version']);
  expect(value).toMatchObject({ schema_version: 1, host: '127.0.0.1', node_version: '24.22.2' });
  return new SpecialistClient({ host: value.host, port: value.port }, 'Bearer ' + credential);
}
afterEach(async () => {
  const settled = await Promise.allSettled(
    children.splice(0).map(async ({ child, done }) => {
      if (child.exitCode === null && child.signalCode === null) {
        child.kill('SIGKILL');
      }
      await bounded(done);
    }),
  );
  const removed = await Promise.allSettled(
    roots.splice(0).map((root) => rm(root, { recursive: true, force: true })),
  );
  const failed = [...settled, ...removed].find((result) => result.status === 'rejected');
  if (failed?.status === 'rejected') throw failed.reason;
});

describe('standalone public specialist fixture', () => {
  it('imports without configuration, files, listeners or a control-loop lifetime', async () => {
    const program = `import {Server} from 'node:net'; Server.prototype.listen=()=>{throw Error('listen_on_import')}; await import(${JSON.stringify(new URL('./fixtures/standalone-server.mjs', import.meta.url).href)}); console.info(JSON.stringify({status:'passed'}));`;
    const run = launch(['--input-type=module', '-e', program], {
      ...baseEnvironment(),
      HOME: 'not-a-fixture-environment',
    });
    expect(await bounded(run.done)).toBe(0);
    expect(run.output()).toEqual({ stdout: '{"status":"passed"}\n', stderr: '' });
  });
  it('serves one strict correlated result, denies wrong scope/auth, and proves actual closed resources', async () => {
    const config = await configured();
    const run = launch([fixture], config.env);
    await ready(run, config.files.ready);
    const client = await clientFor(config.files),
      denied = await clientFor(config.files, 'x'.repeat(43));
    let input: ReturnType<typeof request> | undefined;
    try {
      await expect(denied.invoke(request())).rejects.toThrow();
      await expect(
        client.invoke(request({ tenant_id: 'tenant_standalone', account_id: 'foreign_account' })),
      ).rejects.toThrow();
      input = request();
      const result = await client.invoke(input);
      expect(result).toMatchObject({
        eligible: true,
        uncertainty: 'none',
        scope,
        attempt_id: input.attempt.attempt_id,
        input_fingerprint: input.input_fingerprint,
      });
    } finally {
      await Promise.all([client.close(), denied.close()]);
    }
    await writeFile(config.files.stop, `${run.child.pid}\n`, { mode: 0o600, flag: 'wx' });
    expect(await bounded(run.done)).toBe(0);
    const proof = JSON.parse(await readFile(config.files.proof, 'utf8'));
    expect(proof).toEqual({
      schema_version: 1,
      status: 'closed',
      node_version: '24.22.2',
      invoked: 1,
      strict_completed: 1,
      active: 0,
      requests: 0,
      sockets: 0,
      request_sha256: createHash('sha256').update(encodeRequest(input!)).digest('hex'),
      wire_attempt_id: input!.attempt.attempt_id,
      scope,
    });
    expect(run.output()).toEqual({ stdout: JSON.stringify(proof) + '\n', stderr: '' });
    for (const path of [config.files.ready, config.files.endpoint, config.files.proof]) {
      const stat = await lstat(path);
      expect(stat.isFile()).toBe(true);
      expect(stat.nlink).toBe(1);
      expect(stat.mode & 0o777).toBe(0o600);
    }
    await expect(lstat(config.files.duplicate)).rejects.toMatchObject({ code: 'ENOENT' });
    const closed = await clientFor(config.files);
    try {
      await expect(closed.invoke(request())).rejects.toThrow();
    } finally {
      await closed.close();
    }
  });
  it.each(['HOME', 'PGPASSWORD', 'HTTP_PROXY'])(
    'rejects ambient %s before binding',
    async (key) => {
      const config = await configured({ [key]: 'synthetic-forbidden-setting' });
      const run = launch([fixture], config.env);
      expect(await bounded(run.done)).toBe(1);
      expect(JSON.parse(run.output().stdout)).toEqual({
        schema_version: 1,
        status: 'failed',
        code: 'standalone_fixture_failed',
        cleanup_complete: true,
      });
      expect(run.output().stderr).toBe('');
      await expect(lstat(config.files.endpoint)).rejects.toMatchObject({ code: 'ENOENT' });
    },
  );
  it('rejects an existing endpoint symlink without touching the target', async () => {
    const config = await configured();
    const target = join(config.root, 'unrelated');
    await writeFile(target, 'preserved', { mode: 0o600, flag: 'wx' });
    await symlink(target, config.files.endpoint);
    const run = launch([fixture], config.env);
    expect(await bounded(run.done)).toBe(1);
    expect(await readFile(target, 'utf8')).toBe('preserved');
    expect(JSON.parse(run.output().stdout).cleanup_complete).toBe(true);
  });
  it('rejects another child path before publishing readiness', async () => {
    const config = await configured();
    config.env.P3_STANDALONE_READY_FILE = join(config.root, 'different.ready');
    const run = launch([fixture], config.env);
    expect(await bounded(run.done)).toBe(1);
    await expect(lstat(config.files.ready)).rejects.toMatchObject({ code: 'ENOENT' });
    await expect(lstat(config.files.endpoint)).rejects.toMatchObject({ code: 'ENOENT' });
  });
  it('rejects a nonprivate directory before opening a socket', async () => {
    const config = await configured();
    await chmod(config.root, 0o755);
    const run = launch([fixture], config.env);
    expect(await bounded(run.done)).toBe(1);
    expect(JSON.parse(run.output().stdout).cleanup_complete).toBe(true);
    await expect(lstat(config.files.endpoint)).rejects.toMatchObject({ code: 'ENOENT' });
  });
  it('rejects a nonprivate stop file and still settles the server', async () => {
    const config = await configured();
    const run = launch([fixture], config.env);
    await ready(run, config.files.ready);
    await writeFile(config.files.stop, `${run.child.pid}\n`, { mode: 0o644, flag: 'wx' });
    await chmod(config.files.stop, 0o644);
    expect(await bounded(run.done)).toBe(1);
    expect(JSON.parse(run.output().stdout).cleanup_complete).toBe(true);
    await expect(lstat(config.files.proof)).rejects.toMatchObject({ code: 'ENOENT' });
  });
  it('rejects a wrong stop PID and closes the actual listening server', async () => {
    const config = await configured();
    const run = launch([fixture], config.env);
    await ready(run, config.files.ready);
    await writeFile(config.files.stop, `${run.child.pid! + 1}\n`, { mode: 0o600, flag: 'wx' });
    expect(await bounded(run.done)).toBe(1);
    expect(JSON.parse(run.output().stdout)).toEqual({
      schema_version: 1,
      status: 'failed',
      code: 'standalone_fixture_failed',
      cleanup_complete: true,
    });
    await expect(lstat(config.files.proof)).rejects.toMatchObject({ code: 'ENOENT' });
  });
  it('retains a duplicate-invocation marker and fails rather than hiding a second start', async () => {
    const config = await configured();
    const run = launch([fixture], config.env);
    await ready(run, config.files.ready);
    const client = await clientFor(config.files);
    try {
      const input = request();
      await client.invoke(input);
      await expect(client.invoke(input)).rejects.toThrow();
    } finally {
      await client.close();
    }
    expect(await bounded(run.done)).toBe(1);
    expect(JSON.parse(await readFile(config.files.duplicate, 'utf8'))).toEqual({
      schema_version: 1,
      status: 'failed',
      code: 'duplicate_invocation',
    });
    expect(JSON.parse(run.output().stdout).cleanup_complete).toBe(true);
    await expect(lstat(config.files.proof)).rejects.toMatchObject({ code: 'ENOENT' });
  });
});
