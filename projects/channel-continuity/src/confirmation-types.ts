/** Exact response-linked user consent. Opaque P1 quote bytes are never parsed/reserialized here. */
import { createHash } from 'node:crypto';
import {
  fields,
  id,
  reference,
  revision,
  sameReference,
  type AcceptedInputPort,
  type CaseReference,
  type RoutingIdentity,
} from './routing-types.js';
import type { StoredMessage } from './postgres.js';
export type ConfirmationCode =
  | 'InvalidCommand'
  | 'AccessDenied'
  | 'RevisionConflict'
  | 'IdentityConflict'
  | 'ClarificationRequired'
  | 'OutcomeUnknown'
  | 'Unavailable'
  | 'Overloaded'
  | 'Closed'
  | 'CleanupIncomplete'
  | 'InvalidAdapterResponse';
const CODES: readonly string[] = [
  'InvalidCommand',
  'AccessDenied',
  'RevisionConflict',
  'IdentityConflict',
  'ClarificationRequired',
  'OutcomeUnknown',
  'Unavailable',
  'Overloaded',
  'Closed',
  'CleanupIncomplete',
  'InvalidAdapterResponse',
];
export class ConfirmationError extends Error {
  readonly code: ConfirmationCode;
  constructor(code: ConfirmationCode) {
    const safe = CODES.includes(code) ? code : 'Unavailable';
    super(safe);
    this.name = 'ConfirmationError';
    this.code = safe;
  }
}
export function safeConfirmationCode(value: unknown): ConfirmationCode | undefined {
  if (!(value instanceof ConfirmationError)) return undefined;
  const d = Object.getOwnPropertyDescriptor(value, 'code');
  return d && 'value' in d && typeof d.value === 'string' && CODES.includes(d.value)
    ? (d.value as ConfirmationCode)
    : undefined;
}
export type PromptReference = CaseReference &
  Readonly<{ conversationId: string; responseId: string }>;
export type ConfirmationPrompt = PromptReference &
  Readonly<{
    schemaVersion: 1;
    revision: string;
    quoteId: string;
    quoteDigest: string;
    quoteJson: string;
  }>;
export type StoredPrompt = ConfirmationPrompt & Readonly<{ registeredAt: string }>;
export interface ConfirmationPromptPort {
  find(reference: PromptReference, signal: AbortSignal): Promise<StoredPrompt | null>;
}
/** This distinct input adapter must recheck current original association before a new call.
 * It is a preflight, not an atomic fence across P2 and the selected authority. */
export interface ConfirmationInputPort extends AcceptedInputPort {
  inspectForConfirmation(accountToken: string, receiptId: string): Promise<StoredMessage>;
}
export type ExactConfirmation = CaseReference &
  Readonly<{
    commandId: string;
    expectedRevision: string;
    quoteId: string;
    quoteDigest: string;
    quoteJson: string;
    explicit: true;
  }>;
export type ConfirmationReceipt = CaseReference &
  Readonly<{
    commandId: string;
    revision: string;
    quoteId: string;
    quoteDigest: string;
    intentId: string;
    effectId: string;
  }>;
export interface ConfirmationAuthorityPort {
  confirm(input: ExactConfirmation, signal: AbortSignal): Promise<ConfirmationReceipt>;
}
export type ConfirmationResult = RoutingIdentity &
  (
    | Readonly<{ status: 'accepted'; responseId: string; receipt: ConfirmationReceipt }>
    | Readonly<{ status: 'clarification_required' | 'outcome_unknown' }>
  );
export type StructuredConfirmation = Readonly<{
  schemaVersion: 1;
  kind: 'case.confirm_quote';
  responseId: string;
  expectedRevision: string;
  quoteDigest: string;
  explicit: true;
}>;
export type ConfirmationEvent = Readonly<{
  event: 'completed' | 'waiter_rejected';
  code: 'accepted' | 'clarification_required' | 'outcome_unknown' | 'unavailable';
}>;
export type ConfirmationOptions = Readonly<{
  maxActive?: number;
  timeoutMs?: number;
  cleanupMs?: number;
  observer?: (event: ConfirmationEvent) => void | Promise<void>;
}>;
export function uuid(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length !== 36 ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/.test(value)
  )
    throw new ConfirmationError('InvalidCommand');
  return value;
}
export function quoteIdentifier(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length !== 36 ||
    !/^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![\s\S])/.test(value)
  )
    throw new ConfirmationError('InvalidCommand');
  return value;
}
export function sha(value: unknown): string {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}(?![\s\S])/.test(value))
    throw new ConfirmationError('InvalidCommand');
  return value;
}
export function quoteBytes(value: unknown): string {
  // P1 canonical JSON is ASCII-escaped. Keep its integer literals and every byte.
  if (
    typeof value !== 'string' ||
    value.length < 2 ||
    value.length > 4096 ||
    !value.startsWith('{') ||
    !value.endsWith('}') ||
    !/^[\x20-\x7e]+(?![\s\S])/.test(value)
  )
    throw new ConfirmationError('InvalidCommand');
  return value;
}
export function quoteDigest(value: string): string {
  return createHash('sha256').update(quoteBytes(value), 'utf8').digest('hex');
}
export function promptReference(value: unknown): PromptReference {
  const r = fields(value, ['scope', 'caseId', 'conversationId', 'responseId']);
  return Object.freeze({
    ...reference({ scope: r.scope, caseId: r.caseId }),
    conversationId: id(r.conversationId),
    responseId: id(r.responseId),
  });
}
export function prompt(value: unknown): ConfirmationPrompt {
  try {
    const r = fields(value, [
      'schemaVersion',
      'scope',
      'caseId',
      'conversationId',
      'responseId',
      'revision',
      'quoteId',
      'quoteDigest',
      'quoteJson',
    ]);
    const ref = promptReference({
      scope: r.scope,
      caseId: r.caseId,
      conversationId: r.conversationId,
      responseId: r.responseId,
    });
    const bytes = quoteBytes(r.quoteJson),
      digest = sha(r.quoteDigest);
    if (r.schemaVersion !== 1 || quoteDigest(bytes) !== digest) throw new Error();
    return Object.freeze({
      schemaVersion: 1,
      ...ref,
      revision: revision(r.revision),
      quoteId: quoteIdentifier(r.quoteId),
      quoteDigest: digest,
      quoteJson: bytes,
    });
  } catch {
    throw new ConfirmationError('InvalidCommand');
  }
}
export function storedPrompt(value: unknown, expected: PromptReference): StoredPrompt {
  try {
    const r = fields(value, [
      'schemaVersion',
      'scope',
      'caseId',
      'conversationId',
      'responseId',
      'revision',
      'quoteId',
      'quoteDigest',
      'quoteJson',
      'registeredAt',
    ]);
    const data = { ...r };
    delete data.registeredAt;
    const checked = prompt(data);
    if (
      !sameReference(checked, expected) ||
      checked.conversationId !== expected.conversationId ||
      checked.responseId !== expected.responseId ||
      typeof r.registeredAt !== 'string' ||
      new Date(r.registeredAt).toISOString() !== r.registeredAt
    )
      throw new Error();
    return Object.freeze({ ...checked, registeredAt: r.registeredAt });
  } catch {
    throw new ConfirmationError('InvalidAdapterResponse');
  }
}
export function exactConfirmation(value: unknown): ExactConfirmation {
  try {
    const r = fields(value, [
      'scope',
      'caseId',
      'commandId',
      'expectedRevision',
      'quoteId',
      'quoteDigest',
      'quoteJson',
      'explicit',
    ]);
    const bytes = quoteBytes(r.quoteJson),
      digest = sha(r.quoteDigest);
    if (r.explicit !== true || quoteDigest(bytes) !== digest) throw new Error();
    return Object.freeze({
      ...reference({ scope: r.scope, caseId: r.caseId }),
      commandId: uuid(r.commandId),
      expectedRevision: revision(r.expectedRevision),
      quoteId: quoteIdentifier(r.quoteId),
      quoteDigest: digest,
      quoteJson: bytes,
      explicit: true,
    });
  } catch {
    throw new ConfirmationError('InvalidCommand');
  }
}
export function confirmationReceipt(
  value: unknown,
  expected: ExactConfirmation,
): ConfirmationReceipt {
  try {
    const r = fields(value, [
      'scope',
      'caseId',
      'commandId',
      'revision',
      'quoteId',
      'quoteDigest',
      'intentId',
      'effectId',
    ]);
    const ref = reference({ scope: r.scope, caseId: r.caseId });
    if (
      !sameReference(ref, expected) ||
      r.commandId !== expected.commandId ||
      r.revision !== expected.expectedRevision ||
      r.quoteId !== expected.quoteId ||
      r.quoteDigest !== expected.quoteDigest
    )
      throw new Error();
    return Object.freeze({
      ...ref,
      commandId: uuid(r.commandId),
      revision: revision(r.revision),
      quoteId: quoteIdentifier(r.quoteId),
      quoteDigest: sha(r.quoteDigest),
      intentId: uuid(r.intentId),
      effectId: uuid(r.effectId),
    });
  } catch {
    throw new ConfirmationError('InvalidAdapterResponse');
  }
}
export function encodeConfirmation(value: StructuredConfirmation): string {
  try {
    const r = fields(value, [
      'schemaVersion',
      'kind',
      'responseId',
      'expectedRevision',
      'quoteDigest',
      'explicit',
    ]);
    if (r.schemaVersion !== 1 || r.kind !== 'case.confirm_quote' || r.explicit !== true)
      throw new Error();
    return JSON.stringify({
      schemaVersion: 1,
      kind: 'case.confirm_quote',
      responseId: id(r.responseId),
      expectedRevision: revision(r.expectedRevision),
      quoteDigest: sha(r.quoteDigest),
      explicit: true,
    });
  } catch {
    throw new ConfirmationError('InvalidCommand');
  }
}
export function linkedAnswer(
  message: StoredMessage,
): Readonly<{ responseId: string; expectedRevision?: string; quoteDigest?: string }> {
  try {
    const event = message.event;
    if (event.type !== 'text.received') throw new Error();
    let responseId: string, expectedRevision: string | undefined, digest: string | undefined;
    if (event.body === 'YES') {
      if (event.replyToResponseId === undefined || event.expectedCaseRevision === undefined)
        throw new Error();
      responseId = id(event.replyToResponseId);
      expectedRevision = String(event.expectedCaseRevision);
    } else if (event.body.startsWith('YES ')) {
      responseId = id(event.body.slice(4));
    } else {
      const decoded = JSON.parse(event.body) as StructuredConfirmation;
      if (encodeConfirmation(decoded) !== event.body) throw new Error();
      responseId = id(decoded.responseId);
      expectedRevision = revision(decoded.expectedRevision);
      digest = sha(decoded.quoteDigest);
    }
    if (
      (event.replyToResponseId !== undefined && event.replyToResponseId !== responseId) ||
      (event.expectedCaseRevision !== undefined &&
        expectedRevision !== undefined &&
        String(event.expectedCaseRevision) !== expectedRevision)
    )
      throw new Error();
    if (event.expectedCaseRevision !== undefined)
      expectedRevision = String(event.expectedCaseRevision);
    return Object.freeze({
      responseId,
      ...(expectedRevision === undefined ? {} : { expectedRevision }),
      ...(digest === undefined ? {} : { quoteDigest: digest }),
    });
  } catch {
    throw new ConfirmationError('ClarificationRequired');
  }
}
