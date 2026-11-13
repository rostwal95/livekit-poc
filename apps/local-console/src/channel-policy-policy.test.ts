import { describe, expect, it } from 'vitest';
import { JoinedController } from './channel-policy-policy';
import { policyReadCaption } from './channel-policy-panel';
import type { ParentObservation, StartObservation } from './channel-policy-contract';
const OWNER = '11111111-1111-4111-8111-111111111111',
  COMMAND = '22222222-2222-4222-8222-222222222222',
  B = '33333333-3333-4333-8333-333333333333',
  BINDING = '44444444-4444-4444-8444-444444444444';
const TIME = '2026-11-13T12:00:00.000Z';
const KEY = 'A'.repeat(43);
const parent = (
  generation = '0',
  originalStartCommandId: string | null = null,
  stage: ParentObservation['stage'] = 'dormant',
  workerReady = false,
): ParentObservation => ({
  cursor: { ownerEpoch: OWNER, generation },
  originalStartCommandId,
  stage,
  workerReady,
});
function setup() {
  const c = new JoinedController();
  c.setAuthorization(KEY);
  const t = c.beginStatus();
  c.observeParent(t, parent());
  c.settled(t);
  return c;
}
function answer(command = COMMAND, generation = '1'): StartObservation {
  return {
    cursor: { ownerEpoch: OWNER, generation },
    originalStartCommandId: command,
    workerReady: true,
    grant: {
      mode: 'scripted',
      expiresAt: '2026-11-13T12:03:00.000Z',
      session: {
        schemaVersion: 1,
        url: 'ws://127.0.0.1:7880',
        token: 'rtc.jwt.secret',
        roomId: 'room-a',
        participantId: 'browser-a',
        agentId: 'agent-a',
        bindingId: BINDING,
      },
    },
  };
}
function active() {
  const c = setup();
  const start = c.beginStart(COMMAND);
  expect(c.observeStart(start.ticket, answer())).toBe('adopt');
  c.settled(start.ticket);
  const room = c.retainRoom().owner;
  c.connection(room, 'connected');
  c.native(room, 'agent-a', 'agent', {
    'p2.session_ready': 'true',
    'p2.inference_mode': 'scripted',
    'lk.agent.state': 'listening',
  });
  return { c, room };
}
function end(s: ReturnType<typeof active>) {
  const e = s.c.beginEnd();
  s.c.observeEnd(e.ticket, {
    cursor: { ownerEpoch: OWNER, generation: '1' },
    originalStartCommandId: COMMAND,
    settled: true,
  });
  s.c.settled(e.ticket);
  s.c.roomSettled(s.room);
  return e;
}
describe('joined browser activation decisions', () => {
  it('requires explicit authorization and an observed dormant cursor', () => {
    const c = new JoinedController();
    expect(() => c.beginStart(COMMAND)).toThrow();
    c.setAuthorization(KEY);
    expect(() => c.beginStart(COMMAND)).toThrow();
    expect(c.snapshot().start).toBeNull();
  });
  it('freezes original Parent Start separately from Node diagnostics', () => {
    const c = setup(),
      a = c.beginStart(COMMAND);
    expect(a.intent).toEqual({
      ownerEpoch: OWNER,
      expectedGeneration: '0',
      commandId: COMMAND,
    });
    expect(Object.isFrozen(a.intent)).toBe(true);
    expect(() => c.beginStart(B)).toThrow();
  });
  it('retries an unknown Start with exactly the same original object', () => {
    const c = setup(),
      a = c.beginStart(COMMAND);
    c.failed(a.ticket, 'unknown');
    expect(() => c.retryStart()).toThrow();
    expect(c.snapshot().phase).toBe('start_unknown');
    c.settled(a.ticket);
    expect(c.retryStart().intent).toBe(a.intent);
    expect(() => c.beginStart(B)).toThrow();
  });
  it('does not adopt another concurrent activation during reconciliation', () => {
    const c = setup(),
      a = c.beginStart(COMMAND);
    expect(c.observeStart(a.ticket, answer(B))).toBe('discard');
    expect(c.snapshot().phase).toBe('start_unknown');
    expect(c.snapshot().roomOwned).toBe(false);
  });
  it('requires selected AGENT native readiness and actual Parent worker readiness', () => {
    const c = setup(),
      a = c.beginStart(COMMAND);
    c.observeStart(a.ticket, { ...answer(), workerReady: false });
    c.settled(a.ticket);
    const room = c.retainRoom().owner;
    c.connection(room, 'connected');
    c.native(room, 'agent-a', 'agent', {
      'p2.session_ready': 'true',
      'p2.inference_mode': 'scripted',
      'lk.agent.state': 'speaking',
    });
    expect(c.snapshot().ready).toBe(false);
    const t = c.beginStatus();
    c.observeParent(t, parent('1', COMMAND, 'active', true));
    c.settled(t);
    expect(c.snapshot().ready).toBe(true);
    c.native(room, 'someone-else', 'agent', {
      'p2.session_ready': 'true',
      'p2.inference_mode': 'scripted',
      'lk.agent.state': 'speaking',
    });
    expect(c.snapshot().ready).toBe(false);
  });
  it('uses only current-activation interrupt payload and never business cancellation', () => {
    const { c, room } = active();
    expect(c.interrupt(room)).toBe('{"schemaVersion":1}');
    c.beginEnd();
    expect(() => c.interrupt(room)).toThrow();
  });
  it('blocks B while actual A media remains owned, even after Parent closed ACK', () => {
    const s = active(),
      e = s.c.beginEnd();
    s.c.observeEnd(e.ticket, {
      cursor: { ownerEpoch: OWNER, generation: '1' },
      originalStartCommandId: COMMAND,
      settled: true,
    });
    s.c.settled(e.ticket);
    expect(s.c.snapshot().phase).toBe('ending');
    expect(() => s.c.beginStart(B)).toThrow();
    s.c.roomSettled(s.room);
    expect(s.c.snapshot().phase).toBe('dormant');
    expect(s.c.beginStart(B).intent.expectedGeneration).toBe('1');
  });
  it('End preserves the separately scoped operator authorization for dormant SMS', () => {
    const s = active();
    end(s);
    const sms = s.c.beginSms(B, 'Investigate the updated case', TIME);
    expect(s.c.withAuthorization(sms.ticket, (key) => key)).toBe(KEY);
    expect(s.c.snapshot().authorized).toBe(true);
    expect(s.c.snapshot().policy).toBeNull();
  });
  it('freezes SMS body/time/command across unknown and never revises the case from ACK', () => {
    const c = setup(),
      a = c.beginSms(COMMAND, 'Investigate', TIME);
    c.failed(a.ticket, 'unknown');
    c.settled(a.ticket);
    expect(() => c.beginSms(B, 'Investigate', TIME)).toThrow();
    expect(() => c.beginSms(COMMAND, 'Changed', TIME)).toThrow();
    expect(() => c.beginSms(COMMAND, 'Investigate', '2026-11-13T12:00:01.000Z')).toThrow();
    const retry = c.beginSms(COMMAND, 'Investigate', TIME);
    expect(retry.intent).toEqual(a.intent);
    expect(
      c.observeSms(retry.ticket, {
        commandId: COMMAND,
        status: 'replayed',
        observedAt: TIME,
      }),
    ).toBe(true);
    expect(c.snapshot().case).toBeNull();
  });
  it('fences a late Start grant after End without constructing a room', () => {
    const c = setup(),
      a = c.beginStart(COMMAND);
    c.beginEnd();
    expect(c.observeStart(a.ticket, answer())).toBe('discard');
    expect(c.snapshot().roomOwned).toBe(false);
    expect(c.snapshot().phase).toBe('ending');
  });
  it('keeps unknown End ownership and the original cleanup identity', () => {
    const s = active(),
      e = s.c.beginEnd();
    s.c.failed(e.ticket, 'unknown');
    expect(s.c.snapshot().phase).toBe('cleanup_incomplete');
    s.c.settled(e.ticket);
    const retry = s.c.beginEnd();
    expect(retry.intent.originalStart).toBe(e.intent.originalStart);
    expect(() => s.c.beginStart(B)).toThrow();
  });
  it('rejects old A read/text/native/ACK callbacks after End and after B', () => {
    const s = active();
    const read = s.c.beginRead();
    end(s);
    expect(s.c.agentText(s.room, 'late secret')).toBe(false);
    expect(
      s.c.observeRead(read, {
        case: { revision: '1', observedAt: TIME },
        policy: {
          state: 'no_delivery',
          eligible: null,
          uncertainty: null,
          revision: null,
          asOf: TIME,
        },
      }),
    ).toBe(false);
    s.c.settled(read);
    const b = s.c.beginStart(B);
    s.c.observeStart(b.ticket, answer(B, '2'));
    s.c.settled(b.ticket);
    expect(s.c.native(s.room, 'agent-a', 'agent', {})).toBe(false);
    expect(s.c.acceptance(s.room, new Uint8Array())).toBe(false);
    expect(s.c.snapshot().policy).toBeNull();
  });
  it('preserves independent read timestamps and withholds stale current conclusions', () => {
    const s = active(),
      r = s.c.beginRead();
    s.c.observeRead(r, {
      case: { revision: '2', observedAt: TIME },
      policy: {
        state: 'current',
        eligible: true,
        uncertainty: 'none',
        revision: '1',
        asOf: '2026-11-13T11:59:59.000Z',
      },
    });
    expect(s.c.snapshot().policyHistorical).toBe(true);
    expect(s.c.snapshot().policy?.asOf).not.toBe(s.c.snapshot().case?.observedAt);
  });
  it('preserves no_delivery/not_applicable read times, unavailable stays explicit', () => {
    const c = setup(),
      r = c.beginRead();
    for (const state of ['no_delivery', 'not_applicable'] as const) {
      c.observeRead(r, {
        case: null,
        policy: {
          state,
          eligible: null,
          uncertainty: null,
          revision: null,
          asOf: TIME,
        },
      });
      expect(c.snapshot().policy?.asOf).toBe(TIME);
    }
    c.failed(r, 'unavailable');
    expect(c.snapshot().code).toBe('unavailable');
    expect(c.snapshot().policy?.state).toBe('not_applicable');
  });
  it('retains actual request tickets after a failed observer', () => {
    const c = setup(),
      r = c.beginRead();
    c.failed(r, 'unavailable');
    expect(c.snapshot().requests).toBe(1);
    expect(c.snapshot().reading).toBe(true);
    expect(() => c.beginRead()).toThrow();
    c.settled(r);
    expect(c.snapshot().reading).toBe(false);
  });
  it('Forget clears authorization/history immediately but never fabricates owner settlement', () => {
    const s = active();
    s.c.agentText(s.room, 'observed');
    const e = s.c.beginEnd();
    s.c.forget();
    expect(s.c.snapshot().authorized).toBe(false);
    expect(s.c.snapshot().messages).toEqual([]);
    expect(s.c.snapshot().roomOwned).toBe(true);
    expect(() => s.c.withAuthorization(e.ticket, (key) => key)).toThrow();
    expect(
      s.c.observeEnd(e.ticket, {
        cursor: { ownerEpoch: OWNER, generation: '1' },
        originalStartCommandId: COMMAND,
        settled: true,
      }),
    ).toBe(true);
    s.c.settled(e.ticket);
    s.c.roomSettled(s.room);
    expect(s.c.snapshot().phase).toBe('locked');
  });
  it('bounds transcript and preserves plain untrusted text without markup interpretation', () => {
    const s = active();
    for (let i = 0; i < 40; i++) s.c.agentText(s.room, '<script>' + i + '</script>');
    expect(s.c.snapshot().messages).toHaveLength(32);
    expect(s.c.snapshot().messages.at(-1)?.text).toBe('<script>39</script>');
  });
  it('grows one live agent message per stream in place and finalizes it', () => {
    const s = active();
    s.c.agentText(s.room, 'Checking', 1, true);
    const [first] = s.c.snapshot().messages;
    s.c.agentText(s.room, 'Checking the policy', 1, true);
    s.c.agentText(s.room, 'Another reply', 2, true);
    s.c.agentText(s.room, 'Checking the policy.', 1, false);
    const messages = s.c.snapshot().messages;
    expect(messages.map((row) => [row.id, row.text, row.live])).toEqual([
      [first!.id, 'Checking the policy.', false],
      [first!.id + 1, 'Another reply', true],
    ]);
    expect(() => s.c.agentText(s.room, '   ', 1, true)).toThrow();
    expect(s.c.snapshot().messages[0]!.text).toBe('Checking the policy.');
  });
  it('never exposes either operator key or RTC token through view JSON', () => {
    const s = active();
    const text = JSON.stringify(s.c.snapshot());
    expect(text).not.toContain(KEY);
    expect(text).not.toContain('rtc.jwt.secret');
  });
});

describe('original retirement controller permits', () => {
  it('admits End as third ticket and keeps B blocked until all actual tickets settle', () => {
    const c = setup(),
      start = c.beginStart(COMMAND),
      status = c.beginStatus(),
      end = c.beginEnd();
    expect(c.snapshot().requests).toBe(3);
    expect(() => c.beginStatus()).toThrow();
    expect(() => c.beginEnd()).toThrow();
    expect(
      c.observeEnd(end.ticket, {
        cursor: { ownerEpoch: OWNER, generation: '2' },
        originalStartCommandId: COMMAND,
        settled: true,
      }),
    ).toBe(false);
    c.observeEnd(end.ticket, {
      cursor: { ownerEpoch: OWNER, generation: '1' },
      originalStartCommandId: COMMAND,
      settled: true,
    });
    c.settled(end.ticket);
    expect(c.retirementSettled(end.permit)).toBe(false);
    expect(() => c.beginStart(B)).toThrow();
    c.settled(start.ticket);
    expect(c.retirementSettled(end.permit)).toBe(false);
    c.settled(status);
    expect(c.retirementSettled(end.permit)).toBe(true);
    expect(c.snapshot().requests).toBe(0);
    expect(c.beginStart(B).intent.expectedGeneration).toBe('1');
    expect(() => c.retryEnd(end.permit)).toThrow();
  });
  it('permits only original cleanup after Forget, without restoring general authorization', () => {
    const c = setup(),
      start = c.beginStart(COMMAND),
      end = c.beginEnd();
    c.failed(end.ticket, 'conflict');
    c.settled(end.ticket);
    c.forget();
    expect(() => c.beginStatus()).toThrow();
    expect(() => c.withAuthorization(start.ticket, (key) => key)).toThrow();
    expect(() => c.retryEnd(Object.freeze({ ...end.permit }))).toThrow();
    const retry = c.retryEnd(end.permit);
    expect(retry.intent.originalStart).toBe(end.intent.originalStart);
    expect(() => c.withAuthorization(retry.ticket, (key) => key)).toThrow();
    expect(
      c.observeEnd(retry.ticket, {
        cursor: { ownerEpoch: OWNER, generation: '1' },
        originalStartCommandId: COMMAND,
        settled: true,
      }),
    ).toBe(true);
    c.settled(retry.ticket);
    c.settled(start.ticket);
    expect(c.retirementSettled(end.permit)).toBe(true);
    expect(c.snapshot().authorized).toBe(false);
    expect(c.snapshot().start).toBeNull();
    expect(c.snapshot().phase).toBe('locked');
  });
});

describe('source-scoped current-result availability', () => {
  const fact = (asOf = TIME) => ({
    state: 'current' as const,
    eligible: true,
    uncertainty: 'none' as const,
    revision: '1',
    asOf,
  });
  it('retains exact prior fact/time on busy and clears only that source on useful progress', () => {
    const c = setup(),
      initial = c.beginRead();
    c.observeRead(initial, { case: null, policy: fact() });
    c.settled(initial);
    const sms = c.beginSms(B, 'Investigate the fixed case', TIME);
    c.failed(sms.ticket, 'unknown');
    c.settled(sms.ticket);
    const prior = c.snapshot().policy,
      read = c.beginRead();
    expect(c.beginPolicyRead(read)).toBe(true);
    expect(policyReadCaption(c.snapshot())).toBe('Checking again; showing the prior observation.');
    expect(c.failedPolicyRead(read, 'capacity')).toBe(true);
    expect(c.snapshot().policy).toBe(prior);
    expect(c.snapshot().policy?.asOf).toBe(TIME);
    expect(policyReadCaption(c.snapshot())).toBe(
      'Latest read busy; showing the prior observation.',
    );
    expect(c.snapshot().code).toBe('unknown');
    expect(c.snapshot().sms).toBe('unknown');
    c.settled(read);
    const unavailable = c.beginRead();
    c.beginPolicyRead(unavailable);
    c.failedPolicyRead(unavailable, 'unavailable');
    expect(c.snapshot().policy).toBe(prior);
    expect(c.snapshot().policy?.asOf).toBe(TIME);
    expect(policyReadCaption(c.snapshot())).toBe(
      'Latest read unavailable; showing the prior observation.',
    );
    c.settled(unavailable);
    const next = c.beginRead(),
      later = '2026-11-13T12:00:04.000Z';
    c.beginPolicyRead(next);
    c.observeRead(next, { case: null, policy: fact(later) });
    expect(c.snapshot().policyRead).toBe('ok');
    expect(c.snapshot().policy?.asOf).toBe(later);
    expect(policyReadCaption(c.snapshot())).toBeNull();
    expect(c.snapshot().code).toBe('unknown');
    expect(c.snapshot().sms).toBe('unknown');
  });
  it('does not confuse status or case/progress errors with a failed current-result read', () => {
    const c = setup(),
      status = c.beginStatus();
    c.failed(status, 'unavailable');
    expect(c.failedPolicyRead(status, 'capacity')).toBe(false);
    expect(c.snapshot().policyRead).toBe('idle');
    c.settled(status);
    const read = c.beginRead();
    c.failed(read, 'unavailable');
    expect(c.failedPolicyRead(read, 'capacity')).toBe(false);
    expect(c.snapshot().policyRead).toBe('idle');
    c.observeRead(read, { case: null, policy: fact() });
    expect(c.snapshot().code).toBe('unavailable');
    expect(c.snapshot().policyRead).toBe('ok');
    expect(policyReadCaption(c.snapshot())).toBeNull();
  });
  it('fences late A facts/errors after Forget and a fresh B activation', () => {
    const s = active(),
      old = s.c.beginRead();
    s.c.beginPolicyRead(old);
    const retiring = s.c.beginEnd();
    s.c.forget();
    expect(s.c.snapshot().policyRead).toBe('idle');
    expect(s.c.failedPolicyRead(old, 'capacity')).toBe(false);
    expect(s.c.observeRead(old, { case: null, policy: fact() })).toBe(false);
    expect(s.c.snapshot().policy).toBeNull();
    s.c.observeEnd(retiring.ticket, {
      cursor: { ownerEpoch: OWNER, generation: '1' },
      originalStartCommandId: COMMAND,
      settled: true,
    });
    s.c.settled(retiring.ticket);
    s.c.settled(old);
    s.c.roomSettled(s.room);
    s.c.setAuthorization(KEY);
    const b = s.c.beginStart(B);
    s.c.observeStart(b.ticket, answer(B, '2'));
    s.c.settled(b.ticket);
    const current = s.c.beginRead();
    s.c.beginPolicyRead(current);
    const later = '2026-11-13T12:00:05.000Z';
    s.c.observeRead(current, { case: null, policy: fact(later) });
    expect(s.c.failedPolicyRead(old, 'unavailable')).toBe(false);
    expect(s.c.observeRead(old, { case: null, policy: fact() })).toBe(false);
    expect(s.c.snapshot().policy?.asOf).toBe(later);
    expect(s.c.snapshot().policyRead).toBe('ok');
  });
  it('labels pending/busy/unavailable without inventing a first observation or timestamp', () => {
    const c = setup(),
      read = c.beginRead();
    expect(c.beginPolicyRead(read)).toBe(true);
    expect(policyReadCaption(c.snapshot())).toBe('Reading the current result.');
    c.failedPolicyRead(read, 'capacity');
    expect(policyReadCaption(c.snapshot())).toBe('Latest result read is busy.');
    c.settled(read);
    const next = c.beginRead();
    c.beginPolicyRead(next);
    c.failedPolicyRead(next, 'unavailable');
    expect(policyReadCaption(c.snapshot())).toBe('Latest result read unavailable.');
    expect(c.snapshot().policy).toBeNull();
    expect(c.snapshot().code).toBeNull();
  });
});
