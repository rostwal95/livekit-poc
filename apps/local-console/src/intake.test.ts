import { describe, expect, it, vi } from 'vitest';
import { assertReplay, canCorrectRejectedInput, IntakeError, nextDate, parseInvestigation, requestInvestigation, validateInvestigation } from './intake';
const input = { booking_reference: 'demo-bk-001', new_check_in: '2030-12-10', confirmed: true, idempotency_key: 'showcase-unit' };
const receipt = { created: true, task: { task_id: '12345678-1234-1234-1234-123456789abc', scope_id: 'local-lab', status: 'queued', idempotency_key: input.idempotency_key, created_at: '2026-11-09T00:00:00+00:00', request: { booking_reference: 'DEMO-BK-001', new_check_in: input.new_check_in, confirmed: true } } };
describe('live investigation showcase', () => {
  it('validates the actual intake receipt and canonical booking reference', () => {
    expect(parseInvestigation(receipt, input).task.status).toBe('queued');
  });
  it.each([['confirmed', false], ['new_check_in', '2030-02-31'], ['idempotency_key', ''], ['booking_reference', ' ']])('rejects invalid %s before a request', (key, value) => {
    expect(() => validateInvestigation({ ...input, [key]: value })).toThrow();
  });
  it.each([{ ...receipt, created: 'true' }, { ...receipt, task: { ...receipt.task, scope_id: 'another-account' } }, { ...receipt, task: { ...receipt.task, status: 'completed' } }, { ...receipt, task: { ...receipt.task, idempotency_key: 'another-request' } }, { ...receipt, task: { ...receipt.task, request: { ...receipt.task.request, new_check_in: '2030-12-11' } } }])('does not turn mismatched receipts into progress', (value) => {
    expect(() => parseInvestigation(value, input)).toThrow(IntakeError);
  });
  it('puts credentials only in headers and sends the stable identity', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(receipt));
    const result = await requestInvestigation(input, 'local-test-operator-token', undefined, fetcher);
    expect(result.created).toBe(true);
    const [url, options] = fetcher.mock.calls[0]!;
    expect(url).toBe('/api/investigations');
    expect(options.headers.Authorization).toBe('Bearer local-test-operator-token');
    expect(JSON.parse(options.body).idempotency_key).toBe(input.idempotency_key);
    expect(options.body).not.toContain('local-test-operator-token');
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(options.credentials).toBe('omit');
  });
  it.each([[401, 'unauthorized'], [409, 'conflict'], [422, 'invalid'], [503, 'unknown']])('sanitizes HTTP %s without trusting provider bodies', async (status, code) => {
    const fetcher = vi.fn().mockResolvedValue(new Response('private-provider-token', { status }));
    try { await requestInvestigation(input, 'local-test-operator-token', undefined, fetcher); throw new Error('Expected rejection'); }
    catch (error) { expect(error).toBeInstanceOf(IntakeError); expect((error as IntakeError).code).toBe(code); expect((error as Error).message).not.toContain('private-provider-token'); }
  });
  it('preserves uncertainty after a lost response and never retries implicitly', async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError('private-network-info'));
    await expect(requestInvestigation(input, 'local-test-operator-token', undefined, fetcher)).rejects.toMatchObject({ code: 'unknown' });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(input.idempotency_key).toBe('showcase-unit');
  });
  it('rejects an oversized acknowledgement rather than showing false acceptance', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('x'.repeat(20_000)));
    await expect(requestInvestigation(input, 'local-test-operator-token', undefined, fetcher)).rejects.toMatchObject({ code: 'unknown' });
  });
  it('verifies both duplicate flag and original task identity', () => {
    const original = parseInvestigation(receipt, input);
    expect(() => assertReplay(original, { ...original, created: false })).not.toThrow();
    expect(() => assertReplay(original, original)).toThrow();
    expect(() => assertReplay(original, { ...original, created: false, task: { ...original.task, task_id: 'another' } })).toThrow();
  });
  it('allows correcting definitive invalid input without losing an earlier unknown identity', () => {
    expect(canCorrectRejectedInput(new IntakeError('invalid', 'invalid'), false)).toBe(true);
    expect(canCorrectRejectedInput(new IntakeError('invalid', 'invalid'), true)).toBe(false);
    expect(canCorrectRejectedInput(new IntakeError('unknown', 'unknown'), false)).toBe(false);
    expect(canCorrectRejectedInput(new IntakeError('unauthorized', 'denied'), true)).toBe(false);
  });
  it('uses UTC calendar arithmetic for conflict probes', () => {
    expect(nextDate('2030-12-31')).toBe('2031-01-01');
  });
});
