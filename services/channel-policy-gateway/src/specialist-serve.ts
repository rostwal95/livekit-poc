/** Explicit scripted specialist role; --plan never reads environment/config or starts a server. */
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import {
  ScriptedPolicySpecialistRuntime,
  SCRIPTED_SPECIALIST_LIMITS,
} from './specialist-runtime.js';
import {
  SpecialistRuntimeError,
  SPECIALIST_ENVIRONMENT_KEYS,
  parseSpecialistEnvironment,
  readSpecialistConfiguration,
  specialistFailureCode,
  type SpecialistConfiguration,
  type SpecialistCredentials,
} from './specialist-config.js';
export function specialistPlan(): Readonly<Record<string, unknown>> {
  return Object.freeze({
    schemaVersion: 1,
    status: 'planned',
    label: 'scripted',
    mode: 'scripted_fixed_policy',
    capability: 'booking.evaluate_policy',
    specialistInputVersion: 2,
    p1IssuanceVerified: false,
    providerCalls: false,
    sql: false,
    effectAuthority: false,
    listenerCount: 1,
    fixedPort: true,
    evidenceRecords: 32,
    evidenceBodyBytes: 4096,
    evidenceTotalBytes: 131072,
    configurationBytes: 262144,
    limits: SCRIPTED_SPECIALIST_LIMITS,
    onePrincipalMaximumActive: 2,
    startupMs: 2000,
    shutdownMs: 10000,
    credentialEnvironmentKeys: SPECIALIST_ENVIRONMENT_KEYS,
  });
}
function outputError(): void {
  /* output failure cannot erase actual resource owners */
}
function guardOutput(): void {
  if (!process.stdout.listeners('error').includes(outputError))
    process.stdout.on('error', outputError);
}
function emit(value: Readonly<Record<string, unknown>>): void {
  const bytes = JSON.stringify(value) + '\n';
  if (Buffer.byteLength(bytes) > 2048) throw new SpecialistRuntimeError('unavailable');
  try {
    process.stdout.write(bytes);
  } catch {
    /* finite diagnostics are best effort */
  }
}
function isAborted(signal: AbortSignal): boolean {
  return Reflect.apply(
    Object.getOwnPropertyDescriptor(AbortSignal.prototype, 'aborted')!.get!,
    signal,
    [],
  ) as boolean;
}
async function drain(
  runtime: ScriptedPolicySpecialistRuntime,
  final: number,
  startup: Promise<void>,
  initial: Promise<void>,
): Promise<void> {
  let closing = initial;
  while (performance.now() < final) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([startup, closing]),
        new Promise<never>((_r, reject) => {
          timer = setTimeout(
            () => reject(new SpecialistRuntimeError('cleanup_incomplete')),
            Math.max(0, final - performance.now()),
          );
        }),
      ]);
      if (performance.now() >= final) throw new SpecialistRuntimeError('cleanup_incomplete');
      return;
    } catch {
      if (performance.now() >= final) break;
      await new Promise<void>((r) =>
        setTimeout(r, Math.min(20, Math.max(0, final - performance.now()))),
      );
      if (performance.now() < final) closing = runtime.close();
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  throw new SpecialistRuntimeError('cleanup_incomplete');
}
export async function runSpecialistRuntime(
  configuration: SpecialistConfiguration,
  credentials: SpecialistCredentials,
  signal: AbortSignal,
): Promise<void> {
  guardOutput();
  const runtime = new ScriptedPolicySpecialistRuntime(configuration, credentials);
  let stopping = false,
    deadline = 0,
    shutdown: Promise<void> | undefined,
    startupSettlement: Promise<void> = Promise.resolve(),
    notify!: () => void;
  const stopped = new Promise<void>((r) => {
    notify = r;
  });
  const stop = () => {
    if (stopping) return;
    stopping = true;
    deadline = performance.now() + 10000;
    notify();
    shutdown = runtime.close();
    void shutdown.catch(() => {});
  };
  EventTarget.prototype.addEventListener.call(signal, 'abort', stop, { once: true });
  let primary = false,
    cleanupFailed = false;
  try {
    if (isAborted(signal)) stop();
    if (!stopping) {
      const actual = runtime.start();
      startupSettlement = actual.then(
        () => undefined,
        () => undefined,
      );
      const endpoint = await Promise.race([actual, stopped.then(() => undefined)]);
      if (!stopping && endpoint)
        emit({
          schemaVersion: 1,
          status: 'ready',
          label: 'scripted',
          mode: 'scripted_fixed_policy',
          pid: process.pid,
          endpoint,
        });
    }
    if (!stopping) await stopped;
  } catch {
    if (!stopping) primary = true;
  } finally {
    stop();
    EventTarget.prototype.removeEventListener.call(signal, 'abort', stop);
    try {
      await drain(runtime, deadline, startupSettlement, shutdown!);
      emit({
        schemaVersion: 1,
        status: 'closed',
        label: 'scripted',
        cleanupComplete: true,
        metrics: runtime.metrics(),
      });
    } catch {
      cleanupFailed = true;
    }
  }
  if (primary) throw new SpecialistRuntimeError('unavailable');
  if (cleanupFailed) throw new SpecialistRuntimeError('cleanup_incomplete');
}
export async function main(argv: readonly string[], environment: unknown): Promise<number> {
  try {
    if (argv.length === 1 && argv[0] === '--plan') {
      emit(specialistPlan());
      return 0;
    }
    if (argv.length !== 2 || argv[0] !== '--config' || typeof argv[1] !== 'string')
      throw new SpecialistRuntimeError('invalid_configuration');
    const configuration = readSpecialistConfiguration(argv[1]),
      credentials = parseSpecialistEnvironment(environment),
      controller = new AbortController();
    const stop = () => controller.abort();
    process.once('SIGTERM', stop);
    process.once('SIGINT', stop);
    guardOutput();
    try {
      await runSpecialistRuntime(configuration, credentials, controller.signal);
    } finally {
      process.off('SIGTERM', stop);
      process.off('SIGINT', stop);
    }
    return 0;
  } catch (error) {
    try {
      emit({
        schemaVersion: 1,
        status: 'unavailable',
        label: 'scripted',
        code: specialistFailureCode(error),
      });
    } catch {
      /* no private diagnostics */
    }
    return 1;
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  void main(process.argv.slice(2), process.env).then(
    (code) => {
      process.exitCode = code;
    },
    () => {
      process.exitCode = 1;
    },
  );
}
