/** Authenticated P1 observations. Only exact operator commands can confirm a quote. */

const encoder = new TextEncoder();
export const MAX_BUSINESS_RESPONSE_BYTES = 65_536;
export const MAX_BUSINESS_EVENTS = 100;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const DECIMAL = /^(0|[1-9][0-9]{0,18})$/;
const MAX_INTEGER = 9223372036854775807n;
const REQUEST_KEYS = ['booking_reference', 'new_check_in', 'confirmed'];
const ROOT_KEYS = ['schema_version', 'task_id', 'case_id', 'case_revision', 'request_key', 'request', 'inquiry', 'lifecycle', 'quote', 'confirmation', 'effect', 'outcome', 'delivery', 'events', 'projection_revision', 'next_cursor', 'has_more', 'cursor_reset', 'events_total', 'history_truncated'];
const LIFECYCLE_STATES = ['ready', 'running', 'retry_wait', 'inquiry_complete', 'waiting', 'intent_committed', 'failed', 'uncertain', 'completed', 'cancelled'] as const;
const EFFECT_STATES = ['pending', 'claimed', 'dispatched', 'succeeded', 'failed', 'uncertain', 'cancelled'] as const;
const DELIVERY_STATES = ['pending', 'delivering', 'delivered', 'exhausted'] as const;
const EVENT_KINDS = ['task', 'inquiry_attempt', 'quote', 'confirmation', 'wait', 'mutation_attempt', 'cancellation', 'outcome', 'delivery'] as const;
const ERROR_CODES = new Set(['inquiry_rejected', 'dependency_unavailable', 'permanent_failure', 'retry_exhausted', 'deadline_expired', 'ambiguous_outcome', 'supplier_rejected', 'attempts_exhausted', 'delivery_exhausted']);
export type LifecycleState = typeof LIFECYCLE_STATES[number];
export type EffectState = typeof EFFECT_STATES[number];
export type DeliveryState = typeof DELIVERY_STATES[number];
export type BusinessErrorCode = 'invalid' | 'unauthorized' | 'conflict' | 'unknown' | 'unavailable';
export class BusinessError extends Error {
  constructor(readonly code: BusinessErrorCode, message: string) { super(message); }
}
export interface BusinessInput { booking_reference: string; new_check_in: string; confirmed: boolean; idempotency_key: string }
export interface BusinessRequest { readonly booking_reference: string; readonly new_check_in: string; readonly confirmed: true }
export interface BusinessQuote {
  readonly schema_version: 2; readonly quote_id: string; readonly task_id: string; readonly revision: string;
  readonly booking_reference: string; readonly new_check_in: string; readonly amount_minor: number; readonly currency: string;
  readonly expires_at: string; readonly case_id: string; readonly expected_supplier_revision: string; readonly supplier_id: string;
  readonly confirmation_payload: string;
}
export interface BusinessInquiry {
  readonly request: BusinessRequest; readonly state: 'accepted' | 'running' | 'succeeded' | 'failed'; readonly version: string; readonly effect_id: string;
  readonly result: null | { readonly booking_reference: string; readonly new_check_in: string; readonly available: boolean };
  readonly error_code: string | null; readonly created_at: string; readonly updated_at: string;
}
export interface BusinessLifecycle {
  readonly state: LifecycleState; readonly version: string; readonly deadline: string; readonly next_attempt_at: string | null;
  readonly error_code: string | null; readonly last_failure: 'transient' | 'permanent' | 'ambiguous' | null;
  readonly lease: null | { readonly owner_id: string | null; readonly epoch: string; readonly expires_at: string | null; readonly claimed_at: string; readonly renewed_at: string };
}
export type ObservedResult = Readonly<Record<string, string | number | boolean | null>>;
export type BusinessMutationResult = Readonly<{
  schema_version: 1; effect_id: string; intent_id: string; task_id: string; case_id: string; supplier_id: string; scope_id: string;
  booking_reference: string; previous_check_in: string; new_check_in: string; previous_revision: string; revision: string;
  amount_minor: number; currency: string; created_at: string;
}>;
export interface BusinessEffect {
  readonly state: EffectState; readonly generation: string; readonly attempt_no: number; readonly dispatch_count: number;
  readonly result: BusinessMutationResult | null; readonly error_code: string | null; readonly updated_at: string;
}
export interface BusinessOutcome {
  readonly state: 'succeeded' | 'failed' | 'uncertain' | 'cancelled'; readonly result: BusinessMutationResult | null;
  readonly error_code: string | null; readonly cancellation: string; readonly created_at: string;
  readonly intent_id: string | null; readonly effect_id: string | null; readonly event_id: string;
}
export interface BusinessDelivery {
  readonly state: DeliveryState; readonly event_id: string; readonly target_id: string | null; readonly generation: string;
  readonly attempts: number; readonly next_attempt_at: string | null; readonly error_code: string | null; readonly updated_at: string;
}
export interface BusinessEvent { readonly event_id: string; readonly kind: typeof EVENT_KINDS[number]; readonly state: string; readonly observed_at: string; readonly details: ObservedResult }
export interface BusinessProjection {
  readonly schema_version: 1; readonly task_id: string; readonly case_id: string; readonly case_revision: string; readonly request_key: string;
  readonly request: BusinessRequest; readonly inquiry: BusinessInquiry; readonly lifecycle: BusinessLifecycle | null;
  readonly quote: BusinessQuote | null;
  readonly confirmation: { readonly state: 'not_requested' | 'required' | 'committed' | 'cancelled'; readonly intent_id: string | null; readonly confirmation_id: string | null; readonly committed_at: string | null };
  readonly effect: BusinessEffect | null; readonly outcome: BusinessOutcome | null; readonly delivery: BusinessDelivery | null;
  readonly events: readonly BusinessEvent[]; readonly projection_revision: string; readonly next_cursor: string | null;
  readonly has_more: boolean; readonly cursor_reset: boolean; readonly events_total: number; readonly history_truncated: boolean;
}
export interface ManagedReceipt { readonly created: boolean; readonly task_id: string; readonly case_id: string; readonly projection: BusinessProjection }
export type CommandKind = 'quote' | 'signal' | 'cancel';
export interface CommandReceipt { readonly command_id: string; readonly created: boolean; readonly quote_id?: string; readonly signal_id?: string; readonly cancellation_id?: string; readonly disposition?: string }
export interface CommandResponse { readonly projection: BusinessProjection; readonly receipt: CommandReceipt }
export interface PendingCommand { readonly kind: CommandKind; readonly task_id: string; readonly command_id: string; readonly body: Readonly<Record<string, string | boolean>>; readonly uncertain: boolean }
export interface BusinessState {
  readonly phase: 'idle' | 'busy' | 'observed' | 'unknown' | 'error' | 'access_required'; readonly operation: 'submit' | 'refresh' | 'more' | CommandKind | null;
  readonly task_id: string | null; readonly projection: BusinessProjection | null; readonly events: readonly BusinessEvent[];
  readonly pending_input: Readonly<BusinessInput> | null; readonly pending_command: PendingCommand | null;
  readonly history_limited: boolean; readonly message: string; readonly error_code: BusinessErrorCode | null;
}

function invalid(message = 'The server observation could not be verified. Refresh the same case.'): never { throw new BusinessError('unknown', message); }
function object(value: unknown, keys?: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
  const item = value as Record<string, unknown>;
  if (keys && (Object.keys(item).length !== keys.length || keys.some((key) => !(key in item)))) return invalid();
  return item;
}
function text(value: unknown, maximum = 512): string {
  if (typeof value !== 'string' || !value || encoder.encode(value).length > maximum || /[\u0000-\u001f\u007f]/.test(value)) return invalid();
  return value;
}
function uuid(value: unknown): string { const result = text(value, 36); if (!UUID.test(result)) return invalid(); return result; }
function decimal(value: unknown, maximum = MAX_INTEGER): string {
  if (typeof value !== 'string' || !DECIMAL.test(value) || BigInt(value) > maximum) return invalid();
  return value;
}
function count(value: unknown, maximum = 1_000_000): number { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0 || value > maximum) return invalid(); return value; }
function boolean(value: unknown): boolean { if (typeof value !== 'boolean') return invalid(); return value; }
function nullable<T>(value: unknown, parse: (item: unknown) => T): T | null { return value === null ? null : parse(value); }
function instant(value: unknown): string { const result = text(value, 64); if (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+]00:00)$/.test(result) || Number.isNaN(Date.parse(result))) return invalid(); return result; }
function date(value: unknown): string {
  const result = text(value, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result) || Number.isNaN(Date.parse(result)) || new Date(result).toISOString().slice(0, 10) !== result) return invalid();
  return result;
}
function choice<T extends string>(value: unknown, options: readonly T[]): T { if (typeof value !== 'string' || !options.includes(value as T)) return invalid(); return value as T; }
function errorCode(value: unknown): string | null { if (value === null) return null; const code = text(value, 64); if (!ERROR_CODES.has(code)) return invalid(); return code; }
function freeze<T>(value: T): T { if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } return value; }
function observations(value: unknown): ObservedResult {
  const item = object(value); if (Object.keys(item).length > 20) return invalid();
  const result: Record<string, string | number | boolean | null> = {};
  for (const [key, field] of Object.entries(item)) {
    if (!/^[a-z][a-z0-9_]{0,47}$/.test(key)) return invalid();
    if (field === null || typeof field === 'boolean') result[key] = field;
    else if (typeof field === 'number') result[key] = count(field, Number.MAX_SAFE_INTEGER);
    else result[key] = text(field, 512);
  }
  return result;
}
function request(value: unknown): BusinessRequest {
  const item = object(value, REQUEST_KEYS); if (item.confirmed !== true) return invalid();
  return { booking_reference: text(item.booking_reference, 256), new_check_in: date(item.new_check_in), confirmed: true };
}
function asciiString(value: string): string { return JSON.stringify(value).replace(/[\u007f-\uffff]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`); }
/** Verification uses raw decimal lexemes; the actual command always forwards the original opaque bytes. */
export function verifyQuotePayload(quote: BusinessQuote): void {
  const strings: Record<string, string> = { booking_reference: quote.booking_reference, case_id: quote.case_id, currency: quote.currency, expires_at: quote.expires_at, new_check_in: quote.new_check_in, quote_id: quote.quote_id, supplier_id: quote.supplier_id, task_id: quote.task_id };
  const fields: Record<string, string> = { amount_minor: String(quote.amount_minor), expected_supplier_revision: quote.expected_supplier_revision, revision: quote.revision, schema_version: '2' };
  for (const [key, value] of Object.entries(strings)) fields[key] = asciiString(value);
  const expected = '{' + Object.keys(fields).sort().map((key) => `${JSON.stringify(key)}:${fields[key]}`).join(',') + '}';
  if (quote.confirmation_payload !== expected) return invalid('The displayed quote does not match its exact confirmation payload. Refresh the same case.');
}
function parseQuote(value: unknown, taskId: string, caseId: string, revision: string, current: BusinessRequest): BusinessQuote {
  const item = object(value, ['schema_version', 'quote_id', 'task_id', 'revision', 'booking_reference', 'new_check_in', 'amount_minor', 'currency', 'expires_at', 'case_id', 'expected_supplier_revision', 'supplier_id', 'confirmation_payload']);
  if (item.schema_version !== 2) return invalid();
  const quote: BusinessQuote = { schema_version: 2, quote_id: uuid(item.quote_id), task_id: uuid(item.task_id), revision: decimal(item.revision), booking_reference: text(item.booking_reference, 256), new_check_in: date(item.new_check_in), amount_minor: count(item.amount_minor, Number.MAX_SAFE_INTEGER), currency: choice(item.currency, ['USD', 'EUR', 'GBP', 'INR']), expires_at: instant(item.expires_at), case_id: uuid(item.case_id), expected_supplier_revision: decimal(item.expected_supplier_revision, MAX_INTEGER - 1n), supplier_id: uuid(item.supplier_id), confirmation_payload: text(item.confirmation_payload, 4096) };
  if (quote.task_id !== taskId || quote.case_id !== caseId || quote.revision !== revision || quote.booking_reference !== current.booking_reference || quote.new_check_in !== current.new_check_in) return invalid();
  verifyQuotePayload(quote); return quote;
}
function parseInquiry(value: unknown): BusinessInquiry {
  const item = object(value, ['request', 'state', 'version', 'effect_id', 'result', 'error_code', 'created_at', 'updated_at']);
  return { request: request(item.request), state: choice(item.state, ['accepted', 'running', 'succeeded', 'failed']), version: decimal(item.version), effect_id: uuid(item.effect_id), result: nullable(item.result, (value) => { const data = object(value, ['booking_reference', 'new_check_in', 'available']); return { booking_reference: text(data.booking_reference, 256), new_check_in: date(data.new_check_in), available: boolean(data.available) }; }), error_code: errorCode(item.error_code), created_at: instant(item.created_at), updated_at: instant(item.updated_at) };
}
function parseLifecycle(value: unknown): BusinessLifecycle {
  const item = object(value, ['state', 'version', 'deadline', 'next_attempt_at', 'error_code', 'last_failure', 'lease']);
  return { state: choice(item.state, LIFECYCLE_STATES), version: decimal(item.version), deadline: instant(item.deadline), next_attempt_at: nullable(item.next_attempt_at, instant), error_code: errorCode(item.error_code), last_failure: nullable(item.last_failure, (value) => choice(value, ['transient', 'permanent', 'ambiguous'])), lease: nullable(item.lease, (value) => { const data = object(value, ['owner_id', 'epoch', 'expires_at', 'claimed_at', 'renewed_at']); return { owner_id: nullable(data.owner_id, uuid), epoch: decimal(data.epoch), expires_at: nullable(data.expires_at, instant), claimed_at: instant(data.claimed_at), renewed_at: instant(data.renewed_at) }; }) };
}
function parseMutationResult(value: unknown): BusinessMutationResult {
  const item = object(value, ['schema_version', 'effect_id', 'intent_id', 'task_id', 'case_id', 'supplier_id', 'scope_id', 'booking_reference', 'previous_check_in', 'new_check_in', 'previous_revision', 'revision', 'amount_minor', 'currency', 'created_at']);
  if (item.schema_version !== 1) return invalid();
  const result: BusinessMutationResult = { schema_version: 1, effect_id: uuid(item.effect_id), intent_id: uuid(item.intent_id), task_id: uuid(item.task_id), case_id: uuid(item.case_id), supplier_id: uuid(item.supplier_id), scope_id: text(item.scope_id, 512), booking_reference: text(item.booking_reference, 256), previous_check_in: date(item.previous_check_in), new_check_in: date(item.new_check_in), previous_revision: decimal(item.previous_revision, MAX_INTEGER - 1n), revision: decimal(item.revision), amount_minor: count(item.amount_minor, Number.MAX_SAFE_INTEGER), currency: choice(item.currency, ['USD', 'EUR', 'GBP', 'INR']), created_at: instant(item.created_at) };
  if (BigInt(result.revision) !== BigInt(result.previous_revision) + 1n || result.case_id === result.task_id) return invalid();
  return result;
}
function parseEffect(value: unknown): BusinessEffect {
  const item = object(value, ['state', 'generation', 'attempt_no', 'dispatch_count', 'result', 'error_code', 'updated_at']);
  const result = { state: choice(item.state, EFFECT_STATES), generation: decimal(item.generation), attempt_no: count(item.attempt_no, 100), dispatch_count: count(item.dispatch_count, 100), result: nullable(item.result, parseMutationResult), error_code: errorCode(item.error_code), updated_at: instant(item.updated_at) };
  if (result.dispatch_count > result.attempt_no || (result.state === 'succeeded') !== (result.result !== null) || (['failed', 'uncertain'].includes(result.state) && result.error_code === null) || (['succeeded', 'cancelled'].includes(result.state) && result.error_code !== null)) return invalid(); return result;
}
function parseOutcome(value: unknown): BusinessOutcome {
  const item = object(value, ['state', 'result', 'error_code', 'cancellation', 'created_at', 'intent_id', 'effect_id', 'event_id']);
  const result = { state: choice(item.state, ['succeeded', 'failed', 'uncertain', 'cancelled'] as const), result: nullable(item.result, parseMutationResult), error_code: errorCode(item.error_code), cancellation: choice(item.cancellation, ['not_requested', 'cancelled_before_commit', 'cancelled_before_dispatch', 'requested_best_effort', 'already_terminal']), created_at: instant(item.created_at), intent_id: nullable(item.intent_id, uuid), effect_id: nullable(item.effect_id, uuid), event_id: uuid(item.event_id) };
  if ((result.state === 'succeeded') !== (result.result !== null) || (result.intent_id === null) !== (result.effect_id === null) || (['failed', 'uncertain'].includes(result.state) && result.error_code === null) || (['succeeded', 'cancelled'].includes(result.state) && result.error_code !== null) || (result.state === 'cancelled' && !['cancelled_before_commit', 'cancelled_before_dispatch'].includes(result.cancellation))) return invalid(); return result;
}
function parseDelivery(value: unknown): BusinessDelivery {
  const item = object(value, ['state', 'event_id', 'target_id', 'generation', 'attempts', 'next_attempt_at', 'error_code', 'updated_at']);
  return { state: choice(item.state, DELIVERY_STATES), event_id: uuid(item.event_id), target_id: nullable(item.target_id, uuid), generation: decimal(item.generation), attempts: count(item.attempts, 100), next_attempt_at: nullable(item.next_attempt_at, instant), error_code: nullable(item.error_code, (value) => choice(value, ['dependency_unavailable', 'delivery_exhausted'])), updated_at: instant(item.updated_at) };
}
function parseEvent(value: unknown): BusinessEvent {
  const item = object(value, ['event_id', 'kind', 'state', 'observed_at', 'details']);
  return { event_id: text(item.event_id, 160), kind: choice(item.kind, EVENT_KINDS), state: text(item.state, 64), observed_at: instant(item.observed_at), details: observations(item.details) };
}
export function parseBusinessProjection(value: unknown, expectedTaskId?: string): BusinessProjection {
  const item = object(value, ROOT_KEYS); if (item.schema_version !== 1) return invalid();
  const taskId = uuid(item.task_id), caseId = uuid(item.case_id), revision = decimal(item.case_revision), current = request(item.request);
  if (taskId === caseId || (expectedTaskId !== undefined && taskId !== expectedTaskId)) return invalid();
  const confirmation = object(item.confirmation, ['state', 'intent_id', 'confirmation_id', 'committed_at']);
  if (!Array.isArray(item.events) || item.events.length > 50) return invalid();
  const events = item.events.map(parseEvent); if (new Set(events.map((event) => event.event_id)).size !== events.length) return invalid();
  const result: BusinessProjection = { schema_version: 1, task_id: taskId, case_id: caseId, case_revision: revision, request_key: text(item.request_key, 128), request: current, inquiry: parseInquiry(item.inquiry), lifecycle: nullable(item.lifecycle, parseLifecycle), quote: nullable(item.quote, (value) => parseQuote(value, taskId, caseId, revision, current)), confirmation: { state: choice(confirmation.state, ['not_requested', 'required', 'committed', 'cancelled']), intent_id: nullable(confirmation.intent_id, uuid), confirmation_id: nullable(confirmation.confirmation_id, uuid), committed_at: nullable(confirmation.committed_at, instant) }, effect: nullable(item.effect, parseEffect), outcome: nullable(item.outcome, parseOutcome), delivery: nullable(item.delivery, parseDelivery), events, projection_revision: text(item.projection_revision, 64), next_cursor: nullable(item.next_cursor, (value) => text(value, 512)), has_more: boolean(item.has_more), cursor_reset: boolean(item.cursor_reset), events_total: count(item.events_total, Number.MAX_SAFE_INTEGER), history_truncated: boolean(item.history_truncated) };
  if (!/^[0-9a-f]{64}$/.test(result.projection_revision) || result.has_more !== (result.next_cursor !== null) || result.events_total < events.length || (result.confirmation.state === 'committed') !== (result.confirmation.intent_id !== null) || (result.confirmation.intent_id === null) !== (result.confirmation.confirmation_id === null)) return invalid();
  if (result.delivery && (!result.outcome || result.delivery.event_id !== result.outcome.event_id)) return invalid();
  if (result.effect && result.outcome && result.effect.state !== result.outcome.state) return invalid();
  if (result.confirmation.state === 'required' && result.quote === null) return invalid();
  if (result.confirmation.state === 'committed' && result.confirmation.committed_at === null) return invalid();
  if (result.effect && ['succeeded', 'failed', 'uncertain', 'cancelled'].includes(result.effect.state) && result.outcome === null) return invalid();
  if (result.outcome && result.outcome.state !== 'cancelled' && result.effect === null) return invalid();
  if (result.delivery && ((result.delivery.attempts > 0 && result.delivery.target_id === null) || (result.delivery.state === 'pending') !== (result.delivery.next_attempt_at !== null))) return invalid();
  if (result.lifecycle?.lease) { const lease = result.lifecycle.lease; if (BigInt(lease.epoch) < 1n || (lease.owner_id === null) !== (lease.expires_at === null) || Date.parse(lease.renewed_at) < Date.parse(lease.claimed_at) || (lease.expires_at !== null && Date.parse(lease.expires_at) <= Date.parse(lease.renewed_at))) return invalid(); }
  for (const evidence of [result.effect?.result, result.outcome?.result]) {
    if (!evidence) continue;
    const quote = result.quote;
    if (!quote || evidence.task_id !== result.task_id || evidence.case_id !== result.case_id || evidence.intent_id !== result.confirmation.intent_id || evidence.booking_reference !== result.request.booking_reference || evidence.new_check_in !== result.request.new_check_in || evidence.supplier_id !== quote.supplier_id || evidence.previous_revision !== quote.expected_supplier_revision || evidence.amount_minor !== quote.amount_minor || evidence.currency !== quote.currency || (result.outcome && (evidence.intent_id !== result.outcome.intent_id || evidence.effect_id !== result.outcome.effect_id))) return invalid();
  }
  if (result.effect?.result && result.outcome?.result && JSON.stringify(result.effect.result) !== JSON.stringify(result.outcome.result)) return invalid();
  return freeze(result);
}
export function validateBusinessInput(input: BusinessInput): BusinessInput {
  if (typeof input.booking_reference !== 'string' || /[\u0000-\u001f\u007f]/.test(input.booking_reference) || !input.booking_reference.trim() || [...input.booking_reference.trim()].length > 64 || input.confirmed !== true || !/^[A-Za-z0-9_-]{1,128}$/.test(input.idempotency_key)) throw new BusinessError('invalid', 'Confirm an investigation and enter a valid booking and request identity.');
  try { date(input.new_check_in); } catch { throw new BusinessError('invalid', 'Choose a valid check-in date.'); }
  return freeze({ ...input, booking_reference: input.booking_reference.trim().toUpperCase() });
}
export function parseManagedReceipt(value: unknown, input: BusinessInput): ManagedReceipt {
  const item = object(value, ['created', 'task_id', 'case_id', 'projection']);
  const taskId = uuid(item.task_id), caseId = uuid(item.case_id), projection = parseBusinessProjection(item.projection, taskId);
  if (caseId !== projection.case_id || projection.request_key !== input.idempotency_key || projection.inquiry.request.booking_reference !== input.booking_reference || projection.inquiry.request.new_check_in !== input.new_check_in || projection.inquiry.request.confirmed !== input.confirmed) return invalid('The acceptance did not match the frozen request. Retry its original identity.');
  return freeze({ created: boolean(item.created), task_id: taskId, case_id: caseId, projection });
}
export function parseBusinessJson(value: string): unknown {
  const parsed: unknown = JSON.parse(value);
  const stack: (Set<string> | null)[] = [];
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (character === '{' || character === '[') { stack.push(character === '{' ? new Set<string>() : null); if (stack.length > 16) return invalid(); }
    else if (character === '}' || character === ']') stack.pop();
    else if (character === '"') {
      const start = index; index += 1;
      while (index < value.length) { if (value[index] === '\\') index += 2; else if (value[index] === '"') break; else index += 1; }
      let following = index + 1; while (/\s/.test(value[following] ?? '') && following < value.length) following += 1;
      if (value[following] === ':') {
        const keys = stack.at(-1); if (!keys) return invalid();
        const key: unknown = JSON.parse(value.slice(start, index + 1)); if (typeof key !== 'string' || keys.has(key)) return invalid(); keys.add(key);
      }
    }
  }
  return parsed;
}
export async function readBusinessResponse(response: Response): Promise<unknown> {
  if (!response.body) return invalid();
  const reader = response.body.getReader(), decoder = new TextDecoder('utf-8', { fatal: true });
  let body = '', bytes = 0;
  try {
    while (true) { const part = await reader.read(); if (part.done) break; bytes += part.value.byteLength; if (bytes > MAX_BUSINESS_RESPONSE_BYTES) return invalid(); body += decoder.decode(part.value, { stream: true }); }
    body += decoder.decode(); return parseBusinessJson(body);
  } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
}
export class BusinessClient {
  constructor(private readonly fetcher: typeof fetch = fetch) {}
  private async call(path: string, token: string, body?: unknown, signal?: AbortSignal): Promise<unknown> {
    if (token.length < 16 || token.length > 512 || /\s/.test(token))
      throw new BusinessError('unauthorized', 'Enter the local operator key.');
    const deadline = AbortSignal.timeout(8_000);
    try {
      // Native Window.fetch rejects a BusinessClient receiver; invoke the port as a function.
      const fetcher = this.fetcher;
      const response = await fetcher(path, { method: body === undefined ? 'GET' : 'POST', headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: signal ? AbortSignal.any([signal, deadline]) : deadline, credentials: 'omit', cache: 'no-store' });
      if (response.status === 401 || response.status === 403) throw new BusinessError('unauthorized', 'Operator access was denied. Enter the local token again.');
      if (response.status === 409) throw new BusinessError('conflict', 'The command conflicts with current case facts. Refresh and inspect the same case.');
      if (response.status === 422 || response.status === 413) throw new BusinessError('invalid', 'The command was rejected. Check its fields and current case facts.');
      if (!response.ok) throw new BusinessError(body === undefined ? 'unavailable' : 'unknown', body === undefined ? 'Case observations are temporarily unavailable. The stored work remains independent.' : 'No durable acknowledgement was verified. Reconcile the original command identity.');
      return await readBusinessResponse(response);
    } catch (error) { if (error instanceof BusinessError) throw error; throw new BusinessError(body === undefined ? 'unavailable' : 'unknown', body === undefined ? 'The current case could not be read. Refresh its original identity.' : 'The command outcome is unknown. Retry the same frozen identity to reconcile.'); }
  }
  async submit(input: BusinessInput, token: string, signal?: AbortSignal): Promise<ManagedReceipt> { const frozen = validateBusinessInput(input); return parseManagedReceipt(await this.call('/api/business/investigations', token, frozen, signal), frozen); }
  async get(taskId: string, token: string, cursor?: string, signal?: AbortSignal): Promise<BusinessProjection> { uuid(taskId); if (cursor !== undefined) text(cursor, 512); const query = new URLSearchParams({ limit: '10', ...(cursor === undefined ? {} : { cursor }) }); return parseBusinessProjection(await this.call(`/api/business/cases/${encodeURIComponent(taskId)}?${query}`, token, undefined, signal), taskId); }
  async command(command: PendingCommand, token: string, signal?: AbortSignal): Promise<CommandResponse> {
    uuid(command.task_id); text(command.command_id, 128);
    const body = object(command.body, command.kind === 'quote' ? ['command_id', 'expected_revision'] : command.kind === 'signal' ? ['command_id', 'confirmation_payload', 'explicit'] : ['command_id']);
    if (body.command_id !== command.command_id) return invalid();
    if (command.kind === 'quote') decimal(body.expected_revision);
    if (command.kind === 'signal' && (body.explicit !== true || typeof body.confirmation_payload !== 'string' || encoder.encode(body.confirmation_payload).length > 4096)) return invalid();
    const response = object(await this.call(`/api/business/cases/${encodeURIComponent(command.task_id)}/${command.kind}`, token, command.body, signal), ['projection', 'receipt']);
    const raw = object(response.receipt); const idField = command.kind === 'quote' ? 'quote_id' : command.kind === 'signal' ? 'signal_id' : 'cancellation_id';
    const keys = ['command_id', 'created', idField, ...(command.kind === 'cancel' ? ['disposition'] : [])];
    object(raw, keys); if (raw.command_id !== command.command_id) return invalid('The command acknowledgement did not match its frozen identity. Reconcile the original command.');
    const receipt: CommandReceipt = { command_id: command.command_id, created: boolean(raw.created), [idField]: uuid(raw[idField]), ...(command.kind === 'cancel' ? { disposition: choice(raw.disposition, ['cancelled_before_commit', 'cancelled_before_dispatch', 'requested_best_effort', 'already_terminal']) } : {}) };
    return freeze({ projection: parseBusinessProjection(response.projection, command.task_id), receipt });
  }
}

const INITIAL: BusinessState = freeze({ phase: 'idle', operation: null, task_id: null, projection: null, events: [], pending_input: null, pending_command: null, history_limited: false, message: 'Submit a confirmed investigation or inspect an existing task.', error_code: null });
export class BusinessController {
  private value: BusinessState = INITIAL;
  private pending: AbortController | null = null;
  private generation = 0;
  private disposed = false;
  private uncertainAcceptance = false;
  constructor(private readonly changed: (state: BusinessState) => void, private readonly client = new BusinessClient(), private readonly makeId = () => `ui-${crypto.randomUUID()}`) {}
  get state(): BusinessState { return this.value; }
  private publish(next: Partial<BusinessState>): void { this.value = freeze({ ...this.value, ...next }); try { this.changed(this.value); } catch { /* Presentation cannot change an accepted receipt. */ } }
  private begin(operation: BusinessState['operation']): { signal: AbortSignal; generation: number } | null { if (this.disposed || this.pending) return null; this.pending = new AbortController(); const generation = ++this.generation; this.publish({ phase: 'busy', operation, error_code: null, message: operation === 'refresh' || operation === 'more' ? 'Reading persisted observations…' : 'Awaiting a durable acknowledgement…' }); return { signal: this.pending.signal, generation }; }
  private current(generation: number): boolean { return !this.disposed && this.generation === generation; }
  private finish(generation: number): void { if (this.current(generation)) { this.pending = null; this.publish({ operation: null }); } }
  private accept(projection: BusinessProjection, more = false): void {
    const prior = this.value.projection;
    if (prior && prior.task_id === projection.task_id && (prior.case_id !== projection.case_id || BigInt(projection.case_revision) < BigInt(prior.case_revision))) return invalid();
    const same = prior?.projection_revision === projection.projection_revision && !projection.cursor_reset;
    const events = same ? [...this.value.events] : [];
    for (const event of projection.events) {
      const previous = events.find((item) => item.event_id === event.event_id);
      if (previous && JSON.stringify(previous) !== JSON.stringify(event)) return invalid();
      if (!previous) events.push(event);
    }
    const historyLimited = events.length > MAX_BUSINESS_EVENTS || (events.length >= MAX_BUSINESS_EVENTS && projection.has_more) || projection.history_truncated;
    const observed = same && !more && prior ? { ...projection, next_cursor: prior.next_cursor, has_more: prior.has_more } : projection;
    this.publish({ task_id: projection.task_id, projection: observed, events: events.slice(0, MAX_BUSINESS_EVENTS), history_limited: historyLimited, phase: 'observed', error_code: null, message: projection.cursor_reset ? 'Current case refreshed. History changed, so the visible recent window was reset.' : 'Showing validated persisted observations.' });
  }
  private failure(error: unknown, mutation: boolean): void {
    const safe = error instanceof BusinessError ? error : new BusinessError(mutation ? 'unknown' : 'unavailable', 'The observation could not be verified. Reconcile the same identity.');
    if (mutation && safe.code === 'unknown') { this.uncertainAcceptance = this.uncertainAcceptance || this.value.operation === 'submit'; if (this.value.pending_command) this.publish({ pending_command: { ...this.value.pending_command, uncertain: true } }); }
    if (mutation && this.value.operation !== 'submit' && ['invalid', 'conflict'].includes(safe.code) && this.value.pending_command && !this.value.pending_command.uncertain) this.publish({ pending_command: null });
    if (safe.code === 'invalid' && this.value.operation === 'submit' && !this.uncertainAcceptance) this.publish({ pending_input: null });
    this.publish({ phase: safe.code === 'unauthorized' ? 'access_required' : safe.code === 'unknown' && mutation ? 'unknown' : 'error', error_code: safe.code, message: safe.message });
  }
  async submit(input: BusinessInput, token: string): Promise<void> {
    let frozen: BusinessInput;
    try { frozen = validateBusinessInput(input); } catch (error) { this.failure(error, false); return; }
    if (this.value.pending_input && JSON.stringify(frozen) !== JSON.stringify(this.value.pending_input)) { this.failure(new BusinessError('conflict', 'Keep the original frozen request until its outcome is reconciled.'), false); return; }
    if (this.value.task_id) { this.failure(new BusinessError('conflict', 'Inspect the accepted case or choose a new investigation explicitly.'), false); return; }
    const run = this.begin('submit'); if (!run) return;
    this.publish({ pending_input: this.value.pending_input ?? frozen });
    try { const receipt = await this.client.submit(frozen, token, run.signal); if (!this.current(run.generation)) return; this.uncertainAcceptance = false; this.accept(receipt.projection); this.publish({ message: receipt.created ? 'Investigation accepted with its case and deadline stored.' : 'Original acceptance recovered. No second workflow was created.' }); }
    catch (error) { if (this.current(run.generation)) this.failure(error, true); }
    finally { this.finish(run.generation); }
  }
  async inspect(taskId: string, token: string): Promise<void> {
    try { uuid(taskId); } catch { this.failure(new BusinessError('invalid', 'Enter a valid original task identity.'), false); return; }
    if (this.value.pending_command && this.value.task_id !== taskId) { this.failure(new BusinessError('conflict', 'Reconcile the original pending command before selecting another case.'), false); return; }
    if (this.value.pending_input && !this.value.task_id) {
      const original = this.value.pending_input, run = this.begin('refresh'); if (!run) return;
      try {
        const projection = await this.client.get(taskId, token, undefined, run.signal); if (!this.current(run.generation)) return;
        if (projection.request_key !== original.idempotency_key || projection.inquiry.request.booking_reference !== original.booking_reference || projection.inquiry.request.new_check_in !== original.new_check_in) throw new BusinessError('conflict', 'The observed task does not belong to the frozen original request. Reconcile its original identity.');
        this.uncertainAcceptance = false; this.accept(projection); this.publish({ message: 'Original acceptance observed through its scoped task and exact request key.' });
      } catch (error) { if (this.current(run.generation)) this.failure(error, false); }
      finally { this.finish(run.generation); }
      return;
    }
    if (this.value.task_id !== taskId) { this.pending?.abort(); this.pending = null; this.generation += 1; this.publish({ task_id: taskId, projection: null, events: [], pending_input: null, pending_command: null, history_limited: false }); }
    await this.refresh(token);
  }
  async refresh(token: string, more = false): Promise<void> {
    const taskId = this.value.task_id; if (!taskId || (more && (!this.value.projection?.has_more || this.value.events.length >= MAX_BUSINESS_EVENTS))) return;
    const cursor = more ? this.value.projection?.next_cursor ?? undefined : undefined;
    const run = this.begin(more ? 'more' : 'refresh'); if (!run) return;
    try { const projection = await this.client.get(taskId, token, cursor, run.signal); if (this.current(run.generation)) this.accept(projection, more); }
    catch (error) { if (this.current(run.generation)) this.failure(error, false); }
    finally { this.finish(run.generation); }
  }
  async command(kind: CommandKind, token: string): Promise<void> {
    const projection = this.value.projection; if (!projection || !this.value.task_id) { this.failure(new BusinessError('invalid', 'Inspect an accepted case before issuing a command.'), false); return; }
    let pending = this.value.pending_command;
    if (pending && pending.kind !== kind) { this.failure(new BusinessError('conflict', 'Reconcile the original pending command before issuing a different command.'), false); return; }
    if (!pending) {
      const commandId = this.makeId();
      const body: Record<string, string | boolean> = { command_id: commandId };
      if (kind === 'quote') body.expected_revision = projection.case_revision;
      if (kind === 'signal') {
        if (!projection.quote || projection.confirmation.state !== 'required') { this.failure(new BusinessError('invalid', 'A current exact quote must be visible before confirmation.'), false); return; }
        verifyQuotePayload(projection.quote); body.confirmation_payload = projection.quote.confirmation_payload; body.explicit = true;
      }
      pending = freeze({ kind, task_id: projection.task_id, command_id: commandId, body, uncertain: false });
    }
    const run = this.begin(kind); if (!run) return; this.publish({ pending_command: pending });
    try {
      const response = await this.client.command(pending, token, run.signal); if (!this.current(run.generation)) return;
      this.accept(response.projection); this.publish({ pending_command: null, message: kind === 'signal' ? 'Exact confirmation recorded. Supplier outcome remains a separate observation.' : kind === 'cancel' ? `Cancellation recorded: ${response.receipt.disposition?.replaceAll('_', ' ')}. This does not promise reversal.` : 'Quote request acknowledged. The current proposal is shown below.' });
    } catch (error) { if (this.current(run.generation)) this.failure(error, true); }
    finally { this.finish(run.generation); }
  }
  newInvestigation(): boolean {
    if (this.pending || (this.value.pending_input && !this.value.task_id) || this.value.pending_command) return false;
    this.generation += 1; this.uncertainAcceptance = false; this.value = INITIAL; try { this.changed(this.value); } catch { /* Presentation-only boundary. */ } return true;
  }
  forget(): void { if (this.value.operation === 'submit') this.uncertainAcceptance = true; if (this.value.pending_command && this.value.operation !== null) this.publish({ pending_command: { ...this.value.pending_command, uncertain: true } }); this.generation += 1; this.pending?.abort(); this.pending = null; this.publish({ phase: 'access_required', operation: null, message: 'Operator token forgotten. Re-enter it to inspect the same durable identity.', error_code: 'unauthorized' }); }
  dispose(): void { this.disposed = true; this.generation += 1; this.pending?.abort(); this.pending = null; }
}

/** True when no further server-side progress can appear without a new command. */
export function businessSettled(projection: BusinessProjection | null): boolean {
  if (!projection) return false;
  if (projection.delivery) return projection.delivery.state === 'delivered' || projection.delivery.state === 'exhausted';
  // Only a failed lifecycle with no outcome ends without a completion event.
  return projection.lifecycle?.state === 'failed' && projection.outcome === null;
}
export function formatMoney(amountMinor: number, currency: string): string { const amount = BigInt(amountMinor); return `${currency} ${(amount / 100n).toString()}.${(amount % 100n).toString().padStart(2, '0')}`; }
export function businessStage(projection: BusinessProjection | null): { title: string; description: string; tone: 'neutral' | 'active' | 'success' | 'attention' } {
  if (!projection) return { title: 'No case observed', description: 'Start an investigation or load an original task identity.', tone: 'neutral' };
  if (projection.outcome?.state === 'uncertain' || projection.lifecycle?.state === 'uncertain') return { title: 'Outcome needs review', description: 'A possible external effect is unresolved. Automatic resend is blocked.', tone: 'attention' };
  if (projection.outcome?.state === 'succeeded') return { title: 'Booking change observed', description: projection.delivery?.state === 'delivered' ? 'The receiver accepted the completion event. Human acknowledgement is separate.' : 'Supplier success is stored. Completion delivery has its own status.', tone: 'success' };
  if (projection.outcome?.state === 'cancelled') return { title: 'Mutation prevented', description: 'Cancellation was confirmed before mutation. Delivery remains separate.', tone: 'neutral' };
  if (projection.outcome?.state === 'failed' || projection.lifecycle?.state === 'failed') return { title: 'Work stopped', description: 'The stored policy or a definitive failure stopped automatic progress.', tone: 'attention' };
  if (projection.confirmation.state === 'committed') return { title: 'Exact confirmation stored', description: 'The worker will use the committed identity. A running conversation is not required.', tone: 'active' };
  if (projection.quote && projection.confirmation.state === 'required') return { title: 'Waiting for your exact approval', description: 'Review the date, price, currency and revision before confirming.', tone: 'active' };
  if (projection.inquiry.state === 'succeeded') return { title: 'Investigation complete', description: 'Request a trusted quote. Investigation permission does not authorize a booking change.', tone: 'active' };
  return { title: projection.inquiry.state === 'running' ? 'Investigation running' : 'Investigation accepted', description: 'The durable worker owns progress independently of this session.', tone: 'active' };
}
