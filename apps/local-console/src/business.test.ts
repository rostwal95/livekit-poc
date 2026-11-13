import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { BusinessClient, BusinessController, BusinessError, businessStage, formatMoney, MAX_BUSINESS_EVENTS, parseBusinessJson, parseBusinessProjection, parseManagedReceipt, readBusinessResponse, verifyQuotePayload } from './business';
import type { BusinessInput, BusinessProjection, PendingCommand } from './business';

const source = readFileSync(new URL('../../../contracts/business/case-projection.json', import.meta.url), 'utf-8');
const TASK = '11111111-1111-4111-8111-111111111111';
const OTHER = '99999999-9999-4999-8999-999999999999';
const SIGNAL = '66666666-6666-4666-8666-666666666666';
const TOKEN = 'private-ui-test-operator-token';
const input: BusinessInput = { booking_reference: 'DEMO-BK-001', new_check_in: '2030-12-10', confirmed: true, idempotency_key: 'managed-example-1' };
function data(): Record<string, unknown> { return JSON.parse(source) as Record<string, unknown>; }
function nested(item: Record<string, unknown>, key: string): Record<string, unknown> { return item[key] as Record<string, unknown>; }
function projection(): BusinessProjection { return parseBusinessProjection(data()); }
function receipt(item = data(), created = true): unknown { return { created, task_id: item.task_id, case_id: item.case_id, projection: item }; }
function response(value: unknown, status = 200): Response { return Response.json(value, { status }); }
function setup(fetcher = vi.fn<typeof fetch>()): { fetcher: typeof fetcher; controller: BusinessController } { return { fetcher, controller: new BusinessController(() => undefined, new BusinessClient(fetcher), () => 'ui-fixed-command') }; }
function command(kind: 'quote' | 'signal' | 'cancel'): PendingCommand {
  const base = projection();
  return { kind, task_id: TASK, command_id: 'ui-fixed-command', uncertain: false, body: kind === 'quote' ? { command_id: 'ui-fixed-command', expected_revision: base.case_revision } : kind === 'signal' ? { command_id: 'ui-fixed-command', confirmation_payload: base.quote!.confirmation_payload, explicit: true } : { command_id: 'ui-fixed-command' } };
}
function commandResponse(kind: 'quote' | 'signal' | 'cancel', item = data()): unknown { return { projection: item, receipt: { command_id: 'ui-fixed-command', created: true, ...(kind === 'quote' ? { quote_id: '33333333-3333-4333-8333-333333333333' } : kind === 'signal' ? { signal_id: SIGNAL } : { cancellation_id: SIGNAL, disposition: 'requested_best_effort' }) } }; }

function completedData(): Record<string, unknown> {
  const item = data(), evidence = { schema_version: 1, effect_id: '77777777-7777-4777-8777-777777777777', intent_id: SIGNAL, task_id: TASK, case_id: item.case_id, supplier_id: nested(item, 'quote').supplier_id, scope_id: 'business-lab', booking_reference: input.booking_reference, previous_check_in: '2030-12-01', new_check_in: input.new_check_in, previous_revision: '9223372036854775806', revision: '9223372036854775807', amount_minor: 2500, currency: 'USD', created_at: '2030-12-01T00:00:00+00:00' };
  item.confirmation = { state: 'committed', intent_id: SIGNAL, confirmation_id: SIGNAL, committed_at: evidence.created_at };
  item.effect = { state: 'succeeded', generation: '2', attempt_no: 1, dispatch_count: 1, result: evidence, error_code: null, updated_at: evidence.created_at };
  item.outcome = { state: 'succeeded', result: { ...evidence }, error_code: null, cancellation: 'not_requested', created_at: evidence.created_at, intent_id: SIGNAL, effect_id: evidence.effect_id, event_id: SIGNAL };
  item.delivery = { state: 'exhausted', event_id: SIGNAL, target_id: SIGNAL, generation: '8', attempts: 8, next_attempt_at: null, error_code: 'delivery_exhausted', updated_at: evidence.created_at };
  return item;
}


describe('browser-native fetch invocation', () => {
  it('calls the fetch port without a BusinessClient receiver so real Window.fetch can send HTTP', async () => {
    const fetcher = vi.fn<typeof fetch>(function (this: unknown) {
      if (this !== undefined) throw new TypeError('Illegal invocation');
      return Promise.resolve(response(receipt()));
    });
    const result = await new BusinessClient(fetcher).submit(input, TOKEN);
    expect(result.task_id).toBe(TASK); expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe('shared P1 business projection boundary', () => {
  it('reads the actual producer fixture with BIGINT revisions and opaque consent intact', () => {
    const result = projection();
    expect(result.case_revision).toBe('9007199254740993');
    expect(result.lifecycle?.lease?.epoch).toBe('9223372036854775807');
    expect(result.quote?.expected_supplier_revision).toBe('9223372036854775806');
    expect(result.quote?.confirmation_payload).toContain('"revision":9007199254740993');
    verifyQuotePayload(result.quote!);
  });
  it('keeps request facts and nested receipts immutable after parsing', () => {
    const original = data(), parsed = parseBusinessProjection(original);
    nested(original, 'request').booking_reference = 'changed-after-parse';
    expect(parsed.request.booking_reference).toBe('DEMO-BK-001');
    expect(Object.isFrozen(parsed.quote)).toBe(true);
    expect(Object.isFrozen(parsed.inquiry.request)).toBe(true);
    expect(() => { (parsed.request as { booking_reference: string }).booking_reference = 'forged'; }).toThrow();
  });
  it.each([
    (item: Record<string, unknown>) => { item.schema_version = 2; },
    (item: Record<string, unknown>) => { item.case_revision = 9007199254740992; },
    (item: Record<string, unknown>) => { item.case_revision = '01'; },
    (item: Record<string, unknown>) => { item.case_id = TASK; },
    (item: Record<string, unknown>) => { item.scope_id = 'caller-scope'; },
    (item: Record<string, unknown>) => { nested(item, 'inquiry').state = 'completed'; },
    (item: Record<string, unknown>) => { nested(item, 'lifecycle').state = 'provider-success'; },
    (item: Record<string, unknown>) => { item.has_more = true; },
    (item: Record<string, unknown>) => { item.events_total = 0; },
    (item: Record<string, unknown>) => { item.history_truncated = 'false'; },
  ])('rejects unsupported or incoherent observation instead of inventing progress', (change) => {
    const item = data(); change(item); expect(() => parseBusinessProjection(item)).toThrow(BusinessError);
  });
  it.each(['amount_minor', 'currency', 'revision', 'new_check_in', 'case_id', 'supplier_id'])('rejects displayed %s that differs from the opaque exact approval', (field) => {
    const item = data(), quote = nested(item, 'quote');
    quote[field] = field === 'amount_minor' ? 3500 : field === 'currency' ? 'EUR' : field === 'revision' ? '9007199254740994' : field === 'new_check_in' ? '2030-12-11' : OTHER;
    expect(() => parseBusinessProjection(item)).toThrow(BusinessError);
  });
  it('verifies Python ASCII canonical quotation without converting large numbers', () => {
    const item = data(); nested(item, 'request').booking_reference = 'Δ-😀'; nested(nested(item, 'inquiry'), 'request').booking_reference = 'Δ-😀';
    const quote = nested(item, 'quote'); quote.booking_reference = 'Δ-😀'; quote.confirmation_payload = String(quote.confirmation_payload).replace('DEMO-BK-001', '\\u0394-\\ud83d\\ude00');
    expect(parseBusinessProjection(item).quote?.booking_reference).toBe('Δ-😀');
  });
  it('binds admission replay to its original request key and inquiry request', () => {
    const revised = data(); nested(revised, 'request').new_check_in = '2030-12-11'; revised.quote = null; nested(revised, 'confirmation').state = 'not_requested';
    expect(parseManagedReceipt(receipt(revised, false), input).created).toBe(false);
    revised.request_key = 'same-payload-other-key';
    expect(() => parseManagedReceipt(receipt(revised, false), input)).toThrow(BusinessError);
  });
  it('rejects foreign task observations before exposing them as current facts', () => { expect(() => parseBusinessProjection(data(), OTHER)).toThrow(BusinessError); });
  it('keeps business success separate from delivery and uncertainty', () => {
    const success = parseBusinessProjection(completedData());
    expect(businessStage(success).title).toBe('Booking change observed');
    expect(businessStage(success).description).toContain('own status');
    expect(businessStage({ ...success, outcome: { ...success.outcome!, state: 'uncertain', result: null } }).title).toBe('Outcome needs review');
  });
  it('verifies complete exact supplier evidence without losing its BIGINT revision', () => {
    const observed = parseBusinessProjection(completedData());
    expect(observed.outcome?.result?.revision).toBe('9223372036854775807');
    expect(observed.delivery?.state).toBe('exhausted');
    expect(observed.effect?.state).toBe('succeeded');
  });
  it.each([
    (item: Record<string, unknown>) => { nested(item, 'effect').result = {}; },
    (item: Record<string, unknown>) => { nested(nested(item, 'effect'), 'result').task_id = OTHER; },
    (item: Record<string, unknown>) => { nested(nested(item, 'outcome'), 'result').supplier_id = OTHER; },
    (item: Record<string, unknown>) => { nested(nested(item, 'effect'), 'result').amount_minor = 3500; },
    (item: Record<string, unknown>) => { nested(nested(item, 'outcome'), 'result').previous_revision = '0'; },
    (item: Record<string, unknown>) => { nested(item, 'effect').state = 'pending'; },
    (item: Record<string, unknown>) => { nested(item, 'delivery').event_id = OTHER; },
    (item: Record<string, unknown>) => { nested(item, 'delivery').target_id = null; },
    (item: Record<string, unknown>) => { nested(item, 'delivery').next_attempt_at = '2030-12-01T00:01:00+00:00'; },
    (item: Record<string, unknown>) => { nested(item, 'confirmation').committed_at = null; },
    (item: Record<string, unknown>) => { item.effect = null; },
    (item: Record<string, unknown>) => { item.outcome = null; item.delivery = null; },
  ])('does not display incoherent terminal evidence as supplier success', (change) => {
    const item = completedData(); change(item); expect(() => parseBusinessProjection(item)).toThrow(BusinessError);
  });
  it('formats maximum safe minor units without losing a cent', () => { expect(formatMoney(Number.MAX_SAFE_INTEGER, 'USD')).toBe('USD 90071992547409.91'); });
});


describe('P1 HTTP commands and bounded decoding', () => {
  it('sends tokens only in headers and canonical opaque quote bytes unchanged', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(commandResponse('signal')));
    await new BusinessClient(fetcher).command(command('signal'), TOKEN);
    const [url, options] = fetcher.mock.calls[0]!;
    expect(url).toBe(`/api/business/cases/${TASK}/signal`);
    expect(options?.headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` });
    expect(options?.credentials).toBe('omit'); expect(options?.cache).toBe('no-store');
    const sent = JSON.parse(String(options?.body)) as Record<string, unknown>;
    expect(sent.confirmation_payload).toBe(projection().quote?.confirmation_payload);
    expect(sent.explicit).toBe(true); expect(options?.body).not.toContain(TOKEN);
  });
  it('rejects an altered internal command body before calling the network', async () => {
    const fetcher = vi.fn<typeof fetch>();
    await expect(new BusinessClient(fetcher).command({ ...command('signal'), body: { ...command('signal').body, explicit: false } }, TOKEN)).rejects.toBeInstanceOf(BusinessError);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([[401, 'unauthorized'], [403, 'unauthorized'], [409, 'conflict'], [422, 'invalid'], [503, 'unknown']] as const)('sanitizes command HTTP %s without trusting its body', async (status, code) => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('PRIVATE_PROVIDER_SENTINEL', { status }));
    await expect(new BusinessClient(fetcher).submit(input, TOKEN)).rejects.toMatchObject({ code });
    try { await new BusinessClient(fetcher).submit(input, TOKEN); } catch (error) { expect((error as Error).message).not.toContain('PRIVATE_PROVIDER_SENTINEL'); }
  });
  it('treats a GET outage as unavailable observation, never a failed business outcome', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('', { status: 503 }));
    await expect(new BusinessClient(fetcher).get(TASK, TOKEN)).rejects.toMatchObject({ code: 'unavailable' });
  });
  it('bounds decoded UTF-8 response bytes and closes oversized input', async () => {
    const cancelled = vi.fn();
    const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new TextEncoder().encode('é'.repeat(33_000))); }, cancel: cancelled });
    await expect(readBusinessResponse(new Response(body))).rejects.toBeInstanceOf(BusinessError);
    expect(cancelled).toHaveBeenCalledOnce();
  });
  it('rejects duplicate JSON fields and excessive nesting', () => {
    expect(() => parseBusinessJson('{"task_id":"A","task_id":"B"}')).toThrow();
    expect(() => parseBusinessJson('{"outer":{"key":1,"key":2}}')).toThrow();
    expect(() => parseBusinessJson('['.repeat(17) + '0' + ']'.repeat(17))).toThrow();
    expect(parseBusinessJson('{"message":"quoted \\"key\\":1", "key":2}')).toEqual({ message: 'quoted "key":1', key: 2 });
  });
  it('rejects a command acknowledgement with another command identity', async () => {
    const value = commandResponse('quote') as { receipt: Record<string, unknown> }; value.receipt.command_id = 'foreign-command';
    await expect(new BusinessClient(vi.fn<typeof fetch>().mockResolvedValue(response(value))).command(command('quote'), TOKEN)).rejects.toMatchObject({ code: 'unknown' });
  });
  it('uses only a bounded opaque cursor on the scoped GET', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(data()));
    await new BusinessClient(fetcher).get(TASK, TOKEN, 'abc_-123');
    expect(fetcher.mock.calls[0]?.[0]).toBe(`/api/business/cases/${TASK}?limit=10&cursor=abc_-123`);
    await expect(new BusinessClient(fetcher).get('../other', TOKEN)).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});


describe('P1 pure controller identity, reconciliation and observation progress', () => {
  it('retains the original key across unknown acknowledgement and later rejection, then usefully reconciles', async () => {
    const { fetcher, controller } = setup();
    fetcher.mockRejectedValueOnce(new TypeError('PRIVATE_NETWORK_SENTINEL')).mockResolvedValueOnce(new Response('', { status: 422 })).mockResolvedValueOnce(response(receipt(data(), false)));
    await controller.submit(input, TOKEN); expect(controller.state.phase).toBe('unknown');
    expect(controller.state.pending_input?.idempotency_key).toBe(input.idempotency_key); expect(controller.newInvestigation()).toBe(false);
    await controller.submit(input, TOKEN); expect(controller.state.pending_input?.idempotency_key).toBe(input.idempotency_key);
    await controller.submit(input, TOKEN); expect(controller.state.projection?.task_id).toBe(TASK); expect(controller.state.message).toContain('Original acceptance recovered');
    expect(fetcher.mock.calls.every((call) => JSON.parse(String(call[1]?.body)).idempotency_key === input.idempotency_key)).toBe(true);
  });
  it('permits correction after a first definitive rejection and does not send invalid input', async () => {
    const { fetcher, controller } = setup(); fetcher.mockResolvedValueOnce(new Response('', { status: 422 }));
    await controller.submit({ ...input, confirmed: false }, TOKEN); expect(fetcher).not.toHaveBeenCalled();
    await controller.submit(input, TOKEN); expect(controller.state.pending_input).toBeNull();
    expect(controller.newInvestigation()).toBe(true);
  });
  it('cannot replace a frozen possibly accepted request with a changed date', async () => {
    const { fetcher, controller } = setup(); fetcher.mockRejectedValue(new Error('lost'));
    await controller.submit(input, TOKEN); await controller.submit({ ...input, new_check_in: '2030-12-11' }, TOKEN);
    expect(fetcher).toHaveBeenCalledTimes(1); expect(controller.state.pending_input?.new_check_in).toBe(input.new_check_in);
  });
  it('forget/late-response fencing preserves a possibly accepted identity for subsequent replay', async () => {
    let resolve!: (value: Response) => void;
    const { fetcher, controller } = setup(); fetcher.mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }));
    const first = controller.submit(input, TOKEN); controller.forget();
    resolve(response(receipt())); await first;
    expect(controller.state.phase).toBe('access_required'); expect(controller.state.projection).toBeNull();
    fetcher.mockResolvedValueOnce(new Response('', { status: 422 })); await controller.submit(input, TOKEN);
    expect(controller.state.pending_input?.idempotency_key).toBe(input.idempotency_key);
    fetcher.mockResolvedValueOnce(response(receipt(data(), false))); await controller.submit(input, TOKEN);
    expect(controller.state.projection?.task_id).toBe(TASK);
  });
  it('treats a native task hint only as an authenticated read and binds original request key', async () => {
    const { fetcher, controller } = setup(); fetcher.mockRejectedValueOnce(new Error('lost'));
    await controller.submit(input, TOKEN);
    const other = data(); other.request_key = 'different-request-key'; fetcher.mockResolvedValueOnce(response(other));
    await controller.inspect(TASK, TOKEN); expect(controller.state.projection).toBeNull(); expect(controller.state.pending_input).not.toBeNull();
    fetcher.mockResolvedValueOnce(response(data())); await controller.inspect(TASK, TOKEN);
    expect(controller.state.projection?.request_key).toBe(input.idempotency_key);
    expect(controller.state.message).toContain('Original acceptance observed');
  });
  it('preserves a frozen signal after unknown acknowledgement even when a newer proposal is observed', async () => {
    const { fetcher, controller } = setup(); fetcher.mockResolvedValueOnce(response(receipt())); await controller.submit(input, TOKEN);
    fetcher.mockRejectedValueOnce(new Error('lost')); await controller.command('signal', TOKEN);
    const frozen = controller.state.pending_command?.body.confirmation_payload;
    const newer = data(), quote = nested(newer, 'quote'); quote.quote_id = OTHER; quote.amount_minor = 3500; quote.confirmation_payload = String(quote.confirmation_payload).replace('33333333-3333-4333-8333-333333333333', OTHER).replace('"amount_minor":2500', '"amount_minor":3500'); newer.projection_revision = 'b'.repeat(64);
    fetcher.mockResolvedValueOnce(response(newer)); await controller.refresh(TOKEN);
    expect(controller.state.projection?.quote?.quote_id).toBe(OTHER); expect(controller.state.pending_command?.body.confirmation_payload).toBe(frozen);
    fetcher.mockResolvedValueOnce(response(commandResponse('signal', newer))); await controller.command('signal', TOKEN);
    const sent = JSON.parse(String(fetcher.mock.calls.at(-1)?.[1]?.body)) as Record<string, unknown>;
    expect(sent.confirmation_payload).toBe(frozen); expect(controller.state.projection?.quote?.quote_id).toBe(OTHER); expect(controller.state.pending_command).toBeNull();
  });
  it('blocks a different command and a different case while an earlier command is unresolved', async () => {
    const { fetcher, controller } = setup(); fetcher.mockResolvedValueOnce(response(receipt())); await controller.submit(input, TOKEN);
    fetcher.mockRejectedValueOnce(new Error('lost')); await controller.command('quote', TOKEN);
    await controller.command('cancel', TOKEN); await controller.inspect(OTHER, TOKEN);
    expect(fetcher).toHaveBeenCalledTimes(2); expect(controller.state.pending_command?.kind).toBe('quote');
  });
  it('clears a first definitively rejected command so a fresh explicit action can proceed', async () => {
    const { fetcher, controller } = setup(); fetcher.mockResolvedValueOnce(response(receipt())); await controller.submit(input, TOKEN);
    fetcher.mockResolvedValueOnce(new Response('', { status: 409 })); await controller.command('signal', TOKEN);
    expect(controller.state.pending_command).toBeNull();
    fetcher.mockResolvedValueOnce(response(commandResponse('quote'))); await controller.command('quote', TOKEN);
    expect(controller.state.pending_command).toBeNull(); expect(fetcher).toHaveBeenCalledTimes(3);
  });
  it('refreshes current state, merges same-revision pages and resets changed observation windows', async () => {
    const first = data(); first.has_more = true; first.next_cursor = 'cursor-1';
    const second = data(); second.events = [{ event_id: 'wait:1', kind: 'wait', state: 'pending', observed_at: '2030-12-01T00:00:01+00:00', details: {} }]; second.has_more = true; second.next_cursor = 'cursor-2';
    const changed = data(); changed.projection_revision = 'b'.repeat(64); changed.cursor_reset = true; changed.events = [{ event_id: 'new-window:1', kind: 'wait', state: 'consumed', observed_at: '2030-12-01T00:00:02+00:00', details: {} }];
    const { fetcher, controller } = setup(); fetcher.mockResolvedValueOnce(response(first)); await controller.inspect(TASK, TOKEN);
    fetcher.mockResolvedValueOnce(response(second)); await controller.refresh(TOKEN, true); expect(controller.state.events).toHaveLength(2);
    fetcher.mockResolvedValueOnce(response(first)); await controller.refresh(TOKEN); expect(controller.state.projection?.next_cursor).toBe('cursor-2');
    fetcher.mockResolvedValueOnce(response(changed)); await controller.refresh(TOKEN, true);
    expect(String(fetcher.mock.calls.at(-1)?.[0])).toContain('cursor=cursor-2'); expect(controller.state.events.map((event) => event.event_id)).toEqual(['new-window:1']); expect(controller.state.message).toContain('History changed');
  });
  it('keeps the displayed event window bounded and labels a remaining history limit', async () => {
    const event = projection().events[0]!;
    const page = (offset: number) => { const item = data(); item.events = Array.from({ length: 50 }, (_, index) => ({ ...event, event_id: `quote:${offset + index}` })); item.events_total = 150; item.has_more = true; item.next_cursor = `cursor-${offset}`; return item; };
    const { fetcher, controller } = setup(); fetcher.mockResolvedValueOnce(response(page(0))); await controller.inspect(TASK, TOKEN);
    fetcher.mockResolvedValueOnce(response(page(50))); await controller.refresh(TOKEN, true);
    expect(controller.state.events).toHaveLength(MAX_BUSINESS_EVENTS); expect(controller.state.history_limited).toBe(true);
    await controller.refresh(TOKEN, true); expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it('retains known observations on a read outage without painting a failed business', async () => {
    const { fetcher, controller } = setup(); fetcher.mockResolvedValueOnce(response(data())); await controller.inspect(TASK, TOKEN);
    fetcher.mockRejectedValueOnce(new Error('private')); await controller.refresh(TOKEN);
    expect(controller.state.phase).toBe('error'); expect(controller.state.error_code).toBe('unavailable'); expect(controller.state.projection?.quote?.quote_id).toBe(projection().quote?.quote_id); expect(controller.state.projection?.outcome).toBeNull();
  });
  it('does not turn a presentation exception into unknown business acceptance', async () => {
    const client = new BusinessClient(vi.fn<typeof fetch>().mockResolvedValue(response(receipt())));
    const controller = new BusinessController(() => { throw new Error('broken view'); }, client);
    await controller.submit(input, TOKEN); expect(controller.state.phase).toBe('observed'); expect(controller.state.task_id).toBe(TASK);
  });
  it('disposal aborts pending reads and ignores late callbacks without issuing business cancellation', async () => {
    let resolve!: (value: Response) => void;
    const { fetcher, controller } = setup(); fetcher.mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }));
    const reading = controller.inspect(TASK, TOKEN); controller.dispose(); resolve(response(data())); await reading;
    expect(controller.state.projection).toBeNull(); expect(fetcher).toHaveBeenCalledTimes(1); expect(String(fetcher.mock.calls[0]?.[0])).not.toContain('cancel');
  });
});
