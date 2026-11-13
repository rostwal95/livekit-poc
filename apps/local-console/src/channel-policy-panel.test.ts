import { describe, expect, it } from 'vitest';
import {
  JoinedPanel,
  modeLabel,
  policyTone,
  progressCopy,
  roomInUse,
} from './channel-policy-panel';
import type { ParentObservation, PolicySummary, StartIntent } from './channel-policy-contract';
import type { ProgressView } from './channel-policy-wire';

const T = '2026-11-13T12:00:00.000Z';
function progress(counts: Partial<ProgressView['counts']>): ProgressView {
  return {
    schemaVersion: 1,
    asOf: T,
    counts: {
      native: 0,
      sms: 0,
      pending: 0,
      running: 0,
      dispatched: 0,
      blocked: 0,
      exhausted: 0,
      uncertain: 0,
      workKnown: 0,
      ...counts,
    },
  };
}
function current(eligible: boolean | null, uncertainty: 'none' | 'missing'): PolicySummary {
  return { state: 'current', eligible, uncertainty, revision: '1', asOf: T };
}

describe('progressCopy', () => {
  it('labels the unread state and uses singular or plural input counts', () => {
    expect(progressCopy(null)).toBe('No input or work counts read yet.');
    expect(progressCopy(progress({ native: 1, dispatched: 1, workKnown: 1 }))).toBe(
      '1 input observed · 1 linked to durable work',
    );
    expect(progressCopy(progress({ native: 1, sms: 1, pending: 1, dispatched: 1 }))).toBe(
      '2 inputs observed · 0 linked to durable work · 1 awaiting dispatch',
    );
  });

  it('surfaces inputs that were not dispatched or have an unknown outcome', () => {
    expect(progressCopy(progress({ native: 2, dispatched: 1, exhausted: 1, workKnown: 1 }))).toBe(
      '2 inputs observed · 1 linked to durable work · 1 not dispatched',
    );
    expect(progressCopy(progress({ sms: 2, blocked: 1, uncertain: 1 }))).toBe(
      '2 inputs observed · 0 linked to durable work · 1 not dispatched · 1 dispatch outcome unknown',
    );
  });
});

describe('policyTone', () => {
  it('mirrors the policy copy for every observed state', () => {
    const tone = (policy: PolicySummary | null, policyHistorical = false) =>
      policyTone({ policy, policyHistorical });
    expect(tone(null)).toBe('none');
    expect(tone(current(true, 'none'))).toBe('eligible');
    expect(tone(current(false, 'none'))).toBe('ineligible');
    expect(tone(current(null, 'missing'))).toBe('needs_information');
    expect(tone(current(true, 'none'), true)).toBe('historical');
    expect(
      tone({ state: 'unavailable', eligible: null, uncertainty: null, revision: null, asOf: null }),
    ).toBe('unavailable');
    for (const state of ['no_delivery', 'not_applicable'] as const)
      expect(tone({ state, eligible: null, uncertainty: null, revision: null, asOf: T })).toBe(
        'none',
      );
  });
});

describe('observed-change highlight', () => {
  it('alternates only when a watched observation actually changes', () => {
    const node = { textContent: '', dataset: {} as Record<string, string> };
    class Panel extends JoinedPanel {
      override element<E extends HTMLElement>(): E {
        return node as unknown as E;
      }
    }
    const panel = new Panel({} as ParentNode);
    panel.text('progress', 'first');
    expect(node.dataset.observed).toBe('a');
    panel.text('progress', 'first');
    expect(node.dataset.observed).toBe('a');
    panel.text('progress', 'second');
    expect(node.dataset.observed).toBe('b');
    panel.text('notice', 'not watched');
    expect(node.dataset.observed).toBe('b');
    expect(node.textContent).toBe('not watched');
  });
});

describe('roomInUse', () => {
  const parent = (stage: ParentObservation['stage']): ParentObservation => ({
    cursor: { ownerEpoch: '1', generation: '2' } as ParentObservation['cursor'],
    stage,
    originalStartCommandId: null,
    workerReady: false,
  });
  const start = { ownerEpoch: '1', expectedGeneration: '1', commandId: 'x' } as StartIntent;
  it('names a room held by another activation instead of offering a disabled Join', () => {
    for (const stage of ['starting', 'active', 'ending', 'cleanup_incomplete'] as const)
      expect(
        roomInUse({ phase: 'idle', parent: parent(stage), start: null, roomOwned: false }),
      ).toBe(true);
  });
  it('stays false for a free room, this browser’s own session or an unread parent', () => {
    expect(
      roomInUse({ phase: 'idle', parent: parent('dormant'), start: null, roomOwned: false }),
    ).toBe(false);
    expect(roomInUse({ phase: 'idle', parent: parent('active'), start, roomOwned: false })).toBe(
      false,
    );
    expect(
      roomInUse({ phase: 'idle', parent: parent('active'), start: null, roomOwned: true }),
    ).toBe(false);
    expect(roomInUse({ phase: 'idle', parent: null, start: null, roomOwned: false })).toBe(false);
    expect(
      roomInUse({ phase: 'ready', parent: parent('active'), start: null, roomOwned: false }),
    ).toBe(false);
  });
});

describe('modeLabel', () => {
  it('names the configured profile without implying model quality before Join', () => {
    expect(modeLabel(null)).toBe('profile shown after Join');
    expect(modeLabel(undefined)).toBe('profile shown after Join');
    expect(modeLabel('scripted')).toBe('scripted');
    expect(modeLabel('provider_real')).toBe('Deepgram · OpenAI · ElevenLabs');
  });
});
