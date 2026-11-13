/** Optional trusted worker entrypoint. No imported listener, database or model starts. */
import type { AccountScope } from './index.js';
import {
  AGENT_INPUT_BYTES,
  parseRequest,
  response,
  scopes,
  type AgentContext,
} from './agent-protocol.js';
import type { DispatchDecision } from './dispatch-types.js';
import { ChannelError } from './public-types.js';
export type AgentWorker = Readonly<{
  allowedScopes: readonly AccountScope[];
  prepare(context: AgentContext, signal: AbortSignal): Promise<DispatchDecision>;
}>;
/** One canonical frame/decision inside an AgentProcess-owned child. Ignored abort requires its parent process budget. */
export async function runAgentWorker(configuration: AgentWorker): Promise<void> {
  const configured = scopes(configuration.allowedScopes);
  if (typeof configuration.prepare !== 'function') throw new ChannelError('InvalidConfiguration');
  const controller = new AbortController(),
    deadline = performance.now() + 5000;
  const raw = await new Promise<Buffer>((resolve, reject) => {
    const buffer = Buffer.alloc(AGENT_INPUT_BYTES);
    let used = 0,
      settled = false;
    const finish = (error?: Error): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      process.stdin.off('data', data);
      process.stdin.off('end', end);
      process.stdin.off('error', failed);
      if (error) {
        process.stdin.pause();
        reject(error);
      } else resolve(buffer.subarray(0, used));
    };
    const data = (chunk: Buffer): void => {
      if (used + chunk.byteLength > buffer.byteLength) {
        finish(new ChannelError('OperationConflict'));
        return;
      }
      chunk.copy(buffer, used);
      used += chunk.byteLength;
    };
    const end = (): void =>
      finish(performance.now() >= deadline ? new ChannelError('DispatchUnavailable') : undefined);
    const failed = (): void => finish(new ChannelError('DispatchUnavailable'));
    const timer = setTimeout(() => finish(new ChannelError('DispatchUnavailable')), 5000);
    process.stdin.on('data', data);
    process.stdin.once('end', end);
    process.stdin.once('error', failed);
  });
  const input = parseRequest(raw, configured);
  const timeout = setTimeout(() => controller.abort(), Math.max(0, deadline - performance.now()));
  try {
    let answer: DispatchDecision;
    try {
      answer = await configuration.prepare(input.context, controller.signal);
    } catch {
      throw new ChannelError('DispatchUnavailable');
    }
    if (controller.signal.aborted || performance.now() >= deadline)
      throw new ChannelError('DispatchUnavailable');
    const output = response(input.inputDigest, answer, input.context.caseRevision);
    await new Promise<void>((resolve, reject) => {
      process.stdout.write(output, (error) =>
        error ? reject(new ChannelError('DispatchUnavailable')) : resolve(),
      );
    });
    if (performance.now() >= deadline) throw new ChannelError('DispatchUnavailable');
  } finally {
    clearTimeout(timeout);
  }
}
