/** Optional joined application; Parent owns authority, SDK adapter owns one activation. */
import { JoinedController } from './channel-policy-policy';
import { JoinedUiError } from './channel-policy-contract';
import type { RetirementPermit, RoomTicket, Ticket } from './channel-policy-policy';
import { JoinedClient } from './channel-policy-client';
import type { RequestOwner } from './channel-policy-client';
import { JoinedPanel } from './channel-policy-panel';
import { JoinedRoom } from './channel-policy-room';
import {
  startCommand,
  endCommand,
  smsCommand,
  parseStatus,
  parseGrant,
  parseCase,
  parseProgress,
  parseCurrent,
  parseSms,
  safeCode,
} from './channel-policy-wire';
import type {
  Purpose,
  RoomStatus,
  RoomGrant,
  EndCommand,
  SmsCommand,
  ProgressView,
} from './channel-policy-wire';
import './channel-policy.css';
interface MediaOwner {
  readonly port: JoinedRoom;
  readonly ticket: RoomTicket;
  readonly command: EndCommand;
  readonly expiry: ReturnType<typeof setTimeout>;
  closing: boolean;
  closePass: Promise<void> | null;
  observingClose: boolean;
}
/** One original-only cleanup capability; it cannot issue any other operation. */
class OriginalRetirement {
  #credential: string;
  #active: { ticket: Ticket; owner: RequestOwner<RoomStatus>; observed: boolean } | null = null;
  #startObserved = false;
  #postStartIssued = false;
  #initialIssued = false;
  #knownLocals = new Set<RequestOwner<unknown>>();
  #cleanupPasses = new Map<RequestOwner<unknown>, Promise<void>>();
  #closed = false;
  #released = false;
  constructor(
    readonly client: JoinedClient,
    readonly model: JoinedController,
    readonly permit: RetirementPermit,
    readonly command: EndCommand,
    credential: string,
    starts: readonly RequestOwner<unknown>[],
    locals: readonly RequestOwner<unknown>[],
    readonly changed: () => void,
    readonly released: () => void,
  ) {
    this.#credential = credential;
    for (const owner of new Set(locals))
      void owner.actualResult.then(
        () => this.#knownLocals.add(owner),
        () => this.#knownLocals.add(owner),
      );
    void Promise.allSettled(starts.map((owner) => owner.actualResult)).then(() => {
      this.#startObserved = true;
      this.#postStart();
      this.check();
      this.changed();
    });
  }
  start(ticket: Ticket): void {
    if (this.#initialIssued) return;
    this.#initialIssued = true;
    this.#issue(ticket);
  }
  retry(): void {
    if (this.#released) return;
    for (const owner of this.#knownLocals) this.#cleanup(owner);
    if (this.#active) {
      if (this.#active.observed) this.#cleanup(this.#active.owner);
      return;
    }
    if (!this.#closed) {
      if (this.#startObserved) this.#postStartIssued = true;
      try {
        this.#issue(this.model.retryEnd(this.permit).ticket);
      } catch {
        this.model.retirementIncomplete(this.permit);
      }
    }
    this.check();
  }
  #cleanup(owner: RequestOwner<unknown>): void {
    if (this.#cleanupPasses.has(owner)) return;
    const pass = owner.retryCleanup();
    this.#cleanupPasses.set(owner, pass);
    void pass
      .catch(() => {
        this.model.retirementIncomplete(this.permit);
        this.changed();
      })
      .finally(() => {
        if (this.#cleanupPasses.get(owner) === pass) this.#cleanupPasses.delete(owner);
      });
  }
  #issue(ticket: Ticket): void {
    if (this.#released || this.#active) return;
    let owner: RequestOwner<RoomStatus>;
    try {
      owner = this.client.begin('end', this.command, this.#credential, (value) => {
        const status = parseStatus(value);
        if (
          status.ownerEpoch !== this.command.ownerEpoch ||
          status.generation !== this.command.generation ||
          status.originalStartCommandId !== this.command.originalStartCommandId
        )
          throw new JoinedUiError('conflict');
        return status;
      });
    } catch (error) {
      this.model.failed(ticket, safeCode(error).code);
      this.model.settled(ticket);
      this.model.retirementIncomplete(this.permit);
      this.#postStart();
      this.changed();
      return;
    }
    const active = { ticket, owner, observed: false };
    this.#active = active;
    void owner.actualResult.then(
      (status) => {
        active.observed = true;
        this.#closed ||= status.stage === 'closed';
        this.model.observeEnd(ticket, {
          cursor: { ownerEpoch: status.ownerEpoch, generation: status.generation },
          originalStartCommandId: status.originalStartCommandId!,
          settled: this.#closed,
        });
        this.#cleanup(owner);
        this.check();
        this.changed();
      },
      (error) => {
        active.observed = true;
        this.model.failed(ticket, safeCode(error).code);
        this.model.retirementIncomplete(this.permit);
        this.#cleanup(owner);
        this.changed();
      },
    );
    void owner.result.catch((error) => {
      this.model.failed(ticket, safeCode(error).code);
      this.model.retirementIncomplete(this.permit);
      this.changed();
    });
    void owner.settled.then(() => {
      if (this.#active === active) this.#active = null;
      this.model.settled(ticket);
      this.#postStart();
      this.check();
      this.changed();
    });
  }
  #postStart(): void {
    if (
      this.#released ||
      this.#closed ||
      this.#active ||
      !this.#startObserved ||
      this.#postStartIssued ||
      !this.#initialIssued
    )
      return;
    this.#postStartIssued = true;
    try {
      this.#issue(this.model.retryEnd(this.permit).ticket);
    } catch {
      this.model.retirementIncomplete(this.permit);
    }
  }
  check(): void {
    if (!this.#released && this.#active === null && this.model.retirementSettled(this.permit)) {
      this.#released = true;
      this.#credential = '';
      this.released();
    }
  }
}

export class JoinedApplication {
  readonly model = new JoinedController();
  readonly client: JoinedClient;
  readonly panel: JoinedPanel;
  #requests = new Map<Ticket, RequestOwner<unknown>>();
  #readHandles = new Set<RequestOwner<unknown>>();
  #media: MediaOwner | null = null;
  #retirement: OriginalRetirement | null = null;
  #notice: string | null = null;
  #progress: ProgressView | null = null;
  #busy = false;
  #playing = false;
  #speech: string | null = null;
  #readPass: Promise<void> | null = null;
  #poll: ReturnType<typeof setTimeout> | null = null;
  #pollTicks = 0;
  #sms: SmsCommand | null = null;
  #entryEpoch = 0;
  #voiceInputId: string | null = null;
  #ackTimers = new Map<string, ReturnType<typeof setTimeout>>();
  constructor(
    root: ParentNode = document,
    fetcher: typeof fetch = fetch,
    panel?: JoinedPanel,
    readonly createRoom: (...args: ConstructorParameters<typeof JoinedRoom>) => JoinedRoom = (
      ...args
    ) => new JoinedRoom(...args),
  ) {
    this.client = new JoinedClient(fetcher);
    this.panel = panel ?? new JoinedPanel(root);
    const on = (name: string, kind: string, action: (event: Event) => void): void =>
      this.panel.element(name).addEventListener(kind, action);
    on('access-form', 'submit', (e) => {
      e.preventDefault();
      const input = this.panel.element<HTMLInputElement>('access'),
        key = input.value;
      input.value = '';
      try {
        this.model.setAuthorization(key);
        this.panel.element<HTMLDetailsElement>('setup').open = false;
        this.#notice = null;
        void this.refresh(true);
      } catch {
        this.#notice = 'Enter the generated local browser access key.';
        this.render();
      }
    });
    on('join', 'click', () => {
      if (!this.model.snapshot().authorized) {
        this.panel.element<HTMLDetailsElement>('setup').open = true;
        this.panel.element<HTMLInputElement>('access').focus();
        return;
      }
      this.join();
    });
    on('end', 'click', () => this.end());
    on('forget', 'click', () => this.forget());
    on('refresh', 'click', () => void this.refresh(true));
    on('compose-form', 'submit', (e) => {
      e.preventDefault();
      this.send(false);
    });
    on('message', 'keydown', (e) => {
      const key = e as KeyboardEvent;
      if (key.key === 'Enter' && !key.shiftKey && !key.isComposing) {
        e.preventDefault();
        this.send(false);
      }
    });
    on('retry-text', 'click', () => this.send(true));
    on('mode-text', 'click', () => this.mode(false));
    on('mode-voice', 'click', () => this.mode(true));
    on('prepare-voice', 'click', () => this.voice('prepare'));
    on('start-voice', 'click', () => this.voice('start'));
    on('commit-voice', 'click', () => this.voice('commit'));
    on('interrupt', 'click', () => this.voice('interrupt'));
    on('enable-audio', 'click', () => this.voice('audio'));
    on('sms-form', 'submit', (e) => {
      e.preventDefault();
      this.sms();
    });
    window.addEventListener(
      'pagehide',
      () => {
        this.forget();
        this.stopPolling();
        void this.client.close().catch(() => undefined);
      },
      { once: true },
    );
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this.stopPolling();
    });
    this.render();
  }
  render(): void {
    this.#retirement?.check();
    this.panel.render(this.model.snapshot(), {
      notice: this.#notice,
      progress: this.#progress,
      voicePrepared: this.#media?.port.voicePrepared ?? false,
      turnActive: this.#media?.port.turnInput !== null && this.#media !== null,
      playing: this.#playing,
      busy: this.#busy || (this.#media?.port.controlsPending ?? false),
      speech: this.#speech,
    });
    const end = this.panel.element<HTMLButtonElement>('end');
    end.textContent = this.#retirement ? 'Retry End' : 'End';
    if (this.#retirement) {
      end.disabled = false;
      for (const name of [
        'join',
        'refresh',
        'send',
        'retry-text',
        'enable-audio',
        'prepare-voice',
        'start-voice',
        'commit-voice',
        'interrupt',
      ])
        this.panel.element<HTMLButtonElement>(name).disabled = true;
    }
  }
  mode(voice: boolean): void {
    this.panel.element('voice').hidden = !voice;
    this.panel.element('compose-form').hidden = voice;
    this.panel.element('mode-text').setAttribute('aria-pressed', String(!voice));
    this.panel.element('mode-voice').setAttribute('aria-pressed', String(voice));
  }
  #begin<T>(
    ticket: Ticket,
    purpose: Purpose,
    body: unknown,
    decode: (value: unknown) => T,
    apply: (value: T) => void,
  ): RequestOwner<T> {
    let owner: RequestOwner<T>;
    try {
      owner = this.model.withAuthorization(ticket, (key) =>
        this.client.begin(purpose, body, key, decode),
      );
    } catch (error) {
      this.model.failed(ticket, safeCode(error).code);
      this.model.settled(ticket);
      this.render();
      throw safeCode(error);
    }
    this.#requests.set(ticket, owner as RequestOwner<unknown>);
    void owner.actualResult
      .then(
        (value) => {
          apply(value);
          this.render();
        },
        (error) => {
          this.model.failed(ticket, safeCode(error).code);
          this.render();
        },
      )
      .catch(() => {
        this.model.failed(ticket, 'invalid');
        this.render();
      });
    void owner.result.catch((error) => {
      this.model.failed(ticket, safeCode(error).code);
      this.render();
    });
    void owner.settled.then(() => {
      this.#requests.delete(ticket);
      this.model.settled(ticket);
      this.render();
    });
    return owner;
  }
  #status(value: RoomStatus): import('./channel-policy-contract').ParentObservation {
    return {
      cursor: { ownerEpoch: value.ownerEpoch, generation: value.generation },
      stage: ['idle', 'closed'].includes(value.stage)
        ? 'dormant'
        : value.stage === 'closing'
          ? 'ending'
          : value.stage === 'recovery_required'
            ? 'cleanup_incomplete'
            : value.stage === 'preparing'
              ? 'starting'
              : 'active',
      originalStartCommandId: value.originalStartCommandId,
      workerReady: value.workerRunning && value.sdkReady,
    };
  }
  join(): void {
    if (this.#retirement) {
      this.#notice =
        'The original activation is still being retired. Retry End; a new session stays blocked.';
      this.render();
      return;
    }
    try {
      const state = this.model.snapshot();
      const next =
        state.phase === 'start_unknown'
          ? this.model.retryStart()
          : this.model.beginStart(crypto.randomUUID());
      const command = startCommand({ schemaVersion: 1, ...next.intent });
      ++this.#entryEpoch;
      this.panel.joining();
      this.#notice = null;
      this.#playing = false;
      this.#speech = null;
      this.#pollTicks = 0;
      this.#begin(
        next.ticket,
        'start',
        command,
        (value) => parseGrant(value, command),
        (grant) => this.#grant(next.ticket, grant),
      );
      this.schedulePoll();
      this.render();
    } catch (error) {
      this.#notice = this.#message(error);
      this.render();
    }
  }
  #grant(ticket: Ticket, grant: RoomGrant): void {
    const value = {
      cursor: { ownerEpoch: grant.ownerEpoch, generation: grant.generation },
      originalStartCommandId: grant.originalStartCommandId,
      workerReady: false,
      grant: {
        mode: 'scripted' as const,
        expiresAt: grant.rtc.expiresAt,
        session: {
          schemaVersion: 1 as const,
          url: grant.rtc.url,
          token: grant.rtc.token,
          roomId: grant.rtc.roomId,
          participantId: grant.rtc.participantId,
          agentId: grant.rtc.agentId,
          bindingId: grant.rtc.bindingId,
        },
      },
    };
    if (this.model.observeStart(ticket, value) !== 'adopt') return;
    if (Date.parse(grant.rtc.expiresAt) <= Date.now()) {
      this.end();
      return;
    }
    const retained = this.model.retainRoom();
    const command = endCommand({
      schemaVersion: 1,
      ownerEpoch: grant.ownerEpoch,
      generation: grant.generation,
      originalStartCommandId: grant.originalStartCommandId,
    });
    const expectedAgentId = grant.rtc.agentId;
    let owned!: MediaOwner;
    const port = this.createRoom(
      retained.grant.session,
      {
        connection: (state) => {
          if (this.#media !== owned || owned.closing) return;
          this.model.connection(owned.ticket, state);
          this.render();
          if (state === 'disconnected') this.end();
        },
        native: (identity, kind, attributes) => {
          if (this.#media !== owned || owned.closing) return;
          this.model.native(owned.ticket, identity, kind, attributes);
          this.#speech =
            kind === 'agent' &&
            identity === expectedAgentId &&
            ['idle', 'listening', 'thinking', 'speaking'].includes(
              attributes['lk.agent.state'] ?? '',
            )
              ? attributes['lk.agent.state']!
              : null;
          this.render();
        },
        data: (topic, raw) => {
          if (this.#media !== owned || owned.closing) return;
          try {
            if (topic === 'p2.acceptance') {
              this.model.acceptance(owned.ticket, raw);
              for (const row of this.model.snapshot().inputs)
                if (row.receiptId) {
                  const timer = this.#ackTimers.get(row.inputId);
                  if (timer !== undefined) {
                    clearTimeout(timer);
                    this.#ackTimers.delete(row.inputId);
                  }
                }
              const last = this.model.snapshot().inputs.at(-1),
                field = this.panel.element<HTMLTextAreaElement>('message');
              if (last?.receiptId && last.channel === 'web_chat' && field.value === last.body)
                field.value = '';
            } else this.model.generation(owned.ticket, raw);
          } catch {
            this.#notice = 'An input or generation observation could not be verified.';
          }
          this.render();
        },
        text: (text) => {
          if (this.#media === owned && !owned.closing) {
            this.model.agentText(owned.ticket, text);
            this.render();
          }
        },
        playback: (playing) => {
          if (this.#media === owned && !owned.closing) {
            this.#playing = playing;
            this.render();
          }
        },
        changed: () => this.render(),
      },
      this.panel.element('audio'),
    );
    const expiry = setTimeout(
      () => {
        if (this.#media === owned) this.end();
      },
      Math.max(0, Math.min(180000, Date.parse(grant.rtc.expiresAt) - Date.now())),
    );
    owned = {
      port,
      ticket: retained.owner,
      command,
      expiry,
      closing: false,
      closePass: null,
      observingClose: false,
    };
    this.#media = owned;
    void port.connect(new AbortController().signal).then(
      () => {
        if (this.#media === owned && !owned.closing) void this.refresh(false);
      },
      () => {
        if (this.#media === owned && !owned.closing) {
          this.#notice = 'The media connection is unavailable. Closing this activation.';
          this.end();
        }
      },
    );
    this.render();
  }
  #closeMedia(): void {
    const media = this.#media;
    if (!media) return;
    media.closing = true;
    clearTimeout(media.expiry);
    if (!media.closePass) {
      const pass = media.port.close();
      media.closePass = pass;
      void pass
        .catch(() => {
          this.#notice = 'Media cleanup is incomplete. Retry End; a new session remains blocked.';
          this.render();
        })
        .finally(() => {
          if (media.closePass === pass) media.closePass = null;
        });
    }
    if (!media.observingClose) {
      media.observingClose = true;
      void media.port.whenClosed().then(
        () => {
          this.model.roomSettled(media.ticket);
          if (this.#media === media) this.#media = null;
          this.render();
        },
        () => {
          media.observingClose = false;
        },
      );
    }
  }
  #abortOrdinary(): void {
    // Keep original Start and captured End observations. Aborting them would
    // neither stop remote work nor provide the late original outcome.
    for (const [ticket, owner] of this.#requests)
      if (ticket.kind !== 'start' && ticket.kind !== 'end') owner.abort();
    for (const owner of this.#readHandles) owner.abort();
  }
  end(): void {
    this.panel.cancelFocus();
    this.stopPolling();
    for (const timer of this.#ackTimers.values()) clearTimeout(timer);
    this.#ackTimers.clear();
    this.#voiceInputId = null;
    ++this.#entryEpoch;
    this.#notice = null;
    this.#playing = false;
    this.#speech = null;
    try {
      if (this.#retirement) this.#retirement.retry();
      else {
        const next = this.model.beginEnd();
        const command = endCommand({
          schemaVersion: 1,
          ownerEpoch: next.intent.originalStart.ownerEpoch,
          generation: (BigInt(next.intent.originalStart.expectedGeneration) + 1n).toString(),
          originalStartCommandId: next.intent.originalStart.commandId,
        });
        const starts = [...this.#requests]
          .filter(([ticket]) => ticket.kind === 'start')
          .map(([, owner]) => owner);
        const locals = [...this.#requests.values(), ...this.#readHandles];
        const retirement = this.model.withAuthorization(
          next.ticket,
          (key) =>
            new OriginalRetirement(
              this.client,
              this.model,
              next.permit,
              command,
              key,
              starts,
              locals,
              () => this.render(),
              () => {
                if (this.#retirement === retirement) {
                  this.#retirement = null;
                  this.#notice = null;
                  this.schedulePoll();
                }
              },
            ),
        );
        this.#retirement = retirement;
        retirement.start(next.ticket);
      }
    } catch (error) {
      this.#notice = this.#message(error);
    }
    this.#abortOrdinary();
    this.#closeMedia();
    this.render();
  }
  forget(): void {
    if (!this.#retirement && this.model.snapshot().start) this.end();
    else if (this.#retirement) this.#closeMedia();
    this.stopPolling();
    ++this.#entryEpoch;
    this.model.forget();
    this.#abortOrdinary();
    this.#sms = null;
    this.#progress = null;
    this.#notice = null;
    this.#playing = false;
    this.#speech = null;
    this.panel.element<HTMLInputElement>('access').value = '';
    this.panel.element<HTMLTextAreaElement>('message').value = '';
    this.panel.element<HTMLTextAreaElement>('sms-message').value = '';
    this.render();
  }
  send(retry: boolean): void {
    const media = this.#media;
    if (!media || media.closing) return;
    try {
      const old = [...this.model.snapshot().inputs]
        .reverse()
        .find((row) => row.channel === 'web_chat' && row.status === 'unknown');
      const input =
        retry && old
          ? this.model.addInput(media.ticket, old.inputId, 'web_chat', old.body)
          : this.model.addInput(
              media.ticket,
              crypto.randomUUID(),
              'web_chat',
              this.panel.element<HTMLTextAreaElement>('message').value,
            );
      this.#awaitAck(media, input.inputId);
      this.#busy = true;
      this.#notice = null;
      this.render();
      void media.port
        .sendText(input)
        .catch(() => {
          this.model.inputUnknown(media.ticket, input.inputId);
          this.render();
        })
        .finally(() => {
          if (this.#media === media) this.#busy = false;
          this.render();
        });
    } catch (error) {
      this.#notice = this.#message(error);
      this.render();
    }
  }
  voice(action: 'prepare' | 'start' | 'commit' | 'interrupt' | 'audio'): void {
    const media = this.#media;
    if (!media || media.closing) return;
    try {
      let actual: Promise<unknown>;
      if (action === 'prepare') actual = media.port.prepareVoice();
      else if (action === 'audio') actual = media.port.enableAudio();
      else {
        const method =
          action === 'start'
            ? 'p2.start_turn'
            : action === 'commit'
              ? 'p2.commit_turn'
              : 'p2.interrupt';
        const input =
          action === 'start'
            ? this.model.addInput(
                media.ticket,
                this.#voiceInputId ?? crypto.randomUUID(),
                'voice_transcript',
                null,
              ).inputId
            : action === 'commit'
              ? media.port.turnInput
              : null;
        if (action === 'start') this.#voiceInputId = input;
        if (action === 'commit' && input) this.#awaitAck(media, input);
        if (action === 'interrupt') this.model.interrupt(media.ticket);
        actual = media.port.turn(method, input);
      }
      if (action !== 'interrupt') this.#busy = true;
      this.render();
      void actual
        .then(() => {
          if (action === 'commit' && this.#media === media) this.#voiceInputId = null;
        })
        .catch(() => {
          if (this.#media === media && !media.closing) {
            this.#notice =
              'The voice acknowledgement is unknown. Keep the original turn and End to settle media.';
            this.render();
          }
        })
        .finally(() => {
          if (this.#media === media) this.#busy = false;
          this.render();
        });
    } catch (error) {
      this.#notice = this.#message(error);
      this.render();
    }
  }
  #awaitAck(media: MediaOwner, inputId: string): void {
    const previous = this.#ackTimers.get(inputId);
    if (previous !== undefined) clearTimeout(previous);
    const timer = setTimeout(() => {
      this.#ackTimers.delete(inputId);
      this.model.inputUnknown(media.ticket, inputId);
      this.render();
    }, 8000);
    this.#ackTimers.set(inputId, timer);
  }
  sms(): void {
    try {
      const field = this.panel.element<HTMLTextAreaElement>('sms-message');
      const command =
        this.#sms && this.model.snapshot().sms === 'unknown'
          ? this.#sms
          : smsCommand({
              schemaVersion: 1,
              commandId: crypto.randomUUID(),
              occurredAt: new Date().toISOString(),
              body: field.value,
            });
      const next = this.model.beginSms(command.commandId, command.body, command.occurredAt);
      this.#sms = command;
      this.#begin(
        next.ticket,
        'sms',
        command,
        (value) => parseSms(value, command),
        (receipt) => {
          if (
            this.model.observeSms(next.ticket, {
              commandId: receipt.commandId,
              status: receipt.replayed ? 'replayed' : 'accepted',
              observedAt: receipt.receipt.acceptedAt,
            })
          ) {
            field.value = '';
            this.#notice =
              'The original simulated SMS receipt was observed. Refresh for source counts.';
          }
        },
      );
      this.render();
    } catch (error) {
      this.#notice = this.#message(error);
      this.render();
    }
  }
  refresh(manual: boolean): Promise<void> {
    if (this.#readPass || !this.model.snapshot().authorized)
      return this.#readPass ?? Promise.resolve();
    if (manual) {
      this.#pollTicks = 0;
      this.#notice = null;
    }
    const epoch = this.#entryEpoch;
    const pass = (async () => {
      let statusTicket: Ticket | null = null;
      let read: Ticket | null = null;
      let policyReadStarted = false;
      const handles: RequestOwner<unknown>[] = [];
      try {
        statusTicket = this.model.beginStatus();
        const status = this.#begin(
          statusTicket,
          'status',
          { schemaVersion: 1 },
          parseStatus,
          (value) => this.model.observeParent(statusTicket!, this.#status(value)),
        );
        handles.push(status);
        await status.result;
        await status.settled;
        if (epoch !== this.#entryEpoch) return;
        read = this.model.beginRead();
        const readTicket = read;
        const currentCase = this.model.withAuthorization(readTicket, (key) =>
          this.client.begin('case', { schemaVersion: 1 }, key, parseCase),
        );
        handles.push(currentCase);
        this.#readHandles.add(currentCase);
        void currentCase.settled.then(() => this.#readHandles.delete(currentCase));
        const c = await currentCase.result;
        if (epoch !== this.#entryEpoch) return;
        this.model.observeCase(readTicket, c.case);
        this.render();
        await currentCase.settled;
        const progress = this.model.withAuthorization(readTicket, (key) =>
          this.client.begin('progress', { schemaVersion: 1 }, key, parseProgress),
        );
        handles.push(progress);
        this.#readHandles.add(progress);
        void progress.settled.then(() => this.#readHandles.delete(progress));
        const p = await progress.result;
        if (epoch !== this.#entryEpoch) return;
        this.#progress = p;
        this.render();
        await progress.settled;
        const command = this.#media?.command;
        if (command && !this.#media?.closing) {
          if (!this.model.beginPolicyRead(readTicket)) return;
          policyReadStarted = true;
          this.render();
          const current = this.model.withAuthorization(readTicket, (key) =>
            this.client.begin('current', command, key, (value) => parseCurrent(value, command)),
          );
          handles.push(current);
          this.#readHandles.add(current);
          void current.settled.then(() => this.#readHandles.delete(current));
          const observation = await current.result;
          if (epoch !== this.#entryEpoch) return;
          this.model.observeRead(readTicket, {
            case: this.model.snapshot().case,
            policy: observation.fact,
          });
        }
      } catch (error) {
        if (read && policyReadStarted) this.model.failedPolicyRead(read, safeCode(error).code);
        else if (read) this.model.failed(read, safeCode(error).code);
        else if (statusTicket) this.model.failed(statusTicket, safeCode(error).code);
      } finally {
        await Promise.allSettled(handles.map((handle) => handle.settled));
        if (read) this.model.settled(read);
        this.render();
      }
    })();
    this.#readPass = pass;
    void pass
      .finally(() => {
        if (this.#readPass === pass) this.#readPass = null;
        this.schedulePoll();
      })
      .catch(() => undefined);
    return pass;
  }
  schedulePoll(): void {
    this.stopPolling();
    if (
      document.hidden ||
      this.#retirement ||
      !this.model.snapshot().authorized ||
      this.#pollTicks >= 30
    )
      return;
    this.#poll = setTimeout(() => {
      this.#poll = null;
      ++this.#pollTicks;
      void this.refresh(false);
    }, 2000);
  }
  stopPolling(): void {
    if (this.#poll !== null) clearTimeout(this.#poll);
    this.#poll = null;
  }
  #message(error: unknown): string {
    const code = safeCode(error).code;
    return code === 'capacity'
      ? 'An actual operation is still owned. Wait for it to settle.'
      : code === 'conflict'
        ? 'The original activation or command must be reconciled first.'
        : code === 'denied'
          ? 'Enter the local browser access key.'
          : 'The operation could not be verified. Reuse its original identity after it settles.';
  }
}
if (typeof document !== 'undefined' && document.querySelector('[data-cp-state]'))
  new JoinedApplication();
