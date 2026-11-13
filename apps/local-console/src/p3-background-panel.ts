/** Compact presentation of validated P3 observations; no authority or network I/O. */
import type { BackgroundCode, BackgroundState } from './p3-background-policy';
export interface BackgroundReadEvidence {
  readonly state: string;
  readonly workId: string | null;
  readonly requestRevision: number;
  readonly inputFingerprint: string;
  readonly ownedRun: boolean;
  readonly hasResult: boolean;
  readonly applicability: string | null;
  readonly resultSha256: string | null;
  readonly disposition: string | null;
  readonly attemptId: string | null;
  readonly appReadCompletedAtMs: number;
}
export interface BackgroundCard {
  readonly evidence: BackgroundReadEvidence;
  readonly heading: string;
  readonly summary: string | null;
  readonly facts: readonly Readonly<{ label: string; value: string }>[];
}
export interface BackgroundActions {
  connect(token: string): void;
  send(text: string): void;
  refresh(): void;
  end(): void;
  forget(): void;
}
const notices: Record<BackgroundCode, string> = {
  invalid: 'Check the credential or message. Messages are limited to 4,096 UTF-8 bytes.',
  access_denied:
    'Access was denied. Retained observations are historical. Forget this view to connect again.',
  unavailable:
    'The latest read or connection is unavailable. Check again when the existing request settles.',
  unknown: 'Message delivery is unknown. It has not been sent again automatically.',
  overloaded: 'An existing operation is still active. Wait for it to settle before trying again.',
  closed: 'Join the configured session before sending or reading.',
  cleanup_incomplete:
    'Cleanup is incomplete. The existing owner is retained. Retry End or Forget after it settles.',
};
function required<T extends Element>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  if (!element) throw new Error('The background page is incomplete.');
  return element;
}
function node<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text = '',
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  return element;
}
export class BackgroundPanel<T> {
  readonly token: HTMLInputElement;
  readonly composer: HTMLTextAreaElement;
  readonly setup: HTMLDetailsElement;
  readonly notice: HTMLElement;
  readonly #connect: HTMLButtonElement;
  readonly #send: HTMLButtonElement;
  readonly #refresh: HTMLButtonElement;
  readonly #end: HTMLButtonElement;
  readonly #forget: HTMLButtonElement;
  readonly #connection: HTMLElement;
  readonly #agent: HTMLElement;
  readonly #messages: HTMLElement;
  readonly #empty: HTMLElement;
  readonly #card: HTMLElement;
  readonly #cardState: HTMLElement;
  readonly #evidence: HTMLElement;
  readonly #rows = new Map<number, HTMLElement>();
  #joiningFocus = false;
  #previousPhase = 'idle';
  #renderedObservation: T | null = null;
  #readEvidence: BackgroundReadEvidence | null = null;
  constructor(
    readonly actions: BackgroundActions,
    readonly project: (value: T) => BackgroundCard,
    root: ParentNode = document,
  ) {
    this.token = required(root, '[data-p3-token]');
    this.composer = required(root, '[data-p3-message]');
    this.setup = required(root, '[data-p3-setup]');
    this.notice = required(root, '[data-p3-notice]');
    this.#connect = required(root, '[data-p3-connect]');
    this.#send = required(root, '[data-p3-send]');
    this.#refresh = required(root, '[data-p3-refresh]');
    this.#end = required(root, '[data-p3-end]');
    this.#forget = required(root, '[data-p3-forget]');
    this.#connection = required(root, '[data-p3-connection]');
    this.#agent = required(root, '[data-p3-agent]');
    this.#messages = required(root, '[data-p3-transcript]');
    this.#empty = required(root, '[data-p3-empty]');
    this.#card = required(root, '[data-p3-card]');
    this.#cardState = required(root, '[data-p3-card-state]');
    this.#evidence = required(root, '[data-p3-evidence]');
    required<HTMLFormElement>(root, '[data-p3-connect-form]').addEventListener(
      'submit',
      (event) => {
        event.preventDefault();
        const token = this.token.value;
        this.token.value = '';
        this.#joiningFocus = true;
        this.actions.connect(token);
      },
    );
    const compose = required<HTMLFormElement>(root, '[data-p3-compose-form]');
    compose.addEventListener('submit', (event) => {
      event.preventDefault();
      if (!this.#send.disabled) {
        const text = this.composer.value;
        this.composer.value = '';
        this.actions.send(text);
      }
    });
    this.composer.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (!this.#send.disabled) compose.requestSubmit();
      }
    });
    this.#refresh.addEventListener('click', () => this.actions.refresh());
    this.#end.addEventListener('click', () => this.actions.end());
    this.#forget.addEventListener('click', () => {
      this.token.value = '';
      this.composer.value = '';
      this.actions.forget();
    });
  }
  showError(code: BackgroundCode): void {
    this.notice.textContent = notices[code];
    this.notice.hidden = false;
  }
  clearInputs(): void {
    this.token.value = '';
    this.composer.value = '';
  }
  render(state: BackgroundState<T>): void {
    const phase = {
      idle: 'Not connected',
      joining: 'Joining session',
      connected: 'Connected',
      reconnecting: 'Reconnecting',
      ending: 'Ending session',
      cleanup_incomplete: 'Cleanup incomplete',
      disconnected: 'Session ended',
    }[state.phase];
    this.#connection.textContent = phase;
    this.#connection.dataset.state = state.phase;
    this.#agent.textContent =
      state.ready && state.phase === 'connected'
        ? 'Agent ready · text'
        : state.phase === 'connected'
          ? 'Waiting for agent readiness'
          : 'Native RTC text';
    this.#connect.disabled = state.ownedClient === 1;
    this.token.disabled = state.ownedClient === 1;
    this.composer.disabled =
      state.phase !== 'connected' ||
      state.code === 'access_denied' ||
      !state.ready ||
      state.actualSends === 1;
    this.#send.disabled = this.composer.disabled;
    if (state.phase === 'connected' && this.#previousPhase === 'joining') this.setup.open = false;
    if (this.#joiningFocus && !this.composer.disabled) {
      if (
        document.activeElement === document.body ||
        document.activeElement === this.token ||
        document.activeElement === this.#connect
      )
        this.composer.focus();
      this.#joiningFocus = false;
    }
    if (state.phase === 'ending' || state.phase === 'disconnected' || state.phase === 'idle')
      this.#joiningFocus = false;
    this.#previousPhase = state.phase;
    this.#refresh.disabled =
      state.phase !== 'connected' || state.actualRequests === 1 || state.code === 'access_denied';
    this.#refresh.textContent = state.reading
      ? 'Reading…'
      : state.code === 'unavailable'
        ? 'Retry read'
        : 'Check result';
    this.#end.disabled = state.ownedClient === 0;
    this.#end.textContent = state.phase === 'cleanup_incomplete' ? 'Retry End' : 'End';
    this.#forget.disabled =
      state.ownedClient === 0 && state.observation === null && state.messages.length === 0;
    this.notice.hidden = state.code === null;
    if (state.code) this.notice.textContent = notices[state.code];
    this.#renderMessages(state);
    if (!state.observation) {
      this.#cardState.textContent = state.reading
        ? 'Reading observations'
        : 'Waiting for observations';
      this.#renderedObservation = null;
      this.#readEvidence = null;
      this.#card.replaceChildren(
        node('h3', '', 'No result observed yet'),
        node('p', 'p3-muted', 'Join the session, ask the agent, then check the configured work.'),
      );
    } else {
      this.#cardState.textContent = state.historical
        ? 'Historical observation retained'
        : state.reading
          ? 'Refreshing observation'
          : 'As-of observation';
      if (this.#renderedObservation !== state.observation) {
        const wasOpen = this.#card.querySelector('details')?.open ?? false;
        const card = this.project(state.observation),
          facts = node('dl', 'p3-facts');
        for (const fact of card.facts) {
          const row = node('div', '');
          row.append(node('dt', '', fact.label), node('dd', '', fact.value));
          facts.append(row);
        }
        const summary = card.summary === null ? [] : [node('p', 'p3-result-summary', card.summary)];
        const details = node('details', 'p3-result-details');
        details.open = wasOpen;
        details.append(node('summary', '', 'Original facts and read time'), facts);
        this.#card.replaceChildren(node('h3', '', card.heading), ...summary, details);
        this.#renderedObservation = state.observation;
        this.#readEvidence = card.evidence;
      }
    }
    this.#evidence.textContent = JSON.stringify(
      {
        schemaVersion: 1,
        session: state.identity,
        observation: this.#readEvidence,
        phase: state.phase,
        code: state.code,
        ready: state.ready,
        ownedClient: state.ownedClient,
        actualRequests: state.actualRequests,
        actualSends: state.actualSends,
        observationKnown: state.observation !== null,
        historical: state.historical,
        messages: state.messages.length,
        cleanupComplete: state.cleanupComplete,
      },
      null,
      2,
    );
  }
  #renderMessages(state: BackgroundState<T>): void {
    const nearBottom =
      this.#messages.scrollHeight - this.#messages.scrollTop - this.#messages.clientHeight < 40;
    let added = false;
    const retained = new Set(state.messages.map((message) => message.id));
    for (const [id, element] of this.#rows)
      if (!retained.has(id)) {
        element.remove();
        this.#rows.delete(id);
      }
    this.#empty.hidden = state.messages.length > 0;
    for (const message of state.messages) {
      let row = this.#rows.get(message.id);
      if (!row) {
        row = node('article', `p3-message p3-message-${message.role}`);
        row.dataset.p3MessageId = String(message.id);
        row.append(
          node('span', 'p3-message-role', message.role === 'agent' ? 'Agent' : 'You'),
          node('p', 'p3-message-text', message.text),
          node('span', 'p3-message-delivery'),
        );
        this.#rows.set(message.id, row);
        this.#messages.append(row);
        added = true;
      }
      required<HTMLElement>(row, '.p3-message-delivery').textContent = {
        sending: 'Sending to room',
        sent: 'Sent to room',
        unknown: 'Delivery unknown',
        received: 'Received from selected agent',
      }[message.delivery];
    }
    if (added && nearBottom) this.#messages.scrollTop = this.#messages.scrollHeight;
  }
}
