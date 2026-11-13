/** A read-only continuity view. Past-room evidence never becomes active media controls. */
import type { ContextPhase, RehydrationContext } from './p2-context-policy';

export class ContextPanel {
  #signature = '';
  constructor(readonly host: HTMLElement) {}
  render(value: RehydrationContext | null, phase: ContextPhase, roomLive: boolean): void {
    const signature = `${value?.contextId ?? ''}:${phase}:${roomLive}`;
    if (signature === this.#signature) return;
    this.#signature = signature;
    this.host.replaceChildren();
    if (!value) {
      const empty = document.createElement('p');
      empty.className = 'native-muted';
      empty.textContent =
        phase === 'loading'
          ? 'Checking current access and loading your case…'
          : 'Your verified case and accepted history appear here when the continuity profile is active.';
      this.host.append(empty);
      return;
    }
    const live = phase === 'ready' && roomLive;
    const note = document.createElement('p');
    note.className = 'native-context-note';
    note.textContent = live
      ? 'Verified observations for this session. Case facts and channel history were read separately. These are as-of observations; refresh to inspect later workflow or supplier changes.'
      : 'Retained observations from the last verified read. Refresh current access before continuing.';
    this.host.append(note);
    const grid = document.createElement('div');
    grid.className = 'native-context-grid';
    const facts = document.createElement('dl');
    facts.className = 'native-context-facts';
    const fact = (label: string, text: string, key: string) => {
      const name = document.createElement('dt');
      name.textContent = label;
      const detail = document.createElement('dd');
      detail.textContent = text;
      detail.dataset.contextFact = key;
      facts.append(name, detail);
    };
    fact('Case', value.case.caseId, 'case-id');
    fact('Observed revision', value.case.revision, 'revision');
    fact('Booking', value.case.request.bookingReference, 'booking');
    fact('Requested check-in', value.case.request.newCheckIn, 'check-in');
    fact(
      'Workflow',
      value.case.workflow?.state.replaceAll('_', ' ') ?? 'No authoritative workflow observation',
      'workflow',
    );
    fact(
      'Supplier outcome',
      value.case.supplierResult
        ? `Known change · ${value.case.supplierResult.newCheckIn}`
        : 'Not observed',
      'supplier',
    );
    grid.append(facts);
    const channelHistory = document.createElement('div');
    const heading = document.createElement('h3');
    heading.textContent = 'Accepted conversation';
    const list = document.createElement('ol');
    list.className = 'native-context-history';
    for (const message of value.history.messages) {
      const row = document.createElement('li');
      row.dataset.historyReceipt = message.receipt.receiptId;
      row.dataset.channel = message.event.channel ?? message.event.type;
      const source = document.createElement('span');
      source.className = 'native-entry-source';
      source.textContent =
        message.event.channel === 'sms'
          ? 'SMS · accepted input'
          : message.event.channel === 'voice_transcript'
            ? 'Voice · accepted input'
            : message.event.channel === 'web_chat'
              ? 'Chat · accepted input'
              : 'Retained channel observation';
      const body = document.createElement('p');
      body.textContent = message.event.body ?? 'Source observation retained';
      row.append(source, body);
      list.append(row);
    }
    if (!value.history.messages.length) {
      const empty = document.createElement('li');
      empty.textContent = 'No accepted messages in this window.';
      list.append(empty);
    }
    channelHistory.append(heading, list);
    if (value.history.hasMore) {
      const more = document.createElement('p');
      more.className = 'native-muted';
      more.textContent =
        'A bounded recent window is shown. Additional history remains in the continuity store.';
      channelHistory.append(more);
    }
    grid.append(channelHistory);
    this.host.append(grid);
    const pending = document.createElement('div');
    pending.className = 'native-context-work';
    const title = document.createElement('h3');
    title.textContent = 'Pending input dispatch';
    pending.append(title);
    for (const work of value.work.items) {
      const item = document.createElement('p');
      item.dataset.contextOperation = work.operationKey;
      item.textContent = `${work.state.replaceAll('_', ' ')} · ${work.possibleExternal ? 'An external call may already have happened' : 'No possible external call recorded'}`;
      pending.append(item);
    }
    if (!value.work.items.length) {
      const empty = document.createElement('p');
      empty.className = 'native-muted';
      empty.textContent =
        'No pending input dispatch in this window. Workflow completion is shown separately.';
      pending.append(empty);
    }
    this.host.append(pending);
    if (value.responses.items.length) {
      const evidence = document.createElement('div');
      evidence.className = 'native-context-evidence';
      const title = document.createElement('h3');
      title.textContent = 'Earlier response observations';
      evidence.append(title);
      for (const response of value.responses.items) {
        const item = document.createElement('div');
        item.className = 'native-context-response';
        item.dataset.historicalResponse = response.anchor.responseId;
        item.dataset.originalBinding = response.anchor.bindingId;
        const summary = document.createElement('p');
        summary.textContent = `Generated ${response.generated.state.replaceAll('_', ' ')} · SDK ${response.sdk.state} · browser ${response.browserState.replaceAll('_', ' ')}`;
        const source = document.createElement('p');
        source.className = 'native-muted';
        source.textContent = `Original room ${response.anchor.roomId}. Historical observations; no current-room playback or interruption authority.`;
        item.append(summary, source);
        evidence.append(item);
      }
      this.host.append(evidence);
    }
    if (value.replies.items.length) {
      const title = document.createElement('h3');
      title.textContent = 'Carrier observations';
      this.host.append(title);
      for (const reply of value.replies.items) {
        const item = document.createElement('p');
        item.dataset.contextReply = reply.outboundId;
        const callbacks = reply.callbackObservations.map((observation) =>
          observation.state.replaceAll('_', ' '),
        );
        item.textContent = `Provider attempt ${reply.lastAttempt?.result.replaceAll('_', ' ') ?? 'not observed'}${callbacks.length ? ` · ${callbacks.join(', ')}` : ''}. Human acknowledgement remains unobserved.`;
        this.host.append(item);
      }
    }
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = 'Context observation details';
    const source = document.createElement('p');
    source.className = 'native-entry-ids';
    source.textContent = `${value.case.source} · case read ${value.observed.caseObservedAt} · channel read ${value.observed.p2ObservedAt} · disclosure admitted ${value.observed.disclosureAdmittedAt}. These are separate observations.`;
    details.append(summary, source);
    this.host.append(details);
  }
}
