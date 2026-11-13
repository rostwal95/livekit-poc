/** Pure decisions only. Tickets release ONLY on actual adapter settlement. */
import {
  NativeInputs,
  NativeGenerations,
  freezeNativeInput,
  nativeReady,
  parseNativeAck,
  parseNativeGeneration,
  parseNativeSession,
  turnPayload,
} from './p2-native-policy';
import { JoinedUiError } from './channel-policy-contract';
import type {
  BrowserGrant,
  CaseResultObservation,
  EndObservation,
  ParentCursor,
  ParentObservation,
  RetireIntent,
  SmsIntent,
  SmsObservation,
  StartIntent,
  StartObservation,
  UiCode,
} from './channel-policy-contract';
import type { FrozenNativeInput, NativeInputView } from './p2-native-policy';
export type Phase =
  | 'locked'
  | 'idle'
  | 'starting'
  | 'start_unknown'
  | 'connecting'
  | 'waiting_agent'
  | 'ready'
  | 'reconnecting'
  | 'ending'
  | 'cleanup_incomplete'
  | 'dormant';
export type Kind = 'status' | 'start' | 'end' | 'read' | 'sms';
export interface Ticket {
  readonly sequence: number;
  readonly activation: number;
  readonly kind: Kind;
}
export interface RetirementPermit {
  readonly sequence: number;
}
export interface RoomTicket {
  readonly sequence: number;
  readonly activation: number;
}
export interface Message {
  readonly id: number;
  readonly activation: number;
  readonly role: 'user' | 'agent';
  readonly text: string;
  /** Agent transcript stream within this activation; its text grows in place. */
  readonly stream?: number;
  /** The synchronized stream is still open, so this text may still grow. */
  readonly live?: boolean;
}
export interface View {
  readonly activation: number;
  readonly phase: Phase;
  readonly authorized: boolean;
  readonly ready: boolean;
  readonly code: UiCode | null;
  readonly parent: ParentObservation | null;
  readonly start: StartIntent | null;
  readonly requests: number;
  readonly roomOwned: boolean;
  readonly reading: boolean;
  readonly case: CaseResultObservation['case'];
  readonly policy: CaseResultObservation['policy'] | null;
  readonly policyHistorical: boolean;
  readonly policyRead: 'idle' | 'pending' | 'ok' | 'busy' | 'unavailable';
  readonly sms: 'idle' | 'sending' | 'unknown' | 'accepted';
  readonly messages: readonly Message[];
  readonly inputs: readonly NativeInputView[];
  readonly generationCount: number;
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const encoder = new TextEncoder();
function invalid(): never {
  throw new JoinedUiError('invalid');
}
function cursor(value: ParentCursor): ParentCursor {
  if (
    typeof value.ownerEpoch !== 'string' ||
    !value.ownerEpoch ||
    value.ownerEpoch.length > 128 ||
    !/^(0|[1-9][0-9]{0,18})$/u.test(value.generation) ||
    BigInt(value.generation) > 9223372036854775807n
  )
    return invalid();
  return Object.freeze({
    ownerEpoch: value.ownerEpoch,
    generation: value.generation,
  });
}
function boundedText(value: string, max: number): string {
  if (
    typeof value !== 'string' ||
    !value.trim() ||
    value.length > max ||
    new TextDecoder().decode(encoder.encode(value)) !== value ||
    encoder.encode(value).length > max
  )
    return invalid();
  return value;
}
export class JoinedController {
  #authorization = '';
  #activation = 0;
  #sequence = 0;
  #messageSequence = 0;
  #parent: ParentObservation | null = null;
  #start: StartIntent | null = null;
  #grant: BrowserGrant | null = null;
  #phase: Phase = 'locked';
  #code: UiCode | null = null;
  #nativeReady = false;
  #connected = false;
  #retiring = false;
  #retirementPermit: RetirementPermit | null = null;
  #completedRetirement: RetirementPermit | null = null;
  #parentEnded = false;
  #workerReady = false;
  #tickets = new Set<Ticket>();
  #room: RoomTicket | null = null;
  #messages: Message[] = [];
  #case: CaseResultObservation['case'] = null;
  #policy: CaseResultObservation['policy'] | null = null;
  #policyRead: View['policyRead'] = 'idle';
  #policyReadTicket: Ticket | null = null;
  #inputs = new NativeInputs();
  #generations = new NativeGenerations();
  #sms: SmsIntent | null = null;
  #smsState: View['sms'] = 'idle';
  setAuthorization(value: string): void {
    // Operator authorization stays separate from RTC and room capabilities.
    if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{43}$/u.test(value)) return invalid();
    if (this.#authorization && this.#authorization !== value) throw new JoinedUiError('conflict');
    this.#authorization = value;
    if (this.#phase === 'locked') this.#phase = 'idle';
  }
  withAuthorization<T>(ticket: Ticket, action: (credential: string) => T): T {
    if (!this.#tickets.has(ticket) || !this.#authorization) throw new JoinedUiError('denied');
    return action(this.#authorization);
  }
  #admit(kind: Kind, permit?: RetirementPermit): Ticket {
    const scopedEnd =
      kind === 'end' && permit !== undefined && permit === this.#retirementPermit && this.#retiring;
    if (!this.#authorization && !scopedEnd) throw new JoinedUiError('denied');
    if (this.#retiring && kind !== 'end') throw new JoinedUiError('unavailable');
    const rows = [...this.#tickets];
    const ordinary = rows.filter((ticket) => ticket.kind !== 'end').length;
    if (
      rows.some(
        (ticket) =>
          ticket.kind === kind ||
          (['status', 'read'].includes(kind) && ['status', 'read'].includes(ticket.kind)),
      ) ||
      rows.length >= 3 ||
      (kind !== 'end' && ordinary >= 2)
    )
      throw new JoinedUiError('capacity');
    const ticket = Object.freeze({
      sequence: ++this.#sequence,
      activation: this.#activation,
      kind,
    });
    this.#tickets.add(ticket);
    return ticket;
  }
  #current(ticket: Ticket): boolean {
    return (
      this.#tickets.has(ticket) &&
      ticket.activation === this.#activation &&
      !this.#retiring &&
      !!this.#authorization
    );
  }
  #matchesRoom(room: RoomTicket): boolean {
    return (
      this.#room === room &&
      room.activation === this.#activation &&
      !this.#retiring &&
      !!this.#authorization
    );
  }
  beginStatus(): Ticket {
    return this.#admit('status');
  }
  observeParent(ticket: Ticket, value: ParentObservation): boolean {
    if (!this.#current(ticket) || ticket.kind !== 'status') return false;
    const observed = cursor(value.cursor);
    if (
      this.#start &&
      (observed.ownerEpoch !== this.#start.ownerEpoch ||
        (value.originalStartCommandId !== null &&
          value.originalStartCommandId !== this.#start.commandId))
    ) {
      this.#code = 'conflict';
      return false;
    }
    this.#parent = Object.freeze({
      cursor: observed,
      stage: value.stage,
      originalStartCommandId: value.originalStartCommandId,
      workerReady: value.workerReady,
    });
    this.#workerReady = value.workerReady;
    if (!this.#start)
      this.#phase = value.stage === 'dormant' && observed.generation !== '0' ? 'dormant' : 'idle';
    else this.#readyPhase();
    return true;
  }
  beginStart(commandId: string): Readonly<{ ticket: Ticket; intent: StartIntent }> {
    if (!UUID.test(commandId)) return invalid();
    if (!this.#authorization) throw new JoinedUiError('denied');
    if (this.#parent && BigInt(this.#parent.cursor.generation) >= 1000000n)
      throw new JoinedUiError('capacity');
    if (
      this.#start ||
      this.#room ||
      this.#tickets.size ||
      this.#retiring ||
      this.#parent?.stage !== 'dormant'
    )
      throw new JoinedUiError('conflict');
    ++this.#activation;
    this.#completedRetirement = null;
    this.#start = Object.freeze({
      ownerEpoch: this.#parent.cursor.ownerEpoch,
      expectedGeneration: this.#parent.cursor.generation,
      commandId,
    });
    this.#parentEnded = false;
    this.#phase = 'starting';
    this.#code = null;
    this.#policy = null;
    this.#policyRead = 'idle';
    this.#policyReadTicket = null;
    this.#nativeReady = false;
    this.#connected = false;
    this.#inputs = new NativeInputs();
    this.#generations = new NativeGenerations();
    return Object.freeze({ ticket: this.#admit('start'), intent: this.#start });
  }
  retryStart(): Readonly<{ ticket: Ticket; intent: StartIntent }> {
    if (!this.#start || this.#phase !== 'start_unknown' || this.#retiring)
      throw new JoinedUiError('conflict');
    const ticket = this.#admit('start');
    this.#phase = 'starting';
    return Object.freeze({ ticket, intent: this.#start });
  }
  observeStart(ticket: Ticket, value: StartObservation): 'adopt' | 'discard' {
    if (!this.#current(ticket) || ticket.kind !== 'start' || !this.#start) return 'discard';
    const observed = cursor(value.cursor);
    if (
      observed.ownerEpoch !== this.#start.ownerEpoch ||
      value.originalStartCommandId !== this.#start.commandId
    ) {
      this.#code = 'conflict';
      this.#phase = 'start_unknown';
      return 'discard';
    }
    const session = parseNativeSession(value.grant.session);
    const mode = value.grant.mode;
    if (
      (mode !== 'scripted' && mode !== 'provider_real') ||
      !Number.isFinite(Date.parse(value.grant.expiresAt))
    )
      return invalid();
    this.#grant = Object.freeze({
      session,
      expiresAt: value.grant.expiresAt,
      mode,
    });
    this.#parent = Object.freeze({
      cursor: observed,
      stage: 'active',
      originalStartCommandId: value.originalStartCommandId,
      workerReady: value.workerReady,
    });
    this.#workerReady = value.workerReady;
    this.#phase = 'connecting';
    this.#code = null;
    return 'adopt';
  }
  retainRoom(): Readonly<{ owner: RoomTicket; grant: BrowserGrant }> {
    if (!this.#grant || this.#room || this.#retiring || !this.#authorization)
      throw new JoinedUiError('conflict');
    this.#room = Object.freeze({
      sequence: ++this.#sequence,
      activation: this.#activation,
    });
    return Object.freeze({ owner: this.#room, grant: this.#grant });
  }
  connection(room: RoomTicket, state: 'connected' | 'reconnecting' | 'disconnected'): boolean {
    if (!this.#matchesRoom(room)) return false;
    this.#connected = state === 'connected';
    if (!this.#connected) this.#nativeReady = false;
    this.#phase = state === 'reconnecting' ? 'reconnecting' : 'waiting_agent';
    this.#readyPhase();
    return true;
  }
  native(
    room: RoomTicket,
    identity: string | null,
    kind: 'agent' | 'other',
    attributes: Readonly<Record<string, string>>,
  ): boolean {
    if (!this.#matchesRoom(room)) return false;
    this.#nativeReady = nativeReady(
      this.#connected,
      this.#grant?.session ?? null,
      identity,
      kind,
      attributes,
      this.#grant?.mode ?? 'scripted',
    );
    this.#readyPhase();
    return this.#nativeReady;
  }
  #readyPhase(): void {
    if (this.#retiring || !this.#grant || !this.#room) return;
    if (this.#connected)
      this.#phase = this.#nativeReady && this.#workerReady ? 'ready' : 'waiting_agent';
  }
  beginRead(): Ticket {
    if (['starting', 'start_unknown', 'ending', 'cleanup_incomplete'].includes(this.#phase))
      throw new JoinedUiError('unavailable');
    return this.#admit('read');
  }
  observeCase(ticket: Ticket, value: CaseResultObservation['case']): boolean {
    if (!this.#current(ticket) || ticket.kind !== 'read') return false;
    this.#case =
      value === null
        ? null
        : Object.freeze({
            revision: value.revision,
            observedAt: value.observedAt,
          });
    return true;
  }
  beginPolicyRead(ticket: Ticket): boolean {
    if (!this.#current(ticket) || ticket.kind !== 'read' || this.#policyReadTicket !== null)
      return false;
    this.#policyReadTicket = ticket;
    this.#policyRead = 'pending';
    return true;
  }
  failedPolicyRead(ticket: Ticket, code: UiCode): boolean {
    if (!this.#current(ticket) || ticket.kind !== 'read' || this.#policyReadTicket !== ticket)
      return false;
    this.#policyReadTicket = null;
    this.#policyRead = code === 'capacity' ? 'busy' : 'unavailable';
    return true;
  }
  observeRead(ticket: Ticket, value: CaseResultObservation): boolean {
    if (!this.#current(ticket) || ticket.kind !== 'read') return false;
    this.#case =
      value.case === null
        ? null
        : Object.freeze({
            revision: value.case.revision,
            observedAt: value.case.observedAt,
          });
    this.#policy = Object.freeze({ ...value.policy });
    this.#policyRead = 'ok';
    this.#policyReadTicket = null;
    return true;
  }
  addInput(
    room: RoomTicket,
    inputId: string,
    channel: 'web_chat' | 'voice_transcript',
    body: string | null,
  ): FrozenNativeInput {
    if (!this.#matchesRoom(room) || this.#phase !== 'ready') throw new JoinedUiError('unavailable');
    const input = freezeNativeInput(inputId, channel, body);
    this.#inputs.add(input);
    if (body !== null) this.#message('user', body);
    return input;
  }
  inputUnknown(room: RoomTicket, inputId: string): void {
    if (this.#matchesRoom(room)) this.#inputs.uncertain(inputId);
  }
  acceptance(room: RoomTicket, raw: Uint8Array): boolean {
    if (!this.#matchesRoom(room) || !this.#grant) return false;
    return this.#inputs.apply(parseNativeAck(raw, this.#grant.session.bindingId));
  }
  generation(room: RoomTicket, raw: Uint8Array): boolean {
    if (!this.#matchesRoom(room) || !this.#grant) return false;
    return this.#generations.apply(
      parseNativeGeneration(raw, this.#grant.session.bindingId),
      this.#inputs,
    );
  }
  agentText(room: RoomTicket, text: string, stream?: number, live = false): boolean {
    if (!this.#matchesRoom(room)) return false;
    const bounded = boundedText(text, 16384);
    const index =
      stream === undefined
        ? -1
        : this.#messages.findIndex(
            (row) => row.stream === stream && row.activation === this.#activation,
          );
    if (index < 0) this.#message('agent', bounded, stream, live);
    else {
      this.#messages[index] = Object.freeze({ ...this.#messages[index]!, text: bounded, live });
      this.#trim();
    }
    return true;
  }
  #message(role: Message['role'], text: string, stream?: number, live = false): void {
    this.#messages.push(
      Object.freeze({
        id: ++this.#messageSequence,
        activation: this.#activation,
        role,
        text,
        ...(stream === undefined ? {} : { stream, live }),
      }),
    );
    this.#trim();
  }
  #trim(): void {
    while (
      this.#messages.length > 32 ||
      this.#messages.reduce((sum, row) => sum + encoder.encode(row.text).length, 0) > 65536
    )
      this.#messages.shift();
  }
  interrupt(room: RoomTicket): string {
    if (!this.#matchesRoom(room) || this.#phase !== 'ready') throw new JoinedUiError('unavailable');
    return turnPayload('p2.interrupt', null);
  }
  beginEnd(): Readonly<{ ticket: Ticket; intent: RetireIntent; permit: RetirementPermit }> {
    if (!this.#start || !this.#authorization) throw new JoinedUiError('conflict');
    if (!this.#retiring) {
      ++this.#activation;
      this.#retiring = true;
      this.#nativeReady = false;
      this.#connected = false;
      this.#grant = null;
      this.#policy = null;
      this.#policyRead = 'idle';
      this.#policyReadTicket = null;
      this.#retirementPermit = Object.freeze({ sequence: ++this.#sequence });
    }
    return this.retryEnd(this.#retirementPermit!);
  }
  retryEnd(
    permit: RetirementPermit,
  ): Readonly<{ ticket: Ticket; intent: RetireIntent; permit: RetirementPermit }> {
    if (!this.#start || !this.#retiring || permit !== this.#retirementPermit)
      throw new JoinedUiError('conflict');
    let ticket: Ticket;
    try {
      ticket = this.#admit('end', permit);
    } catch (error) {
      this.#phase = 'cleanup_incomplete';
      this.#code = 'cleanup_incomplete';
      throw error;
    }
    this.#phase = 'ending';
    return Object.freeze({
      ticket,
      permit,
      intent: Object.freeze({
        originalStart: this.#start,
        observedCursor: this.#parent?.cursor ?? null,
      }),
    });
  }
  retirementSettled(permit: RetirementPermit): boolean {
    return this.#completedRetirement === permit;
  }
  retirementIncomplete(permit: RetirementPermit): void {
    if (this.#retiring && this.#retirementPermit === permit) {
      this.#phase = 'cleanup_incomplete';
      this.#code = 'cleanup_incomplete';
    }
  }
  observeEnd(ticket: Ticket, value: EndObservation): boolean {
    if (
      !this.#tickets.has(ticket) ||
      ticket.kind !== 'end' ||
      !this.#retiring ||
      !this.#start ||
      value.originalStartCommandId !== this.#start.commandId ||
      value.cursor.ownerEpoch !== this.#start.ownerEpoch ||
      value.cursor.generation !== (BigInt(this.#start.expectedGeneration) + 1n).toString()
    )
      return false;
    this.#parentEnded = value.settled;
    this.#parent = Object.freeze({
      cursor: cursor(value.cursor),
      stage: value.settled ? 'dormant' : 'cleanup_incomplete',
      originalStartCommandId: value.originalStartCommandId,
      workerReady: false,
    });
    this.#phase = value.settled ? 'ending' : 'cleanup_incomplete';
    this.#finishRetirement();
    return true;
  }
  roomSettled(room: RoomTicket): void {
    if (this.#room === room) {
      this.#room = null;
      this.#finishRetirement();
    }
  }
  settled(ticket: Ticket): void {
    this.#tickets.delete(ticket);
    this.#finishRetirement();
  }
  #finishRetirement(): void {
    if (this.#retiring && this.#parentEnded && this.#room === null && this.#tickets.size === 0) {
      this.#retiring = false;
      this.#completedRetirement = this.#retirementPermit;
      this.#retirementPermit = null;
      this.#start = null;
      this.#grant = null;
      this.#phase = this.#authorization ? 'dormant' : 'locked';
      this.#code = null;
    }
  }
  failed(ticket: Ticket, code: UiCode): void {
    if (!this.#tickets.has(ticket)) return;
    if (ticket.kind === 'end' && ticket.activation === this.#activation) {
      this.#phase = 'cleanup_incomplete';
      this.#code = 'cleanup_incomplete';
    } else if (this.#current(ticket)) {
      this.#code = code;
      if (ticket.kind === 'start') this.#phase = 'start_unknown';
      if (ticket.kind === 'sms') this.#smsState = 'unknown';
    }
  }
  beginSms(
    commandId: string,
    body: string,
    occurredAt: string,
  ): Readonly<{ ticket: Ticket; intent: SmsIntent }> {
    if (!UUID.test(commandId)) return invalid();
    const text = boundedText(body, 4096);
    if (!Number.isFinite(Date.parse(occurredAt))) return invalid();
    if (this.#room || this.#start || this.#retiring || this.#parent?.stage !== 'dormant')
      throw new JoinedUiError('conflict');
    if (
      this.#sms &&
      this.#smsState === 'unknown' &&
      (this.#sms.commandId !== commandId ||
        this.#sms.body !== text ||
        this.#sms.occurredAt !== occurredAt)
    )
      throw new JoinedUiError('conflict');
    const ticket = this.#admit('sms');
    this.#sms = Object.freeze({ commandId, body: text, occurredAt });
    this.#smsState = 'sending';
    return Object.freeze({ ticket, intent: this.#sms });
  }
  observeSms(ticket: Ticket, value: SmsObservation): boolean {
    if (!this.#current(ticket) || ticket.kind !== 'sms' || value.commandId !== this.#sms?.commandId)
      return false;
    this.#smsState = 'accepted';
    return true;
  }
  forget(): void {
    this.#authorization = '';
    ++this.#activation;
    this.#nativeReady = false;
    this.#connected = false;
    this.#grant = null;
    this.#policy = null;
    this.#policyRead = 'idle';
    this.#policyReadTicket = null;
    this.#case = null;
    this.#messages = [];
    this.#inputs = new NativeInputs();
    this.#generations = new NativeGenerations();
    this.#sms = null;
    this.#smsState = 'idle';
    // Retain unknown Parent/room/request ownership; forgetting cannot fabricate settlement.
    this.#retiring = this.#start !== null || this.#room !== null;
    this.#phase = this.#retiring ? 'cleanup_incomplete' : 'locked';
    this.#code = null;
  }
  snapshot(): View {
    const historical =
      this.#policy?.state === 'current' &&
      this.#case !== null &&
      this.#policy.revision !== this.#case.revision;
    return Object.freeze({
      activation: this.#activation,
      phase: this.#phase,
      authorized: !!this.#authorization,
      ready: this.#phase === 'ready',
      code: this.#code,
      parent: this.#authorization ? this.#parent : null,
      start: this.#authorization ? this.#start : null,
      requests: this.#tickets.size,
      roomOwned: this.#room !== null,
      reading: [...this.#tickets].some((ticket) => ticket.kind === 'read'),
      case: this.#case,
      policy: this.#policy,
      policyHistorical: historical,
      policyRead: this.#policyRead,
      sms: this.#smsState,
      messages: Object.freeze([...this.#messages]),
      inputs: this.#inputs.values(),
      generationCount: this.#generations.values().length,
    });
  }
}
