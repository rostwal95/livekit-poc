import {
  readNativeBridgeConfiguration,
  type NativeBridgeConfiguration,
} from './native-bridge-contract.js';
/** Explicit serving entrypoint. --plan is inert; configuration has no provider credentials. */
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { ChannelPolicyGatewayRuntime } from './runtime.js';
import {
  readRoomControlConfiguration,
  type RoomControlConfiguration,
} from './native-room-contract.js';
import {
  GatewayRuntimeError,
  parseRuntimeEnvironment,
  readRuntimeConfiguration,
  RUNTIME_ENVIRONMENT_KEYS,
  type RuntimeConfiguration,
  type RuntimeCredentials,
} from './runtime-config.js';
export function runtimePlan(): Readonly<Record<string, unknown>> {
  return Object.freeze({
    schemaVersion: 1,
    status: 'planned',
    mode: 'scripted_readonly_policy',
    profileInboxLimit: 16,
    applicationOwners: 9,
    pgPools: 6,
    pgPoolMaxEach: 2,
    listeners: 4,
    operationCallOwners: 2,
    operationObserverMs: 1500,
    operationCleanupMs: 1000,
    shutdownMs: 10000,
    sourceDiscoveryBytes: 8192,
    sourcePreparedBytes: 32768,
    providerCalls: false,
    carrierSends: false,
    servingDDL: false,
    credentialEnvironmentKeys: RUNTIME_ENVIRONMENT_KEYS,
  });
}
function aborted(signal: AbortSignal): boolean {
  return Reflect.apply(
    Object.getOwnPropertyDescriptor(AbortSignal.prototype, 'aborted')!.get!,
    signal,
    [],
  ) as boolean;
}
function outputError(): void {
  /* diagnostic sink failure cannot erase resource ownership */
}
function guardOutput(): void {
  if (!process.stdout.listeners('error').includes(outputError))
    process.stdout.on('error', outputError);
}
function emit(value: Readonly<Record<string, unknown>>): void {
  const raw = JSON.stringify(value) + '\n';
  if (Buffer.byteLength(raw) > 2048) throw new GatewayRuntimeError('unavailable');
  try {
    process.stdout.write(raw);
  } catch {
    /* no private diagnostic or business change */
  }
}
async function drain(
  runtime: ChannelPolicyGatewayRuntime,
  final: number,
  startupSettlement: Promise<void>,
  initialClose: Promise<void>,
): Promise<void> {
  let closing = initialClose;
  while (performance.now() < final) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all([startupSettlement, closing]),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(
            () => reject(new GatewayRuntimeError('cleanup_incomplete')),
            Math.max(0, final - performance.now()),
          );
        }),
      ]);
      if (performance.now() >= final) throw new GatewayRuntimeError('cleanup_incomplete');
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
  throw new GatewayRuntimeError('cleanup_incomplete');
}
/** Programmatic entry receives only a trusted signal; no raw input may choose a grant/scope. */
export async function runGatewayRuntime(
  configuration: RuntimeConfiguration,
  credentials: RuntimeCredentials,
  signal: AbortSignal,
  roomControl?: RoomControlConfiguration,
  nativeBridge?: NativeBridgeConfiguration,
): Promise<void> {
  guardOutput();
  const runtime = new ChannelPolicyGatewayRuntime(
    configuration,
    credentials,
    roomControl,
    nativeBridge,
  );
  let stopping = false,
    shutdownDeadline = 0,
    shutdownClose: Promise<void> | undefined,
    startupSettlement: Promise<void> = Promise.resolve(),
    notify!: () => void;
  const stopped = new Promise<void>((r) => {
    notify = r;
  });
  const stop = () => {
    if (stopping) return;
    stopping = true;
    shutdownDeadline = performance.now() + 10000;
    notify();
    shutdownClose = runtime.close();
    void shutdownClose.catch(() => {});
  };
  EventTarget.prototype.addEventListener.call(signal, 'abort', stop, { once: true });
  let primary: unknown;
  let cleanupFailed = false;
  try {
    if (aborted(signal)) stop();
    if (!stopping) {
      const startup = runtime.start();
      // Keep late startup settlement observed even if trusted stop wins this waiter.
      startupSettlement = startup.then(
        () => undefined,
        () => undefined,
      );
      const endpoints = await Promise.race([startup, stopped.then(() => undefined)]);
      if (!stopping && endpoints)
        emit({
          schemaVersion: 1,
          status: 'ready',
          mode: 'scripted_readonly_policy',
          pid: process.pid,
          profileId: configuration.route.profileId,
          endpoints,
          ...(roomControl ? { roomControl: runtime.roomControlReady() } : {}),
          ...(nativeBridge ? { nativeBridge: runtime.nativeBridgeReady() } : {}),
        });
    }
    if (!stopping) await stopped;
  } catch {
    if (!stopping) primary = new GatewayRuntimeError('unavailable');
  } finally {
    stop();
    EventTarget.prototype.removeEventListener.call(signal, 'abort', stop);
    try {
      await drain(runtime, shutdownDeadline, startupSettlement, shutdownClose!);
      emit({
        schemaVersion: 1,
        status: 'closed',
        cleanupComplete: true,
        metrics: runtime.metrics(),
      });
    } catch {
      cleanupFailed = true;
    }
  }
  if (primary) throw primary;
  if (cleanupFailed) throw new GatewayRuntimeError('cleanup_incomplete');
}
export async function main(argv: readonly string[], environment: unknown): Promise<number> {
  try {
    if (argv.length === 1 && argv[0] === '--plan') {
      emit(runtimePlan());
      return 0;
    }
    if (
      (argv.length !== 2 && argv.length !== 4 && argv.length !== 6) ||
      argv[0] !== '--config' ||
      typeof argv[1] !== 'string' ||
      (argv.length >= 4 && (argv[2] !== '--room-control' || typeof argv[3] !== 'string')) ||
      (argv.length === 6 && (argv[4] !== '--native-bridge' || typeof argv[5] !== 'string'))
    )
      throw new GatewayRuntimeError('invalid_configuration');
    let roomControl: RoomControlConfiguration | undefined;
    if (argv.length >= 4) {
      try {
        roomControl = readRoomControlConfiguration(argv[3]!);
      } catch {
        throw new GatewayRuntimeError('invalid_configuration');
      }
    }
    let nativeBridge: NativeBridgeConfiguration | undefined;
    if (argv.length === 6) {
      try {
        nativeBridge = readNativeBridgeConfiguration(argv[5]!);
      } catch {
        throw new GatewayRuntimeError('invalid_configuration');
      }
    }
    const configuration = readRuntimeConfiguration(argv[1]),
      credentials = parseRuntimeEnvironment(environment),
      controller = new AbortController();
    const stop = () => controller.abort();
    process.once('SIGTERM', stop);
    process.once('SIGINT', stop);
    // Diagnostic sink failure must not throw an unhandled EPIPE over retained runtime resources.
    guardOutput();
    try {
      await runGatewayRuntime(
        configuration,
        credentials,
        controller.signal,
        roomControl,
        nativeBridge,
      );
    } finally {
      process.off('SIGTERM', stop);
      process.off('SIGINT', stop);
    }
    return 0;
  } catch (error) {
    const descriptor =
      error instanceof GatewayRuntimeError
        ? Object.getOwnPropertyDescriptor(error, 'code')
        : undefined;
    const code =
      descriptor &&
      'value' in descriptor &&
      typeof descriptor.value === 'string' &&
      ['invalid_configuration', 'unavailable', 'closed', 'cleanup_incomplete'].includes(
        descriptor.value,
      )
        ? descriptor.value
        : 'unavailable';
    try {
      emit({ schemaVersion: 1, status: 'unavailable', code });
    } catch {
      /* diagnostics cannot grant cleanup or reveal private error */
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
