/** Source-labelled, read-only operations presentation. Reviewed 12 November 2026. */
import type { OperationsState, OperationsSection, UiCode } from './p2-operations-policy';

type Control = 'refresh' | 'retry' | 'forget' | 'pause';
export interface PanelActions {
  connect(token: string): void;
  refresh(): void;
  retry(): void;
  forget(): void;
  pause(): void;
  older(section: OperationsSection): void;
}
function node<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className = '',
  text = '',
): HTMLElementTagNameMap[K] {
  const value = document.createElement(tag);
  value.className = className;
  value.textContent = text;
  return value;
}
function badge(value: string, tone = ''): HTMLElement {
  return node('span', 'ops-badge ' + tone, value.replaceAll('_', ' '));
}
function line(label: string, value: string): HTMLElement {
  const d = node('div', 'ops-fact');
  d.append(node('dt', '', label), node('dd', '', value));
  return d;
}
function empty(text: string): HTMLElement {
  return node('p', 'ops-empty', text);
}
function listCard(title: string, subtitle: string): { section: HTMLElement; list: HTMLElement } {
  const section = node('section', 'ops-card');
  const heading = node('header', 'ops-card-heading');
  heading.append(node('h2', '', title), node('p', 'ops-muted', subtitle));
  const list = node('div', 'ops-list');
  section.append(heading, list);
  return { section, list };
}
const messages: Record<UiCode, string> = {
  invalid_query: 'This read request is not supported.',
  access_denied:
    'Current context access was denied. Updates are paused. Forget this view to authenticate again.',
  cursor_stale: 'This older-page cursor is stale. Refresh current to begin a new page window.',
  overloaded: 'A bounded read is already active. Wait for it to settle, then retry.',
  unavailable:
    'The read is unavailable. Retained facts remain labelled with their observation time.',
  closed: 'This read owner is closed.',
  invalid_response: 'The response could not be verified. Retained facts remain historical.',
  cleanup_incomplete:
    'Cleanup is still incomplete. The existing owner is retained; retry Forget after its work settles.',
};
export class OperationsPanel {
  readonly token = document.querySelector<HTMLInputElement>('[data-ops-token]')!;
  readonly connect = document.querySelector<HTMLButtonElement>('[data-ops-connect]')!;
  readonly status = document.querySelector<HTMLElement>('#operations-status')!;
  readonly notice = document.querySelector<HTMLElement>('#operations-notice')!;
  readonly content = document.querySelector<HTMLElement>('#operations-content')!;
  readonly evidence = document.querySelector<HTMLElement>('#operations-evidence')!;
  readonly controls = Object.fromEntries(
    (['refresh', 'retry', 'forget', 'pause'] as const).map((key) => [
      key,
      document.querySelector<HTMLButtonElement>(`[data-ops-${key}]`)!,
    ]),
  ) as Record<Control, HTMLButtonElement>;
  constructor(readonly actions: PanelActions) {
    document
      .querySelector<HTMLFormElement>('#operations-connect-form')!
      .addEventListener('submit', (event) => {
        event.preventDefault();
        const token = this.token.value;
        this.token.value = '';
        this.actions.connect(token);
      });
    for (const control of ['refresh', 'retry', 'forget', 'pause'] as const)
      this.controls[control].addEventListener('click', () => {
        if (control === 'forget') this.token.value = '';
        this.actions[control]();
      });
  }
  render(state: OperationsState): void {
    const focusedSection = this.content.contains(document.activeElement)
      ? ((document.activeElement as HTMLElement).dataset.opsMore ??
        (document.activeElement as HTMLElement).dataset.opsFocusSection)
      : undefined;
    this.connect.disabled = state.ownedClient === 1;
    this.token.disabled = state.ownedClient === 1;
    const available = !!state.view && !['closing', 'denied'].includes(state.phase);
    this.controls.refresh.disabled =
      state.ownedClient === 0 ||
      ['closing', 'denied'].includes(state.phase) ||
      state.contextPending;
    this.controls.retry.disabled =
      state.ownedClient === 0 ||
      ['closing', 'denied'].includes(state.phase) ||
      state.contextPending ||
      state.telemetryPending ||
      !(state.error?.retry === 'same_read' || state.telemetryError);
    this.controls.forget.disabled = state.ownedClient === 0;
    this.controls.pause.disabled = !available;
    this.controls.pause.textContent = state.polling ? 'Pause updates' : 'Resume updates';
    const label =
      state.phase === 'ready'
        ? state.contextHistorical
          ? 'Historical facts retained'
          : 'Current read available'
        : (
            {
              idle: 'Waiting for authenticated read',
              connecting: 'Reading current context',
              unavailable: 'Read unavailable',
              denied: 'Context access denied',
              closing: 'Clearing view · waiting for actual cleanup',
            } as const
          )[state.phase];
    this.status.replaceChildren(
      badge(label, state.phase === 'ready' ? 'good' : state.phase === 'denied' ? 'warn' : ''),
      node(
        'span',
        'ops-muted',
        state.polling
          ? `Updates every 2 seconds · ${state.ticksRemaining} ticks left`
          : 'Automatic updates paused',
      ),
    );
    this.status.dataset.phase = state.phase;
    this.notice.textContent = state.error
      ? messages[state.error.code]
      : state.telemetryError
        ? 'Process diagnostics are unavailable. Case observations are shown separately.'
        : state.phase === 'closing'
          ? 'Private facts and credentials are cleared. Reconnect becomes available only after the retained request owner actually closes.'
          : '';
    this.notice.hidden = !this.notice.textContent;
    this.content.replaceChildren();
    this.caseView(state);
    this.historyView(state);
    this.workView(state);
    this.replyView(state);
    this.responseView(state);
    this.telemetryView(state);
    if (focusedSection && ['history', 'work', 'responses', 'replies'].includes(focusedSection)) {
      const next = this.content.querySelector<HTMLButtonElement>(
        `[data-ops-more="${focusedSection}"]`,
      );
      if (next && !next.disabled) next.focus({ preventScroll: true });
      else {
        const section = next?.closest('section');
        if (section) {
          section.tabIndex = -1;
          section.dataset.opsFocusSection = focusedSection;
          section.setAttribute(
            'aria-label',
            section.querySelector('h2')?.textContent ?? 'Observations',
          );
          section.focus({ preventScroll: true });
        }
      }
    }
    this.evidence.textContent = JSON.stringify(
      {
        schemaVersion: 1,
        phase: state.phase,
        code: state.error?.code ?? null,
        telemetryCode: state.telemetryError,
        contextObserved: !!state.view,
        current: !!state.view && !state.contextHistorical,
        asOf: state.view?.context.observed.caseObservedAt ?? null,
        historical: state.contextHistorical,
        diagnosticsHistorical: state.diagnosticsHistorical,
        ownedClient: state.ownedClient,
        actualRequests: state.actualRequests,
        cleanupComplete: state.cleanupComplete,
        contextPending: state.contextPending,
        telemetryPending: state.telemetryPending,
        polling: state.polling,
        ticks: state.ticks,
        readCounts: {
          context: state.clientMetrics.contextStarted,
          telemetry: state.clientMetrics.telemetryStarted,
          settled: state.clientMetrics.settled,
          abandoned: state.clientMetrics.abandoned,
        },
        receipts: state.rows.history.map((x) => ({
          receiptId: x.value.receipt.receiptId,
          processingState: x.value.processingState,
          operationKey: x.value.operationKey,
        })),
        operations: state.rows.work.map((x) => ({
          operationKey: x.value.operationKey,
          state: x.value.state,
        })),
        outbound: state.rows.replies.map((x) => ({
          outboundId: x.value.outboundId,
          result: x.value.lastAttempt?.result ?? 'not_observed',
          callbacks: x.value.callbackObservations.map((v) => v.state),
        })),
        pages: {
          history: state.rows.history.length,
          work: state.rows.work.length,
          responses: state.rows.responses.length,
          replies: state.rows.replies.length,
        },
        sources:
          state.telemetry?.sources.map((x) => ({
            source: x.source,
            state: x.state,
            metricCount: x.values.length,
          })) ?? [],
        observationCount: state.telemetry?.observations.length ?? 0,
      },
      null,
      2,
    );
  }
  private older(section: OperationsSection, count: number, state: OperationsState): HTMLElement {
    const footer = node('footer', 'ops-card-footer');
    const button = node('button', 'ops-button subtle', 'Load older');
    button.type = 'button';
    button.dataset.opsMore = section;
    button.disabled =
      !state.cursors[section] ||
      count >= 32 ||
      state.contextPending ||
      ['closing', 'denied'].includes(state.phase);
    button.addEventListener('click', () => this.actions.older(section));
    footer.append(
      node(
        'span',
        'ops-muted',
        !state.view
          ? 'Waiting for observations'
          : count >= 32
            ? '32 rows retained · Refresh current to reset this window'
            : `${count} retained observations`,
      ),
      button,
    );
    return footer;
  }
  private caseView(state: OperationsState): void {
    const card = listCard('Current case', 'Latest observation from the case source.');
    card.section.classList.add('ops-case');
    const value = state.view?.context;
    if (!value)
      card.list.append(empty('Connect with an operator credential to read the current case.'));
    else {
      card.list.append(
        badge(
          state.contextHistorical
            ? 'Historical · read unavailable'
            : 'As of latest successful read',
          state.contextHistorical ? 'warn' : 'good',
        ),
      );
      const facts = node('dl', 'ops-facts');
      facts.append(
        line('Case', value.case.caseId),
        line('Revision', value.case.revision),
        line('Case source', value.case.source),
        line('Case observed', value.observed.caseObservedAt),
        line('P2 observed', value.observed.p2ObservedAt),
        line('Disclosure admitted', value.observed.disclosureAdmittedAt),
        line(
          'Investigation',
          `${value.case.request.bookingReference} · ${value.case.request.newCheckIn}`,
        ),
        line('Workflow', value.case.workflow?.state ?? 'not observed'),
        line('Intent', value.case.intent.state),
        line('Mutation outcome', value.case.mutation.outcome),
        line(
          'Supplier result',
          value.case.supplierResult
            ? `${value.case.supplierResult.supplierId} · revision ${value.case.supplierResult.revision}`
            : 'not observed',
        ),
      );
      card.list.append(
        facts,
        node(
          'p',
          'ops-callout',
          value.case.revision === '0'
            ? 'Revision 0 is read-only context. This page cannot advance it or grant execution.'
            : 'Refresh current to check for changes to this case.',
        ),
      );
    }
    this.content.append(card.section);
  }
  private historyView(state: OperationsState): void {
    const card = listCard(
      'Accepted input timeline',
      'Original receipts and their observed processing state.',
    );
    for (const { value, observedAt } of state.rows.history) {
      const row = node('article', 'ops-row');
      row.dataset.opsReceipt = value.receipt.receiptId;
      row.dataset.processingState = value.processingState;
      const top = node('div', 'ops-row-top');
      top.append(
        badge(value.processingState),
        node('span', 'ops-mono ops-muted', `#${value.receipt.acceptanceSequence}`),
      );
      const body = node(
        'p',
        'ops-input-text',
        value.event.body ?? `${value.event.type} · original event`,
      );
      const ids = node('dl', 'ops-facts compact');
      ids.append(
        line('Receipt', value.receipt.receiptId),
        line('Operation', value.operationKey),
        line('Accepted', value.receipt.acceptedAt),
        line('Observed', observedAt),
      );
      row.append(top, body, ids);
      card.list.append(row);
    }
    if (!state.rows.history.length)
      card.list.append(
        empty(
          state.view
            ? 'No accepted inputs in this page window.'
            : 'Connect to view accepted inputs.',
        ),
      );
    card.section.append(this.older('history', state.rows.history.length, state));
    this.content.append(card.section);
  }
  private workView(state: OperationsState): void {
    const card = listCard('Input dispatch', 'Pending work and the latest dispatch state.');
    for (const { value, observedAt } of state.rows.work) {
      const row = node('article', 'ops-row');
      row.dataset.opsWork = value.operationKey;
      row.append(badge(value.state), node('p', 'ops-mono', value.operationKey));
      const facts = node('dl', 'ops-facts compact');
      facts.append(
        line('Receipt', value.receiptId),
        line('Possible external call', String(value.possibleExternal)),
        line('Attempts', String(value.attempts)),
        line('Last code', value.lastCode),
        line('Observed', observedAt),
      );
      row.append(facts);
      card.list.append(row);
    }
    if (!state.rows.work.length)
      card.list.append(
        empty(
          state.view
            ? 'No non-dispatched input work in this page window.'
            : 'Connect to view dispatch work.',
        ),
      );
    card.section.append(this.older('work', state.rows.work.length, state));
    this.content.append(card.section);
  }
  private replyView(state: OperationsState): void {
    const card = listCard('Carrier replies', 'Send results and carrier updates, shown separately.');
    for (const { value, observedAt } of state.rows.replies) {
      const row = node('article', 'ops-row');
      row.dataset.opsOutbound = value.outboundId;
      row.append(node('p', 'ops-mono', value.outboundId));
      const result = node('div', 'ops-evidence-lane');
      result.dataset.opsSource = 'send_result';
      result.append(
        node('h3', '', 'Send result'),
        badge(value.lastAttempt?.result ?? 'not_observed'),
      );
      const callbacks = node('div', 'ops-evidence-lane');
      callbacks.dataset.opsSource = 'callback';
      callbacks.append(node('h3', '', 'Carrier callback'));
      if (!value.callbackObservations.length) callbacks.append(badge('not observed'));
      else
        for (const observation of value.callbackObservations)
          callbacks.append(badge(observation.state));
      if (value.callbacksTruncated)
        callbacks.append(
          node('p', 'ops-muted', 'Callback display is bounded; more retained facts exist.'),
        );
      const facts = node('dl', 'ops-facts compact');
      facts.append(
        line('Original receipt', value.receiptId),
        line('Send attempts', String(value.attemptCount)),
        line('Observed', observedAt),
      );
      row.append(result, callbacks, facts);
      card.list.append(row);
    }
    if (!state.rows.replies.length)
      card.list.append(
        empty(
          state.view
            ? 'No outbound replies in this page window.'
            : 'Connect to view outbound replies.',
        ),
      );
    card.section.append(this.older('replies', state.rows.replies.length, state));
    this.content.append(card.section);
  }
  private responseView(state: OperationsState): void {
    const card = listCard(
      'Response observations',
      'Generated text, SDK output and browser reports.',
    );
    for (const { value } of state.rows.responses) {
      const row = node('article', 'ops-row');
      row.append(node('p', 'ops-mono', value.anchor.responseId), badge('historical'));
      const facts = node('dl', 'ops-facts compact');
      facts.append(
        line('Generated stream', value.generated.state),
        line('SDK settled handle', value.sdk.state),
        line('Browser report', value.browserState),
        line('Conflicting evidence', String(value.conflicted)),
        line('Receipt', value.anchor.receiptId),
      );
      row.append(facts);
      card.list.append(row);
    }
    if (!state.rows.responses.length)
      card.list.append(
        empty(
          state.view
            ? 'No response observations in this page window.'
            : 'Connect to view response observations.',
        ),
      );
    card.section.append(this.older('responses', state.rows.responses.length, state));
    this.content.append(card.section);
  }
  private telemetryView(state: OperationsState): void {
    const card = listCard('Process diagnostics', 'Process counters and observed read activity.');
    card.section.classList.add('ops-diagnostics');
    const value = state.telemetry;
    if (!value)
      card.list.append(
        empty(
          state.telemetryError
            ? 'Process diagnostics could not be read.'
            : 'No authenticated process observation yet.',
        ),
      );
    else {
      card.list.append(
        badge(
          state.diagnosticsHistorical ? 'Historical process observation' : 'Process snapshot',
          state.diagnosticsHistorical ? 'warn' : '',
        ),
        node(
          'p',
          'ops-muted',
          `Observed ${value.observedAt}. These counters can reset on process restart.`,
        ),
      );
      const sources = node('div', 'ops-metric-grid');
      for (const source of value.sources) {
        const box = node('section', 'ops-metric-source');
        box.append(node('h3', '', source.source), badge(source.state));
        if (source.state !== 'observed')
          box.append(node('p', 'ops-muted', 'No numeric observation available.'));
        for (const metric of source.values) box.append(line(metric.name, String(metric.value)));
        sources.append(box);
      }
      card.list.append(sources);
      const heading = node('h3', '', 'Read spans and producer observations');
      card.list.append(heading);
      const table = node('table', 'ops-table');
      const head = node('thead');
      const hr = node('tr');
      for (const label of ['Source / operation', 'Status', 'Elapsed', 'Observed'])
        hr.append(node('th', '', label));
      head.append(hr);
      table.append(head);
      const body = node('tbody');
      for (const item of value.observations) {
        const row = node('tr');
        row.append(
          node('td', '', `${item.source} / ${item.operation}`),
          node('td', '', `${item.status} · ${item.code}`),
          node('td', 'ops-mono', `${item.durationMs} ms`),
          node('td', 'ops-mono', item.observedAt),
        );
        body.append(row);
      }
      table.append(body);
      const scroll = node('div', 'ops-table-scroll');
      scroll.tabIndex = 0;
      scroll.setAttribute('aria-label', 'Process observations table');
      scroll.append(table);
      card.list.append(scroll);
    }
    this.content.append(card.section);
  }
}
