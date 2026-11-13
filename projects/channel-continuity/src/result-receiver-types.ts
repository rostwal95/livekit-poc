/** Opaque result acceptance is separate from provider delivery and current-case applicability. */
import type { AccountScope } from './index.js';
import type { CurrentCase } from './rehydration-types.js';
export const RESULT_INTENT_BYTES = 16384;
export const RESULT_BODY_BYTES = 8192;
export const RESULT_NATIVE_VIEW_BYTES = 32768;
export const RESULT_NOTICE = 'Your review result is ready. Rejoin this conversation to view it.';
export type ResultReceiverCode =
  | 'InvalidCommand'
  | 'AccessDenied'
  | 'NotFound'
  | 'IdentityConflict'
  | 'Overloaded'
  | 'UpgradeRequired'
  | 'Unavailable'
  | 'AcknowledgementUnknown'
  | 'CleanupIncomplete'
  | 'Closed';
const CODES: readonly string[] = [
  'InvalidCommand',
  'AccessDenied',
  'NotFound',
  'IdentityConflict',
  'Overloaded',
  'UpgradeRequired',
  'Unavailable',
  'AcknowledgementUnknown',
  'CleanupIncomplete',
  'Closed',
];
export class ResultReceiverError extends Error {
  readonly code: ResultReceiverCode;
  constructor(code: ResultReceiverCode = 'Unavailable') {
    const safe = typeof code === 'string' && CODES.includes(code) ? code : 'Unavailable';
    super(safe);
    this.name = 'ResultReceiverError';
    this.code = safe;
  }
}
export type P1ResultIntent = Readonly<{
  delivery_id: string;
  scope: Readonly<{ tenant_id: string; account_id: string }>;
  work_id: string;
  attempt_id: string;
  result_sha256: string;
  receiver_id: string;
  recipient_id: string;
  body: string;
  prepared_at_ms: number;
}>;
export type P1ResultReceipt = Readonly<{
  delivery_id: string;
  receipt_id: string;
  receiver_id: string;
  recipient_id: string;
  result_sha256: string;
  accepted_at_ms: number;
}>;
export type ResultRouteBinding = Readonly<{
  scope: AccountScope;
  caseId: string;
  conversationId: string;
  recipientId: string;
}>;
export type ResultReceiverBinding = ResultRouteBinding & Readonly<{ publisherToken: string }>;
export type ResultReceiverConfiguration = Readonly<{
  receiverId: string;
  bindings: readonly ResultReceiverBinding[];
}>;
export type ResultReaderConfiguration = Readonly<{
  receiverId: string;
  bindings: readonly ResultRouteBinding[];
}>;
export type ResultNativeView = Readonly<{
  schemaVersion: 1;
  intent: P1ResultIntent;
  receipt: P1ResultReceipt;
  case: CurrentCase;
  observed: Readonly<{
    p2ObservedAt: string;
    caseObservedAt: string;
    disclosureAdmittedAt: string;
    atomic: false;
  }>;
}>;
export type ResultReceiverEvent = Readonly<{
  event: 'completed' | 'rejected' | 'waiter_rejected' | 'closed';
  code: 'accepted' | 'found' | 'absent' | 'read' | 'unavailable' | 'rejected' | 'closed';
}>;
export type ResultReceiverOptions = Readonly<{
  maxActive?: number;
  timeoutMs?: number;
  cleanupMs?: number;
  observer?: (event: ResultReceiverEvent) => void | Promise<void>;
}>;
