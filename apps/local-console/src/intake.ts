/** Current M1 intake only: no workflow execution or supplier mutation. */
import { boundedResponse, LabInputError } from './lab';

export interface InvestigationInput {
  booking_reference: string;
  new_check_in: string;
  confirmed: boolean;
  idempotency_key: string;
}
export interface InvestigationReceipt {
  created: boolean;
  task: {
    task_id: string;
    scope_id: 'local-lab';
    idempotency_key: string;
    status: 'queued';
    created_at: string;
    request: { booking_reference: string; new_check_in: string; confirmed: true };
  };
}
export class IntakeError extends Error {
  constructor(readonly code: 'unauthorized' | 'conflict' | 'invalid' | 'unknown', message: string) {
    super(message);
  }
}
export function validateOperatorToken(token: string): void {
  if (token.length < 16 || token.length > 512 || /\s/.test(token)) {
    throw new LabInputError('Enter the local operator token from local setup.');
  }
}
export function validateInvestigation(input: InvestigationInput): void {
  if (!input.confirmed) throw new LabInputError('Confirm the investigation before submitting.');
  if (!input.booking_reference.trim() || input.booking_reference.trim().length > 64) {
    throw new LabInputError('Enter a booking reference of 1–64 characters.');
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(input.new_check_in)
      || Number.isNaN(Date.parse(input.new_check_in))
      || new Date(input.new_check_in).toISOString().slice(0, 10) !== input.new_check_in) {
    throw new LabInputError('Choose a valid date.');
  }
  if (!/^[a-zA-Z0-9_-]{1,128}$/.test(input.idempotency_key)) {
    throw new LabInputError('The local request identity is invalid.');
  }
}
export function parseInvestigation(value: unknown, input: InvestigationInput): InvestigationReceipt {
  const unknownOutcome = (): never => { throw new IntakeError('unknown', 'The acknowledgement could not be verified. Retry the same request identity.'); };
  if (!value || typeof value !== 'object' || !('created' in value) || typeof value.created !== 'boolean'
      || !('task' in value) || !value.task || typeof value.task !== 'object') return unknownOutcome();
  const task = value.task;
  if (!('task_id' in task) || typeof task.task_id !== 'string'
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(task.task_id)
      || !('scope_id' in task) || task.scope_id !== 'local-lab'
      || !('status' in task) || task.status !== 'queued'
      || !('idempotency_key' in task) || task.idempotency_key !== input.idempotency_key
      || !('created_at' in task) || typeof task.created_at !== 'string' || Number.isNaN(Date.parse(task.created_at))
      || !('request' in task) || !task.request || typeof task.request !== 'object') return unknownOutcome();
  const request = task.request;
  if (!('booking_reference' in request) || request.booking_reference !== input.booking_reference.trim().toUpperCase()
      || !('new_check_in' in request) || request.new_check_in !== input.new_check_in
      || !('confirmed' in request) || request.confirmed !== true) return unknownOutcome();
  return value as InvestigationReceipt;
}
export async function requestInvestigation(
  input: InvestigationInput, token: string, signal?: AbortSignal, fetcher: typeof fetch = fetch,
): Promise<InvestigationReceipt> {
  validateOperatorToken(token);
  validateInvestigation(input);
  const deadline = AbortSignal.timeout(8_000);
  try {
    const response = await fetcher('/api/investigations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(input),
      signal: signal ? AbortSignal.any([signal, deadline]) : deadline,
      cache: 'no-store', credentials: 'omit',
    });
    if (response.status === 401 || response.status === 403) {
      throw new IntakeError('unauthorized', 'Operator access was denied. Enter the local token again.');
    }
    if (response.status === 409) throw new IntakeError('conflict', 'Changed payload rejected: this request identity already belongs to the original investigation.');
    if (response.status === 422 || response.status === 413) throw new IntakeError('invalid', 'The investigation was not accepted. Check its fields and confirmation.');
    if (!response.ok) throw new IntakeError('unknown', 'No durable acknowledgement was received. Retry the same request identity.');
    return parseInvestigation(await boundedResponse(response), input);
  } catch (error) {
    if (error instanceof IntakeError) throw error;
    // A transport timeout can happen after acceptance; never invent a failed task.
    throw new IntakeError('unknown', 'The outcome is not yet known. Retry the same request identity to reconcile.');
  }
}
export function assertReplay(original: InvestigationReceipt, replay: InvestigationReceipt): void {
  if (replay.created || replay.task.task_id !== original.task.task_id) {
    throw new IntakeError('unknown', 'Replay did not preserve the original investigation identity.');
  }
}
export function nextDate(value: string): string {
  const date = new Date(value + 'T00:00:00Z');
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/** A later rejection cannot erase an earlier possibly accepted request identity. */
export function canCorrectRejectedInput(error: unknown, unacknowledgedAttempt: boolean): boolean {
  return error instanceof IntakeError && error.code === 'invalid' && !unacknowledgedAttempt;
}
