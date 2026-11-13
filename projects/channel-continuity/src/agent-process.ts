/** Explicit trusted Node worker isolation. No child is created until prepare(). */
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { isAbsolute, extname } from 'node:path';
import { statSync, realpathSync } from 'node:fs';
import type { AccountScope } from './index.js';
import { ChannelError } from './public-types.js';
import {
  dispatchFields,
  prepareDispatch,
  type DispatchDecision,
  type DispatchPorts,
} from './dispatch-types.js';
import {
  AGENT_OUTPUT_BYTES,
  AGENT_STDERR_BYTES,
  allowed,
  parseResponse,
  request,
  scopes,
} from './agent-protocol.js';
export { runAgentWorker, type AgentWorker } from './agent-worker.js';
export type { AgentContext } from './agent-protocol.js';
export type AgentProcessEvent = Readonly<{
  event: 'started' | 'settled';
  pid: number;
  code: 'ok' | 'failed';
  signal: NodeJS.Signals | null;
}>;
export type AgentProcessOptions = Readonly<{
  modulePath: string;
  allowedScopes: readonly AccountScope[];
  environment?: Readonly<Record<string, string>>;
  maxActive?: number;
  timeoutMs?: number;
  cleanupTimeoutMs?: number;
  observer?: (event: AgentProcessEvent) => void | Promise<void>;
}>;
type Task = { child: ChildProcessWithoutNullStreams; settled: Promise<void>; stop: () => void };
function positive(value: unknown, fallback: number, maximum: number): number {
  const selected = value ?? fallback;
  if (
    typeof selected !== 'number' ||
    !Number.isInteger(selected) ||
    selected < 20 ||
    selected > maximum
  )
    throw new ChannelError('InvalidConfiguration');
  return selected;
}
function groupExists(pid: number): boolean {
  try {
    process.kill(-pid, 0);
    return true;
  } catch (error) {
    if (error && typeof error === 'object' && 'code' in error && error.code === 'ESRCH')
      return false;
    return true;
  }
}
function signalGroup(pid: number, signal: NodeJS.Signals): void {
  try {
    process.kill(-pid, signal);
  } catch (error) {
    if (!(error && typeof error === 'object' && 'code' in error && error.code === 'ESRCH'))
      throw new ChannelError('CleanupIncomplete');
  }
}
export class AgentProcess {
  readonly port: DispatchPorts['agent'];
  readonly #module: string;
  readonly #scopes: readonly AccountScope[];
  readonly #environment: Readonly<Record<string, string>>;
  readonly #maximum: number;
  readonly #timeout: number;
  readonly #cleanupMs: number;
  readonly #observer: AgentProcessOptions['observer'];
  readonly #tasks = new Set<Task>();
  #closing = false;
  #notices = 0;
  #counts = {
    started: 0,
    succeeded: 0,
    failed: 0,
    telemetryFailures: 0,
    observerDropped: 0,
    waiterRejected: 0,
  };
  constructor(options: AgentProcessOptions) {
    try {
      const f = dispatchFields(options, [
        'modulePath',
        'allowedScopes',
        ...Object.keys(options).filter((k) => !['modulePath', 'allowedScopes'].includes(k)),
      ]);
      if (
        process.platform === 'win32' ||
        Object.keys(f).some(
          (k) =>
            ![
              'modulePath',
              'allowedScopes',
              'environment',
              'maxActive',
              'timeoutMs',
              'cleanupTimeoutMs',
              'observer',
            ].includes(k),
        )
      )
        throw new Error();
      if (
        typeof options.modulePath !== 'string' ||
        !isAbsolute(options.modulePath) ||
        !['.mjs', '.js'].includes(extname(options.modulePath)) ||
        !statSync(options.modulePath).isFile()
      )
        throw new Error();
      this.#module = realpathSync(options.modulePath);
      this.#scopes = scopes(options.allowedScopes);
      this.#maximum = options.maxActive ?? 1;
      if (!Number.isInteger(this.#maximum) || this.#maximum < 1 || this.#maximum > 2)
        throw new Error();
      this.#timeout = positive(options.timeoutMs, 1000, 5000);
      this.#cleanupMs = positive(options.cleanupTimeoutMs, 1000, 2000);
      if (options.observer !== undefined && typeof options.observer !== 'function')
        throw new Error();
      this.#observer = options.observer;
      const environment = options.environment ?? {};
      if (Object.keys(environment).length > 16) throw new Error();
      const copied: Record<string, string> = Object.create(null) as Record<string, string>;
      let size = 0;
      for (const key of Object.keys(environment)) {
        const d = Object.getOwnPropertyDescriptor(environment, key);
        if (
          !/^P2_AGENT_[A-Z0-9_]+$/.test(key) ||
          !d ||
          !('value' in d) ||
          typeof d.value !== 'string' ||
          d.value.includes('\0') ||
          d.value.length > 1024
        )
          throw new Error();
        copied[key] = d.value;
        size += Buffer.byteLength(key + d.value);
      }
      if (size > 4096) throw new Error();
      this.#environment = Object.freeze(copied);
      this.port = Object.freeze({ prepare: (input, signal) => this.prepare(input, signal) });
    } catch {
      throw new ChannelError('InvalidConfiguration');
    }
  }
  #increment(
    key:
      | 'started'
      | 'succeeded'
      | 'failed'
      | 'telemetryFailures'
      | 'observerDropped'
      | 'waiterRejected',
  ): void {
    this.#counts[key] = Math.min(Number.MAX_SAFE_INTEGER, this.#counts[key] + 1);
  }
  #emit(value: AgentProcessEvent): void {
    if (!this.#observer) return;
    if (this.#notices >= 8) {
      this.#increment('observerDropped');
      return;
    }
    try {
      const observed = this.#observer(Object.freeze(value));
      if (observed && typeof observed.then === 'function') {
        this.#notices++;
        void Promise.resolve(observed)
          .catch(() => {
            this.#increment('telemetryFailures');
          })
          .finally(() => {
            this.#notices--;
          });
      }
    } catch {
      this.#increment('telemetryFailures');
    }
  }
  metrics(): Readonly<Record<string, number>> {
    return Object.freeze({
      ...this.#counts,
      active: this.#tasks.size,
      observerPending: this.#notices,
    });
  }
  async prepare(
    input: Parameters<DispatchPorts['agent']['prepare']>[0],
    signal: AbortSignal,
  ): Promise<DispatchDecision> {
    if (this.#closing || signal.aborted) throw new ChannelError('DispatchUnavailable');
    if (this.#tasks.size >= this.#maximum) throw new ChannelError('Overloaded');
    const context = prepareDispatch(input.message, input.currentCase, {
      kind: 'investigation',
      source: 'scripted',
      caseRevision: input.currentCase.revision,
    }).submission;
    allowed(context, this.#scopes);
    const wire = request(context),
      deadline = performance.now() + this.#timeout;
    let child: ChildProcessWithoutNullStreams;
    try {
      child = spawn(process.execPath, [this.#module], {
        env: { ...this.#environment },
        stdio: ['pipe', 'pipe', 'pipe'],
        detached: true,
        shell: false,
      });
    } catch {
      throw new ChannelError('DispatchUnavailable');
    }
    let resolve!: (decision: DispatchDecision) => void, reject!: (error: ChannelError) => void;
    const result = new Promise<DispatchDecision>((yes, no) => {
      resolve = yes;
      reject = no;
    });
    let settled!: () => void;
    const completion = new Promise<void>((done) => {
      settled = done;
    });
    let error: ChannelError | undefined,
      output = Buffer.alloc(AGENT_OUTPUT_BYTES),
      used = 0,
      stderrBytes = 0,
      closed = false;
    let terminate: ReturnType<typeof setTimeout> | undefined;
    const stop = (): void => {
      if (closed) return;
      error ??= new ChannelError('DispatchUnavailable');
      reject(error); // Waiter leaves; the task/slot remains owned until actual group cleanup.
      const pid = child.pid;
      if (pid === undefined) return;
      try {
        signalGroup(pid, 'SIGTERM');
      } catch {
        error = new ChannelError('CleanupIncomplete');
      }
      if (!terminate)
        terminate = setTimeout(() => {
          terminate = undefined;
          try {
            signalGroup(pid, 'SIGKILL');
          } catch {
            error = new ChannelError('CleanupIncomplete');
          }
        }, 50);
    };
    const task: Task = { child, settled: completion, stop };
    this.#tasks.add(task);
    this.#increment('started');
    const timer = setTimeout(stop, this.#timeout);
    signal.addEventListener('abort', stop, { once: true });
    child.stdin.on('error', () => stop());
    child.stdout.on('error', () => stop());
    child.stderr.on('error', () => stop());
    child.once('error', () => stop());
    child.stdout.on('data', (chunk: Buffer) => {
      if (used + chunk.length > output.length) {
        error = new ChannelError('OperationConflict');
        stop();
        return;
      }
      chunk.copy(output, used);
      used += chunk.length;
    });
    child.stderr.on('data', (chunk: Buffer) => {
      stderrBytes += chunk.length;
      if (stderrBytes > AGENT_STDERR_BYTES) {
        error = new ChannelError('OperationConflict');
        stop();
      }
    });
    const finish = (
      problem: ChannelError | undefined,
      answer: DispatchDecision | undefined,
      exitSignal: NodeJS.Signals | null,
    ): void => {
      if (closed) return;
      const pid = child.pid;
      // Every release path observes the group, not only the ordinary result path.
      if (pid !== undefined && groupExists(pid)) throw new ChannelError('CleanupIncomplete');
      closed = true;
      clearTimeout(timer);
      if (terminate) clearTimeout(terminate);
      signal.removeEventListener('abort', stop);
      this.#tasks.delete(task);
      if (problem) {
        this.#increment('failed');
        reject(problem);
      } else {
        this.#increment('succeeded');
        resolve(answer!);
      }
      // This event describes the validated/reaped worker; caller delivery is guarded separately.
      if (pid !== undefined)
        this.#emit({ event: 'settled', pid, code: problem ? 'failed' : 'ok', signal: exitSignal });
      settled();
    };
    child.once('close', (code, exitSignal) => {
      void (async () => {
        const pid = child.pid;
        if (pid !== undefined && groupExists(pid)) {
          try {
            signalGroup(pid, 'SIGKILL');
          } catch {
            error = new ChannelError('CleanupIncomplete');
          }
          // A close timeout is an observation, not permission to forget live descendants.
          while (groupExists(pid)) await new Promise((done) => setTimeout(done, 5));
        }
        let answer: DispatchDecision | undefined;
        try {
          if (error) throw error;
          if (
            signal.aborted ||
            performance.now() >= deadline ||
            code !== 0 ||
            exitSignal !== null ||
            stderrBytes !== 0
          )
            throw new ChannelError('DispatchUnavailable');
          answer = parseResponse(output.subarray(0, used), wire.inputDigest, context.caseRevision);
        } catch (cause) {
          error = cause instanceof ChannelError ? cause : new ChannelError('DispatchUnavailable');
        }
        finish(error, answer, exitSignal);
      })().catch(() => {
        // Even an unexpected cleanup error cannot release live owned descendants.
        reject(new ChannelError('CleanupIncomplete'));
        void (async () => {
          const pid = child.pid;
          while (pid !== undefined && groupExists(pid)) {
            try {
              signalGroup(pid, 'SIGKILL');
            } catch {
              /* Remain owned until permissions/state permit cleanup. */
            }
            await new Promise((done) => setTimeout(done, 5));
          }
          finish(new ChannelError('CleanupIncomplete'), undefined, exitSignal);
        })().catch(() => {
          /* Keep the actual task/slot retained; close remains incomplete. */
        });
      });
    });
    if (child.pid !== undefined)
      this.#emit({ event: 'started', pid: child.pid, code: 'ok', signal: null });
    if (this.#closing || signal.aborted || performance.now() >= deadline) stop();
    else child.stdin.end(wire.raw);
    const answer = await result;
    if (signal.aborted || performance.now() >= deadline) {
      this.#increment('waiterRejected');
      throw new ChannelError('DispatchUnavailable');
    }
    return answer;
  }
  async close(): Promise<void> {
    const deadline = performance.now() + this.#cleanupMs;
    this.#closing = true;
    const tasks = [...this.#tasks];
    for (const task of tasks) task.stop();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all(tasks.map((task) => task.settled)),
        new Promise<never>((_yes, no) => {
          timer = setTimeout(
            () => no(new ChannelError('CleanupIncomplete')),
            Math.max(0, deadline - performance.now()),
          );
        }),
      ]);
      if (this.#tasks.size || performance.now() >= deadline)
        throw new ChannelError('CleanupIncomplete');
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}
