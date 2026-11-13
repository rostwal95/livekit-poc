/** Pure fixture caller/entry ownership regressions. Reviewed 12 November 2026. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { awaitFixtureEntry, fixtureResult, observeFixtureWork } from './fixture-work.js';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  try {
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    vi.useRealTimers();
  }
});

describe('test fixture caller and entry ownership', () => {
  it('retains the exact fulfilled object for both observation and result', async () => {
    const original = Object.freeze({ receipt: 'original' });
    const observed = observeFixtureWork(Promise.resolve(original));
    const outcome = await observed;
    expect(outcome.status).toBe('fulfilled');
    if (outcome.status === 'fulfilled') expect(outcome.value).toBe(original);
    expect(await fixtureResult(observed)).toBe(original);
  });

  it('observes an immediate rejection without replacing its original identity', async () => {
    const original = new Error('original_rejection');
    const observed = observeFixtureWork(Promise.reject(original));
    const outcome = await observed;
    expect(outcome.status).toBe('rejected');
    if (outcome.status === 'rejected') expect(outcome.reason).toBe(original);
    await expect(fixtureResult(observed)).rejects.toBe(original);
  });

  it('accepts actual entry while retaining the pending caller until later fulfillment', async () => {
    const entered = deferred<void>();
    const caller = deferred<object>();
    const original = Object.freeze({ receipt: 'late_fulfillment' });
    const observed = observeFixtureWork(caller.promise);
    let settled = false;
    void observed.then(() => {
      settled = true;
    });
    try {
      const waiting = awaitFixtureEntry(entered.promise, observed, 25);
      expect(vi.getTimerCount()).toBe(1);
      entered.resolve();
      await waiting;
      expect(vi.getTimerCount()).toBe(0);
      expect(settled).toBe(false);
    } finally {
      caller.resolve(original);
      await observed;
    }
    expect(await fixtureResult(observed)).toBe(original);
    expect(settled).toBe(true);
  });

  it('retains a late original rejection after successful entry and watchdog removal', async () => {
    const caller = deferred<never>();
    const original = new Error('late_rejection');
    const observed = observeFixtureWork(caller.promise);
    try {
      await awaitFixtureEntry(Promise.resolve(), observed, 25);
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      caller.reject(original);
      await observed;
    }
    await expect(fixtureResult(observed)).rejects.toBe(original);
  });

  it('fails when the caller fulfills before reaching the required entry', async () => {
    const observed = observeFixtureWork(Promise.resolve('settled_without_entry'));
    await expect(awaitFixtureEntry(new Promise<void>(() => {}), observed, 25)).rejects.toThrow(
      'fixture_entry_not_reached',
    );
    expect(await fixtureResult(observed)).toBe('settled_without_entry');
  });

  it('fails with the original caller rejection before entry and clears its watchdog', async () => {
    const original = new Error('rejected_before_entry');
    const observed = observeFixtureWork(Promise.reject(original));
    await expect(awaitFixtureEntry(new Promise<void>(() => {}), observed, 25)).rejects.toBe(
      original,
    );
    expect(vi.getTimerCount()).toBe(0);
  });

  it('uses the timeout factory once without settling or releasing the actual caller', async () => {
    const caller = deferred<object>();
    const observed = observeFixtureWork(caller.promise);
    const timeout = new Error('owned_entry_watchdog');
    const factory = vi.fn(() => timeout);
    let settled = false;
    void observed.then(() => {
      settled = true;
    });
    try {
      const waiting = awaitFixtureEntry(new Promise<void>(() => {}), observed, 25, factory);
      const checked = expect(waiting).rejects.toBe(timeout);
      await vi.advanceTimersByTimeAsync(25);
      await checked;
      expect(factory).toHaveBeenCalledTimes(1);
      expect(vi.getTimerCount()).toBe(0);
      expect(settled).toBe(false);
    } finally {
      caller.resolve({ receipt: 'released_after_timeout' });
      await observed;
    }
    expect(settled).toBe(true);
  });

  it('preserves aggregate failure while finally draining each other original caller', async () => {
    const original = new Error('one_accept_failed');
    const held = deferred<string>();
    let actualSettled = false;
    const callers = [
      observeFixtureWork(Promise.reject<string>(original)),
      observeFixtureWork(
        held.promise.then((value) => {
          actualSettled = true;
          return value;
        }),
      ),
    ];
    const aggregate = observeFixtureWork(Promise.all(callers.map(fixtureResult)));
    try {
      await expect(awaitFixtureEntry(new Promise<void>(() => {}), aggregate, 25)).rejects.toBe(
        original,
      );
      expect(actualSettled).toBe(false);
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      held.resolve('actual_accept_settled');
      await Promise.all(callers);
    }
    expect(actualSettled).toBe(true);
    await expect(fixtureResult(aggregate)).rejects.toBe(original);
  });
});
