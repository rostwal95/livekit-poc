/** DOM projection of validated source observations; dynamic content always textContent. */
import type { View } from './channel-policy-policy';
import type { ProgressView } from './channel-policy-wire';
export interface PanelFacts {
  readonly notice: string | null;
  readonly progress: ProgressView | null;
  readonly voicePrepared: boolean;
  readonly turnActive: boolean;
  readonly playing: boolean;
  readonly busy: boolean;
  readonly speech: string | null;
}
const phases: Record<View['phase'], string> = {
  locked: 'Not connected',
  idle: 'Ready to join',
  starting: 'Joining session',
  start_unknown: 'Join outcome unknown',
  connecting: 'Connecting media',
  waiting_agent: 'Waiting for the native agent',
  ready: 'Ready',
  reconnecting: 'Reconnecting this session',
  ending: 'Ending session',
  cleanup_incomplete: 'Cleanup incomplete',
  dormant: 'Session ended',
};
export function policyCopy(
  view: Pick<View, 'policy' | 'policyHistorical'>,
): Readonly<{ heading: string; detail: string; time: string | null }> {
  const fact = view.policy;
  if (!fact)
    return {
      heading: 'No result observed',
      detail: 'Join a session to ask the agent for a check.',
      time: null,
    };
  if (view.policyHistorical)
    return {
      heading: 'Previous case observation',
      detail: 'The case revision has changed. Refresh before using this conclusion.',
      time: fact.asOf,
    };
  if (fact.state === 'unavailable')
    return {
      heading: 'Read unavailable',
      detail: 'No current conclusion was established. Retry the read when its owner settles.',
      time: null,
    };
  if (fact.state === 'no_delivery')
    return {
      heading: 'No result observed',
      detail: 'No result was delivered in this read. Accepted work may still be running.',
      time: fact.asOf,
    };
  if (fact.state === 'not_applicable')
    return {
      heading: 'No applicable result',
      detail: 'No applicable policy result was observed for this case.',
      time: fact.asOf,
    };
  return {
    heading:
      fact.uncertainty !== 'none'
        ? 'More information needed'
        : fact.eligible
          ? 'Eligible under the policy'
          : 'Not eligible under the policy',
    detail:
      fact.uncertainty === 'missing'
        ? 'The recorded evidence is missing required facts.'
        : fact.uncertainty === 'conflicting'
          ? 'The recorded evidence contains conflicting facts.'
          : 'This conclusion applies to the result’s observed case revision.',
    time: fact.asOf,
  };
}
/** Availability describes the latest current-result read, independently of other commands. */
export function policyReadCaption(view: Pick<View, 'policy' | 'policyRead'>): string | null {
  const prior = view.policy !== null;
  if (view.policyRead === 'pending')
    return prior ? 'Checking again; showing the prior observation.' : 'Reading the current result.';
  if (view.policyRead === 'busy')
    return prior
      ? 'Latest read busy; showing the prior observation.'
      : 'Latest result read is busy.';
  if (view.policyRead === 'unavailable')
    return prior
      ? 'Latest read unavailable; showing the prior observation.'
      : 'Latest result read unavailable.';
  return null;
}
export class JoinedPanel {
  #focusWhenReady = false;
  joining(): void {
    this.#focusWhenReady = true;
  }
  cancelFocus(): void {
    this.#focusWhenReady = false;
  }
  constructor(readonly root: ParentNode = document) {}
  element<T extends HTMLElement>(name: string): T {
    const element = this.root.querySelector<T>('[data-cp-' + name + ']');
    if (!element) throw new Error('The joined view is incomplete.');
    return element;
  }
  text(name: string, value: string): void {
    const node = this.element(name);
    if (node.textContent !== value) node.textContent = value;
  }
  render(view: View, facts: PanelFacts): void {
    const text = (name: string, value: string): void => this.text(name, value),
      button = (name: string, disabled: boolean): void => {
        this.element<HTMLButtonElement>(name).disabled = disabled;
      };
    text('state', phases[view.phase]);
    this.element('case').dataset.hasObservations = String(
      view.case !== null || view.policy !== null || facts.progress !== null,
    );
    if (view.ready && this.#focusWhenReady) {
      this.#focusWhenReady = false;
      this.element(!this.element('voice').hidden ? 'prepare-voice' : 'message').focus();
    }
    this.element('state').dataset.ready = String(view.ready);
    const join = this.element<HTMLButtonElement>('join');
    join.textContent =
      view.phase === 'start_unknown'
        ? 'Retry original Join'
        : view.phase === 'dormant'
          ? 'Join again'
          : 'Join session';
    join.disabled =
      view.authorized &&
      (view.roomOwned ||
        (view.phase !== 'start_unknown' && view.parent?.stage !== 'dormant') ||
        view.requests > 0 ||
        (view.start !== null && view.phase !== 'start_unknown') ||
        !['idle', 'dormant', 'start_unknown'].includes(view.phase));
    button('end', view.start === null);
    button('forget', !view.authorized && !view.roomOwned);
    button('refresh', !view.authorized || view.reading);
    button('send', !view.ready || facts.busy);
    button('prepare-voice', !view.ready || facts.voicePrepared || facts.busy);
    button('start-voice', !view.ready || !facts.voicePrepared || facts.turnActive || facts.busy);
    button('commit-voice', !view.ready || !facts.turnActive || facts.busy);
    button('interrupt', !view.ready || facts.speech !== 'speaking');
    button('enable-audio', !view.roomOwned);
    this.element<HTMLTextAreaElement>('message').disabled = !view.ready;
    this.element('retry-text').hidden =
      !view.ready ||
      !view.inputs.some((row) => row.channel === 'web_chat' && row.status === 'unknown');
    text(
      'notice',
      facts.notice ??
        (view.code === 'cleanup_incomplete'
          ? 'The original owner is retained. Retry End; a new session stays blocked.'
          : view.code === 'unknown'
            ? 'The acknowledgement is unknown. Reuse the original command unchanged.'
            : view.code === 'denied'
              ? 'Browser access was denied. Forget before entering another key.'
              : view.code === 'unavailable'
                ? 'The latest observation is unavailable. Existing work remains independent.'
                : view.ready
                  ? 'Ready for text or a declared recorded voice turn.'
                  : view.phase === 'dormant'
                    ? 'This media session ended. Background work and browser access remain available.'
                    : 'Readiness and results appear only after their source is observed.'),
    );
    text('native', view.ready ? 'Native agent ready · scripted' : 'Recorded input · scripted');
    text(
      'playback',
      facts.playing ? 'Selected-track audio is playing' : 'No audio playback observed',
    );
    text(
      'speech',
      facts.turnActive
        ? 'Voice turn started · commit to submit'
        : facts.speech
          ? 'Native SDK: ' + facts.speech
          : 'SDK speech and durable input acceptance are separate.',
    );
    text('revision', view.case?.revision ?? 'Not observed');
    text('case-time', view.case?.observedAt ?? '—');
    const copy = policyCopy(view),
      caption = policyReadCaption(view);
    text('policy-title', copy.heading);
    text('policy-detail', caption ? copy.detail + ' ' + caption : copy.detail);
    text('result-time', copy.time ?? '—');
    const p = facts.progress;
    text(
      'progress',
      p
        ? `${p.counts.native + p.counts.sms} inputs observed · ${p.counts.workKnown} original work references · ${p.counts.pending + p.counts.running} awaiting dispatch`
        : 'No input or work counts read yet.',
    );
    text('progress-time', p ? 'Counts read ' + p.asOf : '');
    this.element('dormant').hidden = !(
      view.authorized &&
      view.phase === 'dormant' &&
      !view.roomOwned
    );
    button('sms', view.requests > 0 || view.sms === 'sending');
    text('sms', view.sms === 'unknown' ? 'Retry original SMS' : 'Send simulated SMS');
    this.element<HTMLTextAreaElement>('sms-message').disabled =
      view.sms === 'unknown' || view.sms === 'sending';
    text(
      'sms-state',
      view.sms === 'unknown'
        ? 'SMS acknowledgement unknown. Retry its original body, timestamp and command.'
        : view.sms === 'accepted'
          ? 'The original SMS receipt was observed. Case revision is unchanged by sending.'
          : view.sms === 'sending'
            ? 'Waiting for the original SMS acknowledgement…'
            : '',
    );
    const host = this.element('transcript');
    const ids = new Set(view.messages.map((row) => String(row.id)));
    for (const node of [...host.querySelectorAll<HTMLElement>('[data-message-id]')])
      if (!ids.has(node.dataset.messageId!)) node.remove();
    this.element('empty').hidden = view.messages.length > 0;
    const current = view.activation;
    for (const message of view.messages) {
      let item = host.querySelector<HTMLElement>('[data-message-id="' + message.id + '"]');
      if (!item) {
        item = document.createElement('article');
        item.dataset.messageId = String(message.id);
        const meta = document.createElement('div');
        meta.className = 'cp-message-meta';
        const body = document.createElement('p');
        body.className = 'cp-message-text';
        body.textContent = message.text;
        item.append(meta, body);
        host.append(item);
      }
      item.className =
        'cp-message cp-message-' +
        message.role +
        (view.phase === 'dormant' || message.activation !== current ? ' cp-previous' : '');
      const label =
        (message.role === 'user' ? 'You' : 'Agent') +
        (view.phase === 'dormant' || message.activation !== current ? ' · previous session' : '');
      if (item.firstElementChild!.textContent !== label)
        item.firstElementChild!.textContent = label;
    }
    text(
      'evidence',
      JSON.stringify(
        {
          parentStage: view.parent?.stage ?? null,
          parentGeneration: view.parent?.cursor.generation ?? null,
          actualBrowserRequests: view.requests,
          roomOwned: view.roomOwned,
          acceptedInputs: view.inputs.filter((row) => row.receiptId !== null).length,
          sdkGenerationObservations: view.generationCount,
          lastInput: view.inputs.at(-1)?.status ?? null,
          scope: 'as_of_non_atomic; dispatch is not execution completion',
        },
        null,
        2,
      ),
    );
  }
}
