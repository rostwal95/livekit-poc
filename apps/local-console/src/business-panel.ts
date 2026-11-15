/** DOM adapter: every business state comes from a validated scoped projection. */
import { BusinessController, BusinessError, businessSettled, businessStage, formatMoney, MAX_BUSINESS_EVENTS } from './business';
import type { BusinessInput, BusinessProjection, BusinessState, CommandKind } from './business';
import './business.css';

export interface BusinessPanelOptions {
  takeToken(): string;
  /** Background reads use only the token already held in memory; they never read or clear the input field. */
  heldToken(): string;
  forgetToken(): void;
  onTask?(taskId: string): void;
  signal?: AbortSignal;
  pollMilliseconds?: number;
}
export interface BusinessPanelHandle {
  getCurrentTask(): string | null;
  getFrozenRequest(): Readonly<BusinessInput> | null;
  observeTask(taskId: string): Promise<void>;
  resume(): Promise<void>;
  forget(): void;
  dispose(): void;
}
const EVENT_LABELS: Record<string, string> = { task: 'Investigation accepted', inquiry_attempt: 'Inquiry attempt', quote: 'Quote observed', confirmation: 'Exact confirmation', wait: 'Durable wait', mutation_attempt: 'Supplier attempt', cancellation: 'Cancellation request', outcome: 'Business outcome', delivery: 'Receiver delivery' };
function human(value: string): string { return value.replaceAll('_', ' '); }
function time(value: string | null): string { return value === null ? 'Not observed' : new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'medium' }); }

export function mountBusinessPanel(host: HTMLElement, options: BusinessPanelOptions): BusinessPanelHandle {
  host.classList.add('business-section');
  host.setAttribute('aria-labelledby', 'business-title');
  host.innerHTML = `
    <div class="section-heading"><div><p class="eyebrow">P1 / DURABLE BUSINESS WORK</p><h2 id="business-title">The conversation can end. The work continues.</h2><p>Follow one real case from investigation through exact consent, supplier outcome and receiver delivery.</p></div><span class="badge">POSTGRESQL · LEASED WORKER</span></div>
    <div class="business-layout">
      <section class="panel business-request" aria-labelledby="business-request-title">
        <div class="panel-head"><span class="overline">01 / INVESTIGATE</span><h3 id="business-request-title">Start a durable case</h3></div>
        <form id="business-form" class="business-form">
          <label for="business-booking">Synthetic booking</label><input id="business-booking" value="DEMO-BK-001" maxlength="64" autocomplete="off" required />
          <label for="business-check-in">Requested check-in</label><input id="business-check-in" type="date" value="2030-12-10" required />
          <label class="confirmation" for="business-investigation"><input id="business-investigation" type="checkbox" required /><span>Investigate this change.<small>Investigation permission does not authorize a booking change.</small></span></label>
          <button id="business-submit" type="submit" class="primary">Submit investigation</button>
          <p id="business-request-key" class="business-mono business-request-key" hidden></p>
        </form>
        <div class="business-resume"><span class="overline">ALREADY HAVE A TASK?</span><form id="business-resume-form"><label for="business-resume-id">Original task identity</label><input id="business-resume-id" placeholder="Paste the original task UUID" autocomplete="off" spellcheck="false" maxlength="36" required /><button id="business-resume" type="submit" class="secondary">Load scoped case</button></form><p>No case or token is stored in your browser. After a reload, re-enter both to resume.</p></div>
        <div class="business-request-actions"><button id="business-new" class="text-button" type="button">New investigation</button><button id="business-refresh" class="text-button" type="button" disabled>Refresh observations</button></div>
      </section>
      <section class="panel business-observations" aria-labelledby="business-state-title">
        <div class="business-case-head"><div><span class="overline">02 / CURRENT OBSERVATION</span><h3 id="business-state-title">No case observed</h3></div><span id="business-state-badge" class="business-state" data-tone="neutral">Ready</span></div>
        <p id="business-state-description" class="business-state-description">Start an investigation or load an original task identity.</p>
        <p id="business-status" class="business-status" role="status" aria-live="polite">Submit a confirmed investigation or inspect an existing task.</p>
        <dl id="business-identity" class="business-identity" hidden><div><dt>Original task</dt><dd id="business-task-id"></dd></div><div><dt>Case / revision</dt><dd id="business-case-id"></dd></div></dl>
        <div class="business-facts" aria-label="Independent business observations"><div><span>INVESTIGATION</span><strong id="business-inquiry-state">Not observed</strong></div><div><span>EXACT CONSENT</span><strong id="business-confirmation-state">Not observed</strong></div><div><span>SUPPLIER OUTCOME</span><strong id="business-outcome-state">Not observed</strong></div><div><span>RECEIVER DELIVERY</span><strong id="business-delivery-state">Not observed</strong></div></div>
        <div id="business-pending" class="business-pending" hidden><strong>Original command needs reconciliation.</strong><p id="business-pending-description"></p><details><summary>Frozen command details</summary><pre id="business-pending-payload"></pre></details><button id="business-reconcile" class="secondary" type="button">Reconcile original command</button></div>
        <section class="business-quote" aria-labelledby="business-quote-title"><div class="business-quote-head"><div><span class="overline">03 / EXACT APPROVAL</span><h3 id="business-quote-title">Review the proposal</h3></div><button id="business-request-quote" class="secondary" type="button" disabled>Request trusted quote</button></div>
          <p id="business-quote-empty" class="business-explanation">A trusted producer can issue a quote after the inquiry finishes. The model cannot approve it.</p>
          <div id="business-quote-details" hidden><dl class="business-quote-facts"><div><dt>Booking</dt><dd id="business-quote-booking"></dd></div><div><dt>New check-in</dt><dd id="business-quote-date"></dd></div><div><dt>Exact amount</dt><dd id="business-quote-money"></dd></div><div><dt>Case / booking revision</dt><dd id="business-quote-revisions"></dd></div><div><dt>Quote expiry</dt><dd id="business-quote-expiry"></dd></div></dl>
          <label class="confirmation business-exact-confirmation" for="business-approval"><input id="business-approval" type="checkbox" /><span>I approve this exact date, price, currency and revision.<small>This is a separate command from investigation permission.</small></span></label><button id="business-confirm" class="primary" type="button" disabled>Confirm this exact quote</button><p id="business-confirm-note" class="business-explanation">Only this explicit action submits the frozen confirmation payload.</p></div>
        </section>
        <div class="business-cancel"><button id="business-cancel" class="danger" type="button" disabled>Request business cancellation</button><p>Ending voice or disconnecting does not cancel accepted work. A cancellation after dispatch is best effort.</p></div>
      </section>
      <section class="panel business-history" aria-labelledby="business-history-title"><div class="panel-head"><span class="overline">PERSISTED EVIDENCE</span><h3 id="business-history-title">Observed transitions</h3></div><p id="business-history-note" class="business-explanation">No persisted events have been loaded.</p><ol id="business-events" class="business-events"><li class="business-event-empty">Actual observations will appear here. Timers never create progress.</li></ol><button id="business-more" class="text-button" type="button" disabled>Load more observations</button><details class="business-technical"><summary>Technical details</summary><pre id="business-technical-data">No scoped case loaded.</pre></details></section>
    </div>
    <p class="business-scope-note">Synthetic local workflow. A stored outcome, receiver receipt, spoken response and human acknowledgement are separate facts.</p>`;
  const owned = new AbortController();
  let unauthorizedNotified = false;
  let disposed = false, timer: number | undefined, selectedTask: string | null = null, displayedQuote: string | null = null;
  let formKey = `ui-${crypto.randomUUID()}`;
  function element<T extends HTMLElement>(selector: string): T { const value = host.querySelector<T>(selector); if (!value) throw new Error('A business interface element is missing.'); return value; }
  const booking = element<HTMLInputElement>('#business-booking'), checkIn = element<HTMLInputElement>('#business-check-in'), investigation = element<HTMLInputElement>('#business-investigation');
  const approval = element<HTMLInputElement>('#business-approval'), resumeInput = element<HTMLInputElement>('#business-resume-id');
  const button = (selector: string): HTMLButtonElement => element<HTMLButtonElement>(selector);
  const setText = (selector: string, value: string): void => { element(selector).textContent = value; };
  function actionError(): void { setText('#business-status', 'Enter the local operator token above to inspect this scoped case.'); element('#business-status').dataset.phase = 'access_required'; }
  function token(held = false): string { try { return held ? options.heldToken() : options.takeToken(); } catch { actionError(); throw new BusinessError('unauthorized', 'Enter the local operator token again.'); } }
  function details(projection: BusinessProjection | null): string {
    if (!projection) return 'No scoped case loaded.';
    return JSON.stringify({ task_id: projection.task_id, case_id: projection.case_id, case_revision: projection.case_revision, original_investigation: projection.inquiry.request, current_request: projection.request, inquiry: projection.inquiry, lifecycle: projection.lifecycle, quote: projection.quote, confirmation: projection.confirmation, effect: projection.effect, outcome: projection.outcome, delivery: projection.delivery, projection_revision: projection.projection_revision }, null, 2);
  }
  function render(state: BusinessState): void {
    if (disposed) return;
    const projection = state.projection, stage = businessStage(projection), busy = state.phase === 'busy', access = state.phase === 'access_required', commandPending = state.pending_command !== null;
    setText('#business-state-title', stage.title); setText('#business-state-description', stage.description);
    const badge = element('#business-state-badge'); badge.dataset.tone = stage.tone; badge.textContent = access ? 'Access required' : state.phase === 'unknown' ? 'Acknowledgement unknown' : state.phase === 'error' ? 'Read needs attention' : busy ? 'Checking' : projection ? 'Persisted observation' : 'Ready';
    setText('#business-status', state.message); element('#business-status').dataset.phase = state.phase;
    // Forget after the failing operation finishes; a re-entrant forget() would relabel its definitive rejection as uncertain.
    if (state.error_code === 'unauthorized' && !unauthorizedNotified) { unauthorizedNotified = true; queueMicrotask(() => options.forgetToken()); } else if (state.error_code !== 'unauthorized') unauthorizedNotified = false;
    const frozen = state.pending_input;
    button('#business-submit').disabled = busy || state.task_id !== null;
    button('#business-submit').textContent = state.task_id ? 'Investigation accepted' : frozen ? 'Reconcile same investigation' : 'Submit investigation';
    for (const field of [booking, checkIn, investigation]) field.disabled = busy || frozen !== null || state.task_id !== null;
    if (frozen) { setText('#business-request-key', `Frozen request key: ${frozen.idempotency_key}`); element('#business-request-key').hidden = false; }
    else element('#business-request-key').hidden = true;
    button('#business-new').disabled = busy || (frozen !== null && state.task_id === null) || commandPending;
    button('#business-refresh').disabled = busy || state.task_id === null;
    button('#business-resume').disabled = busy || (frozen !== null && state.task_id === null) || commandPending;
    resumeInput.disabled = button('#business-resume').disabled;
    element('#business-identity').hidden = state.task_id === null;
    setText('#business-task-id', state.task_id ?? 'Not observed'); setText('#business-case-id', projection ? `${projection.case_id} / ${projection.case_revision}` : 'Current case facts unavailable');
    setText('#business-inquiry-state', projection ? human(projection.inquiry.state) : 'Not observed');
    setText('#business-confirmation-state', projection ? human(projection.confirmation.state) : 'Not observed');
    setText('#business-outcome-state', projection?.outcome ? human(projection.outcome.state) : 'Not observed');
    setText('#business-delivery-state', projection?.delivery ? human(projection.delivery.state) : 'Not observed');
    const quote = projection?.quote ?? null;
    if ((quote?.quote_id ?? null) !== displayedQuote) { displayedQuote = quote?.quote_id ?? null; approval.checked = false; }
    element('#business-quote-empty').hidden = quote !== null; element('#business-quote-details').hidden = quote === null;
    if (quote) {
      setText('#business-quote-booking', quote.booking_reference); setText('#business-quote-date', quote.new_check_in); setText('#business-quote-money', formatMoney(quote.amount_minor, quote.currency)); setText('#business-quote-revisions', `${quote.revision} / ${quote.expected_supplier_revision}`); setText('#business-quote-expiry', time(quote.expires_at));
    }
    button('#business-request-quote').disabled = busy || access || commandPending || projection === null || projection.inquiry.state !== 'succeeded' || projection.inquiry.result?.available !== true || projection.confirmation.state === 'committed' || projection.confirmation.state === 'cancelled' || projection.outcome !== null;
    approval.disabled = busy || access || state.phase === 'error' || state.phase === 'unknown' || commandPending || projection?.confirmation.state !== 'required';
    button('#business-confirm').disabled = approval.disabled || !approval.checked;
    button('#business-confirm').textContent = projection?.confirmation.state === 'committed' ? 'Exact confirmation stored' : 'Confirm this exact quote';
    button('#business-cancel').disabled = busy || access || commandPending || projection === null;
    element('#business-pending').hidden = state.pending_command === null;
    if (state.pending_command) {
      setText('#business-pending-description', `The original ${state.pending_command.kind} command is retained under ${state.pending_command.command_id}. Reconciliation repeats its frozen payload and cannot approve a newer proposal.`);
      setText('#business-pending-payload', JSON.stringify(state.pending_command.body, null, 2));
      button('#business-reconcile').disabled = busy || access;
    }
    const list = element<HTMLOListElement>('#business-events');
    const priorIds = new Set([...list.querySelectorAll<HTMLElement>('[data-event-id]')].map((row) => row.dataset.eventId));
    const rows = state.events.map((event) => {
      const row = document.createElement('li'); row.dataset.eventId = event.event_id; row.className = 'business-event'; if (!priorIds.has(event.event_id)) row.classList.add('business-event-new');
      const marker = document.createElement('span'); marker.className = 'business-event-marker'; marker.setAttribute('aria-hidden', 'true');
      const body = document.createElement('div'), heading = document.createElement('strong'), detail = document.createElement('span'), stamp = document.createElement('time');
      heading.textContent = EVENT_LABELS[event.kind] ?? 'Persisted observation'; detail.textContent = human(event.state); stamp.textContent = time(event.observed_at); stamp.dateTime = event.observed_at; body.append(heading, detail, stamp); row.append(marker, body); return row;
    });
    if (rows.length) list.replaceChildren(...rows);
    else { const empty = document.createElement('li'); empty.className = 'business-event-empty'; empty.textContent = 'No persisted events observed. No progress is inferred.'; list.replaceChildren(empty); }
    setText('#business-history-note', projection ? `${state.events.length} displayed / ${projection.events_total} retained observations.${state.history_limited ? ' Recent-window or display limits apply; this is not the complete audit log.' : ''}` : 'No persisted events have been loaded.');
    button('#business-more').disabled = busy || access || !projection?.has_more || state.events.length >= MAX_BUSINESS_EVENTS;
    setText('#business-technical-data', details(projection));
    if (projection && projection.task_id !== selectedTask) { selectedTask = projection.task_id; resumeInput.value = projection.task_id; options.onTask?.(projection.task_id); }
  }
  const controller = new BusinessController(render);
  async function invoke(action: () => Promise<void>): Promise<void> { try { await action(); } catch { actionError(); } }
  element<HTMLFormElement>('#business-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const input = controller.state.pending_input ?? { booking_reference: booking.value, new_check_in: checkIn.value, confirmed: investigation.checked, idempotency_key: formKey };
    void invoke(() => controller.submit(input, token()));
  }, { signal: owned.signal });
  element<HTMLFormElement>('#business-resume-form').addEventListener('submit', (event) => { event.preventDefault(); void invoke(() => controller.inspect(resumeInput.value.trim(), token())); }, { signal: owned.signal });
  approval.addEventListener('change', () => render(controller.state), { signal: owned.signal });
  for (const [selector, kind] of [['#business-request-quote', 'quote'], ['#business-confirm', 'signal'], ['#business-cancel', 'cancel']] as const) button(selector).addEventListener('click', () => {
    if (kind === 'signal' && !approval.checked) return;
    void invoke(() => controller.command(kind, token()));
  }, { signal: owned.signal });
  button('#business-reconcile').addEventListener('click', () => { const pending = controller.state.pending_command; if (pending) void invoke(() => controller.command(pending.kind as CommandKind, token())); }, { signal: owned.signal });
  button('#business-refresh').addEventListener('click', () => { void invoke(() => controller.refresh(token())); }, { signal: owned.signal });
  button('#business-more').addEventListener('click', () => { void invoke(() => controller.refresh(token(), true)); }, { signal: owned.signal });
  button('#business-new').addEventListener('click', () => { if (controller.newInvestigation()) { formKey = `ui-${crypto.randomUUID()}`; investigation.checked = false; approval.checked = false; selectedTask = null; booking.focus(); } }, { signal: owned.signal });
  const pollMilliseconds = options.pollMilliseconds ?? 1500;
  if (!Number.isInteger(pollMilliseconds) || pollMilliseconds < 1000 || pollMilliseconds > 10000) throw new Error('Business polling must have a bounded interval.');
  const schedule = (): void => { if (!disposed) timer = window.setTimeout(() => { const state = controller.state; if (!document.hidden && state.task_id && state.phase !== 'access_required' && state.phase !== 'busy' && !businessSettled(state.projection)) void invoke(() => controller.refresh(token(true))); schedule(); }, pollMilliseconds); };
  schedule(); render(controller.state);
  function dispose(): void { if (disposed) return; disposed = true; if (timer !== undefined) window.clearTimeout(timer); owned.abort(); controller.dispose(); }
  options.signal?.addEventListener('abort', dispose, { once: true });
  if (options.signal?.aborted) dispose();
  return { getCurrentTask: () => controller.state.projection?.task_id ?? null, getFrozenRequest: () => controller.state.pending_input, observeTask: (taskId) => invoke(() => controller.inspect(taskId, token(true))), resume: () => invoke(() => controller.refresh(token())), forget: () => controller.forget(), dispose };
}
