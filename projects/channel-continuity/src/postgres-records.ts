/** Shared stored-row projection validation; no SQL or authority decisions. */
import { parseEventJson } from './index.js';
import { ChannelError, PROCESSING_STATES, type ProcessingState } from './public-types.js';
import type { DurableReceipt, StoredMessage } from './postgres.js';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/;
function iso(value: unknown): string {
  if (!(value instanceof Date) || !Number.isFinite(value.getTime()))
    throw new ChannelError('SchemaMismatch');
  return value.toISOString();
}
function cursor(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^(0|[1-9][0-9]{0,18})(?![\s\S])/.test(value) ||
    BigInt(value) > 9223372036854775807n
  )
    throw new ChannelError('SchemaMismatch');
  return value;
}
export function decodeReceipt(row: Record<string, unknown>): DurableReceipt {
  return Object.freeze({
    receiptId: row.receipt_id as string,
    eventId: row.event_id as string,
    messageId: row.message_id as string,
    acceptanceSequence: String(row.acceptance_sequence),
    acceptedAt: iso(row.accepted_at),
  });
}
export function decodeStoredMessage(row: Record<string, unknown>): StoredMessage {
  if (
    typeof row.operation_key !== 'string' ||
    !PROCESSING_STATES.includes(row.state as ProcessingState)
  )
    throw new ChannelError('SchemaMismatch');
  const p = {
    tenantId: row.tenant_id as string,
    provider: row.provider as string,
    providerAccountId: row.provider_account_id as string,
  };
  try {
    const decoded = parseEventJson(row.wire_json as string, {
      providerScope: p,
      accountScope: { tenantId: p.tenantId, accountId: row.account_id as string },
    });
    if (
      decoded.canonical !== row.canonical_payload ||
      decoded.event.eventId !== row.event_id ||
      decoded.event.conversationId !== row.conversation_id ||
      !UUID.test(row.receipt_id as string) ||
      !UUID.test(row.operation_key) ||
      cursor(String(row.acceptance_sequence)) === '0'
    )
      throw new ChannelError('SchemaMismatch');
    return Object.freeze({
      receipt: decodeReceipt(row),
      event: decoded.event,
      operationKey: row.operation_key,
      processingState: row.state as ProcessingState,
      associationVersion: String(row.association_epoch),
    });
  } catch {
    throw new ChannelError('SchemaMismatch');
  }
}
