/** Private strict process wire; a digest binds the complete read-only context. */
import { createHash } from 'node:crypto';
import { ChannelError } from './public-types.js';
import type { AccountScope } from './index.js';
import {
  dispatchFields,
  dispatchScope,
  preparedSubmission,
  type DispatchDecision,
  type InvestigationSubmission,
} from './dispatch-types.js';
export const AGENT_INPUT_BYTES = 32768;
export const AGENT_OUTPUT_BYTES = 2048;
export const AGENT_STDERR_BYTES = 4096;
export type AgentContext = InvestigationSubmission;
export function scopes(value: readonly AccountScope[]): readonly AccountScope[] {
  if (!Array.isArray(value)) throw new ChannelError('InvalidConfiguration');
  const count = value.length;
  if (!Number.isSafeInteger(count) || count < 1 || count > 64)
    throw new ChannelError('InvalidConfiguration');
  try {
    const result: AccountScope[] = [];
    for (let index = 0; index < count; index++) result.push(dispatchScope(value[index]));
    if (new Set(result.map((scope) => JSON.stringify(scope))).size !== result.length)
      throw new Error();
    return Object.freeze(result);
  } catch {
    throw new ChannelError('InvalidConfiguration');
  }
}
export function allowed(context: AgentContext, configured: readonly AccountScope[]): void {
  if (
    !configured.some(
      (scope) =>
        scope.tenantId === context.scope.tenantId && scope.accountId === context.scope.accountId,
    )
  )
    throw new ChannelError('AccessDenied');
}
export function digest(raw: string): string {
  return createHash('sha256').update(raw).digest('hex');
}
export function json(raw: Uint8Array, maximum: number): unknown {
  try {
    if (raw.byteLength < 2 || raw.byteLength > maximum) throw new Error();
    const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
    if (!text.endsWith('\n') || text.endsWith('\n\n')) throw new Error();
    const body = text.slice(0, -1),
      parsed: unknown = JSON.parse(body);
    if (JSON.stringify(parsed) !== body) throw new Error(); // Includes duplicate-key/coercion rejection.
    return parsed;
  } catch {
    throw new ChannelError('OperationConflict');
  }
}
export function request(context: AgentContext): Readonly<{ raw: Buffer; inputDigest: string }> {
  const normalized = preparedSubmission(context).submission;
  const body = JSON.stringify({ schemaVersion: 1, kind: 'agent.prepare', context: normalized });
  const raw = Buffer.from(body + '\n');
  if (raw.byteLength > AGENT_INPUT_BYTES) throw new ChannelError('OperationConflict');
  return Object.freeze({ raw, inputDigest: digest(body) });
}
export function parseRequest(
  raw: Uint8Array,
  configured: readonly AccountScope[],
): Readonly<{ context: AgentContext; inputDigest: string }> {
  const fields = dispatchFields(json(raw, AGENT_INPUT_BYTES), ['schemaVersion', 'kind', 'context']);
  if (fields.schemaVersion !== 1 || fields.kind !== 'agent.prepare')
    throw new ChannelError('OperationConflict');
  const context = preparedSubmission(fields.context).submission;
  allowed(context, configured);
  return Object.freeze({
    context,
    inputDigest: digest(new TextDecoder().decode(raw).slice(0, -1)),
  });
}
export function decision(value: unknown, revision: string): DispatchDecision {
  const fields = dispatchFields(value, ['kind', 'source', 'caseRevision']);
  if (
    fields.kind !== 'investigation' ||
    fields.source !== 'scripted' ||
    fields.caseRevision !== revision
  )
    throw new ChannelError('OperationConflict');
  return Object.freeze({ kind: 'investigation', source: 'scripted', caseRevision: revision });
}
export function response(inputDigest: string, value: unknown, revision: string): Buffer {
  const raw = Buffer.from(
    JSON.stringify({
      schemaVersion: 1,
      kind: 'agent.prepared',
      inputDigest,
      decision: decision(value, revision),
    }) + '\n',
  );
  if (raw.byteLength > AGENT_OUTPUT_BYTES) throw new ChannelError('OperationConflict');
  return raw;
}
export function parseResponse(
  raw: Uint8Array,
  inputDigest: string,
  revision: string,
): DispatchDecision {
  const fields = dispatchFields(json(raw, AGENT_OUTPUT_BYTES), [
    'schemaVersion',
    'kind',
    'inputDigest',
    'decision',
  ]);
  if (
    fields.schemaVersion !== 1 ||
    fields.kind !== 'agent.prepared' ||
    fields.inputDigest !== inputDigest
  )
    throw new ChannelError('OperationConflict');
  return decision(fields.decision, revision);
}
